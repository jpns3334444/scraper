#!/usr/bin/env python3
"""
Favorites API Lambda - Manages user favorites and hidden properties (US market)
"""
import json
import boto3
import os
from datetime import datetime
from decimal import Decimal
from urllib.parse import unquote


def get_aws_region():
    """Get AWS region from environment or default"""
    return os.environ.get('AWS_REGION', 'us-east-1')


# Setup AWS resources
dynamodb = boto3.resource('dynamodb', region_name=get_aws_region())
lambda_client = boto3.client('lambda', region_name=get_aws_region())

preferences_table = dynamodb.Table(os.environ.get('PREFERENCES_TABLE', 'real-estate-ai-user-preferences'))
properties_table = dynamodb.Table(os.environ.get('PROPERTIES_TABLE', 'real-estate-ai-properties'))


def decimal_to_float(obj):
    """Convert DynamoDB Decimal objects to Python float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(v) for v in obj]
    return obj


def ensure_decimal(value):
    """Convert float/int to Decimal for DynamoDB storage"""
    if isinstance(value, float):
        return Decimal(str(value))
    elif isinstance(value, int):
        return Decimal(value)
    elif isinstance(value, dict):
        return {k: ensure_decimal(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [ensure_decimal(v) for v in value]
    return value


def lambda_handler(event, context):
    """Main Lambda handler for favorites API"""
    print(f"Received event: {json.dumps(event)}")

    # Determine origin_header for CORS
    origin_header = event.get("headers", {}).get("origin", "*")

    try:
        # Handle OPTIONS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-User-Email"
                },
                "body": json.dumps({})
            }

        # Extract request info
        method = event.get('httpMethod', '')
        path = event.get('path', '')
        headers = event.get('headers', {})
        user_email = headers.get('x-user-email') or headers.get('X-User-Email') or 'anonymous'
        user_id = user_email

        print(f"Request: {method} {path}, User: {user_id}")

        # Route handling
        if method == 'POST' and path == '/favorites':
            return add_preference(event, user_id, 'favorite')

        elif method == 'POST' and path == '/favorites/compare':
            return compare_favorites(event, user_id)

        elif method == 'POST' and path == '/hidden':
            return add_preference(event, user_id, 'hidden')

        elif method == 'DELETE' and path.startswith('/favorites/'):
            return remove_preference(event, user_id, 'favorite')

        elif method == 'DELETE' and path.startswith('/hidden/'):
            return remove_preference(event, user_id, 'hidden')

        elif method == 'GET' and '/favorites/' in path:
            path_params = event.get('pathParameters', {})

            # Get user's favorites list: /favorites/user/{userId}
            if '/favorites/user/' in path and path_params and 'userId' in path_params:
                decoded_user_id = unquote(path_params['userId'])
                return get_user_preferences(event, decoded_user_id, 'favorite')

            # Get analysis for specific favorite: /favorites/analysis/{userEmail}/{propertyId}
            elif '/favorites/analysis/' in path and path_params:
                if 'userEmail' in path_params and 'propertyId' in path_params:
                    user_email = unquote(path_params['userEmail'])
                    property_id = unquote(path_params['propertyId'])
                    return get_favorite_analysis(event, user_email, property_id)

        elif method == 'GET' and '/hidden/user/' in path:
            path_params = event.get('pathParameters', {})
            if path_params and 'userId' in path_params:
                decoded_user_id = unquote(path_params['userId'])
                return get_user_preferences(event, decoded_user_id, 'hidden')

        # No route matched
        return {
            "statusCode": 404,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': 'Not Found'})
        }

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': 'Internal server error'})
        }


def add_preference(event, user_id, preference_type):
    """Add a property to favorites or hidden list"""
    origin_header = event.get("headers", {}).get("origin", "*")

    try:
        body = json.loads(event.get('body', '{}'))
        property_id = body.get('property_id')

        if not property_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'property_id is required'})
            }

        # Check if preference already exists
        existing = preferences_table.get_item(
            Key={'user_id': user_id, 'property_id': property_id}
        )

        if 'Item' in existing:
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'message': f'Already {preference_type}'})
            }

        # Get property details
        property_data = properties_table.get_item(
            Key={'property_id': property_id, 'sort_key': 'META'}
        ).get('Item', {})

        # Create preference record with US property fields
        image_urls = property_data.get('image_urls', [])
        first_image = image_urls[0] if image_urls else None

        preference_item = {
            'user_id': user_id,
            'property_id': property_id,
            'preference_type': preference_type,
            'created_at': datetime.utcnow().isoformat(),
            'property_summary': {
                'price': property_data.get('price', Decimal('0')),
                'city': property_data.get('city', ''),
                'state': property_data.get('state', ''),
                'address': property_data.get('address', ''),
                'size_sqft': property_data.get('size_sqft', Decimal('0')),
                'beds': property_data.get('beds', Decimal('0')),
                'baths': property_data.get('baths', Decimal('0')),
                'property_type': property_data.get('property_type', ''),
                'image_url': first_image,
                'listing_url': property_data.get('listing_url', '')
            }
        }

        # Ensure all numeric values are Decimals
        preference_item = ensure_decimal(preference_item)

        # Add analysis fields for favorites only
        if preference_type == 'favorite':
            preference_item.update({
                'analysis_status': 'pending',
                'analysis_requested_at': datetime.utcnow().isoformat()
            })

        preferences_table.put_item(Item=preference_item)

        # Invoke analyzer Lambda for favorites
        if preference_type == 'favorite':
            try:
                analyzer_function = os.environ.get('FAVORITE_ANALYZER_FUNCTION', 'real-estate-ai-favorite-analyzer')
                lambda_client.invoke(
                    FunctionName=analyzer_function,
                    InvocationType='Event',  # async
                    Payload=json.dumps({'user_id': user_id, 'property_id': property_id})
                )
            except Exception as e:
                print(f"Failed to invoke analyzer: {e}")
                # Don't fail the request if analyzer fails

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'success': True, 'user_id': user_id, 'property_id': property_id})
        }

    except Exception as e:
        print(f"ERROR in add_preference: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': str(e)})
        }


def remove_preference(event, user_id, preference_type):
    """Remove a property from favorites or hidden list"""
    origin_header = event.get("headers", {}).get("origin", "*")

    try:
        # Get property_id from path
        path_params = event.get('pathParameters', {})
        property_id = path_params.get('id') or event.get('path', '').split('/')[-1]
        property_id = unquote(property_id)

        if not property_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'property_id not found'})
            }

        # Delete the preference
        delete_response = preferences_table.delete_item(
            Key={'user_id': user_id, 'property_id': property_id},
            ReturnValues='ALL_OLD'
        )

        if 'Attributes' not in delete_response:
            return {
                'statusCode': 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                'body': json.dumps({'error': f'{preference_type.capitalize()} not found'})
            }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({
                'success': True,
                'deleted': True,
                'user_id': user_id,
                'property_id': property_id
            })
        }

    except Exception as e:
        print(f"ERROR in remove_preference: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': 'Internal server error'})
        }


def get_user_preferences(event, user_id, preference_type):
    """Get all preferences of a type for a user"""
    origin_header = event.get("headers", {}).get("origin", "*")

    try:
        user_id = unquote(str(user_id))

        # Query GSI for user's preferences
        response = preferences_table.query(
            IndexName='user-type-index',
            KeyConditionExpression='user_id = :uid AND preference_type = :ptype',
            ExpressionAttributeValues={
                ':uid': user_id,
                ':ptype': preference_type
            },
            ScanIndexForward=False  # Most recent first
        )

        preferences = response.get('Items', [])

        # Convert Decimal to float for JSON serialization
        preferences = decimal_to_float(preferences)

        # Return with appropriate key
        result_key = 'favorites' if preference_type == 'favorite' else 'hidden'

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({result_key: preferences})
        }

    except Exception as e:
        print(f"ERROR in get_user_preferences: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': str(e)})
        }


def get_favorite_analysis(event, user_id, property_id):
    """Get analysis result for a specific favorite"""
    origin_header = event.get("headers", {}).get("origin", "*")

    try:
        user_id = unquote(str(user_id))
        property_id = unquote(str(property_id))

        # Get the favorite item
        favorite_response = preferences_table.get_item(
            Key={'user_id': user_id, 'property_id': property_id}
        )

        if 'Item' not in favorite_response:
            return {
                "statusCode": 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'Favorite not found'})
            }

        favorite_item = favorite_response['Item']

        # Get property data for images
        property_response = properties_table.get_item(
            Key={'property_id': property_id, 'sort_key': 'META'}
        )
        property_data = property_response.get('Item', {})

        # Get image URLs directly (stored from realtor.com)
        property_images = property_data.get('image_urls', [])[:5]

        # Convert Decimals to floats
        analysis_result = decimal_to_float(favorite_item.get('analysis_result', {}))
        property_summary = decimal_to_float(favorite_item.get('property_summary', {}))

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({
                "analysis_result": analysis_result,
                "analysis_status": favorite_item.get('analysis_status', 'pending'),
                "property_images": property_images,
                "property_summary": property_summary
            })
        }

    except Exception as e:
        print(f"ERROR in get_favorite_analysis: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': str(e)})
        }


def compare_favorites(event, user_id):
    """Compare multiple favorite properties using GPT analysis"""
    origin_header = event.get("headers", {}).get("origin", "*")

    try:
        body = json.loads(event.get('body', '{}'))
        property_ids = body.get('property_ids', [])
        user_email = body.get('user_email') or user_id

        if len(property_ids) < 2:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'Need at least 2 properties to compare'})
            }

        # Generate comparison ID
        comparison_timestamp = datetime.utcnow()
        comparison_id = f"COMPARISON_{comparison_timestamp.strftime('%Y-%m-%d_%H-%M-%S')}"

        # Create initial comparison record
        preferences_table.put_item(
            Item={
                'user_id': user_email,
                'property_id': comparison_id,
                'preference_type': 'favorite',
                'analysis_status': 'processing',
                'created_at': comparison_timestamp.isoformat(),
                'comparison_date': comparison_timestamp.isoformat(),
                'property_count': len(property_ids),
                'property_summary': {
                    'compared_properties': property_ids,
                    'property_count': len(property_ids),
                    'comparison_date': comparison_timestamp.isoformat()
                }
            }
        )

        # Invoke analyzer asynchronously
        analyzer_payload = {
            'operation': 'compare_favorites',
            'user_id': user_email,
            'property_ids': property_ids,
            'comparison_id': comparison_id
        }

        lambda_client.invoke(
            FunctionName=os.environ.get('FAVORITE_ANALYZER_FUNCTION', 'real-estate-ai-favorite-analyzer'),
            InvocationType='Event',
            Payload=json.dumps(analyzer_payload)
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({
                'comparison_id': comparison_id,
                'status': 'processing',
                'property_count': len(property_ids)
            })
        }

    except Exception as e:
        print(f"ERROR in compare_favorites: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'error': str(e)})
        }
