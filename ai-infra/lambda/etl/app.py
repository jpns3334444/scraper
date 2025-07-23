"""
ETL Lambda function for processing real estate listings CSV data.
Lean v1.3 implementation with deterministic scoring, gating, and metrics.
"""
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Note: Remove sys.path manipulation - modules should be packaged with Lambda deployment

try:
    from analysis.lean_scoring import LeanScoring, Verdict
    from analysis.comparables import ComparablesFilter, enrich_property_with_comparables
    from analysis.vision_stub import enrich_property_with_vision
    from util.config import get_config, is_lean_mode
    from util.metrics import emit_pipeline_metrics, emit_properties_processed, emit_candidates_enqueued, emit_candidates_suppressed, MetricsTimer
except ImportError as e:
    logging.error(f"Failed to import analysis modules: {e}")
    # Fallback for basic functionality
    LeanScoring = None
    ComparablesFilter = None
    emit_pipeline_metrics = lambda *args: None
    emit_properties_processed = lambda *args: None
    emit_candidates_enqueued = lambda *args: None
    emit_candidates_suppressed = lambda *args: None
    class MetricsTimer:
        def __init__(self, stage): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass


logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for ETL processing.
    
    Args:
        event: Lambda event containing date parameter
        context: Lambda context
        
    Returns:
        Dict containing processed data location and metadata
    """
    try:
        # Extract date from event or use current date
        date_str = event.get('date')
        
        # Handle Step Functions passing the literal string '$.State.EnteredTime'
        if date_str == '$.State.EnteredTime':
            logger.warning("Received literal Step Functions expression, checking execution_time")
            # Try to use execution_time if available
            date_str = event.get('execution_time')
            if date_str and 'T' in date_str:
                try:
                    date_str = datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d')
                    logger.info(f"Using execution time date: {date_str}")
                except ValueError:
                    date_str = None
        
        if not date_str:
            # Use yesterday's date by default (since scraper runs daily)
            date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            logger.info(f"No valid date provided, using yesterday's date: {date_str}")
        elif 'T' in date_str:  # Handle ISO datetime format from EventBridge
            try:
                date_str = datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d')
            except ValueError as e:
                logger.error(f"Failed to parse date '{date_str}': {e}")
                # Fallback to yesterday's date
                date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                logger.info(f"Using fallback date: {date_str}")
        
        try:
            if get_config:
                bucket = get_config().get_str('OUTPUT_BUCKET')
            else:
                bucket = os.environ.get('OUTPUT_BUCKET')
                if not bucket:
                    raise KeyError("OUTPUT_BUCKET environment variable is required")
        except Exception as e:
            logger.error(f"Failed to get OUTPUT_BUCKET configuration: {e}")
            raise ValueError(f"Configuration error: OUTPUT_BUCKET is required but not found: {e}")
        
        logger.info(f"Processing listings for date: {date_str}")
        
        # Discover CSV files from scraper output for the given date
        csv_prefix = f"scraper-output/"
        logger.info(f"Discovering CSV files in s3://{bucket}/{csv_prefix} for date {date_str}")
        
        # List files matching the date pattern
        try:
            response = s3_client.list_objects_v2(Bucket=bucket, Prefix=csv_prefix)
            available_files = []
            csv_key = None
            matching_files = []
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    key = obj['Key']
                    if key.endswith('.csv') and date_str in key:
                        matching_files.append(key)
                    available_files.append(key)
            
            if matching_files:
                # Use the first matching file (prefer specific patterns)
                priority_patterns = [
                    f"listings-{date_str}.csv",  # Generic pattern
                    f"chofu-city-listings-{date_str}.csv",  # Legacy pattern
                    f"{date_str}.csv"  # Simple date pattern
                ]
                
                # Try to find files with priority patterns
                for pattern in priority_patterns:
                    for file_key in matching_files:
                        if pattern in file_key:
                            csv_key = file_key
                            break
                    if csv_key:
                        break
                
                # If no priority pattern found, use the first match
                if not csv_key:
                    csv_key = matching_files[0]
                
                logger.info(f"Found {len(matching_files)} CSV files for date {date_str}, using: {csv_key}")
            else:
                logger.error(f"No CSV files found for date {date_str} in {csv_prefix}")
                logger.info(f"Available files: {available_files[:10]}")  # Show first 10 for debugging
                raise FileNotFoundError(f"No CSV files found for date {date_str} in scraper output")
                
        except ClientError as e:
            logger.error(f"Failed to list files in bucket: {e}")
            return {
                'statusCode': 500,
                'error': 'S3 list objects failed',
                'message': f"Failed to list objects in s3://{bucket}/{csv_prefix}. Error: {e}",
                'date': date_str,
                'bucket': bucket
            }
        
        logger.info(f"Attempting to read CSV from s3://{bucket}/{csv_key}")
        
        # Read the discovered CSV file
        try:
            response = s3_client.get_object(Bucket=bucket, Key=csv_key)
            try:
                df = pd.read_csv(response['Body'])
                logger.info(f"Successfully loaded CSV with {len(df)} rows from {csv_key}")
            finally:
                response['Body'].close()
        except s3_client.exceptions.NoSuchKey:
            logger.error(f"CSV file not found: s3://{bucket}/{csv_key}")
            # Return a more informative error
            return {
                'statusCode': 404,
                'error': 'CSV file not found',
                'message': f"Expected file at s3://{bucket}/{csv_key} does not exist. Check if scraper has run for this date.",
                'date': date_str,
                'bucket': bucket
            }
        except Exception as e:
            logger.error(f"Failed to read CSV from s3://{bucket}/{csv_key}: {e}")
            raise
        
        logger.info(f"Loaded {len(df)} listings from CSV")
        
        # Process the data with Lean v1.3 logic
        processed_result = process_listings_lean(df, bucket, date_str)
        
        # Save processed data as JSONL
        jsonl_key = f"clean/{date_str}/listings.jsonl"
        save_jsonl_to_s3(processed_result['processed_data'], bucket, jsonl_key)
        
        # Save candidates separately if any
        if processed_result['candidates']:
            candidates_key = f"candidates/{date_str}/candidates.jsonl"
            save_jsonl_to_s3(processed_result['candidates'], bucket, candidates_key)
            logger.info(f"Saved {len(processed_result['candidates'])} candidates to {candidates_key}")
        
        logger.info(f"Successfully processed {len(processed_result['processed_data'])} listings")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'jsonl_key': jsonl_key,
            'listings_count': len(processed_result['processed_data']),
            'candidates_count': len(processed_result['candidates']),
            'metrics': processed_result['metrics'],
            'candidates': [clean_for_json(item) for item in processed_result['candidates']]  # Pass all candidates
        }
        
    except Exception as e:
        logger.error(f"ETL processing failed: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'date': date_str if 'date_str' in locals() else 'unknown',
            'bucket': bucket if 'bucket' in locals() else 'unknown'
        }


def process_listings_lean(df: pd.DataFrame, bucket: str, date_str: str) -> Dict[str, Any]:
    """
    Lean v1.3 processing with deterministic scoring, gating, and metrics.
    
    Args:
        df: Input dataframe
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        Dict containing processed_data, candidates, and metrics
    """
    config = get_config()
    
    # Initialize metrics
    metrics = {
        'PropertiesProcessed': 0,
        'CandidatesEnqueued': 0,
        'CandidatesSuppressed': 0,
        'ProcessingErrors': 0,
        'ScoreDistribution': {'BUY_CANDIDATE': 0, 'WATCH': 0, 'REJECT': 0}
    }
    
    processed_data = []
    candidates = []
    all_properties = []  # For comparables calculation
    
    # First pass: Basic processing and data collection
    logger.info(f"Starting Lean v1.3 processing of {len(df)} listings")
    
    for _, row in df.iterrows():
        try:
            # Convert row to dict, keeping all original fields
            listing = row.to_dict()
            
            # Skip if missing critical ID
            if not str(listing.get('id', '')).strip():
                continue
            
            # Process images
            if 'photo_filenames' in listing and listing['photo_filenames']:
                image_urls = process_and_upload_images(
                    listing['photo_filenames'], bucket, date_str, 
                    listing.get('id', 'unknown')
                )
                listing['uploaded_image_urls'] = image_urls
                listing['interior_photos'] = image_urls  # For backward compatibility
            else:
                listing['uploaded_image_urls'] = []
                listing['interior_photos'] = []
            
            # Add basic metadata
            listing['processed_date'] = date_str
            listing['source'] = 'homes_scraper'
            
            # Clean and normalize numeric fields
            listing = normalize_listing_data(listing)
            
            all_properties.append(listing)
            processed_data.append(listing)
            metrics['PropertiesProcessed'] += 1
            
        except Exception as e:
            logger.warning(f"Failed to process listing {row.get('id', 'unknown')}: {e}")
            metrics['ProcessingErrors'] += 1
            continue
    
    # Second pass: Lean v1.3 scoring and gating (if enabled)
    if is_lean_mode() and LeanScoring and ComparablesFilter:
        logger.info("Applying Lean v1.3 scoring and gating...")
        
        # Calculate ward medians for scoring
        ward_medians = calculate_ward_medians(all_properties)
        
        # Calculate building medians for scoring
        building_medians = calculate_building_medians(all_properties)
        
        # Initialize scoring components
        scorer = LeanScoring()
        comparables_filter = ComparablesFilter(max_comparables=config.get_int('MAX_COMPARABLES'))
        
        max_candidates_per_day = config.get_int('MAX_CANDIDATES_PER_DAY')
        
        for listing in processed_data:
            try:
                # Enrich with comparables
                listing = enrich_property_with_comparables(listing, all_properties)
                
                # Enrich with vision analysis
                listing = enrich_property_with_vision(listing)
                
                # Add ward median data
                ward = listing.get('ward', 'unknown')
                if ward in ward_medians:
                    listing.update(ward_medians[ward])
                
                # Add building median data
                building_name = listing.get('building_name', 'unknown')
                if building_name in building_medians:
                    listing.update(building_medians[building_name])
                
                # Calculate score
                scoring_components = scorer.calculate_score(listing)
                
                # Add scoring results to listing
                listing.update({
                    'final_score': scoring_components.final_score,
                    'base_score': scoring_components.base_score,
                    'addon_score': scoring_components.addon_score,
                    'adjustment_score': scoring_components.adjustment_score,
                    'verdict': scoring_components.verdict.value,
                    'ward_discount_pct': scoring_components.ward_discount_pct,
                    'data_quality_penalty': scoring_components.data_quality_penalty,
                    'scoring_components': {
                        'ward_discount': scoring_components.ward_discount,
                        'building_discount': scoring_components.building_discount,
                        'comps_consistency': scoring_components.comps_consistency,
                        'condition': scoring_components.condition,
                        'size_efficiency': scoring_components.size_efficiency,
                        'carry_cost': scoring_components.carry_cost,
                        'price_cut': scoring_components.price_cut,
                        'renovation_potential': scoring_components.renovation_potential,
                        'access': scoring_components.access,
                        'vision_positive': scoring_components.vision_positive,
                        'vision_negative': scoring_components.vision_negative,
                        'overstated_discount_penalty': scoring_components.overstated_discount_penalty
                    }
                })
                
                # Update metrics
                metrics['ScoreDistribution'][scoring_components.verdict.value.upper()] += 1
                
                # Apply candidate gating logic: base_score >= 70 and ward_discount_pct <= -8 and dq_penalty > -5
                is_candidate_eligible = (
                    scoring_components.base_score >= 70 and
                    scoring_components.ward_discount_pct <= -8 and
                    scoring_components.data_quality_penalty > -5
                )
                
                # Add is_candidate flag to listing
                listing['is_candidate'] = is_candidate_eligible
                
                # Apply daily limit cap
                if is_candidate_eligible and len(candidates) < max_candidates_per_day:
                    candidates.append(listing)
                    metrics['CandidatesEnqueued'] += 1
                    logger.info(f"Property {listing.get('id', 'unknown')} qualified as candidate "
                              f"(base_score: {scoring_components.base_score:.1f}, "
                              f"ward_discount_pct: {scoring_components.ward_discount_pct:.1f}%, "
                              f"dq_penalty: {scoring_components.data_quality_penalty:.1f})")
                elif is_candidate_eligible:
                    # Would be a candidate but hit daily limit
                    metrics['CandidatesSuppressed'] += 1
                    logger.info(f"Property {listing.get('id', 'unknown')} suppressed due to daily limit "
                              f"({len(candidates)}/{max_candidates_per_day})")
                else:
                    logger.debug(f"Property {listing.get('id', 'unknown')} did not meet candidate criteria "
                               f"(base_score: {scoring_components.base_score:.1f} >= 70?, "
                               f"ward_discount_pct: {scoring_components.ward_discount_pct:.1f}% <= -8?, "
                               f"dq_penalty: {scoring_components.data_quality_penalty:.1f} > -5?)")
                
            except Exception as e:
                logger.error(f"Failed to score listing {listing.get('id', 'unknown')}: {e}")
                metrics['ProcessingErrors'] += 1
                continue
        
        # Sort candidates by score (highest first)
        candidates.sort(key=lambda x: x.get('final_score', 0), reverse=True)
        
        # Log candidate gating summary
        eligible_count = metrics['CandidatesEnqueued'] + metrics['CandidatesSuppressed']
        logger.info(f"Lean processing complete: {metrics['PropertiesProcessed']} properties processed, "
                   f"{eligible_count} eligible candidates, {metrics['CandidatesEnqueued']} enqueued, "
                   f"{metrics['CandidatesSuppressed']} suppressed (daily limit: {max_candidates_per_day})")
    
    else:
        logger.info("Lean mode disabled or modules unavailable, using legacy processing")
        # Legacy mode - no scoring or gating, mark all as non-candidates
        for listing in processed_data:
            listing['is_candidate'] = False
        
        # Still apply daily limit for consistency
        max_candidates_per_day = config.get_int('MAX_CANDIDATES_PER_DAY', 50)
        candidates = processed_data[:max_candidates_per_day]
        metrics['CandidatesEnqueued'] = len(candidates)
        metrics['CandidatesSuppressed'] = max(0, len(processed_data) - max_candidates_per_day)
        
        # Mark selected candidates
        for candidate in candidates:
            candidate['is_candidate'] = True
    
    # Emit metrics to CloudWatch
    try:
        emit_properties_processed(metrics['PropertiesProcessed'])
        emit_candidates_enqueued(metrics['CandidatesEnqueued'])
        emit_candidates_suppressed(metrics['CandidatesSuppressed'])
        emit_pipeline_metrics('ETL', metrics)
        logger.info(f"Emitted ETL metrics: {metrics}")
    except Exception as e:
        logger.warning(f"Failed to emit metrics: {e}")
    
    return {
        'processed_data': processed_data,
        'candidates': candidates,
        'metrics': metrics
    }


def normalize_listing_data(listing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize and clean listing data for consistent processing.
    
    Args:
        listing: Raw listing dictionary
        
    Returns:
        Normalized listing dictionary
    """
    normalized = listing.copy()
    
    # Convert string numbers to floats/ints where appropriate
    numeric_fields = {
        'price': float,
        'size_sqm': float,
        'price_per_sqm': float,
        'building_age_years': int,
        'floor': int,
        'total_floors': int,
        'monthly_costs': float,
        'management_fee': float,
        'repair_reserve_fee': float
    }
    
    for field, converter in numeric_fields.items():
        if field in normalized:
            try:
                value = normalized[field]
                if pd.isna(value) or value in ['', 'nan', None]:
                    normalized[field] = None
                else:
                    normalized[field] = converter(value)
            except (ValueError, TypeError):
                normalized[field] = None
    
    # Calculate derived fields
    if normalized.get('price') and normalized.get('size_sqm'):
        normalized['price_per_sqm'] = normalized['price'] / normalized['size_sqm']
    
    # Calculate total monthly costs if components available
    monthly_costs = 0
    for cost_field in ['management_fee', 'repair_reserve_fee']:
        if normalized.get(cost_field):
            monthly_costs += normalized[cost_field]
    
    if monthly_costs > 0:
        normalized['total_monthly_costs'] = monthly_costs
    
    return normalized


def calculate_ward_medians(properties: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Calculate ward-level median prices for scoring with DynamoDB fallback.
    
    Args:
        properties: List of property dictionaries
        
    Returns:
        Dictionary with ward medians by ward name
    """
    ward_data = {}
    
    for prop in properties:
        ward = prop.get('ward', 'unknown')
        price_per_sqm = prop.get('price_per_sqm')
        
        if not price_per_sqm:
            continue
            
        if ward not in ward_data:
            ward_data[ward] = []
        
        ward_data[ward].append(price_per_sqm)
    
    ward_medians = {}
    wards_needing_fallback = []
    
    for ward, prices in ward_data.items():
        if len(prices) >= 4:  # Need at least 4 properties for reliable median
            sorted_prices = sorted(prices)
            median_idx = len(sorted_prices) // 2
            median_price = sorted_prices[median_idx]
            
            ward_medians[ward] = {
                'ward_avg_price_per_sqm': median_price,
                'ward_property_count': len(prices)
            }
        else:
            # Mark ward for DynamoDB fallback
            wards_needing_fallback.append(ward)
    
    # Fallback to DynamoDB for wards with insufficient current data
    if wards_needing_fallback:
        try:
            config = get_config()
            if config:
                table_name = config.get_str('DYNAMODB_TABLE')
                if table_name:
                    fallback_medians = fetch_ward_medians_from_dynamodb(wards_needing_fallback, table_name)
                    ward_medians.update(fallback_medians)
                    logger.info(f"Applied DynamoDB fallback for {len(fallback_medians)} wards with <4 properties")
                else:
                    logger.warning("DYNAMODB_TABLE not configured, skipping fallback")
            else:
                logger.warning("Config not available, skipping DynamoDB fallback")
        except Exception as e:
            logger.error(f"Failed to fetch ward medians from DynamoDB: {e}")
    
    logger.info(f"Calculated medians for {len(ward_medians)} wards ({len(wards_needing_fallback)} needed fallback)")
    return ward_medians


def calculate_building_medians(properties: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Calculate building-level median prices for scoring.
    
    Args:
        properties: List of property dictionaries
        
    Returns:
        Dictionary with building medians by building name
    """
    building_data = {}
    
    for prop in properties:
        building_name = prop.get('building_name', 'unknown')
        price_per_sqm = prop.get('price_per_sqm')
        
        if not price_per_sqm or building_name == 'unknown':
            continue
            
        if building_name not in building_data:
            building_data[building_name] = []
        
        building_data[building_name].append(price_per_sqm)
    
    building_medians = {}
    for building, prices in building_data.items():
        if len(prices) >= 2:  # Need at least 2 properties for meaningful building median
            sorted_prices = sorted(prices)
            median_idx = len(sorted_prices) // 2
            median_price = sorted_prices[median_idx]
            
            building_medians[building] = {
                'building_median_price_per_sqm': median_price,
                'building_property_count': len(prices)
            }
    
    logger.info(f"Calculated medians for {len(building_medians)} buildings")
    return building_medians


def fetch_ward_medians_from_dynamodb(wards: List[str], table_name: str) -> Dict[str, Dict[str, float]]:
    """
    Fetch ward median prices from DynamoDB for wards with insufficient current data.
    
    Args:
        wards: List of ward names needing fallback data
        table_name: DynamoDB table name
        
    Returns:
        Dictionary with ward medians from historical data
    """
    try:
        table = dynamodb.Table(table_name)
        ward_medians = {}
        
        for ward in wards:
            # Query recent properties from this ward to calculate median
            # Use district_key as GSI for efficient querying
            district_key = f"DIST#{ward.replace(' ', '_')}"
            
            try:
                # Try to query the GSI first, fall back to scan if GSI doesn't exist
                try:
                    response = table.query(
                        IndexName='district-index',
                        KeyConditionExpression='district_key = :dk',
                        ExpressionAttributeValues={
                            ':dk': district_key
                        },
                        Limit=50,
                        ScanIndexForward=False
                    )
                except table.meta.client.exceptions.ResourceNotFoundException:
                    logger.warning(f"GSI 'district-index' not found, falling back to scan for ward {ward}")
                    # Fallback to scan with filter (less efficient but works)
                    response = table.scan(
                        FilterExpression='contains(ward, :ward_name)',
                        ExpressionAttributeValues={
                            ':ward_name': ward
                        },
                        Limit=50
                    )
                except Exception as gsi_error:
                    logger.warning(f"GSI query failed for ward {ward}: {gsi_error}, falling back to scan")
                    # Fallback to scan with filter
                    response = table.scan(
                        FilterExpression='contains(ward, :ward_name)',
                        ExpressionAttributeValues={
                            ':ward_name': ward
                        },
                        Limit=50
                    )
                
                prices = []
                for item in response.get('Items', []):
                    price_per_sqm = item.get('price_per_sqm')
                    if price_per_sqm and price_per_sqm > 0:
                        # Convert Decimal to float if needed
                        prices.append(float(price_per_sqm))
                
                if len(prices) >= 3:  # Need at least 3 for reliable median
                    sorted_prices = sorted(prices)
                    median_idx = len(sorted_prices) // 2
                    median_price = sorted_prices[median_idx]
                    
                    ward_medians[ward] = {
                        'ward_avg_price_per_sqm': median_price,
                        'ward_property_count': len(prices),
                        'source': 'dynamodb_fallback'
                    }
                    logger.info(f"Fetched DynamoDB median for ward {ward}: {median_price:.0f} yen/sqm from {len(prices)} properties")
                else:
                    logger.warning(f"Insufficient DynamoDB data for ward {ward} ({len(prices)} properties)")
                
            except Exception as e:
                logger.error(f"Failed to query ward {ward} from DynamoDB: {e}")
                continue
        
        return ward_medians
        
    except Exception as e:
        logger.error(f"Failed to initialize DynamoDB table {table_name}: {e}")
        return {}


def process_listings(df: pd.DataFrame, bucket: str, date_str: str) -> List[Dict[str, Any]]:
    """
    Legacy wrapper for backward compatibility.
    
    Args:
        df: Input dataframe
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        List of processed listing dictionaries
    """
    result = process_listings_lean(df, bucket, date_str)
    return result['processed_data']


def process_and_upload_images(photo_filenames: str, bucket: str, date_str: str, listing_id: str) -> List[str]:
    """
    Process image filenames and handle both S3 keys (new format) and filenames (legacy format).
    
    Args:
        photo_filenames: Pipe-separated S3 keys or photo filenames
        bucket: S3 bucket name
        date_str: Processing date string
        listing_id: Listing identifier for image organization
        
    Returns:
        List of S3 URLs for uploaded images
    """
    if not photo_filenames or str(photo_filenames).lower() in ['nan', 'none', '']:
        return []
    
    # Split by pipe and clean entries
    entries = [f.strip() for f in str(photo_filenames).split('|') if f.strip()]
    
    image_urls = []
    
    for i, entry in enumerate(entries):
        # Check if entry is already an S3 key (new format from updated scraper)
        if entry.startswith('raw/') and '/images/' in entry:
            # Entry is already an S3 key - use directly
            image_url = f"s3://{bucket}/{entry}"
            image_urls.append(image_url)
            logger.info(f"Using S3 key from scraper: {entry}")
        
        elif entry.startswith('local_image_'):
            # Local testing mode - create placeholder S3 URL
            clean_filename = entry.replace('local_image_', '').split('_', 1)[-1]
            s3_key = f"raw/{date_str}/images/{listing_id}_{i}_{quote(clean_filename)}"
            image_url = f"s3://{bucket}/{s3_key}"
            image_urls.append(image_url)
            logger.info(f"Converting local image reference to S3 URL: {s3_key}")
        
        else:
            # Legacy format - treat as filename and construct S3 URL
            s3_key = f"raw/{date_str}/images/{listing_id}_{i}_{quote(entry)}"
            image_url = f"s3://{bucket}/{s3_key}"
            image_urls.append(image_url)
            logger.info(f"Processing legacy filename format: {entry}")
    
    return image_urls


def clean_for_json(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean data for JSON serialization by handling pandas data types and NaN values.
    
    Args:
        item: Dictionary that may contain pandas data types and NaN values
        
    Returns:
        Dictionary with all values converted to JSON-serializable types
    """
    cleaned = {}
    for key, value in item.items():
        try:
            # Handle None first
            if value is None:
                cleaned[key] = None
            # Handle pandas/numpy NaN and NaT
            elif pd.isna(value):
                cleaned[key] = None
            # Handle pandas Timestamp
            elif isinstance(value, pd.Timestamp):
                cleaned[key] = value.isoformat() if not pd.isna(value) else None
            # Handle pandas Series (should not happen but just in case)
            elif isinstance(value, pd.Series):
                cleaned[key] = value.tolist() if not value.empty else None
            # Handle numpy integers and floats
            elif hasattr(value, 'item'):  # numpy scalars
                try:
                    cleaned[key] = value.item()
                except (ValueError, OverflowError):
                    cleaned[key] = str(value)
            # Handle regular float NaN
            elif isinstance(value, float) and math.isnan(value):
                cleaned[key] = None
            # Handle pandas nullable integers (Int64, etc.)
            elif hasattr(value, 'dtype') and 'Int' in str(value.dtype):
                cleaned[key] = int(value) if not pd.isna(value) else None
            # Handle pandas Decimal/currency types
            elif hasattr(value, 'dtype') and 'decimal' in str(value.dtype).lower():
                cleaned[key] = float(value) if not pd.isna(value) else None
            # Handle string representations of NaN/NaT
            elif isinstance(value, str) and value.lower() in ['nan', 'nat', 'none', '<na>']:
                cleaned[key] = None
            # Handle pandas extension arrays and nullable types
            elif hasattr(value, '_is_na') and value._is_na:
                cleaned[key] = None
            else:
                cleaned[key] = value
        except (TypeError, ValueError, AttributeError) as e:
            # Last resort: convert to string or None
            try:
                str_value = str(value)
                if str_value.lower() in ['nan', 'nat', 'none', '<na>']:
                    cleaned[key] = None
                else:
                    cleaned[key] = str_value
            except:
                logger.warning(f"Failed to serialize value for key '{key}': {e}")
                cleaned[key] = None
    return cleaned


def save_jsonl_to_s3(data: List[Dict[str, Any]], bucket: str, key: str) -> None:
    """
    Save processed data as JSONL to S3.
    
    Args:
        data: List of listing dictionaries
        bucket: S3 bucket name
        key: S3 key for output file
    """
    # Convert to JSONL format with NaN handling
    jsonl_lines = []
    for item in data:
        # Replace NaN values with None for JSON serialization
        cleaned_item = clean_for_json(item)
        jsonl_lines.append(json.dumps(cleaned_item, ensure_ascii=False))
    
    jsonl_content = '\n'.join(jsonl_lines)
    
    # Upload to S3 with error handling and retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=jsonl_content.encode('utf-8'),
                ContentType='application/jsonl'
            )
            logger.info(f"Successfully uploaded {len(data)} items to s3://{bucket}/{key}")
            break
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"S3 upload attempt {attempt + 1} failed (error: {error_code}), retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to upload to S3 after {max_retries} attempts: {e}")
                raise Exception(f"S3 upload failed after {max_retries} attempts: {error_code} - {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during S3 upload attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Retrying S3 upload in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise Exception(f"S3 upload failed after {max_retries} attempts due to unexpected error: {str(e)}")
    
    logger.info(f"Saved JSONL to s3://{bucket}/{key}")


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-15'  # Use a date that likely has data
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))