#!/usr/bin/env python3
"""
Favorite Analyzer Lambda - GPT-powered analysis for favorited US properties
"""
import json
import boto3
import os
import logging
import uuid
import time
from datetime import datetime
from openai import OpenAI, BadRequestError, RateLimitError
from decimal import Decimal

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_aws_region():
    """Get AWS region from environment or default"""
    return os.environ.get('AWS_REGION', 'us-east-1')


# Setup AWS resources
dynamodb = boto3.resource('dynamodb', region_name=get_aws_region())
secrets_client = boto3.client('secretsmanager', region_name=get_aws_region())

preferences_table = dynamodb.Table(os.environ.get('PREFERENCES_TABLE', 'real-estate-ai-user-preferences'))
properties_table = dynamodb.Table(os.environ.get('PROPERTIES_TABLE', 'real-estate-ai-properties'))


def lambda_handler(event, context):
    """Main Lambda handler"""
    request_id = str(uuid.uuid4())[:8]
    print(f"[DEBUG] Favorite analyzer [{request_id}] received event: {json.dumps(event)}")

    try:
        if 'Records' in event:  # SQS trigger
            for record in event['Records']:
                body = json.loads(record['body'])
                analyze(body['user_id'], body['property_id'])
        elif event.get('operation') == 'compare_favorites':
            return compare_favorites(event['user_id'], event['property_ids'], request_id, event.get('comparison_id'))
        else:  # Direct invocation
            analyze(event['user_id'], event['property_id'])

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
        # Build property data package
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

        # Check size and trim if needed
        import sys
        analysis_size = sys.getsizeof(str(analysis_for_dynamo))

        if analysis_size > 300000:
            print(f"[WARNING] Analysis too large ({analysis_size} bytes), trimming")
            analysis_trimmed = {k: v for k, v in analysis.items()}
            if len(analysis_trimmed.get('analysis_markdown', '')) > 10000:
                analysis_trimmed['analysis_markdown'] = analysis_trimmed['analysis_markdown'][:10000] + '\n\n... [truncated]'
            analysis_for_dynamo = convert_to_dynamo_format(analysis_trimmed)

        # Store in DynamoDB
        preferences_table.update_item(
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
            }
        )
        print(f"[DEBUG] Analysis stored successfully")

    except Exception as e:
        print(f"[ERROR] Analysis failed: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")

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
    """Build property data package for analysis"""
    print(f"[DEBUG] Building data package for {property_id}")

    # Get property data from DynamoDB
    dynamo_response = properties_table.get_item(
        Key={'property_id': property_id, 'sort_key': 'META'}
    )
    property_data = dynamo_response.get('Item', {})

    # Convert Decimal to float
    property_data = json.loads(json.dumps(property_data, default=decimal_default))

    # Get image URLs directly (stored from realtor.com)
    image_urls = property_data.get('image_urls', [])[:5]

    return {
        'property': property_data,
        'image_urls': image_urls
    }


