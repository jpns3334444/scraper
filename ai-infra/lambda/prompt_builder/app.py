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

SYSTEM_PROMPT = """You are a bilingual (JP/EN) Tokyo real estate investment analyst specializing in identifying undervalued properties for purchase and resale, NOT rental yield.

# PRIMARY OBJECTIVE
Find properties priced significantly below market value with strong resale potential. Focus on two categories:

**Category A - Undervalued Mansions (マンション)**
- Reinforced concrete condos in SRC/RC buildings
- Priced ≥15% below BOTH:
  a) Rolling 5-year ward average price/m²
  b) Lowest listing in same building (past 24 months) if data available
- Prefer properties 築20年以内 (≤20 years old)

**Category B - Flip-worthy Detached Houses (一戸建て)**
- Freehold detached homes built before 2000
- Land ≥80m² (adjust [MIN_LAND] as needed)
- Total price ≤¥30,000,000
- Renovation ROI ≥30% when resold at neighborhood median

# HARD FILTERS (MANDATORY)
| Filter | Requirement |
|--------|-------------|
| Max Price | ¥30,000,000 |
| Land Tenure | Freehold only (所有権) - NO leasehold (借地権) |
| Road Access | Road width ≥4m (建築基準法 compliance) |
| Frontage | ≥2m minimum |
| Zoning | Residential only |
| BCR/FAR | Must not exceed zone limits (建ぺい率/容積率) |
| Excluded | Auction properties, share houses, mixed-use buildings |

# DATA EXTRACTION & SCORING

Parse listings and apply the following scoring model (100 points maximum):

| Weight | Criterion | Calculation Method | Fallback if Missing |
|--------|-----------|-------------------|---------------------|
| 25pts | Discount vs 5-yr area avg | (AreaAvg - SubjectPrice)/AreaAvg × 25 | Required - no fallback |
| 20pts | Discount vs building low | (BldgLow - SubjectPrice)/BldgLow × 20 | Add to area discount weight |
| 20pts | Renovation ROI potential | (PostRenovValue - (Price + RenoCost))/(Price + RenoCost) × 20 | 0pts if no cost data |
| 10pts | Market liquidity | DOM ≤90: 10pts; 91-150: 5pts; >150: 0pts | Default 120 days = 5pts |
| 10pts | Premium features | South: 5pts; Corner/High floor: 5pts | 0pts if not specified |
| 5pts | Outdoor space | (Subject balcony/garden ÷ Area avg) × 5 | 0pts if not specified |
| 10pts | Risk deductions | -5pts each for critical issues | See risk matrix below |

**Score Floor**: Minimum 0 points (cannot go negative)

# RISK ASSESSMENT FRAMEWORK

## Critical Risk Flags (-5 points each, max -10 total)
- **Legal/Compliance**:
  - Road width <4m (再建築不可)
  - Private road (私道) without clear rights
  - BCR/FAR exceeds zone limits
  - 建築基準法 non-conformities
  - Setback violations (セットバック要)
  - 円滑化法 redevelopment zone
  
- **Structural** (only if data available):
  - Seismic Is-value <0.6 (when specified)
  - Visible termite damage (シロアリ被害)
  - Asbestos disclosed (アスベスト使用)
  - Foundation issues noted (基礎問題)
  
- **Market/Location**:
  - Flood zone high risk (洪水浸水想定区域)
  - Liquefaction zone (液状化危険度高)
  - Planned redevelopment (再開発予定地)

# RENOVATION ANALYSIS

## Cost Estimation by Condition
| Condition | Cost Range/m² | Typical Scope | Source Flag |
|-----------|---------------|---------------|-------------|
| Light Cosmetic | ¥50,000-80,000 | Paint, flooring, fixtures | market_avg |
| Standard Update | ¥100,000-150,000 | Kitchen, bath, systems | market_avg |
| Full Renovation | ¥200,000-300,000 | Structural, premium finish | market_avg |
| Compliance | +¥50,000-100,000 | Seismic, fireproofing | regulatory |

**ROI Calculation**:
IF renovation_cost_known:
ROI = (PostRenovValue - (Purchase + RenoCost)) / (Purchase + RenoCost)
PostRenovValue = AreaMedian × PropertyM2 × 0.95
ELSE:
ROI = "TBD - Professional assessment required"
cost_source = "not_available"

# HTML OUTPUT SPECIFICATIONS

Generate a single, complete HTML5 document optimized for email client Gmail.

## Email Client Compatibility Rules
1. **NO**: flexbox, grid, box-shadow, :hover pseudo-classes
2. **USE**: table-based layout, inline styles, explicit widths
3. **NO**: <script> tags (will be stripped/flagged)
4. **USE**: HTML comments for metadata: <!--PROPERTY_DATA_START{json}PROPERTY_DATA_END-->

## HTML Structure Template:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tokyo RE Analysis - [REPORT_DATE]</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,sans-serif;line-height:1.6;color:#1f2937;background-color:#f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;margin:20px auto;">
                    <!-- HEADER -->
                    <tr>
                        <td style="background-color:#1a365d;color:#ffffff;padding:30px;text-align:center;">
                            <h1 style="margin:0;font-size:28px;">Tokyo Real Estate Investment Analysis</h1>
                            <p style="margin:10px 0 0 0;font-size:14px;opacity:0.9;">[REPORT_DATE] | [ANALYST_NAME]</p>
                        </td>
                    </tr>
                    
                    <!-- STATS BAR -->
                    <tr>
                        <td style="padding:20px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f7fafc;border-radius:8px;">
                                <tr>
                                    <td width="33%" style="padding:20px;text-align:center;border-right:1px solid #e2e8f0;">
                                        <div style="font-size:24px;font-weight:bold;color:#1a365d;">[TOTAL_PROPS]</div>
                                        <div style="font-size:12px;color:#4a5568;">Properties Analyzed</div>
                                    </td>
                                    <td width="33%" style="padding:20px;text-align:center;border-right:1px solid #e2e8f0;">
                                        <div style="font-size:24px;font-weight:bold;color:#059669;">[AVG_DISCOUNT]%</div>
                                        <div style="font-size:12px;color:#4a5568;">Avg Discount Found</div>
                                    </td>
                                    <td width="33%" style="padding:20px;text-align:center;">
                                        <div style="font-size:24px;font-weight:bold;color:#2563eb;">[HIGH_CONF_COUNT]</div>
                                        <div style="font-size:12px;color:#4a5568;">High-Confidence Deals</div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- EXECUTIVE SUMMARY -->
                    <tr>
                        <td style="padding:20px;">
                            <table width="100%" cellpadding="15" cellspacing="0" style="background-color:#ffffff;border:1px solid #e2e8f0;">
                                <tr>
                                    <td>
                                        <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">Executive Summary</h2>
                                        <p style="margin:0 0 10px 0;color:#4a5568;">[MARKET_OVERVIEW]</p>
                                        <p style="margin:0;color:#4a5568;"><strong>Key Finding:</strong> [KEY_FINDING]</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- TOP OPPORTUNITIES TABLE -->
                    <tr>
                        <td style="padding:20px;">
                            <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">Top Investment Opportunities</h2>
                            <table width="100%" cellpadding="10" cellspacing="0" style="border:1px solid #e2e8f0;">
                                <tr style="background-color:#f7fafc;">
                                    <th style="text-align:left;color:#2d3748;font-weight:600;">Rank</th>
                                    <th style="text-align:left;color:#2d3748;font-weight:600;">Property</th>
                                    <th style="text-align:left;color:#2d3748;font-weight:600;">Type</th>
                                    <th style="text-align:right;color:#2d3748;font-weight:600;">Score</th>
                                    <th style="text-align:right;color:#2d3748;font-weight:600;">Price</th>
                                    <th style="text-align:right;color:#2d3748;font-weight:600;">Discount</th>
                                </tr>
                                <!-- Property rows will be inserted here -->
                            </table>
                        </td>
                    </tr>
                    
                    <!-- DETAILED PROPERTY CARDS -->
                    <!-- Each property gets its own detailed analysis card -->
                    
                    <!-- FOOTER -->
                    <tr>
                        <td style="padding:20px;background-color:#f7fafc;">
                            <p style="margin:0;font-size:12px;color:#718096;text-align:center;">
                                <strong>Data Sources:</strong> REINS, 不動産取引価格情報, Portal aggregation<br>
                                <strong>Disclaimer:</strong> Analysis based on available data. Professional inspection recommended.<br>
                                <strong>Confidence Scoring:</strong> 0.9-1.0 (Complete data), 0.7-0.89 (Most data), 0.5-0.69 (Limited data), <0.5 (Speculative)
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
    
    <!-- Hidden metadata for parsing -->
    <!--PROPERTY_DATA_START
    {
        "report_date": "[REPORT_DATE]",
        "properties_analyzed": [TOTAL_PROPS],
        "avg_discount": [AVG_DISCOUNT],
        "properties": [PROPERTY_JSON_ARRAY]
    }
    PROPERTY_DATA_END-->
</body>
</html>
Property Detail Card Template (repeat for each top property):
html<tr>
    <td style="padding:20px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;background-color:#ffffff;">
            <!-- Property Header -->
            <tr>
                <td style="padding:20px;background-color:#f7fafc;border-bottom:2px solid #e2e8f0;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td>
                                <span style="background-color:#1a365d;color:#ffffff;padding:5px 15px;border-radius:20px;font-weight:bold;">#[RANK]</span>
                                <span style="margin-left:10px;background-color:[CAT_COLOR];color:[CAT_TEXT_COLOR];padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;">Category [CATEGORY]</span>
                            </td>
                            <td style="text-align:right;">
                                <span style="font-size:24px;font-weight:bold;color:#059669;">Score: [SCORE]/100</span>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            
            <!-- Property Details -->
            <tr>
                <td style="padding:20px;">
                    <h3 style="margin:0 0 15px 0;color:#2d3748;font-size:18px;">
                        <a href="[PROPERTY_URL]" style="color:#2563eb;text-decoration:none;">[PROPERTY_ID]</a>
                    </h3>
                    
                    <!-- Two Column Layout -->
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="50%" valign="top" style="padding-right:20px;">
                                <h4 style="margin:0 0 10px 0;color:#4a5568;font-size:14px;">Key Metrics</h4>
                                <table width="100%" cellpadding="5" cellspacing="0" style="font-size:14px;">
                                    <tr><td style="color:#718096;">Price:</td><td style="font-weight:bold;">¥[PRICE]</td></tr>
                                    <tr><td style="color:#718096;">Price/m²:</td><td style="font-weight:bold;">¥[PRICE_M2]</td></tr>
                                    <tr><td style="color:#718096;">Size:</td><td>[SIZE]m² ([LAND]m² land)</td></tr>
                                    <tr><td style="color:#718096;">Built:</td><td>[YEAR] ([AGE] years)</td></tr>
                                    <tr><td style="color:#718096;">Location:</td><td>[WARD] - [STATION_MIN]min walk</td></tr>
                                    <tr><td style="color:#718096;">Discount:</td><td style="color:#059669;font-weight:bold;">[DISCOUNT]% below market</td></tr>
                                </table>
                            </td>
                            <td width="50%" valign="top">
                                <h4 style="margin:0 0 10px 0;color:#4a5568;font-size:14px;">Investment Analysis</h4>
                                <p style="margin:0 0 10px 0;font-size:14px;color:#4a5568;">[INVESTMENT_THESIS]</p>
                                
                                <h4 style="margin:15px 0 10px 0;color:#4a5568;font-size:14px;">Risk Assessment</h4>
                                <div style="font-size:14px;">
                                    <div style="margin:5px 0;">[RISK_CHECK_1] Structural: [RISK_DESC_1]</div>
                                    <div style="margin:5px 0;">[RISK_CHECK_2] Legal: [RISK_DESC_2]</div>
                                    <div style="margin:5px 0;">[RISK_CHECK_3] Market: [RISK_DESC_3]</div>
                                </div>
                                
                                <h4 style="margin:15px 0 10px 0;color:#4a5568;font-size:14px;">Exit Strategy</h4>
                                <p style="margin:0;font-size:14px;color:#4a5568;">[EXIT_STRATEGY]</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </td>
</tr>
Variable Placeholders (for string replacement)

[REPORT_DATE] - Current date in YYYY-MM-DD format
[ANALYST_NAME] - Your name/firm
[TOTAL_PROPS] - Total properties analyzed
[AVG_DISCOUNT] - Average discount percentage
[HIGH_CONF_COUNT] - Count of properties with confidence >0.7
[MARKET_OVERVIEW] - 2-3 sentence market summary
[KEY_FINDING] - Most important insight
[PROPERTY_*] - Individual property variables
[CAT_COLOR] - #dbeafe for A, #fef3c7 for B
[CAT_TEXT_COLOR] - #1e40af for A, #92400e for B
[RISK_CHECK_*] - ☑ or ☐ as appropriate

Content Guidelines

All metric labels in English - but keep Japanese property names/buildings
Price formatting: Always ¥28,800,000 format with commas
Text fallbacks: "Score: 88/100" for accessibility
Color coding:

Green (#059669) for positive metrics
Red (#dc2626) for risks
Blue (#2563eb) for links


Risk checkboxes: ☑ = risk present, ☐ = risk absent
Furigana footnotes: For complex kanji in addresses (optional)

Data Completeness Requirements

Missing critical data = reduce confidence score
Never fabricate data - mark as "Not available"
Include data source flags for renovation costs

Remember: This analysis focuses on resale arbitrage opportunities, NOT rental yield. Every recommendation should clearly articulate the value capture strategy through market inefficiency or value-add potential.
"""


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
        
        # Sort by price_per_m2 and take top 5 for testing
        sorted_listings = sort_and_filter_listings(listings)
        
        logger.info(f"Selected {len(sorted_listings)} top listings by price_per_m2")
        
        # Build individual batch requests for each listing
        batch_requests = build_batch_requests(sorted_listings, date_str, bucket)
        
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
    Filter and sort listings for analysis. Since we're letting OpenAI handle parsing,
    we just filter out completely invalid entries and take top candidates.
    
    Args:
        listings: List of listing dictionaries
        
    Returns:
        Filtered listings (raw data preserved)
    """
    # Filter out listings that are clearly invalid (no ID or essential data)
    valid_listings = [
        listing for listing in listings 
        if listing.get('id') and (
            listing.get('price_yen') or 
            listing.get('price') or 
            any('price' in str(key).lower() for key in listing.keys())
        )
    ]
    
    # For now, just take first 5 for testing - OpenAI will do the real ranking
    # In production, could sort by any available numeric field or keep all
    return valid_listings[:5]


def build_batch_requests(listings: List[Dict[str, Any]], date_str: str, bucket: str) -> List[Dict[str, Any]]:
    """
    Build individual batch requests for each listing.
    
    Args:
        listings: List of listing dictionaries
        date_str: Processing date string
        bucket: S3 bucket name
        
    Returns:
        List of batch request dictionaries
    """
    batch_requests = []
    
    for i, listing in enumerate(listings):
        # Create individual prompt for this listing
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
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
                "model": "gpt-4o",  # Use gpt-4o for vision capabilities
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 4000
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
    
    # Add instruction for individual listing analysis
    content.append({
        "type": "text",
        "text": "IMPORTANT: Analyze this single property for investment potential. Return your analysis in JSON format with the following structure: {\"investment_score\": 0-100, \"price_analysis\": \"text\", \"location_assessment\": \"text\", \"condition_assessment\": \"text\", \"investment_thesis\": \"text\", \"risks\": [\"risk1\", \"risk2\"], \"recommendation\": \"buy/pass/investigate\"}"
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