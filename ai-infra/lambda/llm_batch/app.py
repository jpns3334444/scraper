"""
Lean v1.3 LLM Batch Lambda function with schema validation and fallback.
Processes candidate properties only with strict JSON schema validation and 1 retry.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
import openai
from openai import OpenAI, AsyncOpenAI
from botocore.exceptions import ClientError

# Import schema validation and metrics with better error handling
import sys
from pathlib import Path

# Note: Remove sys.path manipulation - modules should be packaged with Lambda deployment

# Set up logging first
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Try importing schema validation
validate_llm_output = None
create_fallback_evaluation = None
truncate_response_for_logging = None

try:
    from schemas.validate import validate_llm_output, create_fallback_evaluation, truncate_response_for_logging
    logger.info("Successfully imported schema validation utilities")
except ImportError as e:
    logger.warning(f"Schema validation not available: {e}")
    # Provide fallback implementations
    def validate_llm_output(response: str):
        """Fallback validation - basic JSON and structure check."""
        try:
            import json
            data = json.loads(response)
            # Basic structure check for lean evaluation format - use correct field names from schema
            if isinstance(data, dict) and 'upside' in data and 'risks' in data and 'justification' in data:
                # Check that required fields exist and are lists/strings
                if (isinstance(data.get('upside'), list) and 
                    isinstance(data.get('risks'), list) and 
                    isinstance(data.get('justification'), str)):
                    return True, data, None
                else:
                    return False, None, "Invalid structure - upside/risks must be lists, justification must be string"
            else:
                return False, None, "Missing required fields: upside, risks, justification"
        except json.JSONDecodeError as e:
            return False, None, f"Invalid JSON: {str(e)}"
        except Exception as e:
            return False, None, f"Validation error: {str(e)}"
    
    def create_fallback_evaluation(property_id: str, base_score: int, final_score: int, verdict: str = "REJECT"):
        """Fallback evaluation creation."""
        return {
            "property_id": property_id,
            "base_score": base_score,
            "final_score": final_score,
            "verdict": verdict,
            "upside": ["Fallback evaluation - schema validation unavailable"],
            "risks": ["Schema validation module not loaded", "Manual review required"],
            "justification": "Fallback response due to missing schema validation utilities"
        }
    
    def truncate_response_for_logging(response: str, max_length: int = 1500) -> str:
        """Fallback truncation function."""
        return response[:max_length] + "..." if len(response) > max_length else response

# Try importing metrics
emit_llm_calls = None
emit_llm_schema_failures = None
emit_pipeline_metrics = None

try:
    from util.metrics import emit_llm_calls, emit_llm_schema_failures, emit_pipeline_metrics
    logger.info("Successfully imported metrics utilities")
except ImportError as e:
    logger.warning(f"Metrics utilities not available: {e}")
    # Provide fallback implementations
    def emit_llm_calls(count: int):
        logger.info(f"LLM.Calls metric: {count}")
    
    def emit_llm_schema_failures(count: int):
        logger.info(f"Evaluator.SchemaFail metric: {count}")
    
    def emit_pipeline_metrics(stage: str, metrics: dict):
        logger.info(f"Pipeline metrics for {stage}: {metrics}")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Import centralized config helper
try:
    from util.config import get_config
except ImportError:
    logger.warning("Centralized config not available, falling back to direct os.environ access")
    get_config = None

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lean v1.3 Lambda handler - process candidates only with schema validation.
    
    Args:
        event: Lambda event containing prompt data from previous step
        context: Lambda context
        
    Returns:
        Dict containing results location and metadata with lean metrics
    """
    try:
        date_str = event.get('date')
        if get_config:
            bucket = event.get('bucket', get_config().get_str('OUTPUT_BUCKET'))
        else:
            bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        prompt_key = event.get('prompt_key')
        
        if not prompt_key:
            logger.warning("No prompt_key provided - no candidates to process")
            return {
                'statusCode': 200,
                'date': date_str,
                'bucket': bucket,
                'candidates_processed': 0,
                'schema_failures': 0,
                'llm_calls': 0
            }
        
        logger.info(f"Processing lean LLM requests for candidates on {date_str}")
        
        # Initialize OpenAI client
        openai_client = get_openai_client()
        
        # Default model from environment
        if get_config:
            default_model = get_config().get_str('OPENAI_MODEL', 'gpt-4o')
        else:
            default_model = os.environ.get('OPENAI_MODEL', 'gpt-4o')
        logger.info(f"Using model: {default_model}")
        
        # Load batch requests JSONL from S3
        batch_requests = load_batch_requests_from_s3(bucket, prompt_key)
        candidates_count = len(batch_requests)
        logger.info(f"Loaded {candidates_count} candidate requests to process")
        
        if candidates_count == 0:
            return {
                'statusCode': 200,
                'date': date_str,
                'bucket': bucket,
                'candidates_processed': 0,
                'schema_failures': 0,
                'llm_calls': 0
            }
        
        # Process requests with schema validation
        results, metrics = asyncio.run(process_lean_requests(openai_client, batch_requests, default_model))
        
        # Save individual candidate results to candidates/ directory
        save_candidate_results(results, bucket, date_str)
        
        # Save batch summary for compatibility
        result_key = f"batch_output/{date_str}/lean_response.json"
        save_results_to_s3(results, bucket, result_key, batch_requests)
        
        logger.info(f"Processed {candidates_count} candidates: {metrics['llm_calls']} LLM calls, {metrics['schema_failures']} schema failures")
        
        # Emit metrics to CloudWatch
        try:
            emit_llm_calls(metrics['llm_calls'])
            emit_llm_schema_failures(metrics['schema_failures'])
            emit_pipeline_metrics('LLM', metrics)
            logger.info(f"Emitted LLM metrics: {metrics}")
        except Exception as e:
            logger.warning(f"Failed to emit metrics: {e}")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'result_key': result_key,
            'batch_id': f"batch_{date_str}",
            'batch_result': results,
            'candidates_processed': candidates_count,
            'llm_calls': metrics['llm_calls'],
            'schema_failures': metrics['schema_failures'],
            'retry_attempts': metrics['retry_attempts']
        }
        
    except Exception as e:
        logger.error(f"Lean LLM processing failed: {e}")
        raise