def generate_investment_analysis_prompt(data):
    """Generate a US-focused investment analysis prompt"""
    p = data['property']

    # Extract key property details
    price = p.get('price', 0)
    size_sqft = p.get('size_sqft', 0)
    price_per_sqft = p.get('price_per_sqft', 0)
    beds = p.get('beds', 0)
    baths = p.get('baths', 0)
    year_built = p.get('year_built', 'Unknown')
    property_type = p.get('property_type', 'Unknown')

    # Location
    address = p.get('address', 'Not provided')
    city = p.get('city', 'Unknown')
    state = p.get('state', '')
    zip_code = p.get('zip_code', '')

    # Additional details
    lot_size_sqft = p.get('lot_size_sqft', 0)
    lot_size_acres = p.get('lot_size_acres', 0)
    hoa_fee = p.get('hoa_fee', 0)
    mls_id = p.get('mls_id', '')

    # Market context
    city_median_psf = p.get('city_median_price_per_sqft', 0)
    city_discount_pct = p.get('city_discount_pct', 0)
    days_on_market = p.get('days_on_market', 0)

    # Market position description
    if city_discount_pct < -10:
        market_position = f"{abs(city_discount_pct):.1f}% BELOW city median (good value)"
    elif city_discount_pct > 10:
        market_position = f"{city_discount_pct:.1f}% ABOVE city median (premium priced)"
    else:
        market_position = f"Near city median ({city_discount_pct:+.1f}%)"

    prompt = f"""
You are an expert US real estate analyst helping a buyer evaluate this property in {city}, {state}.

PROPERTY DETAILS:
- Address: {address}
- City/State/Zip: {city}, {state} {zip_code}
- MLS ID: {mls_id}
- Price: ${price:,}
- Size: {size_sqft:,} sq ft = ${price_per_sqft:.0f}/sq ft
- Bedrooms: {beds}
- Bathrooms: {baths}
- Property Type: {property_type}
- Year Built: {year_built}
- Lot Size: {lot_size_sqft:,} sq ft ({lot_size_acres:.2f} acres)
- HOA Fee: ${hoa_fee}/month

MARKET CONTEXT:
- Days on Market: {days_on_market}
- City Median: ${city_median_psf:.0f}/sq ft
- Market Position: {market_position}
- Listing URL: {p.get('listing_url', 'N/A')}

BUYER PRIORITIES:
- Looking for good value (fair or below-market price)
- Willing to accept older properties or cosmetic issues for value
- Interested in properties with renovation potential
- Needs structurally sound building
- Considers long-term investment potential

Please provide your analysis in MARKDOWN FORMAT with the following structure:

## 🏆 Overall Verdict
[STRONG BUY / BUY / CONSIDER / PASS]

## 💰 Value Assessment
[Your assessment of value for money compared to the local market]

## ✅ Strengths
- [Strength 1]
- [Strength 2]
- [Strength 3]

## ⚠️ Concerns
- [Concern 1]
- [Concern 2]
- [Concern 3]

## 🏠 Property Condition Assessment
(Based on images if available)
- Exterior condition observations
- Interior condition observations
- Any visible issues (roof, foundation, etc.)
- Items that may need repair/update

## 🔨 Renovation Potential
[Assessment of improvement opportunities and estimated costs]

## 💵 Financial Considerations
- Monthly carrying costs estimate (mortgage, taxes, insurance, HOA)
- Potential rental income if applicable
- Appreciation outlook for the area

## 💡 Negotiation Strategy
[Price negotiation advice based on days on market and market position]

## 📊 Summary
[Overall summary and clear recommendation]

Use proper Markdown formatting. Be practical and direct in your advice.
If information is unknown, say so. Focus on actionable buyer guidance.
"""

    return prompt


def get_ai_analysis(prompt, image_urls):
    """Get analysis from GPT-4o with image support"""
    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)

    # Build content with text and images
    content = [{"type": "text", "text": prompt}]

    for url in (image_urls or [])[:5]:
        content.append({
            "type": "image_url",
            "image_url": {"url": url}
        })

    messages = [
        {
            "role": "system",
            "content": "You are an expert US real estate analyst. Provide analysis in clean Markdown format."
        },
        {"role": "user", "content": content}
    ]

    try:
        logger.info("[AI] Requesting GPT-4o analysis")
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

    return parse_ai_response(text)


def parse_ai_response(text):
    """Parse the Markdown response and extract verdict"""
    text_lower = text.lower()
    verdict = "CONSIDER"  # Default

    if "strong buy" in text_lower:
        verdict = "STRONG BUY"
    elif "pass" in text_lower and "verdict" in text_lower:
        verdict = "PASS"
    elif "buy" in text_lower and "verdict" in text_lower:
        verdict = "BUY"

    return {
        "analysis_markdown": text,
        "verdict": verdict,
        "analysis_text": text
    }


