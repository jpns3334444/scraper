import json
import boto3
import os
from datetime import datetime
from openai import OpenAI
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

favorites_table = dynamodb.Table(os.environ['FAVORITES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
bucket = os.environ['DATA_BUCKET']

def lambda_handler(event, context):
    # Process SQS messages
    for record in event['Records']:
        message = json.loads(record['body'])
        try:
            analyze_favorite(message)
        except Exception as e:
            print(f"Error analyzing favorite: {str(e)}")
            # Message will return to queue if not deleted

def analyze_favorite(message):
    favorite_id = message['favorite_id']
    property_id = message['property_id']
    
    # Update status to processing
    favorites_table.update_item(
        Key={'favorite_id': favorite_id},
        UpdateExpression='SET analysis_status = :status',
        ExpressionAttributeValues={':status': 'processing'}
    )
    
    try:
        # Build comprehensive data package
        data_package = build_property_data_package(property_id)
        
        # Generate prompt
        prompt = generate_investment_analysis_prompt(data_package)
        
        # Get ChatGPT analysis
        analysis = get_chatgpt_analysis(prompt, data_package.get('image_urls', []))
        
        # Store analysis result
        favorites_table.update_item(
            Key={'favorite_id': favorite_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    analysis_completed_at = :completed,
                    analysis_result = :result
            ''',
            ExpressionAttributeValues={
                ':status': 'completed',
                ':completed': datetime.utcnow().isoformat(),
                ':result': analysis
            }
        )
        
    except Exception as e:
        # Update with error status
        favorites_table.update_item(
            Key={'favorite_id': favorite_id},
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
        raise

def build_property_data_package(property_id):
    # 1. Get enriched data from DynamoDB
    dynamo_response = properties_table.get_item(
        Key={'property_id': property_id, 'sort_key': 'META'}
    )
    enriched_data = dynamo_response.get('Item', {})
    
    # Convert Decimal to float
    enriched_data = json.loads(json.dumps(enriched_data, default=decimal_default))
    
    # 2. Get raw scraped data from S3
    date_part = property_id.split('#')[1].split('_')[0]
    formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
    s3_key = f"raw/{formatted_date}/properties/{property_id}.json"
    
    raw_data = {}
    try:
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        raw_data = json.loads(response['Body'].read())
    except Exception as e:
        print(f"Raw property data not found in S3: {s3_key}")
        print(f"Could not load raw data from S3 key {s3_key}: {e}")
    
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
                    print(f"Failed to generate presigned URL for {s3_key}: {e}")
    
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
    enriched = data['enriched']
    raw = data.get('raw', {})
    
    prompt = f"""
    Analyze this Tokyo investment property for purchase potential:

    PROPERTY OVERVIEW:
    - ID: {enriched.get('property_id')}
    - Price: ¥{enriched.get('price', 0) * 10000:,}
    - Size: {enriched.get('size_sqm')} m²
    - Price/m²: ¥{enriched.get('price_per_sqm', 0):,.0f}
    - Location: {enriched.get('ward')}, {enriched.get('district', '')}
    - Station: {enriched.get('closest_station')} ({enriched.get('station_distance_minutes')} min)
    - Building: {enriched.get('building_age_years')} years, Floor {enriched.get('floor')}/{enriched.get('building_floors')}

    FINANCIAL DETAILS:
    - Monthly Costs: ¥{enriched.get('total_monthly_costs', 0):,}
    - Management Fee: ¥{enriched.get('management_fee', 0):,}
    - Repair Reserve: ¥{enriched.get('repair_reserve_fee', 0):,}

    ANALYSIS SCORING:
    - Final Score: {enriched.get('final_score', 'N/A')}/100
    - Base Score: {enriched.get('base_score', 'N/A')}
    - Ward Discount: {enriched.get('ward_discount_pct', 0):.1f}%
    - Verdict: {enriched.get('verdict', 'N/A')}
    
    ADDITIONAL RAW DATA:
    {format_raw_data(raw)}

    IMAGES: {len(data.get('image_urls', []))} property images provided

    PROVIDE COMPREHENSIVE ANALYSIS INCLUDING:
    1. Investment Rating (1-10) with detailed justification
    2. Estimated rental yield (gross and net)
    3. 5-year price appreciation forecast
    4. Renovation potential and estimated costs
    5. Target tenant profile and rental demand
    6. Key risks and red flags
    7. Comparison to market averages
    8. Specific action items if purchasing
    9. Exit strategy recommendations
    10. Final verdict: STRONG BUY / BUY / HOLD / PASS

    Format the response as a structured JSON with these sections:
    {{
        "investment_rating": 8.5,
        "rental_yield_gross": 4.2,
        "rental_yield_net": 3.1,
        "price_appreciation_5yr": "10-15%",
        "renovation_cost_estimate": "¥500,000",
        "target_tenant": "Young professionals",
        "key_risks": ["Risk 1", "Risk 2"],
        "market_comparison": "15% below market average",
        "action_items": ["Item 1", "Item 2"],
        "exit_strategy": "Hold 5-7 years then sell",
        "final_verdict": "BUY",
        "summary": "Detailed summary of analysis"
    }}
    """
    return prompt

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
    # Get OpenAI API key
    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)
    
    # Build messages with images
    messages = [
        {
            "role": "system",
            "content": "You are an expert Tokyo real estate investment analyst. Provide detailed, actionable analysis in valid JSON format only."
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt}
            ]
        }
    ]
    
    # Add images to the user message
    for url in image_urls:
        messages[1]["content"].append({
            "type": "image_url",
            "image_url": {"url": url}
        })
    
    response = client.chat.completions.create(
        model="gpt-4o",  # Use gpt-4o for vision capabilities
        messages=messages,
        max_tokens=2000,
        temperature=0.7
    )
    
    # Parse response and structure it
    analysis_text = response.choices[0].message.content
    
    # Try to parse as JSON, fallback to structured text
    try:
        analysis_json = json.loads(analysis_text)
        return analysis_json
    except json.JSONDecodeError:
        # Structure the text response
        return {
            "raw_analysis": analysis_text,
            "structured": parse_analysis_text(analysis_text),
            "final_verdict": "HOLD",  # Default fallback
            "investment_rating": 5.0
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
        api_key = response['SecretString']
        
        if not api_key or api_key.strip() == '':
            raise ValueError("Retrieved API key is empty")
        
        return api_key
        
    except Exception as e:
        print(f"Failed to get OpenAI API key: {e}")
        # Try fallback to environment variable
        fallback_key = os.environ.get('OPENAI_API_KEY')
        if fallback_key:
            print("Using fallback API key from environment variable")
            return fallback_key
        else:
            raise Exception(f"Failed to get OpenAI API key: {str(e)}")