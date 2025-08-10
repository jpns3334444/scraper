#!/usr/bin/env python3
"""Simple test to verify we can extract fee data from HTML"""

from bs4 import BeautifulSoup

def test_fee_extraction():
    # Load the test HTML file
    with open('html/individual-homes-listing.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    print("=== Fee Extraction Test ===")
    
    # Method 1: Data attributes from loan-simulator
    loan_sim = soup.find('loan-simulator')
    if loan_sim:
        maintenance_fee = loan_sim.get('data-maintenance-fee')
        repair_fund = loan_sim.get('data-repair-reserve-fund')
        print(f"loan-simulator: maintenance_fee={maintenance_fee}, repair_fund={repair_fund}")
    else:
        print("loan-simulator element not found")
    
    # Method 2: Data attributes from budget-estimate  
    budget_est = soup.find('budget-estimate')
    if budget_est:
        mgmt_fees = budget_est.get('data-management-fees')
        repair_fund = budget_est.get('data-repair-reserve-fund')
        print(f"budget-estimate: mgmt_fees={mgmt_fees}, repair_fund={repair_fund}")
    else:
        print("budget-estimate element not found")
    
    # Method 3: Table parsing for 管理費等 and 修繕積立金
    print("\nTable row extraction:")
    
    # Find all table rows
    rows = soup.find_all('tr')
    for row in rows:
        th = row.find('th')
        td = row.find('td')
        if th and td:
            header_text = th.get_text(strip=True)
            cell_text = td.get_text(strip=True)
            if '管理費' in header_text:
                print(f"Found: {header_text} -> {cell_text}")
            elif '修繕積立金' in header_text:
                print(f"Found: {header_text} -> {cell_text}")
    
    print("\n✅ Fee extraction test completed")

if __name__ == "__main__":
    test_fee_extraction()