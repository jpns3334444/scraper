#!/usr/bin/env python3
"""Test script to verify property field parsing, especially management fee"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup
sys.path.insert(0, 'lambda/property_processor')
from core_scraper import extract_property_details, create_session
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def test_property_parsing(filepath):
    """Test property parsing on a single HTML file"""
    print(f"\n{'='*60}")
    print(f"Testing property parsing: {os.path.basename(filepath)}")
    print('='*60)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Create a mock session
    session = create_session()
    
    # Mock URL for testing
    test_url = "https://www.homes.co.jp/mansion/b-1127950071375/"
    
    # Create minimal config
    config = {
        'output_bucket': '',
        'skip_no_interior_photos': False
    }
    
    # Extract property details - but read from local file instead of making HTTP request
    try:
        # Read the local HTML file instead of making HTTP request
        with open('html/individual-homes-listing.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Mock the HTTP response  
        class MockResponse:
            def __init__(self, content):
                self.content = content.encode('utf-8')
                self.text = content
                self.status_code = 200
        
        # Patch the session.get method to return our local file
        original_get = session.get
        session.get = lambda *args, **kwargs: MockResponse(html_content)
        
        result = extract_property_details(
            session, test_url, "https://www.homes.co.jp", 
            config=config, logger=logger,
            session_pool=None,  # No image downloads for this test
            image_rate_limiter=None,
            ward='hachioji-city',
            listing_price=35000000
        )
        
        # Restore original method
        session.get = original_get
        
        if result is None:
            print("❌ Property parsing returned None")
            return False
        
        # Check key fields that are often missing
        key_fields_to_check = [
            'management_fee',
            'repair_reserve_fee', 
            'total_monthly_costs',
            'price',
            'size_sqm',
            'building_age_years',
            'floor',
            'building_floors'
        ]
        
        print("\nParsed property fields:")
        for field in key_fields_to_check:
            value = result.get(field)
            if value is not None and value != 0:
                print(f"  ✅ {field}: {value}")
            else:
                print(f"  ❌ {field}: {value} (missing or zero)")
        
        # Show some overview data if present
        if '_extras' in result and 'overview_data' in result['_extras']:
            overview = result['_extras']['overview_data']
            print("\nRaw overview data (all fields):")
            for key, value in overview.items():
                print(f"  {key}: {value}")
        else:
            print("\nNo _extras or overview_data found in result")
        
        # Show what data attributes we can extract directly
        print("\nDirect extraction from HTML:")
        with open('html/individual-homes-listing.html', 'r', encoding='utf-8') as f:
            html = f.read()
        test_soup = BeautifulSoup(html, 'html.parser')
        
        loan_sim = test_soup.find('loan-simulator')
        if loan_sim:
            print(f"  loan-simulator data-maintenance-fee: {loan_sim.get('data-maintenance-fee')}")
            print(f"  loan-simulator data-repair-reserve-fund: {loan_sim.get('data-repair-reserve-fund')}")
        
        budget_est = test_soup.find('budget-estimate')
        if budget_est:
            print(f"  budget-estimate data-management-fees: {budget_est.get('data-management-fees')}")
            print(f"  budget-estimate data-repair-reserve-fund: {budget_est.get('data-repair-reserve-fund')}")
        
        # Check table rows
        print("  Table rows:")
        rows = test_soup.find_all('tr')
        for row in rows:
            th = row.find('th')
            td = row.find('td')
            if th and td:
                header_text = th.get_text(strip=True)
                if '管理費' in header_text or '修繕積立金' in header_text:
                    cell_text = td.get_text(strip=True)
                    print(f"    {header_text}: {cell_text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during property parsing: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Test property parsing"""
    test_file = 'html/individual-homes-listing.html'
    
    if os.path.exists(test_file):
        result = test_property_parsing(test_file)
        if result:
            print("\n✅ Property parsing test completed")
        else:
            print("\n❌ Property parsing test failed")
    else:
        print(f"Test file not found: {test_file}")

if __name__ == "__main__":
    main()