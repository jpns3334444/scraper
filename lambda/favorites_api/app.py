import json
import boto3
import os
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

favorites_table = dynamodb.Table(os.environ['FAVORITES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
queue_url = os.environ['ANALYSIS_QUEUE_URL']

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,X-User-Id',
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
    method = event['httpMethod']
    path = event['path']
    
    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS}
    
    # Extract user_id from header
    user_id = event['headers'].get('X-User-Id', 'anonymous')
    
    if method == 'POST' and path == '/favorites':
        return add_favorite(event, user_id)
    elif method == 'DELETE' and path.startswith('/favorites/'):
        return remove_favorite(event, user_id)
    elif method == 'GET' and path == f'/favorites/{user_id}':
        return get_user_favorites(user_id)
    elif method == 'GET' and '/analysis' in path:
        return get_analysis(event, user_id)
    
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
    path_parts = event['path'].split('/')
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
    path_parts = event['path'].split('/')
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