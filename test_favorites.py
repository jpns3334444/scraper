#!/usr/bin/env python3
"""
Test script for favorites functionality
"""
import json
import boto3
import requests
from datetime import datetime

# Configuration
API_URL = 'https://nbgnatp0pd.execute-api.ap-northeast-1.amazonaws.com/prod'
TEST_USER_EMAIL = 'test@example.com'
TEST_PROPERTY_ID = 'test_property_123'

def test_favorites_api():
    print("🧪 Testing Favorites API Functionality")
    print("=" * 50)
    
    # Test 1: Check if API endpoint is reachable
    print("\n1. Testing API endpoint connectivity...")
    try:
        response = requests.get(f"{API_URL}/favorites/{TEST_USER_EMAIL}", timeout=10)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   ❌ API endpoint unreachable: {e}")
        return False
    
    # Test 2: Add a favorite
    print("\n2. Testing ADD favorite...")
    headers = {
        'Content-Type': 'application/json',
        'X-User-Email': TEST_USER_EMAIL,
        'Authorization': f'Bearer {TEST_USER_EMAIL}'
    }
    
    payload = {
        'property_id': TEST_PROPERTY_ID
    }
    
    try:
        response = requests.post(f"{API_URL}/favorites", 
                               json=payload, 
                               headers=headers, 
                               timeout=10)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        
        if response.status_code == 200:
            print("   ✅ Add favorite API call successful")
        else:
            print("   ❌ Add favorite API call failed")
            
    except Exception as e:
        print(f"   ❌ Add favorite failed: {e}")
    
    # Test 3: Check DynamoDB directly
    print("\n3. Checking DynamoDB table directly...")
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        
        # Try to find the table
        table_names = []
        for table_name in ['tokyo-real-estate-ai-user-preferences', 'tokyo-real-estate-ai-user-favorites']:
            try:
                table = dynamodb.Table(table_name)
                table.load()
                table_names.append(table_name)
                print(f"   ✅ Found table: {table_name}")
                
                # Scan for our test items
                response = table.scan(
                    FilterExpression=boto3.dynamodb.conditions.Attr('user_id').eq(TEST_USER_EMAIL)
                )
                items = response.get('Items', [])
                print(f"   Items for user {TEST_USER_EMAIL}: {len(items)}")
                for item in items:
                    print(f"      - {item}")
                    
            except Exception as e:
                print(f"   Table {table_name} not found or error: {e}")
        
        if not table_names:
            print("   ❌ No DynamoDB tables found!")
            
    except Exception as e:
        print(f"   ❌ DynamoDB check failed: {e}")
    
    # Test 4: Check Lambda function logs
    print("\n4. Checking Lambda function logs...")
    try:
        logs_client = boto3.client('logs', region_name='ap-northeast-1')
        
        # Get log groups for favorites API
        log_groups = logs_client.describe_log_groups(
            logGroupNamePrefix='/aws/lambda/tokyo-real-estate-ai-favorites-api'
        )
        
        for log_group in log_groups['logGroups']:
            print(f"   Found log group: {log_group['logGroupName']}")
            
            # Get recent log streams
            streams = logs_client.describe_log_streams(
                logGroupName=log_group['logGroupName'],
                orderBy='LastEventTime',
                descending=True,
                limit=3
            )
            
            for stream in streams['logStreams']:
                print(f"     Stream: {stream['logStreamName']}")
                
                # Get recent events
                events = logs_client.get_log_events(
                    logGroupName=log_group['logGroupName'],
                    logStreamName=stream['logStreamName'],
                    limit=10
                )
                
                for event in events['events'][-5:]:  # Last 5 events
                    timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
                    print(f"       {timestamp}: {event['message'].strip()}")
                break  # Only check the most recent stream
            break  # Only check the first log group
            
    except Exception as e:
        print(f"   ❌ Logs check failed: {e}")
    
    print("\n" + "=" * 50)
    print("Test completed!")

def test_api_gateway_config():
    print("\n🔧 Testing API Gateway Configuration")
    print("=" * 50)
    
    try:
        # Check API Gateway configuration
        apigateway = boto3.client('apigatewayv2', region_name='ap-northeast-1')
        
        # List APIs
        apis = apigateway.get_apis()
        favorites_api = None
        
        for api in apis['Items']:
            if 'favorites' in api['Name'].lower():
                favorites_api = api
                print(f"   Found API: {api['Name']} ({api['ApiId']})")
                break
        
        if favorites_api:
            # Get routes
            routes = apigateway.get_routes(ApiId=favorites_api['ApiId'])
            print(f"   Routes:")
            for route in routes['Items']:
                print(f"     - {route['RouteKey']}")
                
            # Get integrations
            integrations = apigateway.get_integrations(ApiId=favorites_api['ApiId'])
            print(f"   Integrations:")
            for integration in integrations['Items']:
                print(f"     - {integration.get('IntegrationUri', 'N/A')}")
        else:
            print("   ❌ Favorites API not found!")
            
    except Exception as e:
        print(f"   ❌ API Gateway check failed: {e}")

if __name__ == "__main__":
    test_favorites_api()
    test_api_gateway_config()