def get_openai_client() -> OpenAI:
    """
    Initialize OpenAI client with API key from Secrets Manager.
    
    Returns:
        OpenAI client instance
    """
    try:
        # Get API key from Secrets Manager
        if get_config:
            secret_name = get_config().get_str('OPENAI_SECRET_NAME', 'ai-scraper/openai-api-key')
        else:
            secret_name = os.environ.get('OPENAI_SECRET_NAME', 'ai-scraper/openai-api-key')
        
        # Retry logic for API key retrieval
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = secrets_client.get_secret_value(SecretId=secret_name)
                api_key = response['SecretString']
                
                if not api_key or api_key.strip() == '':
                    raise ValueError("Retrieved API key is empty")
                
                return OpenAI(api_key=api_key)
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Secrets Manager attempt {attempt + 1} failed (error: {error_code}), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to get API key after {max_retries} attempts: {error_code}")
                    # Try fallback to environment variable
                    fallback_key = os.environ.get('OPENAI_API_KEY')
                    if fallback_key:
                        logger.warning("Using fallback API key from environment variable")
                        return OpenAI(api_key=fallback_key)
                    else:
                        raise Exception(f"Failed to get OpenAI API key from Secrets Manager after {max_retries} attempts: {error_code}")
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Unexpected error retrieving API key, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to get API key after {max_retries} attempts due to unexpected error: {e}")
                    # Try fallback to environment variable
                    fallback_key = os.environ.get('OPENAI_API_KEY')
                    if fallback_key:
                        logger.warning("Using fallback API key from environment variable")
                        return OpenAI(api_key=fallback_key)
                    else:
                        raise Exception(f"Failed to get OpenAI API key after {max_retries} attempts: {str(e)}")
        
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
        
        logger.info(f"Loaded {len(requests)} candidate batch requests from JSONL")
        return requests
        
    except s3_client.exceptions.NoSuchKey:
        logger.error(f"Batch requests file not found: s3://{bucket}/{key}")
        return []
    except Exception as e:
        logger.error(f"Failed to load batch requests from s3://{bucket}/{key}: {e}")
        raise


