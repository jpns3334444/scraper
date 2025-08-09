import json
import boto3

# Import centralized configuration
try:
    from config_loader import get_config
    config = get_config()
    print(f"[DEBUG] Config loaded successfully")
except ImportError as e:
    config = None  # Fallback to environment variables
    print(f"[DEBUG] Config loader import failed: {e}, using env vars")
import os
from datetime import datetime
from decimal import Decimal
import sys
from urllib.parse import unquote
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
s3 = boto3.client('s3')

preferences_table = dynamodb.Table(os.environ['PREFERENCES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
output_bucket = config.get_env_var('OUTPUT_BUCKET') if config else os.environ.get('OUTPUT_BUCKET', 'tokyo-real-estate-ai-data')


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
    print(f"[DEBUG] === LAMBDA_HANDLER START ===")
    # Log the event for debugging
    print(f"Received event: {json.dumps(event)}")
    
    # Check if we have all required environment variables and resources
    print(f"[DEBUG] Checking environment variables and resources...")
    try:
        print(f"[DEBUG] PREFERENCES_TABLE: {os.environ.get('PREFERENCES_TABLE', 'NOT SET')}")
        print(f"[DEBUG] PROPERTIES_TABLE: {os.environ.get('PROPERTIES_TABLE', 'NOT SET')}")
        print(f"[DEBUG] OUTPUT_BUCKET: {os.environ.get('OUTPUT_BUCKET', 'NOT SET')}")
        print(f"[DEBUG] preferences_table: {preferences_table}")
        print(f"[DEBUG] properties_table: {properties_table}")
        print(f"[DEBUG] lambda_client: {lambda_client}")
    except Exception as e:
        print(f"[ERROR] Error checking resources: {e}")
    
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
            print(f"[DEBUG] About to call add_preference with event keys: {list(event.keys())}")
            print(f"[DEBUG] user_id: {user_id}, type: {type(user_id)}")
            try:
                print(f"[DEBUG] Calling add_preference now...")
                result = add_preference(event, user_id, 'favorite')
                print(f"[DEBUG] add_preference returned: {result}")
                return result
            except Exception as e:
                print(f"[ERROR] Exception in add_preference: {e}")
                import traceback
                print(f"[ERROR] add_preference traceback: {traceback.format_exc()}")
                raise
        elif method == 'POST' and path == '/hidden':
            print(f"[DEBUG] Routing to add_preference for hidden")
            return add_preference(event, user_id, 'hidden')
        elif method == 'DELETE' and path.startswith('/favorites/'):
            print(f"[DEBUG] Routing to remove_preference for favorite")
            return remove_preference(event, user_id, 'favorite')
        elif method == 'DELETE' and path.startswith('/hidden/'):
            print(f"[DEBUG] Routing to remove_preference for hidden")
            return remove_preference(event, user_id, 'hidden')
        elif method == 'GET' and '/favorites/' in path:
            path_params = event.get('pathParameters', {})
            
            # Check if this is /favorites/user/{userId} for getting user's favorites list
            if '/favorites/user/' in path and path_params and 'userId' in path_params:
                # CRITICAL: Decode the URL-encoded email address
                decoded_user_id = unquote(path_params['userId'])
                print(f"[DEBUG] Favorites route: encoded userId={path_params['userId']}, decoded={decoded_user_id}")
                return get_user_preferences(event, decoded_user_id, 'favorite')
            
            # Check if this is /favorites/analysis/{userEmail}/{propertyId} for analysis
            elif '/favorites/analysis/' in path and path_params:
                if 'userEmail' in path_params and 'propertyId' in path_params:
                    user_email = unquote(path_params['userEmail'])
                    property_id = unquote(path_params['propertyId'])
                    print(f"[DEBUG] Analysis route: userEmail={user_email}, propertyId={property_id}")
                    return get_favorite_analysis(event, user_email, property_id)
            
            # Fallback to parsing path manually for backward compatibility
            elif path_params and not '/user/' in path and not '/analysis/' in path:
                path_parts = path.strip('/').split('/')
                if len(path_parts) == 3 and path_parts[0] == 'favorites':
                    user_id, property_id = unquote(path_parts[1]), unquote(path_parts[2])
                    return get_favorite_analysis(event, user_id, property_id)
        
        elif method == 'GET' and '/hidden/user/' in path:
            # Extract userId from path
            path_params = event.get('pathParameters', {})
            if path_params and 'userId' in path_params:
                # CRITICAL: Decode the URL-encoded email address
                decoded_user_id = unquote(path_params['userId'])
                print(f"[DEBUG] Hidden route: encoded userId={path_params['userId']}, decoded={decoded_user_id}")
                return get_user_preferences(event, decoded_user_id, 'hidden')
        
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
    print(f"[DEBUG] === add_preference ENTRY === user_id: {user_id}, preference_type: {preference_type}")
    
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
    print(f"[DEBUG] add_preference called with user_id: {user_id}, preference_type: {preference_type}")
    print(f"[DEBUG] origin_header: {origin_header}")
    
    try:
        body = json.loads(event.get('body', '{}'))
        property_id = body.get('property_id')
        
        print(f"[DEBUG] Parsed body: {body}")
        print(f"[DEBUG] Property ID: {property_id}")
        
        if not property_id:
            print(f"[DEBUG] No property_id provided, returning 400")
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'property_id is required'})
            }
        
        # Check if preference already exists using composite key
        print(f"[DEBUG] Checking if preference already exists...")
        existing = preferences_table.get_item(
            Key={
                'user_id': user_id,
                'property_id': property_id
            }
        )
        
        print(f"[DEBUG] Existing preference check result: {existing}")
        
        if 'Item' in existing:
            print(f"[DEBUG] Preference already exists, returning 200")
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
        print(f"[DEBUG] Getting property details for property_id: {property_id}")
        property_data = properties_table.get_item(
            Key={'property_id': property_id, 'sort_key': 'META'}
        ).get('Item', {})
        
        print(f"[DEBUG] Property data retrieved: {bool(property_data)}")
        if property_data:
            print(f"[DEBUG] Property data keys: {list(property_data.keys())}")
        else:
            print(f"[DEBUG] No property data found for property_id: {property_id}")
        
        # Create preference record with Decimal values for DynamoDB
        preference_item = {
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
        
        print(f"[DEBUG] Preference item created and stored in DynamoDB")
        
        # Invoke analyzer Lambda directly for favorites only
        if preference_type == 'favorite':
            try:
                analyzer_function = os.environ.get('FAVORITE_ANALYZER_FUNCTION', 'tokyo-real-estate-ai-favorite-analyzer')
                print(f"[DEBUG] About to invoke analyzer function: {analyzer_function}")
                print(f"[DEBUG] Analyzer payload: {{'user_id': '{user_id}', 'property_id': '{property_id}'}}")
                
                response = lambda_client.invoke(
                    FunctionName=analyzer_function,
                    InvocationType='Event',  # async
                    Payload=json.dumps({'user_id': user_id, 'property_id': property_id})
                )
                print(f"[DEBUG] Analyzer invoke response: {response}")
            except Exception as e:
                print(f"[ERROR] Failed to invoke analyzer: {e}")
                import traceback
                print(f"[ERROR] Analyzer invoke traceback: {traceback.format_exc()}")
                # Don't fail the request if analyzer fails
        
        print(f"[DEBUG] Returning success response for {preference_type}")
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
        # Get property_id from path
        path_params = event.get('pathParameters', {})
        property_id = path_params.get('id') or event.get('path', '').split('/')[-1]
        
        # URL decode the property_id in case it contains encoded characters like %23 for #
        property_id = unquote(property_id)
        print(f"[DEBUG] Remove preference: user_id={user_id}, property_id={property_id}, type={preference_type}")

        if not property_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({'error': 'Invalid path, property_id not found'})
            }

        print(f"[DEBUG] Attempting to delete user_id: {user_id}, property_id: {property_id}")

        # Perform the deletion using the composite primary key
        delete_response = preferences_table.delete_item(
            Key={
                'user_id': user_id,
                'property_id': property_id
            },
            ReturnValues='ALL_OLD'
        )
        
        # Check if anything was actually deleted
        if 'Attributes' not in delete_response:
            print(f"[WARNING] Preference not found for user_id: {user_id}, property_id: {property_id}")
            return {
                'statusCode': 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                'body': json.dumps({'error': f'{preference_type.capitalize()} not found'})
            }

        print(f"[SUCCESS] Deleted item: {delete_response['Attributes']}")
        
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
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
    try:
        # Make absolutely sure user_id is decoded
        user_id = unquote(str(user_id))  # Convert to string first, then decode
        print(f"[DEBUG] get_user_preferences: Getting {preference_type} preferences for user '{user_id}'")
        
        # Log the exact query we're making
        print(f"[DEBUG] DynamoDB Query: user_id='{user_id}', preference_type='{preference_type}'")
        
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
        print(f"[DEBUG] Query returned {len(preferences)} {preference_type} items for user {user_id}")
        
        if len(preferences) > 0:
            print(f"[DEBUG] First item: {preferences[0].get('property_id', 'NO_ID')}")
        
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
        if preference_type == 'favorite':
            result_key = 'favorites'
        elif preference_type == 'hidden':
            result_key = 'hidden'
        else:
            result_key = preference_type + 's'
        
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


def get_favorite_analysis(event, user_id, property_id):
    """Get analysis result and property images for a favorite"""
    # Determine origin_header at runtime
    origin_header = event.get("headers", {}).get("origin", "*")
    
    try:
        # Make sure both are decoded
        user_id = unquote(str(user_id))
        property_id = unquote(str(property_id))
        
        # Get the favorite item with analysis
        favorite_response = preferences_table.get_item(
            Key={
                'user_id': user_id,
                'property_id': property_id
            }
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
        
        # Generate presigned URLs for property images
        property_images = []
        if property_data.get('photo_filenames'):
            for s3_key in property_data['photo_filenames'].split('|')[:5]:
                if s3_key.strip():
                    try:
                        url = s3.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': output_bucket, 'Key': s3_key.strip()},
                            ExpiresIn=3600
                        )
                        property_images.append(url)
                    except Exception as e:
                        print(f"Warning: Failed to generate presigned URL for {s3_key}: {e}")
        
        # Convert Decimals to floats for JSON serialization
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
                "property_images": property_images,
                "property_summary": property_summary
            })
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