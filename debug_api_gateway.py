#!/usr/bin/env python3
"""
Debug API Gateway integration issues
"""
import boto3
import json

def check_api_gateway():
    apigateway = boto3.client('apigatewayv2', region_name='ap-northeast-1')
    
    # Find the favorites API
    apis = apigateway.get_apis()
    favorites_api = None
    
    for api in apis['Items']:
        if 'favorites' in api['Name'].lower():
            favorites_api = api
            print(f"Found API: {api['Name']} ({api['ApiId']})")
            break
    
    if not favorites_api:
        print("❌ Favorites API not found!")
        return
    
    api_id = favorites_api['ApiId']
    
    # Get routes
    routes = apigateway.get_routes(ApiId=api_id)
    print(f"\nRoutes in API {api_id}:")
    for route in routes['Items']:
        route_key = route['RouteKey']
        target = route.get('Target', 'No target')
        print(f"  - {route_key} -> {target}")
    
    # Get integrations
    integrations = apigateway.get_integrations(ApiId=api_id)
    print(f"\nIntegrations:")
    for integration in integrations['Items']:
        int_id = integration['IntegrationId']
        int_uri = integration.get('IntegrationUri', 'N/A')
        int_type = integration.get('IntegrationType', 'N/A')
        print(f"  - {int_id}: {int_type} -> {int_uri}")
    
    # Check if Lambda permissions exist
    lambda_client = boto3.client('lambda', region_name='ap-northeast-1')
    function_name = 'tokyo-real-estate-ai-favorites-api'
    
    try:
        policy = lambda_client.get_policy(FunctionName=function_name)
        print(f"\nLambda policy for {function_name}:")
        policy_doc = json.loads(policy['Policy'])
        for statement in policy_doc['Statement']:
            print(f"  - Principal: {statement.get('Principal', 'N/A')}")
            print(f"    Action: {statement.get('Action', 'N/A')}")
            print(f"    Resource: {statement.get('Resource', 'N/A')}")
    except Exception as e:
        print(f"❌ Error getting Lambda policy: {e}")

if __name__ == "__main__":
    check_api_gateway()