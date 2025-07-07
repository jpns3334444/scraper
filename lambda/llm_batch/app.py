"""
LLM Batch Lambda function for OpenAI Batch API processing.
Creates batch jobs, polls for completion, and saves results.
"""
import json
import logging
import os
import time
from typing import Any, Dict

import boto3
from openai import OpenAI

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for LLM batch processing.
    
    Args:
        event: Lambda event containing prompt data from previous step
        context: Lambda context
        
    Returns:
        Dict containing batch results location and metadata
    """
    try:
        date_str = event.get('date')
        bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        prompt_key = event.get('prompt_key')
        
        logger.info(f"Processing LLM batch for date: {date_str}")
        
        # Initialize OpenAI client
        openai_client = get_openai_client()
        
        # Load prompt payload from S3
        prompt_payload = load_prompt_from_s3(bucket, prompt_key)
        
        # Create batch job
        batch_job = create_batch_job(openai_client, prompt_payload, date_str)
        
        logger.info(f"Created batch job: {batch_job.id}")
        
        # Poll for completion
        completed_batch = poll_batch_completion(openai_client, batch_job.id, context)
        
        # Download and save results
        result_key = f"batch_output/{date_str}/response.json"
        batch_result = download_batch_results(openai_client, completed_batch, bucket, result_key)
        
        logger.info(f"Successfully completed batch processing")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'result_key': result_key,
            'batch_id': completed_batch.id,
            'batch_result': batch_result
        }
        
    except Exception as e:
        logger.error(f"LLM batch processing failed: {e}")
        raise


def get_openai_client() -> OpenAI:
    """
    Initialize OpenAI client with API key from SSM.
    
    Returns:
        OpenAI client instance
    """
    try:
        # Get API key from SSM Parameter Store
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            # Fallback to SSM if not in environment
            stack_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', '').split('-')[0]
            param_name = f'/ai-scraper/{stack_name}/openai-api-key'
            
            response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
            api_key = response['Parameter']['Value']
        
        return OpenAI(api_key=api_key)
        
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        raise


def load_prompt_from_s3(bucket: str, key: str) -> Dict[str, Any]:
    """
    Load prompt payload from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for prompt file
        
    Returns:
        Prompt payload dictionary
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)
        
    except Exception as e:
        logger.error(f"Failed to load prompt from s3://{bucket}/{key}: {e}")
        raise


def create_batch_job(client: OpenAI, prompt_payload: Dict[str, Any], date_str: str) -> Any:
    """
    Create OpenAI batch job.
    
    Args:
        client: OpenAI client instance
        prompt_payload: Prompt payload dictionary
        date_str: Processing date string
        
    Returns:
        Batch job object
    """
    try:
        # Prepare batch request format
        batch_request = {
            "custom_id": f"listing-analysis-{date_str}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": prompt_payload
        }
        
        # Create temporary file for batch input
        batch_input_content = json.dumps(batch_request, ensure_ascii=False)
        
        # Upload batch input file
        batch_input_file = client.files.create(
            file=batch_input_content.encode('utf-8'),
            purpose="batch"
        )
        
        logger.info(f"Created batch input file: {batch_input_file.id}")
        
        # Create batch job
        batch_job = client.batches.create(
            input_file_id=batch_input_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "date": date_str,
                "purpose": "real-estate-analysis"
            }
        )
        
        return batch_job
        
    except Exception as e:
        logger.error(f"Failed to create batch job: {e}")
        raise


def poll_batch_completion(client: OpenAI, batch_id: str, context: Any) -> Any:
    """
    Poll batch job until completion.
    
    Args:
        client: OpenAI client instance
        batch_id: Batch job ID
        context: Lambda context for timeout checking
        
    Returns:
        Completed batch job object
    """
    max_wait_time = 3300  # 55 minutes (Lambda timeout is 60 minutes)
    poll_interval = 30  # Poll every 30 seconds
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            batch = client.batches.retrieve(batch_id)
            
            logger.info(f"Batch status: {batch.status}")
            
            if batch.status == "completed":
                logger.info(f"Batch completed successfully")
                return batch
            elif batch.status in ["failed", "expired", "cancelled"]:
                raise Exception(f"Batch job failed with status: {batch.status}")
            
            # Check Lambda remaining time
            remaining_time = context.get_remaining_time_in_millis() if context else float('inf')
            if remaining_time < 120000:  # Less than 2 minutes remaining
                logger.warning("Lambda timeout approaching, batch may not complete")
                # You might want to implement a continuation mechanism here
                raise Exception("Lambda timeout approaching before batch completion")
            
            time.sleep(poll_interval)
            
        except Exception as e:
            if "Batch job failed" in str(e) or "timeout" in str(e):
                raise
            logger.warning(f"Error polling batch status: {e}")
            time.sleep(poll_interval)
    
    raise Exception(f"Batch job {batch_id} did not complete within timeout")


def download_batch_results(client: OpenAI, batch: Any, bucket: str, result_key: str) -> Dict[str, Any]:
    """
    Download batch results and save to S3.
    
    Args:
        client: OpenAI client instance
        batch: Completed batch job object
        bucket: S3 bucket name
        result_key: S3 key for results file
        
    Returns:
        Parsed batch result dictionary
    """
    try:
        # Download output file
        output_file_id = batch.output_file_id
        if not output_file_id:
            raise Exception("No output file available for completed batch")
        
        output_file_content = client.files.content(output_file_id)
        output_content = output_file_content.read().decode('utf-8')
        
        # Parse the result
        result_line = output_content.strip().split('\n')[0]  # First line contains our result
        result_data = json.loads(result_line)
        
        # Extract the actual response
        response_content = result_data.get('response', {}).get('body', {}).get('choices', [{}])[0].get('message', {}).get('content', '{}')
        batch_result = json.loads(response_content)
        
        # Save full response to S3
        full_result = {
            'batch_id': batch.id,
            'status': batch.status,
            'raw_response': result_data,
            'parsed_result': batch_result
        }
        
        s3_client.put_object(
            Bucket=bucket,
            Key=result_key,
            Body=json.dumps(full_result, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(f"Saved batch results to s3://{bucket}/{result_key}")
        
        return batch_result
        
    except Exception as e:
        logger.error(f"Failed to download batch results: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 're-stock',
        'prompt_key': 'prompts/2025-07-07/payload.json'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))