#!/usr/bin/env python3
"""
Dashboard API Lambda - Serves property data for the frontend (US market)
"""
import json
import logging
import os
from decimal import Decimal
from datetime import datetime
import boto3
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_aws_region():
    """Get AWS region from environment or default"""
    return os.environ.get('AWS_REGION', 'us-east-1')


# Setup DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=get_aws_region())
table_name = os.environ.get('PROPERTIES_TABLE', 'real-estate-ai-properties')
table = dynamodb.Table(table_name)

# Get listing fetch size from environment
LISTING_FETCH_SIZE = int(os.environ.get('LISTING_FETCH_SIZE', '300'))

# S3 configuration for images
s3_bucket = os.environ.get('OUTPUT_BUCKET', 'real-estate-ai-data')
s3_client = boto3.client('s3', region_name=get_aws_region())


def decimal_to_float(obj):
    """Convert DynamoDB Decimal objects to Python float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(v) for v in obj]
    return obj


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
        logger.error(f"Error getting user favorites: {e}")
        return set()


def get_sort_key(sort_by):
    """Get the sort key and reverse flag based on sort_by parameter"""
    sort_mappings = {
        'price_asc': ('price', False),
        'price_desc': ('price', True),
        'price_per_sqft_asc': ('price_per_sqft', False),
        'price_per_sqft_desc': ('price_per_sqft', True),
        'sqft_asc': ('size_sqft', False),
        'sqft_desc': ('size_sqft', True),
        'beds_asc': ('beds', False),
        'beds_desc': ('beds', True),
        'date_asc': ('analysis_date', False),
        'date_desc': ('analysis_date', True),
        'days_on_market_asc': ('days_on_market', False),
        'days_on_market_desc': ('days_on_market', True),
    }

    return sort_mappings.get(sort_by, ('analysis_date', True))


def lambda_handler(event, context):
    """Handle API requests for property data"""

    # Determine origin_header at runtime for CORS
    origin_header = event.get("headers", {}).get("origin", "*")

    # Handle OPTIONS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-User-Id"
            },
            "body": json.dumps({})
        }

    try:
        # Handle routing
        route_key = event.get('routeKey', '')
        raw_path = event.get('rawPath', '')

        # If this is the $default route, return 404
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

        # Get query parameters
        params = event.get('queryStringParameters', {}) or {}

        # Get user_id from headers
        user_id = event.get('headers', {}).get('X-User-Id', 'anonymous')

        # Pagination parameters
        limit = max(1, min(int(params.get('limit', 100)), LISTING_FETCH_SIZE))
        cursor = json.loads(params['cursor']) if 'cursor' in params else None

        # Build filter expression
        filter_expr = Attr('sort_key').eq('META')

        # City filter
        if params.get('city'):
            filter_expr = filter_expr & Attr('city').eq(params['city'])

        # State filter
        if params.get('state'):
            filter_expr = filter_expr & Attr('state').eq(params['state'])

        # Price filters
        if params.get('min_price'):
            filter_expr = filter_expr & Attr('price').gte(int(params['min_price']))
        if params.get('max_price'):
            filter_expr = filter_expr & Attr('price').lte(int(params['max_price']))

        # Beds/Baths filters
        if params.get('min_beds'):
            filter_expr = filter_expr & Attr('beds').gte(int(params['min_beds']))
        if params.get('max_beds'):
            filter_expr = filter_expr & Attr('beds').lte(int(params['max_beds']))
        if params.get('min_baths'):
            filter_expr = filter_expr & Attr('baths').gte(float(params['min_baths']))

        # Size filter
        if params.get('min_sqft'):
            filter_expr = filter_expr & Attr('size_sqft').gte(int(params['min_sqft']))
        if params.get('max_sqft'):
            filter_expr = filter_expr & Attr('size_sqft').lte(int(params['max_sqft']))

        # Property type filter
        if params.get('property_type'):
            filter_expr = filter_expr & Attr('property_type').eq(params['property_type'])

        # Accumulate items with pagination
        items = []
        last_evaluated_key = cursor
        scan_count = 0
        max_scans = 10

        while len(items) < limit and scan_count < max_scans:
            scan_kwargs = {
                'FilterExpression': filter_expr,
                'ProjectionExpression': 'property_id, price, size_sqft, beds, baths, '
                                       'city, #st, zip_code, address, property_type, '
                                       'listing_url, image_urls, image_count, '
                                       'price_per_sqft, city_discount_pct, city_median_price_per_sqft, '
                                       'days_on_market, analysis_date, first_seen_date, '
                                       'year_built, lot_size_sqft, hoa_fee, mls_id',
                'ExpressionAttributeNames': {
                    '#st': 'state'  # 'state' is a reserved word in DynamoDB
                }
            }

            if last_evaluated_key:
                scan_kwargs['ExclusiveStartKey'] = last_evaluated_key

            # Request more items than needed to account for filtering
            remaining_needed = limit - len(items)
            scan_kwargs['Limit'] = min(remaining_needed * 3, 300)

            response = table.scan(**scan_kwargs)
            batch_items = response.get('Items', [])
            items.extend(batch_items)

            last_evaluated_key = response.get('LastEvaluatedKey')
            scan_count += 1

            if not last_evaluated_key or not batch_items:
                break

        # Trim to requested limit
        if len(items) > limit:
            items = items[:limit]

        # Get user's favorites
        user_favorites = get_user_favorite_ids(user_id) if user_id != 'anonymous' else set()

        # Format response
        formatted_items = []
        for item in items:
            # Convert Decimal to float
            property_data = decimal_to_float(item)

            # Add first image URL if available
            image_urls = property_data.get('image_urls', [])
            if image_urls and len(image_urls) > 0:
                property_data['image_url'] = image_urls[0]

            # Add favorite status
            property_data['is_favorited'] = property_data.get('property_id') in user_favorites

            formatted_items.append(property_data)

        # Sort results
        sort_by = params.get('sort', 'date_desc')
        sort_key, reverse = get_sort_key(sort_by)

        try:
            formatted_items.sort(
                key=lambda x: x.get(sort_key) or 0,
                reverse=reverse
            )
        except Exception:
            pass  # Keep original order if sorting fails

        # Prepare response
        body = {
            'items': formatted_items,
            'cursor': last_evaluated_key,
            'total_in_page': len(formatted_items)
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps(body, default=str)
        }

    except Exception as e:
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
