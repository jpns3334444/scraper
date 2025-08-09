import json
import boto3

# Import centralized configuration
try:
    from config_loader import get_config
    config = get_config()
except ImportError:
    config = None  # Fallback to environment variables
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
    print(f"[DEBUG] Favorite analyzer received event: {json.dumps(event)}")
    print(f"[DEBUG] Context: {context}")
    
    try:
        if 'Records' in event:  # backward compatibility
            print(f"[DEBUG] Processing SQS records: {len(event['Records'])}")
            for record in event['Records']:
                body = json.loads(record['body'])
                print(f"[DEBUG] Processing record body: {body}")
                analyze(body['user_id'], body['property_id'])
        else:
            print(f"[DEBUG] Direct invocation - user_id: {event.get('user_id')}, property_id: {event.get('property_id')}")
            analyze(event['user_id'], event['property_id'])
            
        print(f"[DEBUG] Favorite analyzer completed successfully")
    except Exception as e:
        print(f"[ERROR] Favorite analyzer failed: {e}")
        import traceback
        print(f"[ERROR] Favorite analyzer traceback: {traceback.format_exc()}")
        raise

def analyze(user_id, property_id):
    print(f"[DEBUG] analyze() called with user_id: {user_id}, property_id: {property_id}")
    
    # Update status to processing
    print(f"[DEBUG] Updating preference status to 'processing'")
    preferences_table.update_item(
        Key={'user_id': user_id, 'property_id': property_id},
        UpdateExpression='SET analysis_status = :status',
        ExpressionAttributeValues={':status': 'processing'}
    )
    print(f"[DEBUG] Status updated to processing")
    
    try:
        # Build comprehensive data package
        print(f"[DEBUG] Building data package for property_id: {property_id}")
        data_package = build_property_data_package(property_id)
        print(f"[DEBUG] Data package built successfully. Keys: {list(data_package.keys())}")
        
        # Generate prompt
        print(f"[DEBUG] Generating analysis prompt")
        prompt = generate_investment_analysis_prompt(data_package)
        print(f"[DEBUG] Prompt generated - length: {len(prompt)} characters")
        
        # Get ChatGPT analysis
        print(f"[DEBUG] Getting ChatGPT analysis with {len(data_package.get('image_urls', []))} images")
        analysis = get_chatgpt_analysis(prompt, data_package.get('image_urls', []))
        print(f"[DEBUG] ChatGPT analysis received: {type(analysis)}")
        
        # Store analysis result
        print(f"[DEBUG] Storing analysis result in preferences table")
        
        # Convert float values to Decimal for DynamoDB compatibility
        def convert_floats_to_decimal(obj):
            """Recursively convert float values to Decimal for DynamoDB"""
            if isinstance(obj, dict):
                return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_floats_to_decimal(v) for v in obj]
            elif isinstance(obj, float):
                return Decimal(str(obj))
            else:
                return obj
        
        # Convert the analysis data
        analysis_for_dynamo = convert_floats_to_decimal(analysis)
        summary_for_dynamo = convert_floats_to_decimal({
            'investment_rating': analysis.get('investment_rating'),
            'final_verdict': analysis.get('final_verdict'),
            'rental_yield_net': analysis.get('rental_yield_net')
        })
        
        preferences_table.update_item(
            Key={'user_id': user_id, 'property_id': property_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    analysis_completed_at = :completed,
                    analysis_result = :result,
                    analysis_summary = :summary
            ''',
            ExpressionAttributeValues={
                ':status': 'completed',
                ':completed': datetime.utcnow().isoformat(),
                ':result': analysis_for_dynamo,
                ':summary': summary_for_dynamo
            }
        )
        print(f"[DEBUG] Analysis result stored successfully with status 'completed'")
        
    except Exception as e:
        print(f"[ERROR] Analysis failed for user_id: {user_id}, property_id: {property_id}")
        print(f"[ERROR] Exception: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        
        # Update with error status
        print(f"[DEBUG] Updating preference status to 'failed'")
        preferences_table.update_item(
            Key={'user_id': user_id, 'property_id': property_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    last_error = :error,
                    retry_count = if_not_exists(retry_count, :zero) + :inc
            ''',
            ExpressionAttributeValues={
                ':status': 'failed',
                ':error': str(e),
                ':zero': 0,
                ':inc': 1
            }
        )
        print(f"[DEBUG] Status updated to 'failed'")
        raise

def build_property_data_package(property_id):
    print(f"[DEBUG] build_property_data_package() called for property_id: {property_id}")
    
    # 1. Get enriched data from DynamoDB
    print(f"[DEBUG] Getting enriched data from DynamoDB")
    dynamo_response = properties_table.get_item(
        Key={'property_id': property_id, 'sort_key': 'META'}
    )
    enriched_data = dynamo_response.get('Item', {})
    print(f"[DEBUG] Enriched data retrieved: {bool(enriched_data)}")
    if enriched_data:
        print(f"[DEBUG] Enriched data keys: {list(enriched_data.keys())}")
    else:
        print(f"[DEBUG] No enriched data found for property_id: {property_id}")
    
    # Convert Decimal to float
    enriched_data = json.loads(json.dumps(enriched_data, default=decimal_default))
    
    # 2. Get raw scraped data from S3
    date_part = property_id.split('#')[1].split('_')[0]
    formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
    
    # Extract numeric ID from property_id (PROP#20250804_1421770022572 -> 1421770022572)
    numeric_id = property_id.split('#')[1].split('_')[1] if '#' in property_id and '_' in property_id else property_id
    s3_key = f"raw/{formatted_date}/properties/{numeric_id}.json"
    
    raw_data = {}
    try:
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        raw_data = json.loads(response['Body'].read())
    except Exception as e:
        logger.warning(f"Raw property data not found in S3: {s3_key}")
        logger.debug(f"Could not load raw data from S3 key {s3_key}: {e}")
    
    # 3. Get image URLs
    image_urls = []
    if enriched_data.get('photo_filenames'):
        for s3_key in enriched_data['photo_filenames'].split('|')[:5]:
            if s3_key.strip():
                try:
                    url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket, 'Key': s3_key.strip()},
                        ExpiresIn=3600
                    )
                    image_urls.append(url)
                except Exception as e:
                    logger.warning(f"Failed to generate presigned URL for {s3_key}: {e}")
    
    return {
        'enriched': enriched_data,
        'raw': raw_data,
        'image_urls': image_urls
    }

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def generate_investment_analysis_prompt(data):
    """Prompt for a top-tier Tokyo buyer’s agent analysis + commute times."""
    e = data['enriched']
    r = data.get('raw', {})

    price_10k = e.get('price') or 0
    price_yen = int(price_10k) * 10000
    size_sqm = e.get('size_sqm') or 0
    psm = e.get('price_per_sqm') or 0
    ward = e.get('ward') or ""
    district = e.get('district') or ""
    station = e.get('closest_station') or r.get('nearest_station') or ""
    walk_min = e.get('station_distance_minutes') or r.get('station_distance_minutes') or ""
    b_age = e.get('building_age_years') or ""
    floor = e.get('floor') or ""
    floors = e.get('building_floors') or ""
    hoa = e.get('total_monthly_costs') or 0
    mgmt = e.get('management_fee') or 0
    reserve = e.get('repair_reserve_fee') or 0
    light = e.get('primary_light') or ""
    view_ob = e.get('view_obstructed')
    title = e.get('title') or r.get('title') or ""
    addr = e.get('address') or r.get('address') or ""
    year = e.get('building_year') or r.get('building_year') or ""
    
    # Market context data - CRITICAL for analysis
    ward_median_psm = e.get('ward_median_price_per_sqm') or 0
    ward_discount_pct = e.get('ward_discount_pct') or 0
    ward_property_count = e.get('ward_property_count') or 0
    days_on_market = e.get('days_on_market') or 0
    
    # Investment scoring components
    final_score = e.get('final_score') or 0
    base_score = e.get('base_score') or 0
    addon_score = e.get('addon_score') or 0
    adjustment_score = e.get('adjustment_score') or 0
    
    # Detailed scoring breakdown
    scoring = e.get('scoring_components', {})
    
    # Additional property details
    num_bedrooms = e.get('num_bedrooms') or 0
    balcony_size = e.get('balcony_size_sqm') or 0
    good_lighting = e.get('good_lighting', 0)
    negotiability = e.get('negotiability_score') or 0
    
    # Calculate market premium/discount
    market_comparison = ""
    if ward_median_psm > 0:
        price_vs_market = ((psm - ward_median_psm) / ward_median_psm) * 100
        if price_vs_market > 0:
            market_comparison = f"PREMIUM: +{price_vs_market:.1f}% above ward median"
        else:
            market_comparison = f"DISCOUNT: {abs(price_vs_market):.1f}% below ward median"

    base_facts = f"""
PROPERTY SNAPSHOT
- Title: {title}
- Address: {addr}
- Ward/District: {ward} / {district}
- Station: {station} (walk {walk_min} min)
- Price: ¥{price_yen:,} | Size: {size_sqm} m² | ¥/m²: ¥{psm:,.0f}
- Building: {year} build (~{b_age} yrs), Floor {floor}/{floors}, Light: {light}, View obstructed: {view_ob}
- Layout: {num_bedrooms} bedrooms, Balcony: {balcony_size} m²
- Monthly HOA: ¥{hoa:,} (Mgmt ¥{mgmt:,}, Reserve ¥{reserve:,})
- Days on Market: {days_on_market}

MARKET CONTEXT (CRITICAL FOR VALUATION):
- Ward Median ¥/m²: ¥{ward_median_psm:,.0f}
- This Property vs Ward Median: {market_comparison}
- Ward Sample Size: {ward_property_count} properties
- Negotiability Score: {negotiability:.3f}

INVESTMENT SCORING BREAKDOWN:
- Final Investment Score: {final_score}/100 (Base: {base_score}, Addons: {addon_score}, Adjustments: {adjustment_score})
- Component Scores: Access({scoring.get('access', 0)}), Condition({scoring.get('condition', 0)}), 
  Building Discount({scoring.get('building_discount', 0)}), Carry Cost({scoring.get('carry_cost', 0)}),
  Size Efficiency({scoring.get('size_efficiency', 0)}), Comps Consistency({scoring.get('comps_consistency', 0)})

RAW EXTRAS:
{format_raw_data(r)}
""".strip()

    return f"""
You are an elite Tokyo buyer’s agent representing a client who wants a fantastic home at a fair or below-market price.
Your job:
- Assess suitability for **living in** (layout, light, noise, view, building quality, management, surrounding area).
- Protect the buyer from **overpaying** (compare to recent similar sales if possible).
- Flag any **liquidity/resale risks** so they’re not trapped later.
- Identify potential for future value appreciation.

Your client:
- Ideal purchase would be an apartment that: looks somewhat old/ugly, but the building is structurally sound, high quality, built after 1981, and 
- Would prefer something that looks somewhat old, and could use some fixing up (but is built after 1981), over an apartment that was given a quick renovation and is overpriced
- 


CRITICAL: Return ONLY a JSON object in this schema:
{{
  "summary": "2–4 sentences with your overall take as a trusted buyers' agent.",
  "value_for_money": "Good / Fair / Poor and why.",
  "strengths": ["bullet", "bullet", "bullet"],
  "weaknesses": ["bullet", "bullet", "bullet"],
  "renovation_or_improvement_ideas": ["bullet", "bullet"],
  "price_negotiation_advice": "Specific tactics or % to target.",
  "commute_times_minutes": {{
     "Shinjuku": {{"minutes": 0, "route": "Line/transfer note"}},
     "Tokyo":    {{"minutes": 0, "route": "Line/transfer note"}},
     "Ginza":    {{"minutes": 0, "route": "Line/transfer note"}},
     "Shibuya":  {{"minutes": 0, "route": "Line/transfer note"}},
     "Ikebukuro":{{"minutes": 0, "route": "Line/transfer note"}}
  }},
  "verdict": "STRONG BUY | BUY | CONSIDER | PASS"
}}

Rules:
- Use the station "{station}" and walk time {walk_min} to give realistic commute times + routes.
- Pay special attention to the ward median price comparison - this is KEY market context.
- Factor in the investment scoring components in your analysis.
- Consider the negotiability score when giving price negotiation advice.
- Avoid marketing fluff; speak like a trusted agent advising a smart client.
- If data is missing, make conservative assumptions but say so in the note.
- No extra text outside JSON.

Context:
{base_facts}
""".strip()


