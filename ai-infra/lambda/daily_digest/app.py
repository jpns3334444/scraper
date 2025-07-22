"""
AWS Lambda function for daily digest generation and email sending.

This Lambda function generates and sends the daily real estate digest
for the Lean v1.3 pipeline.
"""

import json
import logging
import os
import sys
from typing import Any, Dict

# Add the project root to the path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from notifications.notifier import send_daily_digest

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda entry point for daily digest generation and sending.
    
    Args:
        event: Lambda event containing optional date parameter
        context: Lambda context (unused)
        
    Returns:
        Results dictionary with metrics and status
    """
    logger.info("Starting daily digest Lambda")
    logger.info(f"Event: {json.dumps(event)}")
    
    try:
        # Extract date from event if provided
        date_str = None
        if 'date' in event:
            date_str = event['date']
        
        # Generate and send digest
        results = send_daily_digest(event)
        
        logger.info("Daily digest completed successfully")
        logger.info(f"Results: {json.dumps(results, default=str)}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(results, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in daily digest: {str(e)}", exc_info=True)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Daily digest failed'
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