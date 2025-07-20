"""
Prompt Builder Lambda function for creating GPT-4.1 vision prompts.
Loads JSONL data, sorts by price_per_m2, and builds vision payload with interior photos.
"""
import base64
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlparse
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

def decimal_default(obj):
    """JSON serializer for Decimal types from DynamoDB"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

# Initialize DynamoDB table - will be set via environment variable
table = None
if os.environ.get('DYNAMODB_TABLE'):
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

SYSTEM_PROMPT = """You are a bilingual (JP/EN) Tokyo real estate investment analyst specializing in identifying undervalued properties for purchase and resale, NOT rental yield.

# OUTPUT REQUIREMENTS
You must provide your response as a single JSON object with two top-level keys: "database_fields" and "email_report".

1.  **`database_fields`**: A structured JSON object for database storage. The schema for this object is defined below.
2.  **`email_report`**: A complete, self-contained HTML email report for human review.

# `database_fields` JSON SCHEMA:
```json
{
  "property_type": "string (apartment/house/condo/land)",
  "price": "integer or null",
  "price_per_sqm": "integer or null",
  "price_trend": "string (above_market/at_market/below_market) or null",
  "estimated_market_value": "integer or null",
  "price_negotiability_score": "integer 1-10 or null",
  "monthly_management_fee": "integer or null",
  "annual_property_tax": "integer or null",
  "reserve_fund_balance": "integer or null",
  "special_assessments": "integer or null",
  "address": "string or empty string",
  "district": "string or empty string",
  "nearest_station": "string or empty string",
  "station_distance_minutes": "integer or null",
  "building_name": "string or empty string",
  "building_age_years": "integer or null",
  "total_units_in_building": "integer or null",
  "floor_number": "integer or null",
  "total_floors": "integer or null",
  "direction_facing": "string (N/S/E/W/NE/SE/SW/NW) or empty string",
  "corner_unit": "boolean or null",
  "total_sqm": "number or null",
  "num_bedrooms": "integer or null",
  "num_bathrooms": "number or null",
  "balcony_sqm": "number or null",
  "storage_sqm": "number or null",
  "parking_included": "boolean or null",
  "parking_type": "string (covered/uncovered/tandem/none) or null",
  "layout_efficiency_score": "integer 1-10 or null",
  "overall_condition_score": "integer 1-10 or null",
  "natural_light_score": "integer 1-10 or null",
  "view_quality_score": "integer 1-10 or null",
  "mold_detected": "boolean or null",
  "water_damage_detected": "boolean or null",
  "visible_cracks": "boolean or null",
  "renovation_needed": "string (none/minor/major/complete) or null",
  "flooring_condition": "string (excellent/good/fair/poor) or null",
  "kitchen_condition": "string (modern/dated/needs_renovation) or null",
  "bathroom_condition": "string (modern/dated/needs_renovation) or null",
  "wallpaper_present": "boolean or null",
  "tatami_present": "boolean or null",
  "cleanliness_score": "integer 1-10 or null",
  "staging_quality": "string (professional/basic/none) or null",
  "earthquake_resistance_standard": "string (pre-1981/1981/2000) or null",
  "elevator_access": "boolean or null",
  "auto_lock_entrance": "boolean or null",
  "delivery_box": "boolean or null",
  "pet_allowed": "boolean or null",
  "balcony_direction": "string or empty string",
  "double_glazed_windows": "boolean or null",
  "floor_heating": "boolean or null",
  "security_features": "array of strings or []",
  "investment_score": "integer 0-100",
  "rental_yield_estimate": "number or null",
  "appreciation_potential": "string (high/medium/low)",
  "liquidity_score": "integer 1-10",
  "target_tenant_profile": "string or empty string",
  "renovation_roi_potential": "number or null",
  "price_analysis": "string (detailed analysis)",
  "location_assessment": "string (detailed analysis)",
  "condition_assessment": "string (detailed analysis)",
  "investment_thesis": "string (detailed analysis)",
  "competitive_advantages": "array of strings or []",
  "risks": "array of strings or []",
  "recommended_offer_price": "integer or null",
  "recommendation": "string (strong_buy/buy/hold/pass)",
  "confidence_score": "number 0.0-1.0",
  "comparable_properties": "array of property_ids or []",
  "market_days_listed": "integer or null",
  "price_reductions": "integer or null",
  "similar_units_available": "integer or null",
  "recent_sales_same_building": "[{\"property_id\": \"string\", \"price\": integer, \"date\": \"string\"}] or []",
  "neighborhood_trend": "string (appreciating/stable/declining)",
  "image_analysis_model_version": "string or empty string",
  "processing_errors": "array of error messages or []",
  "data_quality_score": "number 0.0-1.0"
}
```

# `email_report` HTML SPECIFICATIONS
Generate a single, complete HTML5 document.
- **Layout**: Use table-based layouts and inline CSS for maximum email client compatibility.
- **Content**: Include a market overview, ranked list of properties, detailed cards for top opportunities, price drop alerts, and actionable next steps.
- **No Scripts**: Do not include any `<script>` tags.

# PRIMARY OBJECTIVE
Find properties priced significantly below market value with strong resale potential. Focus on two categories:
- **Category A - Undervalued Mansions (マンション)**: Reinforced concrete condos (SRC/RC), priced ≥15% below 5-year ward average and same-building comps, preferably ≤20 years old.
- **Category B - Flip-worthy Detached Houses (一戸建て)**: Freehold homes built before 2000, land ≥80m², price ≤¥30,000,000, with renovation ROI ≥30%.

# CRITICAL REMINDERS:
- Your entire output must be a single JSON object.
- The JSON object must have exactly two keys: `database_fields` and `email_report`.
- NEVER fabricate data. Use `null` or empty values for missing information.
- This analysis focuses on resale arbitrage, not rental yield.
"""

def get_market_context() -> Dict[str, Any]:
    """
    Queries DynamoDB to get multiple types of market context:
    1. Top 20 investment properties
    2. Recent price drops
    3. District-specific comparables
    4. Market summary statistics
    """
    if not table:
        logger.warning("DynamoDB table not configured, skipping market context")
        return {}
    
    market_context = {}
    
    try:
        # Get top investment properties
        investment_response = table.query(
            IndexName='GSI_INVEST',
            KeyConditionExpression=Key('invest_partition').eq('INVEST'),
            ScanIndexForward=False,  # Sort by investment_score descending
            Limit=20,
            ProjectionExpression="property_id, investment_score, price, price_per_sqm, district, total_sqm, recommendation, listing_url"
        )
        market_context['top_investments'] = investment_response.get('Items', [])
        
        # Get recent analyses (last 7 days)
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        recent_response = table.query(
            IndexName='GSI_ANALYSIS_DATE',
            KeyConditionExpression=Key('invest_partition').eq('INVEST') & Key('analysis_date').gte(seven_days_ago),
            ScanIndexForward=False,
            Limit=50
        )
        
        # Filter for properties with significant price drops
        recent_items = recent_response.get('Items', [])
        price_drops = [
            {
                'property_id': item['property_id'],
                'price': item['price'],
                'price_per_sqm': item['price_per_sqm'],
                'district': item.get('district', ''),
                'price_trend': item.get('price_trend', '')
            }
            for item in recent_items 
            if item.get('price_trend') == 'below_market'
        ][:10]  # Top 10 price drops
        
        market_context['recent_price_drops'] = price_drops
        
        # Summary statistics
        if recent_items:
            avg_price_per_sqm = sum(item.get('price_per_sqm', 0) for item in recent_items) / len(recent_items)
            avg_investment_score = sum(item.get('investment_score', 0) for item in recent_items) / len(recent_items)
            
            market_context['market_summary'] = {
                'properties_analyzed_last_7_days': len(recent_items),
                'average_price_per_sqm': int(avg_price_per_sqm),
                'average_investment_score': int(avg_investment_score),
                'strong_buy_count': sum(1 for item in recent_items if item.get('recommendation') == 'strong_buy'),
                'buy_count': sum(1 for item in recent_items if item.get('recommendation') == 'buy')
            }
        
    except Exception as e:
        logger.error(f"Failed to query DynamoDB for market context: {e}")
        return {}
    
    return market_context


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
        
        # Get market context from DynamoDB
        market_context = get_market_context()
        logger.info(f"Retrieved market context with {len(market_context.get('top_investments', []))} top investments")
        
        # Load processed JSONL data
        jsonl_key = event.get('jsonl_key', f"clean/{date_str}/listings.jsonl")
        listings = load_jsonl_from_s3(bucket, jsonl_key)
        
        logger.info(f"Loaded {len(listings)} listings")
        
        # Sort by price_per_m2 and take top 5 for testing
        sorted_listings = sort_and_filter_listings(listings)
        
        logger.info(f"Selected {len(sorted_listings)} top listings by price_per_m2")
        
        # Build individual batch requests for each listing
        batch_requests = build_batch_requests(sorted_listings, date_str, bucket, market_context)
        
        # Save batch requests as JSONL to S3
        prompt_key = f"prompts/{date_str}/batch_requests.jsonl"
        save_batch_requests_to_s3(batch_requests, bucket, prompt_key)
        
        logger.info(f"Successfully built prompt with {len(sorted_listings)} listings")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'prompt_key': prompt_key,
            'listings_count': len(sorted_listings),
            'total_images': sum(len(prioritize_images(listing.get('interior_photos', []))) for listing in sorted_listings),
            'batch_requests_count': len(batch_requests)
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
    Filter listings for analysis. Let the LLM handle Japanese field names and parsing.
    Just filter out completely empty entries.
    
    Args:
        listings: List of listing dictionaries
        
    Returns:
        Filtered listings (raw Japanese data preserved)
    """
    # Filter out listings that are clearly invalid (no ID or URL)
    valid_listings = [
        listing for listing in listings 
        if listing.get('id') or listing.get('url')
    ]
    
    # Take up to 100 listings for analysis (or all if fewer)
    return valid_listings[:100]


