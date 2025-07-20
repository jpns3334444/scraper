"""
Prompt Builder Lambda function for creating GPT-4.1 vision prompts.
Loads JSONL data, sorts by price_per_m2, and builds vision payload with interior photos.
"""
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlparse
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

# Import our structured logger
try:
    from common.logger import get_logger, lambda_log_context
    logger = get_logger(__name__)
except ImportError:
    import logging
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

def load_system_prompt() -> str:
    """
    Load the system prompt from external file.
    
    Returns:
        System prompt string
    """
    try:
        # Try to load from file in same directory
        prompt_file = Path(__file__).parent / 'system_prompt.txt'
        if prompt_file.exists():
            return prompt_file.read_text(encoding='utf-8')
        
        # Fallback to inline prompt for testing
        logger.warning("system_prompt.txt not found, using fallback prompt")
        return """You are a bilingual (JP/EN) Tokyo real estate investment analyst.
        
        Analyze the provided property data and return a JSON object with 'database_fields' and 'email_report' keys.
        
        For database_fields, provide structured analysis data.
        For email_report, provide a complete HTML email report.
        
        Focus on identifying undervalued properties with strong resale potential.
        NEVER fabricate data - use null for missing information."""
        
    except Exception as e:
        logger.error(f"Failed to load system prompt: {e}")
        return "You are a real estate analyst. Analyze the property and return JSON with database_fields and email_report."