def compare_favorites(user_id, property_ids, request_id="unknown", comparison_id=None):
    """Compare multiple favorite properties"""
    print(f"[DEBUG] [{request_id}] Comparing favorites for user: {user_id}, properties: {property_ids}")

    if len(property_ids) < 2:
        raise ValueError("Need at least 2 properties to compare")

    comparison_timestamp = datetime.utcnow()
    if not comparison_id:
        comparison_id = f"COMPARISON_{comparison_timestamp.strftime('%Y-%m-%d_%H-%M-%S')}"

    try:
        # Collect property data and analyses
        properties_data = []

        for property_id in property_ids:
            # Get property data
            dynamo_response = properties_table.get_item(
                Key={'property_id': property_id, 'sort_key': 'META'}
            )
            property_data = dynamo_response.get('Item', {})

            # Get individual analysis
            pref_response = preferences_table.get_item(
                Key={'user_id': user_id, 'property_id': property_id}
            )
            preference_data = pref_response.get('Item', {})

            if not property_data:
                raise ValueError(f"Property data missing for {property_id}")

            if not preference_data.get('analysis_result'):
                raise ValueError(f"Individual analysis missing for {property_id}. Please analyze this property first.")

            # Convert Decimal to float
            property_data = json.loads(json.dumps(property_data, default=decimal_default))
            preference_data = json.loads(json.dumps(preference_data, default=decimal_default))

            properties_data.append({
                'property_id': property_id,
                'property_data': property_data,
                'individual_analysis': preference_data.get('analysis_result', {})
            })

        # Generate comparison prompt
        comparison_prompt = generate_comparison_prompt(properties_data)

        # Get AI comparison
        comparison_analysis = get_comparison_ai_analysis(comparison_prompt, request_id)

        # Store results
        analysis_for_dynamo = convert_to_dynamo_format(comparison_analysis)

        property_summary = {
            'compared_properties': [p['property_id'] for p in properties_data],
            'property_count': len(properties_data),
            'comparison_date': comparison_timestamp.isoformat()
        }

        preferences_table.update_item(
            Key={'user_id': user_id, 'property_id': comparison_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    analysis_completed_at = :completed,
                    analysis_result = :result,
                    property_summary = :summary
            ''',
            ExpressionAttributeValues={
                ':status': 'completed',
                ':completed': comparison_timestamp.isoformat(),
                ':result': analysis_for_dynamo,
                ':summary': property_summary
            }
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'comparison_id': comparison_id,
                'status': 'completed',
                'property_count': len(properties_data)
            })
        }

    except Exception as e:
        print(f"[ERROR] Comparison failed: {e}")

        preferences_table.update_item(
            Key={'user_id': user_id, 'property_id': comparison_id},
            UpdateExpression='SET analysis_status = :status, last_error = :error',
            ExpressionAttributeValues={
                ':status': 'failed',
                ':error': str(e)[:500]
            }
        )

        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e), 'comparison_id': comparison_id})
        }


def generate_comparison_prompt(properties_data):
    """Generate comparison prompt for multiple US properties"""

    prompt = f"""You are an expert US real estate analyst comparing {len(properties_data)} properties to help a buyer choose the best investment.

COMPARISON OVERVIEW:
For each property, I'll provide the key details and my previous individual analysis.

"""

    for i, prop in enumerate(properties_data, 1):
        p = prop['property_data']
        analysis = prop['individual_analysis']

        # Format property summary
        property_summary = f"""
=== PROPERTY {i} ===
Address: {p.get('address', 'N/A')}
City: {p.get('city', '')}, {p.get('state', '')}
Price: ${p.get('price', 0):,}
Size: {p.get('size_sqft', 0):,} sq ft ({p.get('beds', 0)} bed / {p.get('baths', 0)} bath)
Price/SqFt: ${p.get('price_per_sqft', 0):.0f}
Year Built: {p.get('year_built', 'Unknown')}
Days on Market: {p.get('days_on_market', 0)}
City Discount: {p.get('city_discount_pct', 0):.1f}%

PREVIOUS ANALYSIS:
{analysis.get('analysis_markdown', 'No previous analysis')}
"""
        prompt += property_summary

    prompt += """

Based on the above properties, provide a clear comparison and recommendation.

FORMAT YOUR RESPONSE WITH:

## 🏆 Overall Recommendation
- Best Choice: [Address]
- Why: [Brief reason in 1-2 sentences]

## 📊 Rankings (Best to Worst)
1. [Address] - [Key reason]
2. [Address] - [Key reason]
3. [Address] - [Key reason]

## 💰 Value Comparison
- Best price per square foot: [Property]
- Best overall value: [Property]
- Lowest carrying costs: [Property]

## ✅ Why #1 Stands Out
- [Advantage 1]
- [Advantage 2]
- [Advantage 3]

## ⚠️ Key Tradeoffs
[Brief discussion of what you give up with each choice]

## 💡 Recommended Strategy
[Action steps for the top choice]

## 📋 Decision Summary
[2-3 bullet points with the bottom line recommendation]

Be decisive and practical. Focus on investment value.
"""

    return prompt


def get_comparison_ai_analysis(prompt, request_id="unknown"):
    """Get comparison analysis from GPT"""
    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)

    messages = [
        {
            "role": "system",
            "content": "You are an expert US real estate analyst comparing investment properties. Provide clear rankings and recommendations in Markdown format."
        },
        {"role": "user", "content": prompt}
    ]

    try:
        logger.info(f"[AI] [{request_id}] Requesting comparison analysis")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=3000,
            temperature=0.7
        )
        text = response.choices[0].message.content

    except Exception as e:
        logger.error(f"[AI] [{request_id}] Comparison analysis failed: {e}")
        text = "Comparison analysis failed. Please try again."

    return {
        "analysis_markdown": text,
        "recommendation": "See analysis for details",
        "analysis_text": text
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
        secret_name = os.environ.get('OPENAI_SECRET_NAME', 'real-estate-ai/openai-api-key')
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret = response['SecretString']

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
            return fallback_key
        raise ValueError("No OpenAI API key available")
