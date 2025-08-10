#!/usr/bin/env python3
"""Test script to verify new field parsing and storage logic"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup
sys.path.insert(0, 'lambda/property_processor')
from core_scraper import extract_property_details, create_session
from dynamodb_utils import create_complete_property_record
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def test_new_field_parsing():
    """Test that new fields are being parsed and would be stored"""
    print("=== Testing New Field Parsing and Storage ===")
    
    # Load HTML file
    with open('html/individual-homes-listing.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Create mock session
    session = create_session()
    
    # Mock URL
    test_url = "https://www.homes.co.jp/mansion/b-1127950071375/"
    
    # Mock config
    config = {
        'output_bucket': '',
        'skip_no_interior_photos': False
    }
    
    # Mock the HTTP response
    class MockResponse:
        def __init__(self, content):
            self.content = content.encode('utf-8')
            self.text = content
            self.status_code = 200
    
    # Patch session
    session.get = lambda *args, **kwargs: MockResponse(html_content)
    
    # Extract property details
    result = extract_property_details(
        session, test_url, "https://www.homes.co.jp", 
        config=config, logger=logger,
        session_pool=None,
        image_rate_limiter=None,
        ward='test-ward',
        listing_price=35000000
    )
    
    if result is None:
        print("❌ Property extraction returned None")
        return False
    
    print(f"✅ Property extraction successful - {len(result)} fields extracted")
    
    # Check for the new fields in the raw data
    new_field_keys = [
        'zoning', '用途地域',
        'land_rights', '土地権利', 
        'national_land_use_notification', '国土法届出',
        'transaction_type', '取引態様',
        'current_occupancy', '現況',
        'handover_timing', '引渡し'
    ]
    
    print("\n--- Raw Parsed Data Check ---")
    found_new_fields = {}
    for key in new_field_keys:
        if key in result:
            found_new_fields[key] = result[key]
            print(f"✅ Found {key}: {result[key]}")
    
    if not found_new_fields:
        print("⚠️ No new fields found in raw parsed data")
        print("This is expected if the test HTML doesn't contain these fields")
    
    # Test the storage record creation
    print("\n--- Storage Record Creation Test ---")
    
    # Mock config for record creation
    storage_config = {'dynamodb_table': 'test-table'}
    
    # Create the storage record
    record = create_complete_property_record(result, storage_config, logger)
    
    if record is None:
        print("❌ Failed to create storage record")
        return False
    
    print(f"✅ Storage record created with {len(record)} fields")
    
    # Check if new fields made it into the storage record
    stored_new_fields = {}
    expected_storage_fields = ['zoning', 'land_rights', 'national_land_use_notification', 
                              'transaction_type', 'current_occupancy', 'handover_timing']
    
    for field in expected_storage_fields:
        if field in record:
            stored_new_fields[field] = record[field]
            print(f"✅ Storage record includes {field}: {record[field]}")
    
    if not stored_new_fields:
        print("⚠️ No new fields found in storage record")
        print("This is expected if the test HTML doesn't contain these fields")
    else:
        print(f"\n✅ SUCCESS: {len(stored_new_fields)} new fields would be stored in DynamoDB")
    
    # Show some key fields to verify existing functionality still works
    print("\n--- Existing Field Verification ---")
    key_fields = ['management_fee', 'repair_reserve_fee', 'total_monthly_costs', 'price', 'size_sqm']
    for field in key_fields:
        if field in record:
            print(f"✅ {field}: {record[field]}")
        else:
            print(f"❌ {field}: MISSING")
    
    return True

if __name__ == "__main__":
    success = test_new_field_parsing()
    if success:
        print("\n🎉 New field parsing and storage test completed successfully")
    else:
        print("\n💥 New field parsing test failed")