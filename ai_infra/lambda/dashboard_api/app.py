import json
import logging
import os
from decimal import Decimal
from datetime import datetime
import boto3
from boto3.dynamodb.conditions import Key, Attr
import re

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-RealEstateAnalysis')
table = dynamodb.Table(table_name)

# S3 configuration for image URLs
s3_bucket = os.environ.get('OUTPUT_BUCKET', 'tokyo-real-estate-ai-data')
s3_region = os.environ.get('AWS_REGION', 'ap-northeast-1')
s3_client = boto3.client('s3')

# CORS headers for browser access
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
    'Access-Control-Allow-Methods': 'GET,OPTIONS'
}

def decimal_to_float(obj):
    """Convert DynamoDB Decimal objects to Python float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(v) for v in obj]
    return obj

def generate_image_urls(property_item):
    """Generate S3 presigned URLs for a property"""
    image_urls = []
    
    # Get property ID and analysis date
    property_id = property_item.get('property_id', '')
    analysis_date = property_item.get('analysis_date', '')
    photo_filenames = property_item.get('photo_filenames', '')
    
    if not property_id or not analysis_date:
        return image_urls
    
    # Extract date from analysis_date (format: 2025-01-25T10:30:00Z -> 2025-01-25)
    try:
        if 'T' in analysis_date:
            date_part = analysis_date.split('T')[0]
        else:
            date_part = analysis_date[:10]  # Take first 10 chars (YYYY-MM-DD)
    except:
        return image_urls
    
    # If we have photo_filenames, use those
    if photo_filenames:
        filenames = photo_filenames.split('|')
        for filename in filenames:
            if filename.strip():
                try:
                    # Generate presigned URL (valid for 1 hour)
                    presigned_url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': s3_bucket, 'Key': filename.strip()},
                        ExpiresIn=3600
                    )
                    image_urls.append(presigned_url)
                except Exception as e:
                    logger.warning(f"Failed to generate presigned URL for {filename}: {e}")
                    continue
    else:
        # Fallback: try to generate URLs based on expected pattern
        # Pattern: raw/{date}/images/{property_id}_{index}.jpg
        for i in range(3):  # Try first 3 images
            s3_key = f"raw/{date_part}/images/{property_id}_{i}.jpg"
            try:
                # Check if object exists first
                s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
                # Generate presigned URL (valid for 1 hour)
                presigned_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': s3_bucket, 'Key': s3_key},
                    ExpiresIn=3600
                )
                image_urls.append(presigned_url)
            except Exception as e:
                # Object doesn't exist or other error, skip
                continue
    
    return image_urls

def build_filter_expression(params):
    """Build DynamoDB filter expression from query parameters"""
    filter_parts = []
    expr_values = {}
    expr_names = {}
    
    # Price filters
    if params.get('min_price'):
        filter_parts.append('#price >= :min_price')
        expr_values[':min_price'] = int(params['min_price'])
        expr_names['#price'] = 'price'
    
    if params.get('max_price'):
        filter_parts.append('#price <= :max_price')
        expr_values[':max_price'] = int(params['max_price'])
        expr_names['#price'] = 'price'
    
    if params.get('min_price_per_sqm'):
        filter_parts.append('price_per_sqm >= :min_ppsqm')
        expr_values[':min_ppsqm'] = int(params['min_price_per_sqm'])
    
    if params.get('max_price_per_sqm'):
        filter_parts.append('price_per_sqm <= :max_ppsqm')
        expr_values[':max_ppsqm'] = int(params['max_price_per_sqm'])
    
    # Location filters
    if params.get('ward'):
        filter_parts.append('ward = :ward')
        expr_values[':ward'] = params['ward']
    
    if params.get('district'):
        filter_parts.append('district = :district')
        expr_values[':district'] = params['district']
    
    if params.get('max_station_distance'):
        filter_parts.append('station_distance_minutes <= :max_station')
        expr_values[':max_station'] = int(params['max_station_distance'])
    
    # Property filters
    if params.get('property_type'):
        filter_parts.append('property_type = :prop_type')
        expr_values[':prop_type'] = params['property_type']
    
    if params.get('min_bedrooms'):
        filter_parts.append('num_bedrooms >= :min_br')
        expr_values[':min_br'] = int(params['min_bedrooms'])
    
    if params.get('max_bedrooms'):
        filter_parts.append('num_bedrooms <= :max_br')
        expr_values[':max_br'] = int(params['max_bedrooms'])
    
    if params.get('min_sqm'):
        filter_parts.append('total_sqm >= :min_sqm')
        expr_values[':min_sqm'] = Decimal(params['min_sqm'])
    
    if params.get('max_sqm'):
        filter_parts.append('total_sqm <= :max_sqm')
        expr_values[':max_sqm'] = Decimal(params['max_sqm'])
    
    if params.get('max_building_age'):
        filter_parts.append('building_age_years <= :max_age')
        expr_values[':max_age'] = int(params['max_building_age'])
    
    # Investment filters
    if params.get('verdict'):
        verdicts = params['verdict'].split(',')
        verdict_conditions = []
        for i, verdict in enumerate(verdicts):
            verdict_key = f':verdict{i}'
            verdict_conditions.append(f'verdict = {verdict_key}')
            expr_values[verdict_key] = verdict.upper()
        filter_parts.append(f"({' OR '.join(verdict_conditions)})")
    
    if params.get('min_score'):
        filter_parts.append('investment_score >= :min_score')
        expr_values[':min_score'] = int(params['min_score'])
    
    # Combine all filter parts
    filter_expr = ' AND '.join(filter_parts) if filter_parts else None
    
    return filter_expr, expr_values, expr_names

def get_sort_key(sort_by):
    """Get the sort key and reverse flag based on sort_by parameter"""
    sort_mappings = {
        'price_asc': ('price', False),
        'price_desc': ('price', True),
        'price_per_sqm_asc': ('price_per_sqm', False),
        'price_per_sqm_desc': ('price_per_sqm', True),
        'sqm_asc': ('total_sqm', False),
        'sqm_desc': ('total_sqm', True),
        'age_asc': ('building_age_years', False),
        'age_desc': ('building_age_years', True),
        'station_asc': ('station_distance_minutes', False),
        'station_desc': ('station_distance_minutes', True),
        'score_asc': ('investment_score', False),
        'score_desc': ('investment_score', True),
        'date_asc': ('analysis_date', False),
        'date_desc': ('analysis_date', True),
    }
    
    return sort_mappings.get(sort_by, ('analysis_date', True))

def lambda_handler(event, context):
    """Handle API requests for property data"""
    
    # Handle OPTIONS request for CORS
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': ''
        }
    
    try:
        # Get query parameters
        params = event.get('queryStringParameters', {}) or {}
        
        # Pagination parameters
        page = int(params.get('page', 1))
        limit = min(int(params.get('limit', 50)), 1000)  # Max 1000 items per page
        
        # Build filter expression
        filter_expr, expr_values, expr_names = build_filter_expression(params)
        
        # Query DynamoDB - scan all META items
        scan_kwargs = {
            'FilterExpression': Attr('sort_key').eq('META')
        }
        
        if filter_expr:
            # Add custom filters
            scan_kwargs['FilterExpression'] = scan_kwargs['FilterExpression'] & eval(filter_expr.replace(' AND ', ' & ').replace(' OR ', ' | ').replace('=', '.eq(').replace('>=', '.gte(').replace('<=', '.lte(').replace(')', '))'))
            
        # Perform scan to get all matching items
        items = []
        last_evaluated_key = None
        
        while True:
            if last_evaluated_key:
                scan_kwargs['ExclusiveStartKey'] = last_evaluated_key
                
            response = table.scan(**scan_kwargs)
            items.extend(response.get('Items', []))
            
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        
        # Sort items
        sort_key, reverse = get_sort_key(params.get('sort_by', 'date_desc'))
        items.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
        
        # Paginate results
        total_count = len(items)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_items = items[start_idx:end_idx]
        
        # Get unique values for filters
        all_wards = sorted(list(set(item.get('ward', '') for item in items if item.get('ward'))))
        all_districts = sorted(list(set(item.get('district', '') for item in items if item.get('district'))))
        all_property_types = sorted(list(set(item.get('property_type', '') for item in items if item.get('property_type'))))
        
        # Format response with image URLs
        formatted_properties = []
        for item in paginated_items:
            property_data = decimal_to_float(item)
            # Add image URLs
            property_data['image_urls'] = generate_image_urls(item)
            # Fix listing URL field mapping (scraper uses 'url', frontend expects 'listing_url')
            if 'url' in property_data and not property_data.get('listing_url'):
                property_data['listing_url'] = property_data['url']
            # If listing_url is still empty, try to reconstruct from property_id
            elif not property_data.get('listing_url') and property_data.get('property_id'):
                # Extract the actual homes.co.jp ID from property_id (format: PROP#YYYYMMDD_XXXXX)
                prop_id = property_data['property_id']
                if '#' in prop_id and '_' in prop_id:
                    # Extract the ID after the underscore
                    homes_id = prop_id.split('_')[-1]
                    if homes_id.isdigit():
                        property_data['listing_url'] = f"https://www.homes.co.jp/mansion/b-{homes_id}"
            # Ensure price_per_sqm is included (it should already be in DynamoDB)
            if 'price_per_sqm' not in property_data and 'price' in property_data and 'total_sqm' in property_data:
                if property_data['total_sqm'] and property_data['total_sqm'] > 0:
                    property_data['price_per_sqm'] = property_data['price'] / property_data['total_sqm']
                else:
                    property_data['price_per_sqm'] = 0
            formatted_properties.append(property_data)
        
        response_data = {
            'properties': formatted_properties,
            'total_count': total_count,
            'page': page,
            'limit': limit,
            'total_pages': (total_count + limit - 1) // limit,
            'filters': {
                'wards': all_wards,
                'districts': all_districts,
                'property_types': all_property_types
            }
        }
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps(response_data)
        }
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }