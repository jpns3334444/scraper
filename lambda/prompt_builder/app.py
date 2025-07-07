"""
Prompt Builder Lambda function for creating GPT-4.1 vision prompts.
Loads JSONL data, sorts by price_per_m2, and builds vision payload with interior photos.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

SYSTEM_PROMPT = """You are an aggressive Tokyo condo investor.
Goal: pick the FIVE best bargains in this feed.

Rank strictly by:
- lowest price_per_m2 versus 3-year ward median
- structural / cosmetic risks visible in PHOTOS (mold, warped floor, low light)
- walking minutes to nearest station
- south or southeast exposure, open view, balcony usability

Return JSON only:
{
"top_picks":[
{ "id":"...", "score":0-100,
"why":"concise reasoning",
"red_flags":[ "...", ... ] },
...
],
"runners_up":[ ... up to 10 ... ],
"market_notes":"brief observation"
}"""


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for prompt building.
    
    Args:
        event: Lambda event containing processed data from ETL step
        context: Lambda context
        
    Returns:
        Dict containing prompt payload location and metadata
    """
    try:
        date_str = event.get('date')
        bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        
        logger.info(f"Building prompt for date: {date_str}")
        
        # Load processed JSONL data
        jsonl_key = event.get('jsonl_key', f"clean/{date_str}/listings.jsonl")
        listings = load_jsonl_from_s3(bucket, jsonl_key)
        
        logger.info(f"Loaded {len(listings)} listings")
        
        # Sort by price_per_m2 and take top 100
        sorted_listings = sort_and_filter_listings(listings)
        
        logger.info(f"Selected {len(sorted_listings)} top listings by price_per_m2")
        
        # Build GPT-4.1 vision prompt
        prompt_payload = build_vision_prompt(sorted_listings, date_str, bucket)
        
        # Save prompt to S3
        prompt_key = f"prompts/{date_str}/payload.json"
        save_prompt_to_s3(prompt_payload, bucket, prompt_key)
        
        logger.info(f"Successfully built prompt with {len(sorted_listings)} listings")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'prompt_key': prompt_key,
            'listings_count': len(sorted_listings),
            'total_images': sum(len(listing.get('interior_photos', [])) for listing in sorted_listings)
        }
        
    except Exception as e:
        logger.error(f"Prompt building failed: {e}")
        raise


def load_jsonl_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Load JSONL data from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for JSONL file
        
    Returns:
        List of listing dictionaries
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        
        listings = []
        for line in content.strip().split('\n'):
            if line.strip():
                listings.append(json.loads(line))
        
        return listings
        
    except Exception as e:
        logger.error(f"Failed to load JSONL from s3://{bucket}/{key}: {e}")
        raise


def sort_and_filter_listings(listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort listings by price_per_m2 and take top 100.
    
    Args:
        listings: List of listing dictionaries
        
    Returns:
        Filtered and sorted listings
    """
    # Filter out listings without valid price_per_m2
    valid_listings = [
        listing for listing in listings 
        if listing.get('price_per_m2', 0) > 0
    ]
    
    # Sort by price_per_m2 ascending (cheapest first)
    sorted_listings = sorted(valid_listings, key=lambda x: x.get('price_per_m2', float('inf')))
    
    # Take top 100
    return sorted_listings[:100]


def build_vision_prompt(listings: List[Dict[str, Any]], date_str: str, bucket: str) -> Dict[str, Any]:
    """
    Build GPT-4.1 vision prompt payload.
    
    Args:
        listings: List of listing dictionaries
        date_str: Processing date string
        bucket: S3 bucket name
        
    Returns:
        OpenAI Chat API payload dictionary
    """
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": build_user_message_content(listings, date_str, bucket)
        }
    ]
    
    payload = {
        "model": "gpt-4o",  # Use gpt-4o for vision capabilities
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "max_tokens": 4000
    }
    
    return payload


def build_user_message_content(listings: List[Dict[str, Any]], date_str: str, bucket: str) -> List[Dict[str, Any]]:
    """
    Build user message content with text and images.
    
    Args:
        listings: List of listing dictionaries
        date_str: Processing date string
        bucket: S3 bucket name
        
    Returns:
        List of message content items
    """
    content = [
        {
            "type": "text",
            "text": f"Listings scraped on {date_str}:"
        }
    ]
    
    for listing in listings:
        # Add listing data as text
        listing_text = json.dumps({
            "id": listing.get("id"),
            "headline": listing.get("headline"),
            "price_yen": listing.get("price_yen"),
            "area_m2": listing.get("area_m2"),
            "price_per_m2": listing.get("price_per_m2"),
            "age_years": listing.get("age_years"),
            "walk_mins_station": listing.get("walk_mins_station"),
            "ward": listing.get("ward")
        }, ensure_ascii=False, separators=(',', ':'))
        
        content.append({
            "type": "text",
            "text": listing_text
        })
        
        # Add interior photos (max 20 per listing)
        interior_photos = listing.get('interior_photos', [])[:20]
        
        for photo_url in interior_photos:
            # Generate presigned URL for the photo
            presigned_url = generate_presigned_url(photo_url, bucket)
            
            if presigned_url:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": presigned_url,
                        "detail": "low"
                    }
                })
    
    return content


def generate_presigned_url(s3_url: str, bucket: str, expiration: int = 28800) -> str:
    """
    Generate presigned URL for S3 object.
    
    Args:
        s3_url: S3 URL (s3://bucket/key format)
        bucket: S3 bucket name
        expiration: URL expiration time in seconds (default 8 hours)
        
    Returns:
        Presigned URL string or empty string if failed
    """
    try:
        # Extract key from S3 URL
        parsed = urlparse(s3_url)
        if parsed.scheme != 's3':
            logger.warning(f"Invalid S3 URL format: {s3_url}")
            return ""
        
        key = parsed.path.lstrip('/')
        
        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expiration
        )
        
        return presigned_url
        
    except Exception as e:
        logger.warning(f"Failed to generate presigned URL for {s3_url}: {e}")
        return ""


def save_prompt_to_s3(payload: Dict[str, Any], bucket: str, key: str) -> None:
    """
    Save prompt payload to S3.
    
    Args:
        payload: OpenAI API payload dictionary
        bucket: S3 bucket name
        key: S3 key for output file
    """
    try:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(f"Saved prompt payload to s3://{bucket}/{key}")
        
    except Exception as e:
        logger.error(f"Failed to save prompt to S3: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 're-stock',
        'jsonl_key': 'clean/2025-07-07/listings.jsonl'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))