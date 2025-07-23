#!/usr/bin/env python3
"""
Basic verification test for daily digest functionality.
"""

import sys
import os
sys.path.append(os.getcwd())

from analysis.lean_scoring import Verdict
from notifications.daily_digest import generate_daily_digest

def create_mock_verdict(value):
    """Create a mock verdict object."""
    class MockVerdict:
        def __init__(self, val):
            self.value = val
    return MockVerdict(value)

def test_basic_digest_generation():
    """Test basic digest generation functionality."""
    print("Testing basic daily digest generation...")
    
    # Sample candidates
    candidates = [
        {
            'id': 'TEST_001',
            'price': 50000000,
            'total_sqm': 60.5,
            'price_per_sqm': 826446,
            'ward': 'Shibuya',
            'building_age_years': 8,
            'nearest_station_meters': 400,
            'components': {
                'final_score': 82.5,
                'verdict': create_mock_verdict('BUY_CANDIDATE'),
                'ward_discount_pct': -18.5
            }
        },
        {
            'id': 'TEST_002',
            'price': 35000000,
            'total_sqm': 45.0,
            'price_per_sqm': 777778,
            'ward': 'Setagaya',
            'building_age_years': 12,
            'nearest_station_meters': 600,
            'components': {
                'final_score': 68.8,
                'verdict': create_mock_verdict('WATCH'),
                'ward_discount_pct': -10.5
            }
        }
    ]
    
    # Sample snapshots
    snapshots = {
        'global': {
            'median_price_per_sqm': 950000,
            'total_properties': 15420,
        },
        'wards': {
            'Shibuya': {
                'median_price_per_sqm': 1100000,
                'total_properties': 2850,
                'candidate_count': 8
            },
            'Setagaya': {
                'median_price_per_sqm': 800000,
                'total_properties': 4200,
                'candidate_count': 12
            }
        }
    }
    
    # Generate digest
    try:
        package = generate_daily_digest(candidates, snapshots)
        
        # Basic validation
        assert 'html' in package, "HTML content missing"
        assert 'csv' in package, "CSV content missing"
        assert 'date' in package, "Date missing"
        assert 'candidate_count' in package, "Candidate count missing"
        
        print(f"✓ Package structure valid")
        print(f"✓ Candidate count: {package['candidate_count']}")
        print(f"✓ Date: {package['date']}")
        
        # Check HTML content
        html = package['html']
        assert 'TEST_001' in html, "TEST_001 not found in HTML"
        assert 'TEST_002' in html, "TEST_002 not found in HTML"
        assert 'Market Summary' in html, "Market Summary section missing"
        assert 'Top Candidates' in html, "Top Candidates section missing"
        print(f"✓ HTML content valid")
        
        # Check CSV content
        csv = package['csv']
        assert 'TEST_001' in csv, "TEST_001 not found in CSV"
        assert 'TEST_002' in csv, "TEST_002 not found in CSV"
        lines = csv.strip().split('\n')
        assert len(lines) >= 3, f"Expected at least 3 lines (header + 2 candidates), got {len(lines)}"
        print(f"✓ CSV content valid ({len(lines)} lines)")
        
        print("\n✅ All basic tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_basic_digest_generation()
    sys.exit(0 if success else 1)