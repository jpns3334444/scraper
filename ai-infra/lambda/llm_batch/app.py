"""
LLM Batch Lambda function for OpenAI Batch API processing.
Creates batch jobs, polls for completion, and saves results.
"""
import io
import json
import logging
import os
import time
from typing import Any, Dict

import boto3
import openai                      # ← add this
from openai import OpenAI
logging.getLogger().info("OpenAI SDK %s", openai.__version__)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')


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
        
        # Load batch requests JSONL from S3
        batch_requests_jsonl = load_batch_requests_from_s3(bucket, prompt_key)
        
        # Create batch job
        batch_job = create_batch_job(openai_client, batch_requests_jsonl, date_str)
        
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
    Initialize OpenAI client with API key from Secrets Manager.
    
    Returns:
        OpenAI client instance
    """
    try:
        # Get API key from Secrets Manager
        secret_name = os.environ.get('OPENAI_SECRET_NAME', 'ai-scraper/openai-api-key')
        
        response = secrets_client.get_secret_value(SecretId=secret_name)
        api_key = response['SecretString']
        
        return OpenAI(api_key=api_key)
        
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        raise


def load_batch_requests_from_s3(bucket: str, key: str) -> str:
    """
    Load batch requests JSONL from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for JSONL file
        
    Returns:
        JSONL content as string
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        
        # Validate that it's valid JSONL
        lines = content.strip().split('\n')
        for i, line in enumerate(lines):
            if line.strip():
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON on line {i+1}: {e}")
                    raise
        
        logger.info(f"Loaded {len(lines)} batch requests from JSONL")
        return content
        
    except Exception as e:
        logger.error(f"Failed to load batch requests from s3://{bucket}/{key}: {e}")
        raise


def create_batch_job(client: OpenAI, batch_requests_jsonl: str, date_str: str) -> Any:
    """
    Create OpenAI batch job from JSONL content.
    
    Args:
        client: OpenAI client instance
        batch_requests_jsonl: JSONL content with batch requests
        date_str: Processing date string
        
    Returns:
        Batch job object
    """
    try:
        # Upload batch input file (JSONL is already in correct format)
        batch_input_file = client.files.create(
            file=io.BytesIO(batch_requests_jsonl.encode('utf-8')),
            purpose="batch"
        )
        
        logger.info(f"Created batch input file: {batch_input_file.id}")
        
        # Count number of requests
        request_count = len([line for line in batch_requests_jsonl.strip().split('\n') if line.strip()])
        logger.info(f"Batch contains {request_count} individual listing analysis requests")
        
        # Create batch job
        batch_job = client.batches.create(
            input_file_id=batch_input_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "date": date_str,
                "purpose": "real-estate-analysis",
                "request_count": str(request_count)
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
        
        # Parse multiple results (one per line for each listing)
        result_lines = output_content.strip().split('\n')
        individual_results = []
        
        for line in result_lines:
            if line.strip():
                try:
                    result_data = json.loads(line)
                    custom_id = result_data.get('custom_id', 'unknown')
                    
                    # Extract the JSON analysis from model response
                    analysis_json = result_data.get('response', {}).get('body', {}).get('choices', [{}])[0].get('message', {}).get('content', '')
                    
                    individual_results.append({
                        'custom_id': custom_id,
                        'analysis': analysis_json,
                        'full_response': result_data
                    })
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse result line: {e}")
                    continue
        
        logger.info(f"Processed {len(individual_results)} individual listing results")
        
        # Save individual results to S3
        full_result = {
            'batch_id': batch.id,
            'status': batch.status,
            'total_results': len(individual_results),
            'individual_results': individual_results
        }
        
        s3_client.put_object(
            Bucket=bucket,
            Key=result_key,
            Body=json.dumps(full_result, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(f"Saved batch results to s3://{bucket}/{result_key}")
        
        return full_result
        
    except Exception as e:
        logger.error(f"Failed to download batch results: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 'tokyo-real-estate-ai-data',
        'prompt_key': 'prompts/2025-07-07/payload.json'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))