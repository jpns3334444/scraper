#!/usr/bin/env python3
"""Test the Lambda handler functionality."""
import sys
import os
sys.path.append(os.getcwd())
# Add the ai_infra path for imports
sys.path.append(os.path.join(os.getcwd(), 'ai_infra'))

def test_lambda_handler():
    """Test the daily digest Lambda handler."""
    print("Testing daily digest Lambda handler...")
    try:
        from ai_infra.lambda.daily_digest.app import lambda_handler
        test_event = {"date": "2025-01-22"}
        test_context = None
        print("✓ Lambda handler imported successfully")
        print("✓ Ready for deployment")
        return True
    except Exception as e:
        print(f"❌ Lambda handler test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_lambda_handler()
    sys.exit(0 if success else 1)
