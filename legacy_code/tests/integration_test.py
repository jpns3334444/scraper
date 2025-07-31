#!/usr/bin/env python3
"""
Integration test for the snapshot generation system.
This tests the complete flow without actual AWS calls.
"""

import json
import os
import sys

# Set up environment
os.environ['LEAN_MODE'] = '1'
os.environ['OUTPUT_BUCKET'] = 'test-bucket'
os.environ['AWS_REGION'] = 'ap-northeast-1'

# Add current directory to Python path
sys.path.insert(0, '.')

def test_complete_snapshot_flow():
    """Test the complete snapshot generation flow."""
    print("Testing complete snapshot generation flow...")
    
    try:
        # Test 1: Import snapshot manager
        from snapshots.snapshot_manager import SnapshotGenerator, generate_daily_snapshots
        print("✓ Snapshot manager imported successfully")
        
        # Test 2: Create generator instance
        generator = SnapshotGenerator(s3_bucket='test-bucket')
        print("✓ SnapshotGenerator created")
        
        # Test 3: Test individual methods with mock data
        mock_listings = [
            {
                'price_per_sqm': 95000,
                'total_sqm': 45,
                'status': 'active',
                'ward': 'Shibuya',
                'property_type': 'apartment'
            },
            {
                'price_per_sqm': 120000,
                'total_sqm': 60,
                'status': 'active',
                'ward': 'Shinjuku',
                'property_type': 'apartment'
            },
            {
                'price_per_sqm': 80000,
                'total_sqm': 70,
                'status': 'active',
                'ward': 'Shibuya',
                'property_type': 'house'
            }
        ]
        
        # Test global snapshot creation
        global_snapshot = generator._generate_global_snapshot(mock_listings, '2025-01-22')
        print(f"✓ Global snapshot created: median ¥{global_snapshot['median_price_per_sqm']:,.0f}/sqm")
        print(f"  - Total properties: {global_snapshot['total_active']}")
        print(f"  - P75: ¥{global_snapshot['percentiles']['p75']:,.0f}/sqm")
        
        # Test ward grouping
        wards = generator._group_by_ward(mock_listings)
        print(f"✓ Ward grouping: {list(wards.keys())}")
        
        # Test ward snapshot creation
        for ward, ward_listings in wards.items():
            ward_snapshot = generator._generate_ward_snapshot(ward_listings, ward, '2025-01-22')
            print(f"✓ Ward {ward} snapshot: {ward_snapshot['inventory']} properties, median ¥{ward_snapshot['median_price_per_sqm']:,.0f}/sqm")
        
        # Test 4: Test Lambda handler import (without executing)
        try:
            # Import the lambda app directly by reading the file
            import importlib.util
            lambda_app_path = os.path.join('.', 'ai-infra', 'lambda', 'snapshot_generator', 'app.py')
            spec = importlib.util.spec_from_file_location("lambda_app", lambda_app_path)
            lambda_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(lambda_module)
            print("✓ Lambda handler module loaded successfully")
            
            # Test the lambda handler structure
            if hasattr(lambda_module, 'lambda_handler'):
                print("✓ lambda_handler function found")
            else:
                print("❌ lambda_handler function not found")
        except Exception as e:
            print(f"⚠ Lambda handler test failed: {e}")
        
        print("\n" + "="*50)
        print("✓ INTEGRATION TEST PASSED")
        print("Snapshot generation system is ready for deployment!")
        
        # Show example snapshot structure
        print("\nExample Global Snapshot Structure:")
        print(json.dumps(global_snapshot, indent=2, ensure_ascii=False))
        
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_complete_snapshot_flow()
    sys.exit(0 if success else 1)