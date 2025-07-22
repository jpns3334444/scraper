#!/usr/bin/env python3
"""
Simple verification that the digest components work.
"""

# Test just the daily_digest.py module which doesn't have the problematic import
import sys
import os
sys.path.append(os.getcwd())

from notifications.daily_digest import DailyDigestGenerator, generate_daily_digest

def create_mock_verdict(value):
    """Create a mock verdict object."""
    class MockVerdict:
        def __init__(self, val):
            self.value = val
    return MockVerdict(value)

def test_digest_components():
    """Test the basic digest generation components."""
    print("Testing digest generation components...")
    
    # Sample candidates
    candidates = [
        {
            'id': 'VERIFY_001',
            'price': 50000000,
            'size_sqm': 60.5,
            'price_per_sqm': 826446,
            'ward': 'Shibuya',
            'building_age_years': 8,
            'nearest_station_meters': 400,
            'components': {
                'final_score': 82.5,
                'verdict': create_mock_verdict('BUY_CANDIDATE'),
                'ward_discount_pct': -18.5
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
            }
        }
    }
    
    try:
        # Test the standalone generator
        generator = DailyDigestGenerator()
        print(f"✓ Generator initialized (date: {generator.date})")
        
        # Test HTML generation
        html = generator.generate_html_digest(candidates, snapshots)
        assert 'VERIFY_001' in html
        assert 'Market Summary' in html
        print("✓ HTML generation works")
        
        # Test CSV generation
        csv = generator.generate_csv_digest(candidates)
        assert 'VERIFY_001' in csv
        lines = csv.strip().split('\n')
        assert len(lines) >= 2  # Header + data
        print("✓ CSV generation works")
        
        # Test package generation
        package = generate_daily_digest(candidates, snapshots)
        assert 'html' in package
        assert 'csv' in package
        print("✓ Package generation works")
        
        print(f"\n✅ All digest components work correctly!")
        print(f"   - HTML content: {len(package['html'])} characters")
        print(f"   - CSV content: {len(package['csv'])} characters") 
        print(f"   - Candidate count: {package['candidate_count']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_digest_components()
    sys.exit(0 if success else 1)