def build_batch_requests(listings: List[Dict[str, Any]], date_str: str, bucket: str, market_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build individual batch requests for each listing.
    
    Args:
        listings: List of listing dictionaries
        date_str: Processing date string
        bucket: S3 bucket name
        market_context: Market context data from DynamoDB
        
    Returns:
        List of batch request dictionaries
    """
    batch_requests = []
    
    # Update system prompt with market context
    market_context_text = json.dumps(market_context, ensure_ascii=False, indent=2, default=decimal_default) if market_context else "No recent market data available."
    updated_system_prompt = SYSTEM_PROMPT + f"""

# Current Market Analysis Data

Here is comprehensive market context from recently analyzed properties:

```json
{market_context_text}
```

Use this data to:
- Compare new properties against top performers
- Identify if pricing is competitive based on recent trends
- Spot opportunities based on price drops and market movements
- Provide data-driven investment recommendations

When analyzing a property, reference specific comparable properties from this dataset when relevant.
"""
    
    for i, listing in enumerate(listings):
        # Create individual prompt for this listing
        messages = [
            {
                "role": "system",
                "content": updated_system_prompt
            },
            {
                "role": "user",
                "content": build_individual_listing_content(listing, date_str, bucket)
            }
        ]
        
        # Create batch request format
        batch_request = {
            "custom_id": f"listing-analysis-{date_str}-{listing.get('id', i)}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "o3",  # Use o3 model (supports vision)
                "messages": messages,
                "max_completion_tokens": 8000
            }
        }
        
        batch_requests.append(batch_request)
    
    return batch_requests


def build_individual_listing_content(listing: Dict[str, Any], date_str: str, bucket: str) -> List[Dict[str, Any]]:
    """
    Build user message content for a single listing with all its images.
    
    Args:
        listing: Single listing dictionary
        date_str: Processing date string
        bucket: S3 bucket name
        
    Returns:
        List of message content items for this listing
    """
    content = [
        {
            "type": "text",
            "text": f"Analyze this individual real estate listing scraped on {date_str}. Parse and analyze ALL data including Japanese fields."
        }
    ]
    
    # Create a clean copy excluding image processing metadata
    clean_listing = {k: v for k, v in listing.items() 
                    if k not in ['uploaded_image_urls', 'processed_date', 'source']}
    
    # Pass ALL raw fields to OpenAI - let it handle the parsing
    listing_text = json.dumps(clean_listing, ensure_ascii=False, indent=2)
    
    content.append({
        "type": "text", 
        "text": f"LISTING DATA (includes 'url' field for property link):\n{listing_text}"
    })
    
    # Add all available property images with smart prioritization
    all_photos = listing.get('interior_photos', [])
    prioritized_photos = prioritize_images(all_photos)
    
    content.append({
        "type": "text",
        "text": f"Below are all available property images (exterior, interior, neighborhood, etc.) for this listing ({len(prioritized_photos)} images):"
    })
    
    for photo_url in prioritized_photos:
        # Convert S3 image to base64 data URL for OpenAI
        data_url = get_image_as_base64_data_url(photo_url, bucket)
        
        if data_url:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                    "detail": "low"
                }
            })
    
    # Add instruction for individual listing analysis
    content.append({
        "type": "text",
        "text": "IMPORTANT: Analyze this single property and return the full JSON object with `database_fields` and `email_report` as top-level keys, following all instructions in the system prompt."
    })
    
    return content


def prioritize_images(image_urls: List[str]) -> List[str]:
    """
    Prioritize images to show the most important ones first.
    Prioritizes: exterior (1-2), interior living spaces (5-6), kitchen/bath (3-4), then others.
    
    Args:
        image_urls: List of all image URLs
        
    Returns:
        List of up to 20 prioritized image URLs
    """
    if not image_urls:
        return []
    
    # Categorize images based on URL/filename
    exterior = []
    living_spaces = []
    kitchen_bath = []
    others = []
    
    for url in image_urls:
        filename = url.split('/')[-1].lower()
        
        if any(kw in filename for kw in ['exterior', 'outside', 'building', 'entrance']):
            exterior.append(url)
        elif any(kw in filename for kw in ['living', 'bedroom', 'room']):
            living_spaces.append(url)
        elif any(kw in filename for kw in ['kitchen', 'bath', 'toilet', 'dining']):
            kitchen_bath.append(url)
        else:
            others.append(url)
    
    # Prioritize and limit each category
    prioritized = (
        exterior[:2] +           # Max 2 exterior shots
        living_spaces[:8] +      # Max 8 living spaces
        kitchen_bath[:4] +       # Max 4 kitchen/bath
        others[:6]               # Max 6 others
    )
    
    # Return up to 20 images total
    return prioritized[:20]


def get_image_as_base64_data_url(s3_url: str, bucket: str) -> str:
    """
    Download S3 image and convert to base64 data URL for OpenAI.
    
    Args:
        s3_url: S3 URL (s3://bucket/key format)
        bucket: S3 bucket name
        
    Returns:
        Base64 data URL string or empty string if failed
    """
    try:
        # Extract key from S3 URL
        parsed = urlparse(s3_url)
        if parsed.scheme != 's3':
            logger.warning(f"Invalid S3 URL format: {s3_url}")
            return ""
        
        key = parsed.path.lstrip('/')
        
        # Download image from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        image_data = response['Body'].read()
        
        # Determine MIME type from file extension
        file_ext = key.lower().split('.')[-1]
        mime_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        mime_type = mime_type_map.get(file_ext, 'image/jpeg')
        
        # Convert to base64
        base64_data = base64.b64encode(image_data).decode('utf-8')
        
        # Create data URL
        data_url = f"data:{mime_type};base64,{base64_data}"
        
        return data_url
        
    except Exception as e:
        logger.warning(f"Failed to convert S3 image to base64 data URL for {s3_url}: {e}")
        return ""


def save_batch_requests_to_s3(batch_requests: List[Dict[str, Any]], bucket: str, key: str) -> None:
    """
    Save batch requests as JSONL to S3.
    
    Args:
        batch_requests: List of batch request dictionaries
        bucket: S3 bucket name
        key: S3 key for saving
    """
    try:
        # Convert to JSONL format (one JSON object per line)
        jsonl_lines = []
        for request in batch_requests:
            jsonl_lines.append(json.dumps(request, ensure_ascii=False))
        
        content = '\n'.join(jsonl_lines)
        
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType='application/x-ndjson'
        )
        
        logger.info(f"Saved {len(batch_requests)} batch requests to s3://{bucket}/{key}")
        
    except Exception as e:
        logger.error(f"Failed to save batch requests to S3: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 'tokyo-real-estate-ai-data',
        'jsonl_key': 'clean/2025-07-07/listings.jsonl'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))