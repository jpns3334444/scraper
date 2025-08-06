import json
import boto3
import bcrypt
import re
from datetime import datetime
import os
import sys
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

dynamodb = boto3.resource('dynamodb')
users_table_name = os.environ.get('USERS_TABLE', 'tokyo-real-estate-users')
users_table = dynamodb.Table(users_table_name)

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    return len(password) >= 8


def lambda_handler(event, context):
    # Debug logging
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
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        email = body.get('email', '').strip().lower()
        password = body.get('password', '')
        
        # Validate input
        if not email or not password:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({
                    'success': False,
                    'error': 'Email and password are required'
                })
            }
        
        if not validate_email(email):
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({
                    'success': False,
                    'error': 'Invalid email format'
                })
            }
        
        if not validate_password(password):
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({
                    'success': False,
                    'error': 'Password must be at least 8 characters long'
                })
            }
        
        # Check if user already exists
        existing_user = users_table.get_item(Key={'email': email})
        if 'Item' in existing_user:
            return {
                "statusCode": 409,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": origin_header,
                    "Access-Control-Allow-Credentials": "true"
                },
                "body": json.dumps({
                    'success': False,
                    'error': 'Email already registered'
                })
            }
        
        # Hash password
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        
        # Create user record
        timestamp = datetime.now().isoformat()
        users_table.put_item(
            Item={
                'email': email,
                'password_hash': password_hash,
                'created_at': timestamp,
                'last_login': timestamp
            }
        )
        
        # Simple token (email for now, can be replaced with JWT)
        token = email
        
        return {
            "statusCode": 201,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({
                'success': True,
                'email': email,
                'token': token
            })
        }
        
    except Exception as e:
        print("ERROR:", e)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin_header,
                "Access-Control-Allow-Credentials": "true"
            },
            "body": json.dumps({
                'success': False,
                'error': 'Internal server error'
            })
        }