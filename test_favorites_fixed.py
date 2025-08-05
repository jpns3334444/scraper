#!/usr/bin/env python3
"""
Test script for favorites functionality using correct endpoint
"""
import json
import requests

# Use the correct Favorites API endpoint
FAVORITES_API_URL = 'https://4qjxa4sny4.execute-api.ap-northeast-1.amazonaws.com/prod'
TEST_USER_EMAIL = 'test@example.com'
TEST_PROPERTY_ID = 'test_property_123'

def test_correct_endpoint():
    print("🧪 Testing Favorites API with Correct Endpoint")
    print("=" * 50)
    
    # Test 1: Add a favorite
    print("\n1. Testing ADD favorite with correct endpoint...")
    headers = {
        'Content-Type': 'application/json',
        'X-User-Email': TEST_USER_EMAIL,
        'Authorization': f'Bearer {TEST_USER_EMAIL}'
    }
    
    payload = {
        'property_id': TEST_PROPERTY_ID
    }
    
    try:
        response = requests.post(f"{FAVORITES_API_URL}/favorites", 
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
    
    # Test 2: Get favorites
    print("\n2. Testing GET favorites...")
    try:
        response = requests.get(f"{FAVORITES_API_URL}/favorites/{TEST_USER_EMAIL}", 
                               headers=headers,
                               timeout=10)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        
        if response.status_code == 200:
            print("   ✅ Get favorites API call successful")
        else:
            print("   ❌ Get favorites API call failed")
            
    except Exception as e:
        print(f"   ❌ Get favorites failed: {e}")

if __name__ == "__main__":
    test_correct_endpoint()