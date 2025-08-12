import json
import logging
import os

# Load environment variables from .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, use existing environment
from decimal import Decimal
from datetime import datetime
import boto3
from boto3.dynamodb.conditions import Key, Attr
import re
import sys
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('PROPERTIES_TABLE', 'tokyo-real-estate-ai-analysis-db')
table = dynamodb.Table(table_name)

# Get listing fetch size from environment (matches config.json)
LISTING_FETCH_SIZE = int(os.environ.get('LISTING_FETCH_SIZE', '300'))

# S3 configuration for image URLs
s3_bucket = os.environ.get('OUTPUT_BUCKET', 'tokyo-real-estate-ai-data')
s3_region = os.environ.get('AWS_REGION', 'ap-northeast-1')
s3_client = boto3.client('s3')


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

def get_user_favorite_ids(user_id):
    """Get set of property IDs favorited by user"""
    if not user_id or user_id == 'anonymous':
        return set()
    
    try:
        preferences_table_name = os.environ.get('PREFERENCES_TABLE')
        if not preferences_table_name:
            return set()
        
        prefs_table = dynamodb.Table(preferences_table_name)
        
        response = prefs_table.query(
            IndexName='user-type-index',
            KeyConditionExpression='user_id = :uid AND preference_type = :fav',
            ExpressionAttributeValues={':uid': user_id, ':fav': 'favorite'},
            ProjectionExpression='property_id'
        )
        
        return {item['property_id'] for item in response.get('Items', [])}
    except Exception as e:
        print(f"Error getting user favorites: {e}")
        return set()

def lambda_handler(event, context):
    """Handle API requests for property data with cursor-based pagination"""
    
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
    # Debug logging for OPTIONS
    if event.get('httpMethod') == 'OPTIONS':
        logger.info(f"OPTIONS request received. Full event: {json.dumps(event)}")
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({})
        }
    
    try:
        # Handle default route (404 for unmatched paths) - ensure CORS headers
        route_key = event.get('routeKey', '')
        raw_path = event.get('rawPath', '')
        
        # If this is the $default route (catches all unmatched paths), return 404
        if route_key == '$default':
            return {
                "statusCode": 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'message': 'Not Found'})
            }
        
        # If the path is not exactly /properties, return 404
        if raw_path and raw_path not in ['/properties', '/prod/properties']:
            return {
                "statusCode": 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'message': 'Not Found'})
            }
        
        # Get query parameters
        params = event.get('queryStringParameters', {}) or {}
        
        # Get user_id from headers
        user_id = event.get('headers', {}).get('X-User-Id', 'anonymous')
        
        # Pagination parameters
        limit = max(1, min(int(params.get('limit', 100)), LISTING_FETCH_SIZE))  # Default 100, max LISTING_FETCH_SIZE
        cursor = json.loads(params['cursor']) if 'cursor' in params else None
        
        # Accumulate items until we reach the desired limit
        # DynamoDB scan with filters can return fewer items than the limit due to filtering
        items = []
        last_evaluated_key = cursor
        scan_count = 0
        max_scans = 10  # Prevent infinite loops
        
        while len(items) < limit and scan_count < max_scans:
            # Add price filtering to DynamoDB scan - filter out properties over 3000 万円 (30M yen)
            filter_expr = Attr('sort_key').eq('META') & (Attr('price').lt(3000) | Attr('price').not_exists())
            
            scan_kwargs = {
                'FilterExpression': filter_expr,
                'ProjectionExpression': 'PK, price, size_sqm, total_sqm, ward, ward_discount_pct, img_url, listing_url, #url_attr, verdict, recommendation, property_id, analysis_date, photo_filenames, price_per_sqm, total_monthly_costs, ward_median_price_per_sqm, closest_station, station_distance_minutes, #floor_attr, building_age_years, primary_light',
                'ExpressionAttributeNames': {
                    '#url_attr': 'url',
                    '#floor_attr': 'floor'
                }
            }
            
            if last_evaluated_key:
                scan_kwargs['ExclusiveStartKey'] = last_evaluated_key
            
            # Scan for more items than needed to account for filtering
            # Request 3x the remaining needed items, capped at 300
            remaining_needed = limit - len(items)
            scan_kwargs['Limit'] = min(remaining_needed * 3, 300)
            
            response = table.scan(**scan_kwargs)
            batch_items = response.get('Items', [])
            items.extend(batch_items)
            
            last_evaluated_key = response.get('LastEvaluatedKey')
            scan_count += 1
            
            # Stop if no more items or we got no items in this batch
            if not last_evaluated_key or not batch_items:
                break
        
        # Trim to requested limit if we got more than needed
        if len(items) > limit:
            items = items[:limit]
            # If we trimmed, we might have more items available, so preserve the cursor
            # by using the last evaluated key from before the trim
        
        # Get user's favorites if user is authenticated
        user_favorites = get_user_favorite_ids(user_id) if user_id != 'anonymous' else set()
        
        # Format response with necessary transformations
        formatted_items = []
        for item in items:
            # Convert Decimal to float for JSON serialization
            property_data = json.loads(json.dumps(item, default=str))
            
            # Parse numeric strings back to numbers
            numeric_fields = ['price', 'size_sqm', 'total_sqm', 'ward_discount_pct', 'price_per_sqm', 
                            'total_monthly_costs', 'ward_median_price_per_sqm', 'station_distance_minutes', 
                            'floor', 'building_age_years']
            for field in numeric_fields:
                if field in property_data and property_data[field]:
                    try:
                        property_data[field] = float(property_data[field])
                    except:
                        pass
            
            # Fix listing URL field mapping
            if 'url' in property_data and not property_data.get('listing_url'):
                property_data['listing_url'] = property_data['url']
            # If listing_url is still empty, try to reconstruct from property_id
            elif not property_data.get('listing_url') and property_data.get('property_id'):
                prop_id = property_data['property_id']
                if '#' in prop_id and '_' in prop_id:
                    homes_id = prop_id.split('_')[-1]
                    if homes_id.isdigit():
                        property_data['listing_url'] = f"https://www.homes.co.jp/mansion/b-{homes_id}"
            
            # Ensure size_sqm exists (some records might have total_sqm instead)
            if 'total_sqm' in property_data and 'size_sqm' not in property_data:
                property_data['size_sqm'] = property_data['total_sqm']
            
            # Add first image URL if available
            if property_data.get('img_url'):
                property_data['image_url'] = property_data['img_url']
            elif property_data.get('photo_filenames'):
                # Use first photo if available
                first_photo = property_data['photo_filenames'].split('|')[0].strip()
                if first_photo:
                    try:
                        property_data['image_url'] = s3_client.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': s3_bucket, 'Key': first_photo},
                            ExpiresIn=3600
                        )
                    except:
                        pass
            
            # Add favorite status
            property_data['is_favorited'] = property_data.get('property_id') in user_favorites
            
            formatted_items.append(property_data)
        
        # Prepare response
        body = {
            'items': formatted_items,
            'cursor': last_evaluated_key
        }
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps(body)
        }
        
    except Exception as e:
        print("ERROR:", e)
        logger.error(f"Error processing request: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': str(e)})
        }