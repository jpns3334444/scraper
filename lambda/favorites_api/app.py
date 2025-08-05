import json
import boto3
import os
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')
s3 = boto3.client('s3')

preferences_table = dynamodb.Table(os.environ['PREFERENCES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
queue_url = os.environ['ANALYSIS_QUEUE_URL']
output_bucket = os.environ.get('OUTPUT_BUCKET', 'tokyo-real-estate-ai-data')

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-User-Id,X-User-Email',
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
    # Handle OPTIONS request for CORS (REST API format)
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': ''
        }
    
    # Use REST API event structure
    method = event.get('httpMethod')
    path = event.get('path')
    
    # Extract user email from header (authenticated user) - handle both cases
    headers = event.get('headers', {})
    user_email = headers.get('x-user-email') or headers.get('X-User-Email') or 'anonymous'
    # For backward compatibility, use email as user_id
    user_id = user_email
    
    if method == 'POST' and path == '/favorites':
        return add_preference(event, user_id, 'favorite')
    elif method == 'POST' and path == '/hidden':
        return add_preference(event, user_id, 'hidden')
    elif method == 'DELETE' and path.startswith('/favorites/'):
        return remove_preference(event, user_id, 'favorite')
    elif method == 'DELETE' and path.startswith('/hidden/'):
        return remove_preference(event, user_id, 'hidden')
    elif method == 'GET' and '/favorites/' in path:
        # Extract userId from path parameters (REST API format)
        path_params = event.get('pathParameters', {})
        if path_params and 'userId' in path_params:
            return get_user_preferences(path_params['userId'], 'favorite')
        elif path_params and 'id' in path_params and '/analysis' in path:
            return get_analysis(event, user_id)
    elif method == 'GET' and '/hidden/' in path:
        # Extract userId from path parameters (REST API format)
        path_params = event.get('pathParameters', {})
        if path_params and 'userId' in path_params:
            return get_user_preferences(path_params['userId'], 'hidden')
    
    # Fallback to path parsing for compatibility
    if method == 'GET' and path.count('/') == 2:  # /favorites/{userId} or /hidden/{userId}
        path_parts = path.split('/')
        if len(path_parts) == 3 and path_parts[1] == 'favorites':
            return get_user_preferences(path_parts[2], 'favorite')
        elif len(path_parts) == 3 and path_parts[1] == 'hidden':
            return get_user_preferences(path_parts[2], 'hidden')
    
    return {
        'statusCode': 404,
        'headers': CORS_HEADERS,
        'body': json.dumps({'error': 'Not Found'})
    }

def add_preference(event, user_id, preference_type):
    body = json.loads(event['body'])
    property_id = body['property_id']
    
    # Create unique preference ID
    preference_id = f"{user_id}_{property_id}_{preference_type}"
    
    try:
        # Check if preference already exists
        existing = preferences_table.get_item(Key={'preference_id': preference_id})
        
        if 'Item' in existing:
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps({'message': f'Already {preference_type}'})
            }
        
        # Get property details for thumbnail
        property_data = properties_table.get_item(
            Key={'property_id': property_id, 'sort_key': 'META'}
        ).get('Item', {})
        
        # Create preference record
        preference_item = {
            'preference_id': preference_id,
            'user_id': user_id,
            'property_id': property_id,
            'preference_type': preference_type,
            'created_at': datetime.utcnow().isoformat(),
            # Store essential property data for quick display
            'property_summary': {
                'price': decimal_to_float(property_data.get('price', 0)),
                'ward': property_data.get('ward', ''),
                'size_sqm': decimal_to_float(property_data.get('size_sqm', 0)),
                'station': property_data.get('closest_station', ''),
                'image_url': property_data.get('photo_filenames', '').split('|')[0] if property_data.get('photo_filenames') else None
            }
        }
        
        # Add analysis fields for favorites only
        if preference_type == 'favorite':
            preference_item.update({
                'analysis_status': 'pending',
                'analysis_requested_at': datetime.utcnow().isoformat()
            })
        
        preferences_table.put_item(Item=preference_item)
        
        # Send to analysis queue for favorites only
        if preference_type == 'favorite':
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    'preference_id': preference_id,
                    'user_id': user_id,
                    'property_id': property_id
                })
            )
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'success': True, 'preference_id': preference_id})
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }

def remove_preference(event, user_id, preference_type):
    # Try to get ID from path parameters first (REST API format)
    path_params = event.get('pathParameters', {})
    if path_params and 'id' in path_params:
        preference_id = path_params['id']
    else:
        # Fallback to path parsing - extract property_id and reconstruct preference_id
        path_parts = event.get('path', '').split('/')
        property_id = path_parts[-1]
        preference_id = f"{user_id}_{property_id}_{preference_type}"
    
    try:
        # Verify ownership
        if not preference_id.startswith(user_id + '_'):
            return {
                'statusCode': 403,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        preferences_table.delete_item(Key={'preference_id': preference_id})
        
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

def get_user_preferences(user_id, preference_type):
    try:
        # Query GSI for user's preferences of specific type
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
        
        # Convert S3 keys to presigned URLs for images
        for preference in preferences:
            property_summary = preference.get('property_summary', {})
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
        
        # Return appropriate key name based on preference type
        result_key = 'favorites' if preference_type == 'favorite' else preference_type + 's'
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({result_key: preferences})
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }

def get_analysis(event, user_id):
    # Try to get ID from path parameters first (REST API format)
    path_params = event.get('pathParameters', {})
    if path_params and 'id' in path_params:
        preference_id = path_params['id']
    else:
        # Fallback to path parsing
        path_parts = event.get('path', '').split('/')
        preference_id = path_parts[-2]  # Assuming path like /favorites/{preference_id}/analysis
    
    try:
        # Verify ownership
        if not preference_id.startswith(user_id + '_'):
            return {
                'statusCode': 403,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        # Get preference record
        response = preferences_table.get_item(Key={'preference_id': preference_id})
        
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Preference not found'})
            }
        
        preference = decimal_to_float(response['Item'])
        
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'preference_id': preference_id,
                'analysis_status': preference.get('analysis_status'),
                'analysis_result': preference.get('analysis_result'),
                'analysis_completed_at': preference.get('analysis_completed_at')
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }