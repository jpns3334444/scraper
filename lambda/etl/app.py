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
                
                # Extract interior photos for AI analysis
                listing['interior_photos'] = extract_interior_photos(image_urls)
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
    Process image filenames and create S3 URLs. In a real implementation, this would
    handle base64 image extraction and upload to S3.
    
    Args:
        photo_filenames: Pipe-separated photo filenames or base64 image data
        bucket: S3 bucket name
        date_str: Processing date string
        listing_id: Listing identifier for image organization
        
    Returns:
        List of S3 URLs for uploaded images
    """
    if not photo_filenames or str(photo_filenames).lower() in ['nan', 'none', '']:
        return []
    
    # Split by pipe and clean filenames
    filenames = [f.strip() for f in str(photo_filenames).split('|') if f.strip()]
    
    image_urls = []
    
    for i, filename in enumerate(filenames):
        # Create S3 URL - in real implementation, this would be the actual uploaded image URL
        s3_key = f"raw/{date_str}/images/{listing_id}_{i}_{quote(filename)}"
        image_url = f"s3://{bucket}/{s3_key}"
        image_urls.append(image_url)
    
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