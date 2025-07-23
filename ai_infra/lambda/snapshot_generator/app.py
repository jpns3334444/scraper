"""
AWS Lambda function for daily snapshot generation.

This Lambda function generates global and ward-level market snapshots
for the Lean v1.3 real estate analysis pipeline.
"""

import json
import logging
import os
import sys
from typing import Any, Dict

# Configure logging first
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Import snapshot manager - ensure modules are packaged with Lambda deployment
try:
    from snapshots.snapshot_manager import generate_daily_snapshots
except ImportError as e:
    logger.error(f"Failed to import snapshot_manager: {e}")
    logger.error("DEPLOYMENT ERROR: The 'snapshots' module must be packaged with this Lambda function")
    logger.error("Include snapshots/ directory in the deployment package or use a Lambda layer")
    raise RuntimeError(f"Missing required module 'snapshots': {e}")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda entry point for snapshot generation.
    
    Args:
        event: Lambda event containing optional date parameter
        context: Lambda context (unused)
        
    Returns:
        Results dictionary with metrics and status
    """
    logger.info("Starting snapshot generation Lambda")
    logger.info(f"Event: {json.dumps(event)}")
    
    try:
        # Extract date from event if provided
        date_str = None
        if 'date' in event:
            date_str = event['date']
        
        # Generate snapshots
        results = generate_daily_snapshots(event)
        
        logger.info("Snapshot generation completed successfully")
        logger.info(f"Results: {json.dumps(results, default=str)}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(results, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in snapshot generation: {str(e)}", exc_info=True)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Snapshot generation failed'
            })
        }


# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        "date": "2025-01-22"
    }
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))