async def process_lean_requests(
    client: OpenAI, 
    batch_requests: List[Dict[str, Any]], 
    model: str
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Process requests with schema validation and retry logic.
    
    Args:
        client: OpenAI client instance
        batch_requests: List of candidate batch request dictionaries
        model: Model to use (o3 or o3-mini)
        
    Returns:
        Tuple of (results, metrics)
    """
    # Create async client
    api_key = client.api_key
    async_client = AsyncOpenAI(api_key=api_key)
    
    # Metrics tracking
    metrics = {
        'llm_calls': 0,
        'schema_failures': 0,
        'retry_attempts': 0
    }
    
    # Create tasks for parallel processing
    tasks = []
    for i, request in enumerate(batch_requests):
        task = process_candidate_with_validation(async_client, request, model, i, metrics)
        tasks.append(task)
    
    # Run all tasks in parallel
    logger.info(f"Starting processing of {len(tasks)} candidate requests with schema validation")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle exceptions
    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Request {i+1} failed with exception: {result}")
            # Create fallback result
            custom_id = batch_requests[i].get('custom_id', f'request-{i}')
            property_id = extract_property_id_from_request(batch_requests[i])
            fallback_data = create_fallback_evaluation(property_id, 0, 0, "REJECT") if create_fallback_evaluation else {}
            
            # Add metadata for fallback
            if fallback_data and '_metadata' not in fallback_data:
                fallback_data['_metadata'] = {
                    'property_id': property_id,
                    'base_score': 0,
                    'evaluation_date': f"{datetime.utcnow().isoformat()}Z"
                }
            
            final_results.append({
                'custom_id': custom_id,
                'property_id': property_id,
                'evaluation_data': fallback_data,
                'schema_valid': False,
                'error': str(result)
            })
            metrics['schema_failures'] += 1
        else:
            final_results.append(result)
    
    logger.info(f"Completed processing: {metrics['llm_calls']} calls, {metrics['schema_failures']} failures, {metrics['retry_attempts']} retries")
    return final_results, metrics


async def process_candidate_with_validation(
    client: AsyncOpenAI,
    request: Dict[str, Any],
    model: str,
    index: int,
    metrics: Dict[str, int]
) -> Dict[str, Any]:
    """
    Process a single candidate with schema validation and retry.
    
    Args:
        client: Async OpenAI client
        request: Batch request dictionary
        model: Model to use
        index: Request index for logging
        metrics: Metrics tracking dictionary
        
    Returns:
        Result dictionary with validation status
    """
    custom_id = request.get('custom_id', f'request-{index}')
    property_id = extract_property_id_from_request(request)
    
    logger.info(f"Processing candidate {index+1}: {property_id}")
    
    # Extract request body details
    request_body = request.get('body', {})
    messages = request_body.get('messages', [])
    base_score = extract_base_score_from_messages(messages)
    
    max_attempts = 2  # Original + 1 retry
    
    for attempt in range(max_attempts):
        try:
            # Call OpenAI API
            metrics['llm_calls'] += 1
            if attempt > 0:
                metrics['retry_attempts'] += 1
                logger.info(f"Retry attempt {attempt} for {property_id}")
            
            response = await call_openai_async(
                client=client,
                model=model,
                messages=messages,
                max_tokens=request_body.get('max_completion_tokens', 1000)
            )
            
            # Extract and validate response
            raw_response = response.choices[0].message.content if response.choices else ""
            logger.debug(f"Raw LLM response for {property_id}: {truncate_response_for_logging(raw_response, 1500)}")
            
            # Validate against schema
            if validate_llm_output:
                is_valid, parsed_data, error_msg = validate_llm_output(raw_response)
                
                if is_valid and parsed_data:
                    # Add deterministic metadata that's not part of the LLM schema
                    parsed_data['_metadata'] = {
                        'property_id': property_id,
                        'base_score': base_score,
                        'evaluation_date': f"{datetime.utcnow().isoformat()}Z"
                    }
                    
                    logger.info(f"Successfully validated response for {property_id}")
                    return {
                        'custom_id': custom_id,
                        'property_id': property_id,
                        'evaluation_data': parsed_data,
                        'schema_valid': True,
                        'raw_response': raw_response,
                        'attempts': attempt + 1
                    }
                else:
                    # Schema validation failed
                    logger.warning(f"Schema validation failed for {property_id} (attempt {attempt+1}): {error_msg}")
                    if attempt == max_attempts - 1:  # Last attempt
                        break
                    continue
            else:
                # No validation available - assume valid
                logger.warning(f"Schema validation not available for {property_id}")
                return {
                    'custom_id': custom_id,
                    'property_id': property_id,
                    'evaluation_data': {},
                    'schema_valid': False,
                    'raw_response': raw_response,
                    'attempts': attempt + 1,
                    'error': "Schema validation not available"
                }
                
        except Exception as e:
            logger.error(f"API error for {property_id} (attempt {attempt+1}): {e}")
            if attempt == max_attempts - 1:  # Last attempt
                metrics['schema_failures'] += 1
                # Return fallback evaluation
                fallback_data = create_fallback_evaluation(property_id, base_score, base_score, "REJECT") if create_fallback_evaluation else {}
                
                # Add metadata for fallback
                if fallback_data and '_metadata' not in fallback_data:
                    fallback_data['_metadata'] = {
                        'property_id': property_id,
                        'base_score': base_score,
                        'evaluation_date': f"{datetime.utcnow().isoformat()}Z"
                    }
                
                return {
                    'custom_id': custom_id,
                    'property_id': property_id,
                    'evaluation_data': fallback_data,
                    'schema_valid': False,
                    'error': str(e),
                    'attempts': attempt + 1
                }
            continue
    
    # All attempts failed - create fallback
    metrics['schema_failures'] += 1
    fallback_data = create_fallback_evaluation(property_id, base_score, base_score, "REJECT") if create_fallback_evaluation else {}
    
    # Add metadata for fallback
    if fallback_data and '_metadata' not in fallback_data:
        fallback_data['_metadata'] = {
            'property_id': property_id,
            'base_score': base_score,
            'evaluation_date': f"{datetime.utcnow().isoformat()}Z"
        }
    
    return {
        'custom_id': custom_id,
        'property_id': property_id,
        'evaluation_data': fallback_data,
        'schema_valid': False,
        'error': "All validation attempts failed",
        'attempts': max_attempts
    }


def extract_property_id_from_request(request: Dict[str, Any]) -> str:
    """Extract property ID from batch request."""
    custom_id = request.get('custom_id', '')
    # Format: lean-analysis-YYYY-MM-DD-property_id
    parts = custom_id.split('-')
    if len(parts) >= 4:
        return '-'.join(parts[3:])  # Everything after date
    return 'unknown'


def extract_base_score_from_messages(messages: List[Dict[str, Any]]) -> int:
    """Extract base_score from prompt messages for validation."""
    for message in messages:
        if message.get('role') == 'user':
            content = message.get('content', [])
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text':
                    text = item.get('text', '')
                    if 'base_score' in text and 'PROPERTY:' in text:
                        try:
                            # Find JSON in property section
                            start = text.find('{')
                            end = text.rfind('}')
                            if start != -1 and end != -1:
                                property_data = json.loads(text[start:end+1])
                                return property_data.get('base_score', 0)
                        except:
                            continue
    return 0


def save_candidate_results(results: List[Dict[str, Any]], bucket: str, date_str: str) -> None:
    """
    Save individual candidate evaluation results to candidates/ directory.
    
    Args:
        results: List of result dictionaries
        bucket: S3 bucket name  
        date_str: Processing date string
    """
    try:
        for result in results:
            property_id = result.get('property_id', 'unknown')
            evaluation_data = result.get('evaluation_data', {})
            
            if evaluation_data and property_id != 'unknown':
                # Save to candidates/YYYY-MM-DD/{property_id}.json
                key = f"candidates/{date_str}/{property_id}.json"
                
                # Extract metadata and create clean result
                metadata = evaluation_data.pop('_metadata', {})
                base_score = metadata.get('base_score', 0)
                
                candidate_result = {
                    'property_id': property_id,
                    'evaluation_date': date_str,
                    'schema_valid': result.get('schema_valid', False),
                    'llm_attempts': result.get('attempts', 1),
                    'base_score': base_score,
                    **evaluation_data
                }
                
                s3_client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=json.dumps(candidate_result, ensure_ascii=False, indent=2).encode('utf-8'),
                    ContentType='application/json'
                )
        
        valid_results = sum(1 for r in results if r.get('schema_valid', False))
        logger.info(f"Saved {len(results)} candidate results ({valid_results} valid) to candidates/{date_str}/")
        
    except Exception as e:
        logger.error(f"Failed to save candidate results: {e}")
        raise


async def call_openai_async(
    client: AsyncOpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int = 1000,
    max_retries: int = 3
):
    """
    Call OpenAI API asynchronously with exponential backoff retry logic.
    """
    for attempt in range(max_retries):
        try:
            # o3 models don't support temperature parameter
            if model.startswith('o3'):
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_completion_tokens=max_tokens
                )
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    max_completion_tokens=max_tokens
                )
            return response
            
        except openai.RateLimitError as e:
            # Handle rate limit with exponential backoff
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2  # 2s, 4s, 8s
                logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Rate limit exceeded after {max_retries} attempts")
                raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt)  # 1s, 2s, 4s
                logger.warning(f"API error: {e}, waiting {wait_time}s before retry {attempt + 1}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"API error after {max_retries} attempts: {e}")
                raise


def save_results_to_s3(
    results: List[Dict[str, Any]], 
    bucket: str, 
    result_key: str,
    original_requests: List[Dict[str, Any]]
) -> None:
    """
    Save batch summary results to S3 in lean format.
    
    Args:
        results: List of result dictionaries
        bucket: S3 bucket name
        result_key: S3 key for results file
        original_requests: Original batch requests for reference
    """
    try:
        # Create lean result structure
        lean_result = {
            'batch_id': f"lean-{os.path.basename(result_key).split('.')[0]}",
            'status': 'completed',
            'processing_date': result_key.split('/')[1],  # Extract date from path
            'candidates_processed': len(results),
            'schema_valid_count': sum(1 for r in results if r.get('schema_valid', False)),
            'total_llm_calls': sum(r.get('attempts', 1) for r in results),
            'individual_results': [
                {
                    'property_id': r.get('property_id', 'unknown'),
                    'schema_valid': r.get('schema_valid', False),
                    'attempts': r.get('attempts', 1),
                    'has_evaluation': bool(r.get('evaluation_data')),
                    'base_score': r.get('evaluation_data', {}).get('_metadata', {}).get('base_score', 0)
                }
                for r in results
            ]
        }
        
        # Save to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=result_key,
            Body=json.dumps(lean_result, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(f"Saved lean batch results to s3://{bucket}/{result_key}")
        
    except Exception as e:
        logger.error(f"Failed to save results to S3: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-22',
        'bucket': 'tokyo-real-estate-ai-data',
        'prompt_key': 'ai/prompts/2025-07-22/batch_requests.jsonl'
    }
    
    # Set environment variables for local testing (if not already set)
    if 'OUTPUT_BUCKET' not in os.environ:
        os.environ['OUTPUT_BUCKET'] = 'tokyo-real-estate-ai-data'
    if 'OPENAI_MODEL' not in os.environ:
        os.environ['OPENAI_MODEL'] = 'gpt-4o'
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2, default=str))