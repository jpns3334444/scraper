"""
LLM Synchronous Lambda function for OpenAI API processing.
Processes real estate listings directly using chat completions API with o3 model.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import boto3
import openai
from openai import OpenAI

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for synchronous LLM processing.
    
    Args:
        event: Lambda event containing prompt data from previous step
        context: Lambda context
        
    Returns:
        Dict containing results location and metadata
    """
    try:
        date_str = event.get('date')
        bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        prompt_key = event.get('prompt_key')
        
        logger.info(f"Processing LLM requests for date: {date_str}")
        
        # Initialize OpenAI client
        openai_client = get_openai_client()
        
        # Determine which model to use (o3 or o3-mini)
        model = os.environ.get('OPENAI_MODEL', 'o3')
        logger.info(f"Using model: {model}")
        
        # Load batch requests JSONL from S3
        batch_requests = load_batch_requests_from_s3(bucket, prompt_key)
        logger.info(f"Loaded {len(batch_requests)} requests to process")
        
        # Process each request synchronously
        results = process_requests_sync(openai_client, batch_requests, model, context)
        
        # Save results to S3 in the same format as batch API
        result_key = f"batch_output/{date_str}/response.json"
        save_results_to_s3(results, bucket, result_key, batch_requests)
        
        logger.info(f"Successfully completed synchronous processing")
        
        # Return the same structure as the batch version for compatibility
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'result_key': result_key,
            'batch_id': f"sync-{date_str}",  # Simulated batch ID for compatibility
            'batch_result': {
                'batch_id': f"sync-{date_str}",
                'status': 'completed',
                'total_results': len(results),
                'individual_results': results
            }
        }
        
    except Exception as e:
        logger.error(f"LLM processing failed: {e}")
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


def load_batch_requests_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Load batch requests JSONL from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for JSONL file
        
    Returns:
        List of batch request dictionaries
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        
        requests = []
        for line in content.strip().split('\n'):
            if line.strip():
                requests.append(json.loads(line))
        
        logger.info(f"Loaded {len(requests)} batch requests from JSONL")
        return requests
        
    except Exception as e:
        logger.error(f"Failed to load batch requests from s3://{bucket}/{key}: {e}")
        raise


def process_requests_sync(
    client: OpenAI, 
    batch_requests: List[Dict[str, Any]], 
    model: str,
    context: Any
) -> List[Dict[str, Any]]:
    """
    Process all requests synchronously with retry logic.
    
    Args:
        client: OpenAI client instance
        batch_requests: List of batch request dictionaries
        model: Model to use (o3 or o3-mini)
        context: Lambda context for timeout checking
        
    Returns:
        List of result dictionaries
    """
    results = []
    total_requests = len(batch_requests)
    
    for i, request in enumerate(batch_requests):
        # Check Lambda timeout (leave 2 minutes buffer)
        if context:
            remaining_time = context.get_remaining_time_in_millis()
            if remaining_time < 120000:  # Less than 2 minutes
                logger.warning(f"Lambda timeout approaching. Processed {i}/{total_requests} requests")
                break
        
        custom_id = request.get('custom_id', f'request-{i}')
        logger.info(f"Processing request {i+1}/{total_requests}: {custom_id}")
        
        try:
            # Extract the actual request body
            request_body = request.get('body', {})
            
            # Call OpenAI API with retry logic
            response = call_openai_with_retry(
                client=client,
                model=model,
                messages=request_body.get('messages', []),
                temperature=request_body.get('temperature', 0.2),
                max_tokens=request_body.get('max_tokens', 4000)
            )
            
            # Format result to match batch API output structure
            result = {
                'custom_id': custom_id,
                'analysis': response.choices[0].message.content if response.choices else '',
                'full_response': {
                    'custom_id': custom_id,
                    'response': {
                        'status_code': 200,
                        'body': {
                            'id': response.id,
                            'object': 'chat.completion',
                            'created': response.created,
                            'model': response.model,
                            'choices': [
                                {
                                    'index': 0,
                                    'message': {
                                        'role': 'assistant',
                                        'content': response.choices[0].message.content
                                    },
                                    'finish_reason': response.choices[0].finish_reason
                                }
                            ],
                            'usage': {
                                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                                'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                                'total_tokens': response.usage.total_tokens if response.usage else 0
                            }
                        }
                    }
                }
            }
            
            results.append(result)
            
            # Small delay between requests to avoid rate limits
            if i < total_requests - 1:  # Don't delay after last request
                time.sleep(0.5)  # 500ms delay
                
        except Exception as e:
            logger.error(f"Failed to process request {custom_id}: {e}")
            # Add error result to maintain consistency
            results.append({
                'custom_id': custom_id,
                'analysis': '',
                'full_response': {
                    'custom_id': custom_id,
                    'error': {
                        'message': str(e),
                        'type': type(e).__name__
                    }
                }
            })
    
    logger.info(f"Processed {len(results)} requests successfully")
    return results


def call_openai_with_retry(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 4000,
    max_retries: int = 3
) -> Any:
    """
    Call OpenAI API with exponential backoff retry logic.
    
    Args:
        client: OpenAI client
        model: Model name (o3, o3-mini, or gpt-4o)
        messages: Chat messages including images
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        max_retries: Maximum number of retry attempts
        
    Returns:
        OpenAI API response
    """
    for attempt in range(max_retries):
        try:
            # Use correct parameter name based on model
            if model.startswith('gpt-4o'):
                # gpt-4o uses max_completion_tokens
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_completion_tokens=max_tokens
                )
            else:
                # o3 and o3-mini use max_tokens
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            return response
            
        except openai.RateLimitError as e:
            # Handle rate limit with exponential backoff
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2  # 2s, 4s, 8s
                logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}")
                time.sleep(wait_time)
            else:
                logger.error(f"Rate limit exceeded after {max_retries} attempts")
                raise
                
        except (openai.APIError, openai.APIConnectionError) as e:
            # Handle temporary API errors
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 1  # 1s, 2s, 4s
                logger.warning(f"API error: {e}, waiting {wait_time}s before retry {attempt + 1}")
                time.sleep(wait_time)
            else:
                logger.error(f"API error after {max_retries} attempts: {e}")
                raise
                
        except Exception as e:
            # Don't retry on other errors
            logger.error(f"Unexpected error calling OpenAI API: {e}")
            raise


def save_results_to_s3(
    results: List[Dict[str, Any]], 
    bucket: str, 
    result_key: str,
    original_requests: List[Dict[str, Any]]
) -> None:
    """
    Save results to S3 in the same format as batch API.
    
    Args:
        results: List of result dictionaries
        bucket: S3 bucket name
        result_key: S3 key for results file
        original_requests: Original batch requests for reference
    """
    try:
        # Create the full result structure matching batch API output
        full_result = {
            'batch_id': f"sync-{os.path.basename(result_key).split('.')[0]}",
            'status': 'completed',
            'total_results': len(results),
            'individual_results': results
        }
        
        # Save to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=result_key,
            Body=json.dumps(full_result, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(f"Saved results to s3://{bucket}/{result_key}")
        
    except Exception as e:
        logger.error(f"Failed to save results to S3: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 'tokyo-real-estate-ai-data',
        'prompt_key': 'prompts/2025-07-07/batch_requests.jsonl'
    }
    
    # Set environment variables for local testing
    os.environ['OUTPUT_BUCKET'] = 'tokyo-real-estate-ai-data'
    os.environ['OPENAI_MODEL'] = 'o3'  # or 'o3-mini' for cost savings
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))