def format_raw_data(raw):
    """Format raw data for inclusion in prompt"""
    if not raw:
        return "No additional raw data available"
    
    # Extract key fields from raw data
    formatted = []
    key_fields = ['title', 'building_name', 'address', 'layout_text', 'building_age_text', 'primary_light']
    
    for field in key_fields:
        if field in raw and raw[field]:
            formatted.append(f"{field}: {raw[field]}")
    
    return "\n".join(formatted) if formatted else "No additional raw data available"

def get_chatgpt_analysis(prompt, image_urls):
    """
    Responses API version: JSON mode, images supported, robust parsing.
    Requires openai python SDK >= 1.x that includes `responses`.
    """
    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)

    # Build Responses API input: role + content parts
    # Use `input_text` / `input_image` for Responses API
    user_content = [{"type": "input_text", "text": prompt}]
    for url in (image_urls or []):
        user_content.append({"type": "input_image", "image_url": url})

    inputs = [
        {"role": "system", "content": [{"type": "input_text", "text": "You are an expert Tokyo real estate investment analyst. Reply with valid JSON ONLY."}]},
        {"role": "user",   "content": user_content}
    ]

    try:
        resp = client.responses.create(
            model="gpt-5",
            input=inputs,
            max_output_tokens=2000,
            reasoning={"effort": "minimal"}
        )
    except BadRequestError as e:
        logger.warning(f"[AI DEBUG] GPT-5 responses.create failed: {e}; falling back to gpt-4o")
        resp = client.responses.create(
            model="gpt-4o",
            input=inputs,
            response_format={"type": "json_object"},
            max_output_tokens=2000,
        )

    # Debug snapshot
    try:
        logger.info(f"[AI RAW SNAPSHOT] {str(resp)[:1500]}")
    except Exception:
        pass

    # Preferred: JSON already parsed by SDK in JSON mode
    parsed = getattr(resp, "output_parsed", None)
    if parsed:
        # Some SDKs return pydantic-like objects; coerce to plain dict if needed
        try:
            return dict(parsed)
        except Exception:
            return json.loads(json.dumps(parsed, default=str))

    # Fallback 1: single concatenated string
    text = getattr(resp, "output_text", None)
    if text and text.strip():
        try:
            return json.loads(text)
        except json.JSONDecodeError as je:
            logger.error(f"[AI DEBUG] JSON decode failed (output_text): {je}. First 300: {text[:300]!r}")
            return {
                "raw_analysis": text,
                "structured": parse_analysis_text(text),
                "final_verdict": "HOLD",
                "investment_rating": 5.0,
            }

    # Fallback 2: manual walk (older SDKs expose a list structure)
    try:
        chunks = getattr(resp, "output", []) or []
        parts = []
        for ch in chunks:
            for c in getattr(ch, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
        joined = "\n".join(parts).strip()
        if joined:
            try:
                return json.loads(joined)
            except json.JSONDecodeError as je:
                logger.error(f"[AI DEBUG] JSON decode failed (manual): {je}. First 300: {joined[:300]!r}")
                return {
                    "raw_analysis": joined,
                    "structured": parse_analysis_text(joined),
                    "final_verdict": "HOLD",
                    "investment_rating": 5.0,
                }
    except Exception as e:
        logger.error(f"[AI DEBUG] Could not manually read resp.output: {e}")

    # Ultimate fallback
    logger.warning("[AI DEBUG] Empty response from model; returning minimal fallback.")
    return {
        "raw_analysis": "",
        "structured": {"summary": "", "key_points": []},
        "final_verdict": "HOLD",
        "investment_rating": 5.0,
    }



def parse_analysis_text(analysis_text):
    """Parse unstructured analysis text into structured format"""
    # Simple parsing for fallback
    lines = analysis_text.split('\n')
    structured = {
        "summary": analysis_text[:500] + "..." if len(analysis_text) > 500 else analysis_text,
        "key_points": [line.strip() for line in lines if line.strip() and len(line.strip()) > 10][:5]
    }
    return structured

def get_openai_api_key():
    """Get OpenAI API key from Secrets Manager"""
    try:
        secret_name = os.environ.get('OPENAI_SECRET_NAME', 'ai-scraper/openai-api-key')
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret = response['SecretString']
        # Handle JSON-formatted secrets like {"OPENAI_API_KEY":"..."} or plain string
        try:
            maybe_json = json.loads(secret)
            api_key = maybe_json.get("OPENAI_API_KEY") or maybe_json.get("api_key") or maybe_json.get("key")
        except json.JSONDecodeError:
            api_key = secret

        if not api_key or api_key.strip() == '':
            raise ValueError("Retrieved API key is empty")

        return api_key

    except Exception as e:
        logger.error(f"Failed to get OpenAI API key: {e}")
        fallback_key = os.environ.get('OPENAI_API_KEY')
        if fallback_key:
            logger.info("Using fallback API key from environment variable")
            return fallback_key
        raise
