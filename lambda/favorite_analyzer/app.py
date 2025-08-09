import json
import boto3
import os
import logging
from datetime import datetime
from openai import OpenAI, BadRequestError
from decimal import Decimal

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

preferences_table = dynamodb.Table(os.environ['PREFERENCES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
bucket = os.environ['DATA_BUCKET']

def lambda_handler(event, context):
    """Main Lambda handler"""
    print(f"[DEBUG] Favorite analyzer received event: {json.dumps(event)}")
    
    try:
        if 'Records' in event:  # SQS trigger
            for record in event['Records']:
                body = json.loads(record['body'])
                analyze(body['user_id'], body['property_id'])
        else:  # Direct invocation
            analyze(event['user_id'], event['property_id'])
            
        print(f"[DEBUG] Favorite analyzer completed successfully")
        return {'statusCode': 200, 'body': 'Success'}
    except Exception as e:
        print(f"[ERROR] Favorite analyzer failed: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise

def analyze(user_id, property_id):
    """Analyze a property and store results"""
    print(f"[DEBUG] Analyzing user_id: {user_id}, property_id: {property_id}")
    
    # Update status to processing
    preferences_table.update_item(
        Key={'user_id': user_id, 'property_id': property_id},
        UpdateExpression='SET analysis_status = :status',
        ExpressionAttributeValues={':status': 'processing'}
    )
    
    try:
        # Build comprehensive data package
        data_package = build_property_data_package(property_id)
        print(f"[DEBUG] Data package built with {len(data_package.get('image_urls', []))} images")
        
        # Generate prompt
        prompt = generate_investment_analysis_prompt(data_package)
        print(f"[DEBUG] Prompt generated - {len(prompt)} characters")
        
        # Get AI analysis
        analysis = get_ai_analysis(prompt, data_package.get('image_urls', []))
        print(f"[DEBUG] AI analysis received")
        
        # Ensure DynamoDB compatibility
        analysis_for_dynamo = convert_to_dynamo_format(analysis)
        
        # Check size and trim if needed (DynamoDB has 400KB item limit)
        import sys
        analysis_size = sys.getsizeof(str(analysis_for_dynamo))
        print(f"[DEBUG] Analysis size: {analysis_size} bytes")
        
        # If the full analysis is too large, create a trimmed version
        if analysis_size > 300000:  # Leave buffer for other fields
            print(f"[WARNING] Analysis too large ({analysis_size} bytes), trimming")
            # Keep everything except very long fields
            analysis_trimmed = {k: v for k, v in analysis.items()}
            if len(analysis_trimmed.get('analysis_markdown', '')) > 10000:
                analysis_trimmed['analysis_markdown'] = analysis_trimmed['analysis_markdown'][:10000] + '\n\n... [truncated]'
            analysis_for_dynamo = convert_to_dynamo_format(analysis_trimmed)
        
        # Debug what we're actually storing
        print(f"[DEBUG] Storing analysis_result with keys: {list(analysis_for_dynamo.keys())}")
        print(f"[DEBUG] Analysis verdict: {analysis.get('verdict')}")
        
        # Store in DynamoDB
        update_result = preferences_table.update_item(
            Key={'user_id': user_id, 'property_id': property_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    analysis_completed_at = :completed,
                    analysis_result = :result
            ''',
            ExpressionAttributeValues={
                ':status': 'completed',
                ':completed': datetime.utcnow().isoformat(),
                ':result': analysis_for_dynamo
            },
            ReturnValues='ALL_NEW'
        )
        print(f"[DEBUG] Analysis stored successfully")
        
    except Exception as e:
        print(f"[ERROR] Analysis failed: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        
        # Update with error status
        preferences_table.update_item(
            Key={'user_id': user_id, 'property_id': property_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    last_error = :error,
                    retry_count = if_not_exists(retry_count, :zero) + :inc
            ''',
            ExpressionAttributeValues={
                ':status': 'failed',
                ':error': str(e)[:500],
                ':zero': 0,
                ':inc': 1
            }
        )
        raise

def build_property_data_package(property_id):
    """Build comprehensive property data package"""
    print(f"[DEBUG] Building data package for {property_id}")
    
    # Get enriched data from DynamoDB
    dynamo_response = properties_table.get_item(
        Key={'property_id': property_id, 'sort_key': 'META'}
    )
    enriched_data = dynamo_response.get('Item', {})
    
    # Convert Decimal to float for easier handling
    enriched_data = json.loads(json.dumps(enriched_data, default=decimal_default))
    
    # Get raw scraped data from S3
    raw_data = {}
    try:
        date_part = property_id.split('#')[1].split('_')[0]
        formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        numeric_id = property_id.split('#')[1].split('_')[1]
        s3_key = f"raw/{formatted_date}/properties/{numeric_id}.json"
        
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        raw_data = json.loads(response['Body'].read())
    except Exception as e:
        logger.warning(f"Could not load raw data: {e}")
    
    # Generate presigned URLs for images
    image_urls = []
    if enriched_data.get('photo_filenames'):
        for s3_key in enriched_data['photo_filenames'].split('|')[:5]:  # Max 5 images
            if s3_key.strip():
                try:
                    url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket, 'Key': s3_key.strip()},
                        ExpiresIn=3600
                    )
                    image_urls.append(url)
                except Exception as e:
                    logger.warning(f"Failed to generate URL for {s3_key}: {e}")
    
    return {
        'enriched': enriched_data,
        'raw': raw_data,
        'image_urls': image_urls
    }

def generate_investment_analysis_prompt(data):
    """Generate a comprehensive prompt for AI analysis"""
    e = data['enriched']
    r = data.get('raw', {})
    
    # Extract key property details
    price_yen = int(e.get('price', 0)) * 10000
    size_sqm = e.get('size_sqm', 0)
    psm = e.get('price_per_sqm', 0)
    ward = e.get('ward', 'Unknown')
    station = e.get('closest_station') or r.get('nearest_station', 'Unknown')
    walk_min = e.get('station_distance_minutes') or r.get('station_distance_minutes', 'Unknown')
    building_age = e.get('building_age_years', 'Unknown')
    
    # Market context
    ward_median_psm = e.get('ward_median_price_per_sqm', 0)
    days_on_market = e.get('days_on_market', 0)
    
    # Calculate market comparison
    if ward_median_psm > 0 and psm > 0:
        price_vs_market = ((psm - ward_median_psm) / ward_median_psm) * 100
        market_position = f"{abs(price_vs_market):.1f}% {'above' if price_vs_market > 0 else 'below'} ward median"
    else:
        market_position = "No market data available"
    
    # Building details
    floor = e.get('floor', 'Unknown')
    building_floors = e.get('building_floors', 'Unknown')
    year_built = e.get('building_year') or r.get('building_year', 'Unknown')
    
    # Monthly costs
    hoa = e.get('total_monthly_costs', 0)
    mgmt_fee = e.get('management_fee', 0)
    reserve_fee = e.get('repair_reserve_fee', 0)
    
    # Additional enriched data
    num_bedrooms = e.get('num_bedrooms', 'Unknown')
    balcony_size = e.get('balcony_size_sqm', 0)
    primary_light = e.get('primary_light', 'Unknown')
    view_obstructed = e.get('view_obstructed', 'Unknown')
    
    # Investment scores
    final_score = e.get('final_score', 0)
    negotiability = e.get('negotiability_score', 0)
    
    # Raw data extras
    raw_title = r.get('title', '')
    raw_address = r.get('address', '')
    raw_layout = r.get('layout_text', '')
    raw_building_name = r.get('building_name', '')
    
    prompt = f"""
You are an expert Tokyo real estate analyst helping a buyer evaluate this property.

PROPERTY DETAILS:
- Title: {raw_title or e.get('title', 'Not provided')}
- Address: {raw_address or e.get('address', 'Not provided')}
- Building: {raw_building_name or 'Not provided'}
- Location: {ward} ward, {station} station ({walk_min} min walk)
- Price: ¥{price_yen:,} ({size_sqm} m²) = ¥{psm:,.0f}/m²
- Building Age: {building_age} years (Built: {year_built})
- Floor: {floor} / {building_floors} floors
- Layout: {num_bedrooms} bedrooms, {raw_layout or 'Not specified'}
- Balcony: {balcony_size} m²
- Light: {primary_light}, View obstructed: {view_obstructed}
- Monthly Costs: ¥{hoa:,} total (Management: ¥{mgmt_fee:,}, Reserve: ¥{reserve_fee:,})
- Days on Market: {days_on_market}
- Market Position: {market_position} (Ward median: ¥{ward_median_psm:,.0f}/m²)
- Investment Score: {final_score}/100
- Negotiability Score: {negotiability:.3f}

ENRICHED ANALYTICS:
{json.dumps({k: v for k, v in e.items() if k not in ['photo_filenames', 'property_id', 'sort_key', 'verdict']}, ensure_ascii=False, indent=2)}


BUYER PRIORITIES:
- Wants a good deal (fair or below-market price)
- Willing to accept older/cosmetic issues for value
- Needs structurally sound building (post-1981 preferred)
- Commute time to major hubs is important

Please provide your analysis in MARKDOWN FORMAT with the following structure:

## 🏆 Overall Verdict
[STRONG BUY / BUY / CONSIDER / PASS]

## 💰 Value Assessment
[Your assessment of value for money]

## ✅ Strengths
- [Strength 1]
- [Strength 2]
- [Strength 3]
- [etc.]

## ⚠️ Weaknesses
- [Weakness 1]
- [Weakness 2]
- [Weakness 3]
- [etc.]

## 🚇 Commute Times (estimated)
| Station | Time (minutes) |
|---------|---------------|
| Shinjuku | XX min |
| Tokyo | XX min |
| Ginza | XX min |
| Shibuya | XX min |
| Ikebukuro | XX min |

## ⚠️ Image assesment
- Building structural damage indication
- Mold spots? Cracks, blemishes etc
- Anything missing? no bath, no AC etc
- Any other key information gleamed from image analysis

## 🔨 Renovation Potential
[Your assessment of renovation/improvement opportunities]

## 💡 Negotiation Strategy
[Your price negotiation advice]

## 📊 Summary
[An overall summary of your analysis of the property and your recommendation.]

Use proper Markdown formatting including:
- Headers (##, ###)
- Bold text for emphasis (**text**)
- Bullet points (-)
- Tables for structured data
- Emojis where appropriate for visual appeal

Do not invent data. If unknown, say 'Unknown'. Focus on practical buyer advice.
"""
    
    return prompt

def get_ai_analysis(prompt, image_urls):
    """Get analysis from GPT-5 using responses API or GPT-4o fallback"""
    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)

    # Build content for the request
    user_content = [{"type": "input_text", "text": prompt}]
    for url in (image_urls or [])[:5]:
        user_content.append({"type": "input_image", "image_url": url})

    inputs = [
        {"role": "system", "content": [{"type": "input_text", "text": "You are an expert Tokyo real estate analyst. Provide analysis in clean Markdown format."}]},
        {"role": "user", "content": user_content}
    ]

    try:
        # Try GPT-5 with responses API
        logger.info("[AI] Attempting GPT-5 analysis with responses API")
        resp = client.responses.create(
            model="gpt-5",
            input=inputs,
            max_output_tokens=2000,
            reasoning={"effort": "minimal"}
        )
        
        # Get the text from response
        text = getattr(resp, "output_text", None)
        if not text:
            # Try to extract from output structure
            chunks = getattr(resp, "output", []) or []
            parts = []
            for ch in chunks:
                for c in getattr(ch, "content", []) or []:
                    t = getattr(c, "text", None)
                    if t:
                        parts.append(t)
            text = "\n".join(parts).strip()
            
    except BadRequestError as e:
        # Fallback to GPT-4o with regular chat API
        logger.warning(f"[AI] GPT-5 responses API failed: {e}; falling back to GPT-4o")
        
        # Convert to regular chat format
        content = [{"type": "text", "text": prompt}]
        for url in image_urls[:5]:
            content.append({"type": "image_url", "image_url": {"url": url}})
        
        messages = [
            {"role": "system", "content": "You are an expert Tokyo real estate analyst. Provide analysis in clean Markdown format."},
            {"role": "user", "content": content}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=2000,
            temperature=0.7
        )
        text = response.choices[0].message.content
    
    except Exception as e:
        logger.error(f"[AI] Analysis failed: {e}")
        text = "Analysis failed. Please try again."
    
    # Parse the response into structured format
    return parse_ai_response(text)

def parse_ai_response(text):
    """Parse the Markdown response and extract verdict"""
    print(f"[DEBUG] AI response received, text length: {len(text)}")
    
    # Extract the verdict for quick filtering/sorting
    text_lower = text.lower()
    verdict = "CONSIDER"  # Default
    
    if "strong buy" in text_lower:
        verdict = "STRONG BUY"
    elif "pass" in text_lower and "verdict" in text_lower:
        verdict = "PASS"  
    elif "buy" in text_lower and "verdict" in text_lower:
        verdict = "BUY"
    
    # Store the markdown text for display
    return {
        "analysis_markdown": text,
        "verdict": verdict,
        "analysis_text": text  # Keep for backwards compatibility
    }

def convert_to_dynamo_format(obj):
    """Convert Python objects to DynamoDB-compatible format"""
    if isinstance(obj, dict):
        return {k: convert_to_dynamo_format(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_dynamo_format(v) for v in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, (int, str, bool, type(None))):
        return obj
    else:
        return str(obj)

def decimal_default(obj):
    """JSON encoder for Decimal objects"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def get_openai_api_key():
    """Get OpenAI API key from Secrets Manager or environment"""
    try:
        secret_name = os.environ.get('OPENAI_SECRET_NAME', 'ai-scraper/openai-api-key')
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret = response['SecretString']
        
        # Handle different secret formats
        try:
            secret_dict = json.loads(secret)
            api_key = (secret_dict.get("OPENAI_API_KEY") or 
                      secret_dict.get("api_key") or 
                      secret_dict.get("key"))
        except json.JSONDecodeError:
            api_key = secret
        
        if not api_key or not api_key.strip():
            raise ValueError("API key is empty")
        
        return api_key.strip()
        
    except Exception as e:
        logger.error(f"Failed to get OpenAI API key from Secrets Manager: {e}")
        
        # Fallback to environment variable
        fallback_key = os.environ.get('OPENAI_API_KEY')
        if fallback_key:
            logger.info("Using fallback API key from environment variable")
            return fallback_key
        raise ValueError("No OpenAI API key available")