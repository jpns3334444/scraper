import json
import boto3
import bcrypt
from datetime import datetime
import os

dynamodb = boto3.resource('dynamodb')
users_table_name = os.environ.get('USERS_TABLE', 'tokyo-real-estate-users')
users_table = dynamodb.Table(users_table_name)

def lambda_handler(event, context):
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST, OPTIONS'
    }
    
    try:
        # Handle OPTIONS request for CORS
        if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': headers,
                'body': ''
            }
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        email = body.get('email', '').strip().lower()
        password = body.get('password', '')
        
        # Validate input
        if not email or not password:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({
                    'success': False,
                    'error': 'Email and password are required'
                })
            }
        
        # Get user from database
        response = users_table.get_item(Key={'email': email})
        if 'Item' not in response:
            return {
                'statusCode': 401,
                'headers': headers,
                'body': json.dumps({
                    'success': False,
                    'error': 'Invalid email or password'
                })
            }
        
        user = response['Item']
        
        # Verify password
        password_hash = user.get('password_hash', '')
        if not bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            return {
                'statusCode': 401,
                'headers': headers,
                'body': json.dumps({
                    'success': False,
                    'error': 'Invalid email or password'
                })
            }
        
        # Update last login
        timestamp = datetime.now().isoformat()
        users_table.update_item(
            Key={'email': email},
            UpdateExpression='SET last_login = :timestamp',
            ExpressionAttributeValues={':timestamp': timestamp}
        )
        
        # Simple token (email for now, can be replaced with JWT)
        token = email
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'success': True,
                'email': email,
                'token': token
            })
        }
        
    except Exception as e:
        print(f"Error in login_user: {str(e)}")
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({
                'success': False,
                'error': 'Internal server error'
            })
        }