#!/usr/bin/env python3
"""Direct test of the fee parsing logic modifications"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup
sys.path.insert(0, 'lambda/property_processor')

def test_fee_parsing_direct():
    """Test the fee parsing logic directly"""
    print("=== Direct Fee Parsing Test ===")
    
    # Load the HTML file
    with open('html/individual-homes-listing.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Simulate the data dict that would be built up during parsing
    data = {
        # Add some dummy data to simulate overview parsing
        '価格': '2,780万円',
        '間取り': '2LDK',
        '専有面積': '39.67㎡(壁心)',
    }
    
    # Now test the fee parsing logic directly (copy from core_scraper.py)
    mgmt_fee = None
    repair_fee = None
    
    print("Testing fee extraction methods:")
    
    # PRIORITY 1: Try data attributes from loan-simulator and budget-estimate elements
    # Method 1: loan-simulator data-maintenance-fee
    loan_sim = soup.find('loan-simulator')
    if loan_sim and loan_sim.get('data-maintenance-fee'):
        try:
            mgmt_fee = int(loan_sim.get('data-maintenance-fee'))
            print(f"✅ Found mgmt_fee from loan-simulator: {mgmt_fee}")
        except (ValueError, TypeError):
            pass
    else:
        print("❌ No loan-simulator or data-maintenance-fee found")
    
    # Method 2: budget-estimate data-management-fees (if loan-simulator didn't work)
    if mgmt_fee is None:
        budget_est = soup.find('budget-estimate')
        if budget_est and budget_est.get('data-management-fees'):
            try:
                mgmt_fee = int(budget_est.get('data-management-fees'))
                print(f"✅ Found mgmt_fee from budget-estimate: {mgmt_fee}")
            except (ValueError, TypeError):
                pass
        else:
            print("❌ No budget-estimate or data-management-fees found")
    
    # Repair fee extraction
    for element_name in ['loan-simulator', 'budget-estimate']:
        element = soup.find(element_name)
        if element and element.get('data-repair-reserve-fund'):
            try:
                repair_fee = int(element.get('data-repair-reserve-fund'))
                print(f"✅ Found repair_fee from {element_name}: {repair_fee}")
                break
            except (ValueError, TypeError):
                continue
    else:
        print("❌ No repair reserve fund data attributes found")
    
    # Test table row fallback
    if mgmt_fee is None or repair_fee is None:
        print("\nTesting table row fallback:")
        rows = soup.find_all('tr')
        for row in rows:
            th = row.find('th')
            td = row.find('td')
            if th and td:
                header_text = th.get_text(strip=True)
                cell_text = td.get_text(strip=True)
                
                if mgmt_fee is None and '管理費' in header_text:
                    import re
                    m = re.search(r'([\d,]+)', cell_text)
                    if m:
                        try:
                            mgmt_fee = int(m.group(1).replace(',', ''))
                            print(f"✅ Found mgmt_fee from table row: {mgmt_fee}")
                        except ValueError:
                            pass
                
                if repair_fee is None and '修繕積立金' in header_text:
                    import re
                    m = re.search(r'([\d,]+)', cell_text)
                    if m:
                        try:
                            repair_fee = int(m.group(1).replace(',', ''))
                            print(f"✅ Found repair_fee from table row: {repair_fee}")
                        except ValueError:
                            pass
    
    print(f"\n=== FINAL RESULTS ===")
    print(f"Management Fee: {mgmt_fee}")
    print(f"Repair Reserve Fee: {repair_fee}")
    print(f"Total Monthly Costs: {(mgmt_fee or 0) + (repair_fee or 0)}")

if __name__ == "__main__":
    test_fee_parsing_direct()