def get_market_context(target_districts: List[str] = None) -> Dict[str, Any]:
    """
    Queries DynamoDB to get comprehensive market context.
    
    Args:
        target_districts: List of district names to focus analysis on
        
    Returns:
        Dictionary containing market context data:
        - top_investments: Best performing properties
        - recent_price_drops: Properties with significant price reductions
        - district_analysis: District-specific market data
        - market_summary: Overall market statistics
        - comparable_properties: Similar properties for comparison
    """
    if not table:
        logger.warning("DynamoDB table not configured, skipping market context")
        return {}
    
    market_context = {}
    
    try:
        # Get top investment properties with enhanced filtering
        investment_response = table.query(
            IndexName='GSI_INVEST',
            KeyConditionExpression=Key('invest_partition').eq('INVEST'),
            ScanIndexForward=False,  # Sort by investment_score descending
            Limit=30,
            ProjectionExpression="property_id, investment_score, price, price_per_sqm, district, total_sqm, recommendation, listing_url, property_type, building_age_years"
        )
        top_investments = investment_response.get('Items', [])
        
        # Filter and categorize top investments
        market_context['top_investments'] = {
            'all': top_investments[:20],
            'mansions': [p for p in top_investments if p.get('property_type') == 'apartment'][:10],
            'houses': [p for p in top_investments if p.get('property_type') == 'house'][:10]
        }
        
        # Get recent analyses with extended time range
        fourteen_days_ago = (datetime.utcnow() - timedelta(days=14)).isoformat()
        recent_response = table.query(
            IndexName='GSI_ANALYSIS_DATE',
            KeyConditionExpression=Key('invest_partition').eq('INVEST') & Key('analysis_date').gte(fourteen_days_ago),
            ScanIndexForward=False,
            Limit=100
        )
        
        recent_items = recent_response.get('Items', [])
        
        # Enhanced price drop analysis
        price_drops = []
        for item in recent_items:
            if item.get('price_trend') == 'below_market':
                price_drops.append({
                    'property_id': item['property_id'],
                    'price': item.get('price'),
                    'price_per_sqm': item.get('price_per_sqm'),
                    'district': item.get('district', ''),
                    'price_trend': item.get('price_trend', ''),
                    'investment_score': item.get('investment_score', 0),
                    'property_type': item.get('property_type', ''),
                    'price_negotiability_score': item.get('price_negotiability_score')
                })
        
        # Sort by investment score and take top 15
        price_drops.sort(key=lambda x: x.get('investment_score', 0), reverse=True)
        market_context['recent_price_drops'] = price_drops[:15]
        
        # District-specific analysis
        district_data = {}
        for item in recent_items:
            district = item.get('district', 'Unknown')
            if district not in district_data:
                district_data[district] = {
                    'properties': [],
                    'avg_price_per_sqm': 0,
                    'avg_investment_score': 0,
                    'price_trend_distribution': {'above_market': 0, 'at_market': 0, 'below_market': 0}
                }
            
            district_data[district]['properties'].append(item)
            trend = item.get('price_trend', 'at_market')
            if trend in district_data[district]['price_trend_distribution']:
                district_data[district]['price_trend_distribution'][trend] += 1
        
        # Calculate district averages
        for district, data in district_data.items():
            properties = data['properties']
            if properties:
                data['avg_price_per_sqm'] = int(sum(p.get('price_per_sqm', 0) for p in properties) / len(properties))
                data['avg_investment_score'] = int(sum(p.get('investment_score', 0) for p in properties) / len(properties))
                data['property_count'] = len(properties)
        
        market_context['district_analysis'] = district_data
        
        # Enhanced market summary
        if recent_items:
            total_properties = len(recent_items)
            avg_price_per_sqm = sum(item.get('price_per_sqm', 0) for item in recent_items) / total_properties
            avg_investment_score = sum(item.get('investment_score', 0) for item in recent_items) / total_properties
            
            # Property type distribution
            type_distribution = {}
            for item in recent_items:
                prop_type = item.get('property_type', 'unknown')
                type_distribution[prop_type] = type_distribution.get(prop_type, 0) + 1
            
            market_context['market_summary'] = {
                'properties_analyzed_last_14_days': total_properties,
                'average_price_per_sqm': int(avg_price_per_sqm),
                'average_investment_score': int(avg_investment_score),
                'strong_buy_count': sum(1 for item in recent_items if item.get('recommendation') == 'strong_buy'),
                'buy_count': sum(1 for item in recent_items if item.get('recommendation') == 'buy'),
                'pass_count': sum(1 for item in recent_items if item.get('recommendation') == 'pass'),
                'type_distribution': type_distribution,
                'price_trend_summary': {
                    'below_market': sum(1 for item in recent_items if item.get('price_trend') == 'below_market'),
                    'at_market': sum(1 for item in recent_items if item.get('price_trend') == 'at_market'),
                    'above_market': sum(1 for item in recent_items if item.get('price_trend') == 'above_market')
                }
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
        jsonl_key = event.get('jsonl_key', f"data/processed/{date_str}/listings.jsonl")
        listings = load_jsonl_from_s3(bucket, jsonl_key)
        
        logger.info(f"Loaded {len(listings)} listings")
        
        # Sort by price_per_m2 and take top 5 for testing
        sorted_listings = sort_and_filter_listings(listings)
        
        logger.info(f"Selected {len(sorted_listings)} top listings by price_per_m2")
        
        # Build individual batch requests for each listing
        batch_requests = build_batch_requests(sorted_listings, date_str, bucket, market_context)
        
        # Save batch requests as JSONL to S3
        prompt_key = f"ai/prompts/{date_str}/batch_requests.jsonl"
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
    
    # Load base system prompt from file
    base_system_prompt = load_system_prompt()
    
    # Update system prompt with market context
    market_context_text = json.dumps(market_context, ensure_ascii=False, indent=2, default=decimal_default) if market_context else "No recent market data available."
    updated_system_prompt = base_system_prompt + f"""

# Current Market Analysis Data

Here is comprehensive market context from recently analyzed properties in Tokyo:

```json
{market_context_text}
```

## How to Use This Market Data:

1. **Benchmark Pricing**: Compare the property's price per sqm against district averages and top-performing properties
2. **Investment Score Context**: Use the average investment scores to calibrate your analysis
3. **Price Trend Analysis**: Reference recent price drops and market trends to assess opportunity timing
4. **District Comparison**: Compare properties within the same district and against city-wide averages
5. **Property Type Analysis**: Use type-specific data (mansions vs houses) for targeted comparisons

## Key Analysis Guidelines:
- Properties scoring above district average investment scores deserve closer examination
- Below-market pricing with high investment potential indicates strong opportunities
- Consider district-specific trends when evaluating appreciation potential
- Factor in property type distributions when assessing market position

When analyzing the target property, explicitly reference relevant comparable properties from this dataset and explain how the property compares to current market conditions.
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
        'jsonl_key': 'data/processed/2025-07-07/listings.jsonl'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))