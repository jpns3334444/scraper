#!/usr/bin/env python3
"""
Simple test runner for AI pipeline lambda functions.
Directly imports and calls lambda handlers without SAM.
"""
import json
import logging
import os
import sys
import traceback
from pathlib import Path

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Mock context class for lambda testing
class MockContext:
    def __init__(self):
        self.function_name = "test-function"
        self.function_version = "$LATEST"
        self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        self.memory_limit_in_mb = 512
        self.remaining_time_in_millis = 300000
        self.log_group_name = "/aws/lambda/test-function"
        self.log_stream_name = "2023/01/01/[$LATEST]abcdefghijklmnopqrstuvwxyz"
        self.aws_request_id = "12345678-1234-1234-1234-123456789012"
    
    def get_remaining_time_in_millis(self):
        return self.remaining_time_in_millis

def load_env_vars(function_name):
    """Load environment variables from .env.json"""
    logger.info(f"Loading environment variables for function: {function_name}")
    env_file = Path(__file__).parent / ".env.json"
    if not env_file.exists():
        logger.error(f"Environment file not found: {env_file}")
        return
        
    with open(env_file) as f:
        env_config = json.load(f)
    
    # Set environment variables for the function
    if function_name in env_config:
        logger.info(f"Found config for {function_name}")
        for key, value in env_config[function_name].items():
            os.environ[key] = value
            logger.info(f"Set {key}={value}")
    else:
        logger.warning(f"No config found for function: {function_name}")
        logger.info(f"Available functions: {list(env_config.keys())}")

def validate_result(function_name, result, event):
    """Validate function results and detect silent failures"""
    logger.info(f"Validating result for {function_name}")
    
    if function_name == "dynamodb_writer":
        # Check if DynamoDB write was actually attempted
        if result.get("statusCode") == 200:
            logger.info("DynamoDB writer returned success, but need to verify actual write")
            # Check for any error indicators in the result
            if "error" in result:
                logger.error(f"Silent failure detected in DynamoDB writer: {result['error']}")
                return False
        return True
        
    elif function_name == "report_sender":
        # Check if email was actually sent
        if result.get("email_sent"):
            logger.info("Report sender claims email was sent")
            # Look for actual AWS SES or email service confirmation
            if "email_message_id" not in result and "ses_message_id" not in result:
                logger.warning("No email message ID returned - email may not have been sent")
        return True
        
    elif function_name == "llm_batch":
        # Check if OpenAI requests were processed
        batch_result = result.get("batch_result", {})
        if batch_result.get("total_results", 0) > 0:
            logger.info(f"LLM batch processed {batch_result['total_results']} results")
        return True
        
    return True

def run_function(function_name, event_file):
    """Run the specified lambda function with the given event"""
    
    logger.info(f"Starting test for function: {function_name}")
    
    # Load event data
    try:
        with open(event_file) as f:
            event = json.load(f)
        logger.info(f"Loaded event from {event_file}")
        logger.debug(f"Event data: {json.dumps(event, indent=2)}")
    except Exception as e:
        logger.error(f"Failed to load event file {event_file}: {e}")
        return False
    
    print(f"Testing function: {function_name}")
    print(f"Event: {json.dumps(event, indent=2)}")
    print("-" * 50)
    
    # Load environment variables
    load_env_vars(function_name)
    
    # Import and run the appropriate lambda function
    try:
        logger.info(f"Importing lambda function: {function_name}")
        
        if function_name == "etl":
            sys.path.insert(0, str(Path(__file__).parent / "lambda" / "etl"))
            from app import lambda_handler
        elif function_name == "prompt_builder":
            sys.path.insert(0, str(Path(__file__).parent / "lambda" / "prompt_builder"))
            from app import lambda_handler
        elif function_name == "llm_batch":
            sys.path.insert(0, str(Path(__file__).parent / "lambda" / "llm_batch"))
            from app import lambda_handler
        elif function_name == "report_sender":
            sys.path.insert(0, str(Path(__file__).parent / "lambda" / "report_sender"))
            from app import lambda_handler
        elif function_name == "dynamodb_writer":
            sys.path.insert(0, str(Path(__file__).parent / "lambda" / "dynamodb_writer"))
            from app import lambda_handler
        else:
            logger.error(f"Unknown function: {function_name}")
            print(f"Unknown function: {function_name}")
            return False
        
        logger.info(f"Successfully imported {function_name}")
        
        # Create mock context and run function
        context = MockContext()
        logger.info("Executing lambda function...")
        result = lambda_handler(event, context)
        
        logger.info("Function execution completed")
        logger.debug(f"Result: {json.dumps(result, indent=2)}")
        
        # Validate the result
        if validate_result(function_name, result, event):
            print("Function executed successfully!")
            print(f"Result: {json.dumps(result, indent=2)}")
            return True
        else:
            logger.error("Function validation failed - potential silent failure detected")
            return False
        
    except Exception as e:
        logger.error(f"Error running function {function_name}: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        print(f"Error running function: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 test_runner.py <function_name> <event_file>")
        print("Example: python3 test_runner.py etl test-events/etl-event.json")
        sys.exit(1)
    
    function_name = sys.argv[1]
    event_file = sys.argv[2]
    
    success = run_function(function_name, event_file)
    sys.exit(0 if success else 1)