"""
ETL Lambda function for processing real estate listings CSV data.
Adds numeric features and expands photo filenames to S3 URLs.
"""
import json
import logging
import math
import os
from datetime import datetime, timedelta
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
        
        bucket = os.environ['OUTPUT_BUCKET']
        
        logger.info(f"Processing listings for date: {date_str}")
        
        # Read CSV from S3
        csv_key = f"scraper-output/chofu-city-listings-{date_str}.csv"
        logger.info(f"Attempting to read CSV from s3://{bucket}/{csv_key}")
        
        # List files in the bucket to help debug
        try:
            list_response = s3_client.list_objects_v2(
                Bucket=bucket, 
                Prefix="scraper-output/chofu-city-listings-",
                MaxKeys=10
            )
            if 'Contents' in list_response:
                available_files = [obj['Key'] for obj in list_response['Contents']]
                logger.info(f"Available listing files: {available_files}")
                
                # If the requested file doesn't exist, try to find the most recent one
                if csv_key not in available_files and available_files:
                    # Sort files by date in filename
                    sorted_files = sorted(available_files, reverse=True)
                    latest_file = sorted_files[0]
                    logger.warning(f"Requested file {csv_key} not found. Using latest file: {latest_file}")
                    csv_key = latest_file
                    # Extract date from the filename
                    date_str = latest_file.split('listings-')[1].replace('.csv', '')
            else:
                logger.warning("No listing files found in scraper-output/")
        except Exception as list_error:
            logger.error(f"Failed to list bucket contents: {list_error}")
        
        try:
            response = s3_client.get_object(Bucket=bucket, Key=csv_key)
            df = pd.read_csv(response['Body'])
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
            'processed_data': [clean_for_json(item) for item in processed_data[:100]]  # Pass first 100 for next step
        }
        
    except Exception as e:
        logger.error(f"ETL processing failed: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'date': date_str if 'date_str' in locals() else 'unknown',
            'bucket': bucket if 'bucket' in locals() else 'unknown'
        }


def process_listings(df: pd.DataFrame, bucket: str, date_str: str) -> List[Dict[str, Any]]:
    """
    Simplified processing - just handle images and pass raw data to OpenAI.
    
    Args:
        df: Input dataframe
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        List of processed listing dictionaries with raw data preserved
    """
    processed = []
    
    for _, row in df.iterrows():
        try:
            # Convert row to dict, keeping all original fields
            listing = row.to_dict()
            
            # Only process images if present
            if 'photo_filenames' in listing and listing['photo_filenames']:
                image_urls = process_and_upload_images(listing['photo_filenames'], bucket, date_str, listing.get('id', 'unknown'))
                listing['uploaded_image_urls'] = image_urls
                
                # Include ALL photos for comprehensive AI analysis (exterior, interior, neighborhood)
                listing['interior_photos'] = image_urls  # Now includes all images, not just interior
            else:
                listing['uploaded_image_urls'] = []
                listing['interior_photos'] = []
            
            # Add minimal metadata
            listing['processed_date'] = date_str
            listing['source'] = 'homes_scraper'
            
            # Only skip if completely empty or missing ID
            if not str(listing.get('id', '')).strip():
                continue
                
            processed.append(listing)
            
        except Exception as e:
            logger.warning(f"Failed to process listing {row.get('id', 'unknown')}: {e}")
            continue
    
    return processed


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


def extract_interior_photos(image_urls: List[str]) -> List[str]:
    """
    Extract interior photos from the list of image URLs based on filename keywords.
    
    Args:
        image_urls: List of S3 image URLs
        
    Returns:
        List of interior photo URLs
    """
    interior_photos = []
    interior_keywords = ['living', 'bedroom', 'kitchen', 'interior', 'room', 'dining', 'bath']
    
    for url in image_urls:
        # Extract filename from URL for keyword matching
        filename = url.split('/')[-1].lower()
        if any(keyword in filename for keyword in interior_keywords):
            interior_photos.append(url)
    
    return interior_photos


def clean_for_json(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replace NaN values with None for JSON serialization.
    
    Args:
        item: Dictionary that may contain NaN values
        
    Returns:
        Dictionary with NaN values replaced with None
    """
    cleaned = {}
    for key, value in item.items():
        try:
            if isinstance(value, float) and math.isnan(value):
                cleaned[key] = None
            elif pd.isna(value):  # Handle pandas NaN/NaT
                cleaned[key] = None
            elif str(value).lower() in ['nan', 'nat', 'none']:
                cleaned[key] = None
            else:
                cleaned[key] = value
        except (TypeError, ValueError):
            # Handle cases where isnan/isna fails (e.g., on arrays)
            if str(value).lower() in ['nan', 'nat', 'none']:
                cleaned[key] = None
            else:
                cleaned[key] = value
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
        'date': '2025-07-15'  # Use a date that likely has data
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))