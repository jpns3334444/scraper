#!/usr/bin/env python3
"""
Test the corrected favorites API endpoint
"""
import requests
import json

FAVORITES_API_URL = 'https://4qjxa4sny4.execute-api.ap-northeast-1.amazonaws.com/prod'
TEST_USER_EMAIL = 'test@example.com'
TEST_PROPERTY_ID = 'test_property_123'

def test_favorites():
    print("🧪 Testing Corrected Favorites API")
    print("=" * 40)
    
    headers = {
        'Content-Type': 'application/json',
        'X-User-Email': TEST_USER_EMAIL,
        'Authorization': f'Bearer {TEST_USER_EMAIL}'
    }
    
    # Test adding favorite
    print("\n1. Adding favorite...")
    response = requests.post(f"{FAVORITES_API_URL}/favorites", 
                           json={'property_id': TEST_PROPERTY_ID}, 
                           headers=headers)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Test getting favorites
    print("\n2. Getting favorites...")
    response = requests.get(f"{FAVORITES_API_URL}/favorites/{TEST_USER_EMAIL}", 
                           headers=headers)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")

if __name__ == "__main__":
    test_favorites()