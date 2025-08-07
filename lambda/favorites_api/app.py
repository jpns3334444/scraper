import json
import boto3
import os
from datetime import datetime
from decimal import Decimal
import sys
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')
s3 = boto3.client('s3')

preferences_table = dynamodb.Table(os.environ['PREFERENCES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
queue_url = os.environ['ANALYSIS_QUEUE_URL']
output_bucket = os.environ.get('OUTPUT_BUCKET', 'tokyo-real-estate-ai-data')


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
    # Log the event for debugging
    print(f"Received event: {json.dumps(event)}")
    
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
    try:
        # Handle OPTIONS request for CORS (REST API format)
        if event.get('httpMethod') == 'OPTIONS':
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({})
            }
        
        # Use REST API event structure
        method = event.get('httpMethod', '')
        path = event.get('path', '')
        
        # Extract user email from header (authenticated user) - handle both cases
        headers = event.get('headers', {})
        user_email = headers.get('x-user-email') or headers.get('X-User-Email') or 'anonymous'
        # For backward compatibility, use email as user_id
        user_id = user_email
        
        print(f"[DEBUG] Request: {method} {path}")
        print(f"[DEBUG] User ID: {user_id}")
        print(f"[DEBUG] Headers: {headers}")
        
        # Route handling
        if method == 'POST' and path == '/favorites':
            print(f"[DEBUG] Routing to add_preference for favorite")
            return add_preference(event, user_id, 'favorite')
        elif method == 'POST' and path == '/hidden':
            print(f"[DEBUG] Routing to add_preference for hidden")
            return add_preference(event, user_id, 'hidden')
        elif method == 'DELETE' and path.startswith('/favorites/'):
            print(f"[DEBUG] Routing to remove_preference for favorite")
            return remove_preference(event, user_id, 'favorite')
        elif method == 'DELETE' and path.startswith('/hidden/'):
            print(f"[DEBUG] Routing to remove_preference for hidden")
            return remove_preference(event, user_id, 'hidden')
        elif method == 'GET' and '/favorites/user/' in path:
            # Extract userId from path
            path_params = event.get('pathParameters', {})
            if path_params and 'userId' in path_params:
                return get_user_preferences(event, path_params['userId'], 'favorite')
        elif method == 'GET' and '/hidden/user/' in path:
            # Extract userId from path
            path_params = event.get('pathParameters', {})
            if path_params and 'userId' in path_params:
                return get_user_preferences(event, path_params['userId'], 'hidden')
        
        # If no route matched, return 404
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
        print("ERROR:", e)
        import traceback
        print(traceback.format_exc())
        # ALWAYS return CORS headers even on error
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
    # Determine origin_header at runtime
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
        
        # Create unique preference ID
        preference_id = f"{user_id}_{property_id}_{preference_type}"
        
        # Check if preference already exists
        existing = preferences_table.get_item(Key={'preference_id': preference_id})
        
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
        
        # Get property details for thumbnail
        property_data = properties_table.get_item(
            Key={'property_id': property_id, 'sort_key': 'META'}
        ).get('Item', {})
        
        # Create preference record with Decimal values for DynamoDB
        preference_item = {
            'preference_id': preference_id,
            'user_id': user_id,
            'property_id': property_id,
            'preference_type': preference_type,
            'created_at': datetime.utcnow().isoformat(),
            # Store essential property data for quick display
            # Keep as Decimal for DynamoDB storage
            'property_summary': {
                'price': property_data.get('price', Decimal('0')),  # Keep as Decimal
                'ward': property_data.get('ward', ''),
                'size_sqm': property_data.get('size_sqm', Decimal('0')),  # Keep as Decimal
                'station': property_data.get('closest_station', ''),
                'image_url': property_data.get('photo_filenames', '').split('|')[0] if property_data.get('photo_filenames') else None
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
        
        # Send to analysis queue for favorites only
        if preference_type == 'favorite':
            try:
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({
                        'preference_id': preference_id,
                        'user_id': user_id,
                        'property_id': property_id
                    })
                )
            except Exception as e:
                print(f"Warning: Failed to send SQS message: {str(e)}")
                # Don't fail the request if SQS fails
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({'success': True, 'preference_id': preference_id})
        }
        
    except Exception as e:
        print("ERROR:", e)
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
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
    try:
        print(f"[DEBUG] Remove preference called - user_id: {user_id}, preference_type: {preference_type}")
        print(f"[DEBUG] Event path: {event.get('path', '')}")
        print(f"[DEBUG] Path parameters: {event.get('pathParameters', {})}")
        
        # Get ID from path parameters (REST API format)
        path_params = event.get('pathParameters', {})
        if path_params and 'id' in path_params:
            property_id = path_params['id']
            # Construct the full preference_id
            preference_id = f"{user_id}_{property_id}_{preference_type}"
            print(f"[DEBUG] Using path params - property_id: {property_id}, preference_id: {preference_id}")
        else:
            # Fallback - try to extract from path
            path_parts = event.get('path', '').split('/')
            print(f"[DEBUG] Path parts: {path_parts}")
            if len(path_parts) > 2:
                property_id = path_parts[-1]
                preference_id = f"{user_id}_{property_id}_{preference_type}"
                print(f"[DEBUG] Using path fallback - property_id: {property_id}, preference_id: {preference_id}")
            else:
                print(f"[ERROR] Invalid path - cannot extract property_id")
                return {
                    "statusCode": 400,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": origin_header,
                        "Access-Control-Allow-Credentials": "true"
                    },
                    "body": json.dumps({'error': 'Invalid path'})
                }
        
        # Verify ownership
        if not preference_id.startswith(user_id + '_'):
            print(f"[ERROR] Unauthorized - preference_id does not start with user_id")
            return {
                "statusCode": 403,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'Unauthorized'})
            }
        
        print(f"[DEBUG] About to delete from DynamoDB - preference_id: {preference_id}")
        print(f"[DEBUG] Table name: {preferences_table.name}")
        
        # Check if the item exists before deleting
        try:
            existing_item = preferences_table.get_item(Key={'preference_id': preference_id})
            if 'Item' in existing_item:
                print(f"[DEBUG] Found existing item: {existing_item['Item']}")
            else:
                print(f"[DEBUG] No existing item found for preference_id: {preference_id}")
        except Exception as get_error:
            print(f"[ERROR] Failed to check existing item: {str(get_error)}")
        
        # Perform the deletion
        delete_response = preferences_table.delete_item(
            Key={'preference_id': preference_id},
            ReturnValues='ALL_OLD'
        )
        
        print(f"[DEBUG] Delete response: {delete_response}")
        
        # Check if anything was actually deleted
        deleted_item = delete_response.get('Attributes')
        if deleted_item:
            print(f"[SUCCESS] Successfully deleted item: {deleted_item}")
        else:
            print(f"[WARNING] No item was deleted - item may not have existed")
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({
                'success': True, 
                'deleted': deleted_item is not None,
                'preference_id': preference_id
            })
        }
        
    except Exception as e:
        print("ERROR in remove_preference:", e)
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


def get_user_preferences(event, user_id, preference_type):
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
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
        
        # Convert Decimal to float for JSON serialization (only for response)
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
                    print(f"Warning: Failed to generate presigned URL: {str(e)}")
                    # If presigned URL generation fails, remove the image_url
                    property_summary['image_url'] = None
        
        # Return appropriate key name based on preference type
        result_key = 'favorites' if preference_type == 'favorite' else preference_type + 's'
        
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
        print("ERROR:", e)
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