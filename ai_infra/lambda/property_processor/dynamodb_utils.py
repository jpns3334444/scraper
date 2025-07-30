#!/usr/bin/env python3
"""
DynamoDB utilities for deduplication and data persistence
"""
import boto3
import re
from datetime import datetime
import time

def setup_dynamodb_client(logger=None):
    """Setup DynamoDB client and table reference"""
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table_name = 'tokyo-real-estate-ai-analysis-db'
        table = dynamodb.Table(table_name)
        
        # Test connection
        table.load()
        
        if logger:
            logger.debug(f"DynamoDB connected: {table_name}")
        
        return dynamodb, table
        
    except Exception as e:
        if logger:
            logger.error(f"DynamoDB setup failed: {str(e)}")
        raise

def extract_property_id_from_url(url):
    """Extract property ID from listing URL"""
    patterns = [
        r'/mansion/b-(\d+)/?$',
        r'/b-(\d+)/?$',
        r'property[_-]?id[=:](\d+)',
        r'mansion[_-]?(\d{8,})',
        r'/(\d{10,})/?$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None

def create_property_id_key(raw_property_id, date_str=None):
    """Create property_id key for DynamoDB"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    return f"PROP#{date_str}_{raw_property_id}"

def load_all_existing_properties(table, logger=None):
    """Load all existing properties from DynamoDB"""
    if logger:
        logger.info("Loading existing properties from DynamoDB...")
    
    existing_properties = {}
    
    try:
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        }
        
        items_processed = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                property_id = item.get('property_id', '')
                if property_id and '#' in property_id and '_' in property_id:
                    raw_property_id = property_id.split('#')[1].split('_')[1]
                    if raw_property_id:
                        existing_properties[raw_property_id] = {
                            'property_id': item.get('property_id'),
                            'price': int(item.get('price', 0)),
                            'listing_url': item.get('listing_url', ''),
                            'analysis_date': item.get('analysis_date', '')
                        }
                        items_processed += 1
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Loaded {items_processed} existing properties")
        
        return existing_properties
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to load properties: {str(e)}")
        return {}

def save_complete_properties_to_dynamodb(properties_data, config, logger=None):
    """Save successfully scraped properties to DynamoDB"""
    if not properties_data:
        return 0
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table_name = config.get('dynamodb_table', 'tokyo-real-estate-ai-analysis-db')
        table = dynamodb.Table(table_name)
        
        saved_count = 0
        error_count = 0
        
        # Filter out properties with errors
        successful_properties = [p for p in properties_data if 'error' not in p]
        
        if logger:
            logger.info(f"Saving {len(successful_properties)} properties to DynamoDB...")
        
        # Save in batches
        with table.batch_writer() as batch:
            for property_data in successful_properties:
                try:
                    record = create_complete_property_record(property_data, config, logger)
                    
                    if record and record.get('property_id') and record.get('sort_key'):
                        batch.put_item(Item=record)
                        saved_count += 1
                        
                        if saved_count % 25 == 0:
                            if logger:
                                logger.debug(f"Progress: {saved_count}/{len(successful_properties)}")
                    else:
                        error_count += 1
                        
                except Exception as e:
                    error_count += 1
                    if logger:
                        logger.error(f"Error saving property: {str(e)}")
        
        if logger:
            logger.debug(f"DynamoDB save complete: {saved_count} saved, {error_count} errors")
        
        return saved_count
        
    except Exception as e:
        if logger:
            logger.error(f"Fatal DynamoDB error: {str(e)}")
        return 0

def create_complete_property_record(property_data, config, logger=None):
    """Create a complete property record with all enriched fields"""
    try:
        # Extract property ID
        if not property_data.get('property_id'):
            raw_property_id = extract_property_id_from_url(property_data.get('url', ''))
            if raw_property_id:
                property_data['property_id'] = create_property_id_key(raw_property_id)
        
        property_id = property_data.get('property_id')
        if not property_id:
            return None
        
        now = datetime.now()
        
        # Create district key for GSI
        ward = property_data.get('ward', '')
        district_key = f"DIST#{ward.replace(' ', '_')}" if ward else None
        
        # Create record with all fields
        record = {
            'property_id': property_id,
            'sort_key': 'META',
            'listing_url': property_data.get('url', ''),
            'listing_status': 'scraped',
            'scraped_date': now.isoformat(),
            'analysis_date': now.isoformat(),
            'data_source': 'scraper_complete',
            'analysis_yymm': now.strftime('%Y-%m'),
            'invest_partition': 'SCRAPED',
            
            # Core numeric fields (normalized)
            'price': int(property_data.get('price', 0)) if property_data.get('price') else 0,
            'size_sqm': float(property_data.get('size_sqm', 0)) if property_data.get('size_sqm') else 0,
            'price_per_sqm': float(property_data.get('price_per_sqm', 0)) if property_data.get('price_per_sqm') else 0,
            'building_age_years': int(property_data.get('building_age_years', 0)) if property_data.get('building_age_years') is not None else None,
            'floor': int(property_data.get('floor', 0)) if property_data.get('floor') is not None else None,
            'total_floors': int(property_data.get('total_floors', 0)) if property_data.get('total_floors') is not None else None,
            'management_fee': float(property_data.get('management_fee', 0)) if property_data.get('management_fee') else 0,
            'repair_reserve_fee': float(property_data.get('repair_reserve_fee', 0)) if property_data.get('repair_reserve_fee') else 0,
            'monthly_costs': float(property_data.get('monthly_costs', 0)) if property_data.get('monthly_costs') else 0,
            'total_monthly_costs': float(property_data.get('total_monthly_costs', 0)) if property_data.get('total_monthly_costs') else 0,
            'station_distance_minutes': int(property_data.get('station_distance_minutes', 0)) if property_data.get('station_distance_minutes') is not None else None,
            'num_bedrooms': int(property_data.get('num_bedrooms', 0)) if property_data.get('num_bedrooms') is not None else None,
            
            # Location fields
            'ward': ward,
            'district': property_data.get('district', ''),
            'district_key': district_key,  # For GSI queries
            
            # Property details (raw Japanese text)
            'price_display': property_data.get('価格', ''),
            'title': property_data.get('title', ''),
            'address': property_data.get('address') or property_data.get('所在地', ''),
            'transportation': property_data.get('station_info') or property_data.get('交通', ''),
            'building_age': property_data.get('building_age_text') or property_data.get('築年月', ''),
            'floor_area': property_data.get('size_sqm_text') or property_data.get('専有面積', ''),
            'balcony_area': property_data.get('balcony_area_text') or property_data.get('バルコニー', ''),
            'floor_number': property_data.get('floor_text') or property_data.get('所在階', ''),
            'total_units': property_data.get('total_units_text') or property_data.get('総戸数', ''),
            'layout': property_data.get('layout_text') or property_data.get('間取り', ''),
            'layout_type': property_data.get('layout_type', ''),
            'direction_facing': property_data.get('direction_facing') or property_data.get('向き', ''),
            'building_name': property_data.get('building_name') or property_data.get('建物名', ''),
            'management_company': property_data.get('管理会社', ''),
            'management_fee_display': property_data.get('management_fee_text') or property_data.get('管理費', ''),
            'repair_fund_display': property_data.get('repair_reserve_fee_text') or property_data.get('修繕積立金', ''),
            
            # Scoring and enrichment fields (if available)
            'final_score': float(property_data.get('final_score', 0)) if property_data.get('final_score') else None,
            'base_score': float(property_data.get('base_score', 0)) if property_data.get('base_score') else None,
            'addon_score': float(property_data.get('addon_score', 0)) if property_data.get('addon_score') else None,
            'adjustment_score': float(property_data.get('adjustment_score', 0)) if property_data.get('adjustment_score') else None,
            'verdict': property_data.get('verdict', ''),
            'ward_discount_pct': float(property_data.get('ward_discount_pct', 0)) if property_data.get('ward_discount_pct') else None,
            'data_quality_penalty': float(property_data.get('data_quality_penalty', 0)) if property_data.get('data_quality_penalty') else None,
            'is_candidate': property_data.get('is_candidate', False),
            
            # Ward median data (if available)
            'ward_avg_price_per_sqm': float(property_data.get('ward_avg_price_per_sqm', 0)) if property_data.get('ward_avg_price_per_sqm') else None,
            'ward_property_count': int(property_data.get('ward_property_count', 0)) if property_data.get('ward_property_count') else None,
            
            # Building median data (if available)
            'building_median_price_per_sqm': float(property_data.get('building_median_price_per_sqm', 0)) if property_data.get('building_median_price_per_sqm') else None,
            'building_property_count': int(property_data.get('building_property_count', 0)) if property_data.get('building_property_count') else None,
            
            # Comparables data (if available)
            'num_comparables': int(property_data.get('num_comparables', 0)) if property_data.get('num_comparables') else 0,
            'comps_avg_price_per_sqm': float(property_data.get('comps_avg_price_per_sqm', 0)) if property_data.get('comps_avg_price_per_sqm') else None,
            'comps_min_price_per_sqm': float(property_data.get('comps_min_price_per_sqm', 0)) if property_data.get('comps_min_price_per_sqm') else None,
            'comps_max_price_per_sqm': float(property_data.get('comps_max_price_per_sqm', 0)) if property_data.get('comps_max_price_per_sqm') else None,
            
            # Image data
            'photo_filenames': property_data.get('photo_filenames', ''),
            'uploaded_image_urls': property_data.get('uploaded_image_urls', []),
            'interior_photos': property_data.get('interior_photos', []),
            'image_count': property_data.get('image_count', 0),
            
            # Metadata
            'extraction_timestamp': property_data.get('extraction_timestamp', now.isoformat()),
            'scraper_session': config.get('session_id', 'unknown'),
            'source': property_data.get('source', 'homes_scraper'),
            'processed_date': property_data.get('processed_date', now.strftime('%Y-%m-%d'))
        }
        
        # Store scoring components if available
        if 'scoring_components' in property_data:
            record['scoring_components'] = property_data['scoring_components']
        
        # Remove empty values and None
        record = {k: v for k, v in record.items() if v is not None and v != '' and v != []}
        
        return record
        
    except Exception as e:
        if logger:
            logger.error(f"Error creating record: {str(e)}")
        return None

def update_listing_with_price_change(existing_record, new_price, table, logger=None):
    """Update existing listing with new price"""
    try:
        property_id = existing_record['property_id']
        old_price = existing_record.get('price', 0)
        now = datetime.now()
        
        # Update META record
        table.update_item(
            Key={'property_id': property_id, 'sort_key': 'META'},
            UpdateExpression="SET price = :new_price, analysis_date = :now, listing_status = :status",
            ExpressionAttributeValues={
                ':new_price': new_price,
                ':now': now.isoformat(),
                ':status': 'price_updated'
            }
        )
        
        # Create price history record
        price_change = new_price - old_price
        price_change_pct = (price_change / old_price * 100) if old_price > 0 else 0
        
        hist_record = {
            'property_id': property_id,
            'sort_key': f"HIST#{now.strftime('%Y-%m-%d_%H:%M:%S')}",
            'price': new_price,
            'previous_price': old_price,
            'price_change_amount': price_change,
            'price_drop_pct': price_change_pct,
            'listing_status': 'price_updated',
            'analysis_date': now.isoformat(),
            'ttl_epoch': int(time.time()) + 60*60*24*365  # 1 year TTL
        }
        
        table.put_item(Item=hist_record)
        
        if logger:
            logger.debug(f"Updated price: {old_price:,} -> {new_price:,}")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to update price: {str(e)}")
        return False

def process_listings_with_existing_check(listings, existing_properties, logger=None):
    """Process listings to categorize as new, price changed, or unchanged"""
    new_urls = []
    price_changed_urls = []
    price_unchanged_urls = []
    
    for url in listings:
        raw_property_id = extract_property_id_from_url(url)
        if not raw_property_id:
            new_urls.append(url)
            continue
        
        if raw_property_id in existing_properties:
            # For now, treat all existing as unchanged
            # Price comparison would require fetching the listing page
            price_unchanged_urls.append(url)
        else:
            new_urls.append(url)
    
    return new_urls, price_changed_urls, price_unchanged_urls

# URL Tracking Table (DYDB2) Functions

def setup_url_tracking_table(table_name='tokyo-real-estate-urls', logger=None):
    """Setup URL tracking table reference"""
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table = dynamodb.Table(table_name)
        
        # Test connection
        table.load()
        
        if logger:
            logger.debug(f"URL tracking table connected: {table_name}")
        
        return dynamodb, table
        
    except Exception as e:
        if logger:
            logger.error(f"URL tracking table setup failed: {str(e)}")
        raise

def put_url_to_tracking_table(url, table, logger=None):
    """Add URL to tracking table with processed = empty"""
    try:
        table.put_item(
            Item={
                'url': url,
                'processed': ''
            }
        )
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to put URL {url}: {str(e)}")
        return False

def put_urls_batch_to_tracking_table(urls, table, logger=None):
    """Add multiple URLs to tracking table in batch"""
    if not urls:
        return 0
    
    try:
        saved_count = 0
        
        with table.batch_writer() as batch:
            for url in urls:
                try:
                    batch.put_item(
                        Item={
                            'url': url,
                            'processed': ''
                        }
                    )
                    saved_count += 1
                except Exception as e:
                    if logger:
                        logger.error(f"Failed to batch write URL {url}: {str(e)}")
        
        if logger:
            logger.debug(f"Batch wrote {saved_count} URLs to tracking table")
        
        return saved_count
        
    except Exception as e:
        if logger:
            logger.error(f"Batch write failed: {str(e)}")
        return 0

def scan_unprocessed_urls(table, logger=None):
    """Scan for all URLs where processed is empty"""
    unprocessed_urls = []
    
    try:
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('processed').eq('')
        }
        
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                url = item.get('url')
                if url:
                    unprocessed_urls.append(url)
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Found {len(unprocessed_urls)} unprocessed URLs")
        
        return unprocessed_urls
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to scan unprocessed URLs: {str(e)}")
        return []

def mark_url_processed(url, table, logger=None):
    """Mark URL as processed by setting processed = 'Y'"""
    try:
        table.update_item(
            Key={'url': url},
            UpdateExpression="SET #processed = :processed",
            ExpressionAttributeNames={
                '#processed': 'processed'
            },
            ExpressionAttributeValues={
                ':processed': 'Y'
            }
        )
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to mark URL processed {url}: {str(e)}")
        return False

def load_recent_properties_for_comparables(table, ward=None, limit=200, logger=None):
    """Load recent properties for comparables calculation"""
    if logger:
        logger.info(f"Loading recent properties for comparables (ward: {ward}, limit: {limit})")
    
    properties = []
    
    try:
        if ward and ward != 'unknown':
            # Use GSI to query by ward (more efficient)
            district_key = f"DIST#{ward.replace(' ', '_')}"
            try:
                response = table.query(
                    IndexName='district-index',
                    KeyConditionExpression='district_key = :dk',
                    ExpressionAttributeValues={
                        ':dk': district_key
                    },
                    Limit=limit,
                    ScanIndexForward=False  # Most recent first
                )
                properties.extend(response.get('Items', []))
            except:
                # GSI doesn't exist, fall back to scan
                if logger:
                    logger.debug("GSI query failed, falling back to scan")
        
        # If no ward specified or GSI failed, do a general scan
        if not properties:
            scan_kwargs = {
                'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META'),
                'Limit': limit
            }
            
            response = table.scan(**scan_kwargs)
            properties = response.get('Items', [])
        
        # Convert DynamoDB items to dict format
        converted_properties = []
        for prop in properties:
            # Only include properties with required fields for comparables
            if prop.get('price_per_sqm') and prop.get('size_sqm'):
                converted_properties.append({
                    'property_id': prop.get('property_id'),
                    'price': float(prop.get('price', 0)),
                    'size_sqm': float(prop.get('size_sqm', 0)),
                    'price_per_sqm': float(prop.get('price_per_sqm', 0)),
                    'ward': prop.get('ward', 'unknown'),
                    'district': prop.get('district', ''),
                    'building_name': prop.get('building_name', ''),
                    'building_age_years': int(prop.get('building_age_years', 0)) if prop.get('building_age_years') else None,
                    'floor': int(prop.get('floor', 0)) if prop.get('floor') else None,
                    'station_distance_minutes': int(prop.get('station_distance_minutes', 0)) if prop.get('station_distance_minutes') else None,
                    'layout_type': prop.get('layout_type', ''),
                    'analysis_date': prop.get('analysis_date', '')
                })
        
        if logger:
            logger.debug(f"Loaded {len(converted_properties)} properties for comparables")
        
        return converted_properties
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to load properties for comparables: {str(e)}")
        return []

def calculate_ward_medians_from_dynamodb(table, logger=None):
    """Calculate ward median prices from recent DynamoDB data"""
    if logger:
        logger.info("Calculating ward medians from DynamoDB")
    
    ward_data = {}
    
    try:
        # Scan recent properties
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        }
        
        items_processed = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                ward = item.get('ward', 'unknown')
                price_per_sqm = item.get('price_per_sqm')
                
                if ward and ward != 'unknown' and price_per_sqm:
                    if ward not in ward_data:
                        ward_data[ward] = []
                    ward_data[ward].append(float(price_per_sqm))
                    items_processed += 1
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Calculate medians
        ward_medians = {}
        for ward, prices in ward_data.items():
            if len(prices) >= 3:  # Need at least 3 properties for median
                sorted_prices = sorted(prices)
                median_idx = len(sorted_prices) // 2
                median_price = sorted_prices[median_idx]
                
                ward_medians[ward] = {
                    'ward_avg_price_per_sqm': median_price,
                    'ward_property_count': len(prices)
                }
        
        if logger:
            logger.info(f"Calculated medians for {len(ward_medians)} wards from {items_processed} properties")
        
        return ward_medians
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to calculate ward medians: {str(e)}")
        return {}