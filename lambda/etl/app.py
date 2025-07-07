"""
ETL Lambda function for processing real estate listings CSV data.
Adds numeric features and expands photo filenames to S3 URLs.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import boto3
import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')


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
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
        elif 'T' in date_str:  # Handle ISO datetime format from EventBridge
            date_str = datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d')
        
        bucket = os.environ['OUTPUT_BUCKET']
        
        logger.info(f"Processing listings for date: {date_str}")
        
        # Read CSV from S3
        csv_key = f"raw/{date_str}/listings.csv"
        logger.info(f"Reading CSV from s3://{bucket}/{csv_key}")
        
        try:
            response = s3_client.get_object(Bucket=bucket, Key=csv_key)
            df = pd.read_csv(response['Body'])
        except Exception as e:
            logger.error(f"Failed to read CSV: {e}")
            raise
        
        logger.info(f"Loaded {len(df)} listings from CSV")
        
        # Process the data
        processed_data = process_listings(df, bucket, date_str)
        
        # Save as JSONL
        jsonl_key = f"clean/{date_str}/listings.jsonl"
        save_jsonl_to_s3(processed_data, bucket, jsonl_key)
        
        logger.info(f"Successfully processed {len(processed_data)} listings")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'jsonl_key': jsonl_key,
            'listings_count': len(processed_data),
            'processed_data': processed_data[:100]  # Pass first 100 for next step
        }
        
    except Exception as e:
        logger.error(f"ETL processing failed: {e}")
        raise


def process_listings(df: pd.DataFrame, bucket: str, date_str: str) -> List[Dict[str, Any]]:
    """
    Process listings dataframe and add computed features.
    
    Args:
        df: Input dataframe
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        List of processed listing dictionaries
    """
    processed = []
    
    for _, row in df.iterrows():
        try:
            listing = process_single_listing(row, bucket, date_str)
            if listing:
                processed.append(listing)
        except Exception as e:
            logger.warning(f"Failed to process listing {row.get('id', 'unknown')}: {e}")
            continue
    
    return processed


def process_single_listing(row: pd.Series, bucket: str, date_str: str) -> Optional[Dict[str, Any]]:
    """
    Process a single listing row.
    
    Args:
        row: Pandas series representing one listing
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        Processed listing dictionary or None if invalid
    """
    try:
        # Extract basic fields
        listing_id = str(row.get('id', ''))
        headline = str(row.get('headline', ''))
        price_yen = pd.to_numeric(row.get('price_yen', 0), errors='coerce')
        area_m2 = pd.to_numeric(row.get('area_m2', 0), errors='coerce')
        year_built = pd.to_numeric(row.get('year_built', 0), errors='coerce')
        walk_mins_station = pd.to_numeric(row.get('walk_mins_station', 0), errors='coerce')
        ward = str(row.get('ward', ''))
        photo_filenames = str(row.get('photo_filenames', ''))
        
        # Skip if missing critical data
        if not listing_id or price_yen <= 0 or area_m2 <= 0:
            return None
        
        # Compute derived features
        price_per_m2 = price_yen / area_m2 if area_m2 > 0 else 0
        current_year = datetime.now().year
        age_years = current_year - year_built if year_built > 0 else 0
        
        # Process photo filenames
        photo_urls, interior_photos = process_photos(photo_filenames, bucket, date_str)
        
        listing = {
            'id': listing_id,
            'headline': headline,
            'price_yen': int(price_yen),
            'area_m2': float(area_m2),
            'year_built': int(year_built) if year_built > 0 else None,
            'walk_mins_station': float(walk_mins_station),
            'ward': ward,
            'price_per_m2': round(price_per_m2, 2),
            'age_years': int(age_years),
            'photo_urls': photo_urls,
            'interior_photos': interior_photos,
            'photo_count': len(photo_urls),
            'interior_photo_count': len(interior_photos)
        }
        
        return listing
        
    except Exception as e:
        logger.warning(f"Error processing listing: {e}")
        return None


def process_photos(photo_filenames: str, bucket: str, date_str: str) -> tuple[List[str], List[str]]:
    """
    Process photo filenames and categorize interior photos.
    
    Args:
        photo_filenames: Pipe-separated photo filenames
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        Tuple of (all_photo_urls, interior_photo_urls)
    """
    if not photo_filenames or photo_filenames.lower() in ['nan', 'none', '']:
        return [], []
    
    # Split by pipe and clean filenames
    filenames = [f.strip() for f in photo_filenames.split('|') if f.strip()]
    
    photo_urls = []
    interior_photos = []
    
    interior_keywords = ['living', 'bedroom', 'kitchen', 'interior', 'room', 'dining']
    
    for filename in filenames:
        # Create S3 URL
        s3_key = f"raw/{date_str}/images/{quote(filename)}"
        photo_url = f"s3://{bucket}/{s3_key}"
        photo_urls.append(photo_url)
        
        # Check if it's an interior photo
        filename_lower = filename.lower()
        if any(keyword in filename_lower for keyword in interior_keywords):
            interior_photos.append(photo_url)
    
    return photo_urls, interior_photos


def save_jsonl_to_s3(data: List[Dict[str, Any]], bucket: str, key: str) -> None:
    """
    Save processed data as JSONL to S3.
    
    Args:
        data: List of listing dictionaries
        bucket: S3 bucket name
        key: S3 key for output file
    """
    # Convert to JSONL format
    jsonl_content = '\n'.join(json.dumps(item, ensure_ascii=False) for item in data)
    
    # Upload to S3
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=jsonl_content.encode('utf-8'),
        ContentType='application/jsonl'
    )
    
    logger.info(f"Saved JSONL to s3://{bucket}/{key}")


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))