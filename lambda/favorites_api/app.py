import json
import boto3
import os
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')
s3 = boto3.client('s3')

favorites_table = dynamodb.Table(os.environ['FAVORITES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
queue_url = os.environ['ANALYSIS_QUEUE_URL']
output_bucket = os.environ.get('OUTPUT_BUCKET', 'tokyo-real-estate-ai-data')

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,X-User-Email,Authorization',
    'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS'
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

def lambda_handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    
    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS}
    
    # Extract user email from header (authenticated user)
    user_email = event['headers'].get('x-user-email', event['headers'].get('X-User-Email', 'anonymous'))
    # For backward compatibility, use email as user_id
    user_id = user_email
    
    if method == 'POST' and path == '/favorites':
        return add_favorite(event, user_id)
    elif method == 'DELETE' and path.startswith('/favorites/'):
        return remove_favorite(event, user_id)
    elif method == 'GET' and path.startswith('/favorites/'):
        # Extract userId from path parameters
        path_params = event.get('pathParameters', {})
        if path_params and 'userId' in path_params:
            return get_user_favorites(path_params['userId'])
        elif '/analysis' in path:
            return get_analysis(event, user_id)
    
    # Fallback to path parsing for compatibility
    if method == 'GET' and path.count('/') == 2:  # /favorites/{userId}
        path_parts = path.split('/')
        if len(path_parts) == 3 and path_parts[1] == 'favorites':
            return get_user_favorites(path_parts[2])
    
    return {'statusCode': 404, 'headers': CORS_HEADERS}

def add_favorite(event, user_id):
    body = json.loads(event['body'])
    property_id = body['property_id']
    
    # Check if already favorited
    favorite_id = f"{user_id}_{property_id}"
    
    try:
        existing = favorites_table.get_item(Key={'favorite_id': favorite_id})
        
        if 'Item' in existing:
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps({'message': 'Already favorited'})
            }
        
        # Get property details for thumbnail
        property_data = properties_table.get_item(
            Key={'property_id': property_id, 'sort_key': 'META'}
        ).get('Item', {})
        
        # Create favorite record
        favorite_item = {
            'favorite_id': favorite_id,
            'user_id': user_id,
            'property_id': property_id,
            'favorited_at': datetime.utcnow().isoformat(),
            'analysis_status': 'pending',
            'analysis_requested_at': datetime.utcnow().isoformat(),
            # Store essential property data for quick display
            'property_summary': {
                'price': decimal_to_float(property_data.get('price', 0)),
                'ward': property_data.get('ward', ''),
                'size_sqm': decimal_to_float(property_data.get('size_sqm', 0)),
                'station': property_data.get('closest_station', ''),
                'image_url': property_data.get('photo_filenames', '').split('|')[0] if property_data.get('photo_filenames') else None
            }
        }
        
        favorites_table.put_item(Item=favorite_item)
        
        # Send to analysis queue
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                'favorite_id': favorite_id,
                'user_id': user_id,
                'property_id': property_id
            })
        )
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'success': True, 'favorite_id': favorite_id})
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }

def remove_favorite(event, user_id):
    # Try to get ID from path parameters first (HTTP API v2)
    path_params = event.get('pathParameters', {})
    if path_params and 'id' in path_params:
        favorite_id = path_params['id']
    else:
        # Fallback to path parsing
        path_parts = event['rawPath'].split('/')
        favorite_id = path_parts[-1]
    
    try:
        # Verify ownership
        if not favorite_id.startswith(user_id + '_'):
            return {
                'statusCode': 403,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        favorites_table.delete_item(Key={'favorite_id': favorite_id})
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'success': True})
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }

def get_user_favorites(user_id):
    try:
        # Query GSI for user's favorites
        response = favorites_table.query(
            IndexName='user-favorites-index',
            KeyConditionExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id},
            ScanIndexForward=False  # Most recent first
        )
        
        favorites = response.get('Items', [])
        
        # Convert Decimal to float for JSON serialization
        favorites = decimal_to_float(favorites)
        
        # Convert S3 keys to presigned URLs for images
        for favorite in favorites:
            property_summary = favorite.get('property_summary', {})
            if property_summary.get('image_url'):
                try:
                    # Generate presigned URL for the image
                    presigned_url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': output_bucket, 'Key': property_summary['image_url']},
                        ExpiresIn=3600
                    )
                    property_summary['image_url'] = presigned_url
                except Exception as e:
                    # If presigned URL generation fails, remove the image_url
                    property_summary['image_url'] = None
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'favorites': favorites})
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }

def get_analysis(event, user_id):
    # Try to get ID from path parameters first (HTTP API v2)
    path_params = event.get('pathParameters', {})
    if path_params and 'id' in path_params:
        favorite_id = path_params['id']
    else:
        # Fallback to path parsing
        path_parts = event['rawPath'].split('/')
        favorite_id = path_parts[-2]  # Assuming path like /favorites/{favorite_id}/analysis
    
    try:
        # Verify ownership
        if not favorite_id.startswith(user_id + '_'):
            return {
                'statusCode': 403,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        # Get favorite record
        response = favorites_table.get_item(Key={'favorite_id': favorite_id})
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Favorite not found'})
            }
        
        favorite = decimal_to_float(response['Item'])
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'favorite_id': favorite_id,
                'analysis_status': favorite.get('analysis_status'),
                'analysis_result': favorite.get('analysis_result'),
                'analysis_completed_at': favorite.get('analysis_completed_at')
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }