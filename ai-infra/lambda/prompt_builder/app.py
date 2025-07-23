"""
Lean v1.3 Prompt Builder Lambda function for candidate properties only.
Implements lean prompt format with candidate filtering, ≤8 comps, ≤3 images, token controls.
"""
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

# Import our structured logger
try:
    from common.logger import get_logger, lambda_log_context
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

# Import analysis modules
try:
    from analysis.comparables import ComparablesFilter
    from analysis.vision_stub import generate_vision_summary
except ImportError:
    logger.warning("Analysis modules not available - using stubs")
    ComparablesFilter = None
    generate_vision_summary = None

# Import centralized config helper
try:
    from util.config import get_config
except ImportError:
    logger.warning("Centralized config not available, falling back to direct os.environ access")
    get_config = None

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

def decimal_default(obj):
    """JSON serializer for Decimal types from DynamoDB"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

# Initialize DynamoDB table - will be set via environment variable
table = None
if get_config:
    dynamodb_table = get_config().get_str('DYNAMODB_TABLE', '')
    if dynamodb_table:
        table = dynamodb.Table(dynamodb_table)
elif os.environ.get('DYNAMODB_TABLE'):
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

def load_lean_system_prompt() -> str:
    """
    Load the lean system prompt for Lean v1.3.
    
    Returns:
        Lean system prompt string
    """
    try:
        # Try to load from file in same directory
        prompt_file = Path(__file__).parent / 'system_prompt.txt'
        if prompt_file.exists():
            base_prompt = prompt_file.read_text(encoding='utf-8')
            # Replace with lean prompt if it's the old format
            if 'database_fields' in base_prompt:
                return get_lean_fallback_prompt()
            return base_prompt
        
        # Fallback to lean prompt
        logger.warning("system_prompt.txt not found, using lean fallback prompt")
        return get_lean_fallback_prompt()
        
    except Exception as e:
        logger.error(f"Failed to load system prompt: {e}")
        return get_lean_fallback_prompt()


def get_lean_fallback_prompt() -> str:
    """Get the lean system prompt as fallback."""
    return """You are a bilingual (JP/EN) Tokyo real estate investment analyst specializing in undervalued properties for purchase and resale (NOT rental yield).

TASK: Analyze the provided property with context and return ONLY a JSON object with the exact keys specified below.

REQUIRED OUTPUT FORMAT:
{
  "property_id": "string",
  "base_score": integer (must match the provided base_score exactly),
  "final_score": integer (your adjusted score 0-100),
  "verdict": "BUY_CANDIDATE" | "WATCH" | "REJECT",
  "upside": [3 strings, max 60 chars each],
  "risks": [3 strings, max 60 chars each], 
  "justification": "string max 600 chars"
}

CRITICAL RULES:
- Return ONLY the JSON object, no other text
- base_score MUST exactly match the provided value
- final_score is your judgment (can differ from base_score)
- All fields are required, no additional properties allowed
- Focus on resale potential, not rental yield
- Be concise: upside/risks ≤60 chars, justification ≤600 chars"""

def get_snapshots_context(date_str: str, bucket: str) -> Dict[str, Any]:
    """
    Get market context from snapshot files for lean prompt.
    
    Args:
        date_str: Processing date string
        bucket: S3 bucket name
        
    Returns:
        Dictionary with global and ward medians
    """
    context = {}
    
    try:
        # Load global snapshot
        global_key = "snapshots/current/global.json"
        response = s3_client.get_object(Bucket=bucket, Key=global_key)
        global_data = json.loads(response['Body'].read().decode('utf-8'))
        
        context['global'] = {
            'median_ppm2': global_data.get('median_price_per_sqm', 0),
            'active_properties': global_data.get('total_properties', 0),
            'price_change_7d': global_data.get('price_change_7d_pct', 0)
        }
        
    except s3_client.exceptions.NoSuchKey:
        logger.warning(f"Global snapshot not found at {global_key}, using defaults")
        context['global'] = {'median_ppm2': 650000, 'active_properties': 0, 'price_change_7d': 0}
    except Exception as e:
        logger.warning(f"Failed to load global snapshot: {e}, using defaults")
        context['global'] = {'median_ppm2': 650000, 'active_properties': 0, 'price_change_7d': 0}
    
    return context


def load_candidate_properties(bucket: str, date_str: str) -> List[Dict[str, Any]]:
    """
    Load only candidate properties from processed data.
    
    Args:
        bucket: S3 bucket name
        date_str: Processing date string
        
    Returns:
        List of candidate properties only
    """
    try:
        # Load processed listings JSONL
        jsonl_key = f"clean/{date_str}/listings.jsonl"
        response = s3_client.get_object(Bucket=bucket, Key=jsonl_key)
        content = response['Body'].read().decode('utf-8')
        
        candidates = []
        total_properties = 0
        
        for line in content.strip().split('\n'):
            if line.strip():
                total_properties += 1
                property_data = json.loads(line)
                
                # Only process candidates
                if property_data.get('is_candidate', False):
                    candidates.append(property_data)
        
        logger.info(f"Filtered {len(candidates)} candidates from {total_properties} total properties")
        return candidates
        
    except s3_client.exceptions.NoSuchKey:
        logger.error(f"Candidate properties file not found: s3://{bucket}/{jsonl_key}")
        return []
    except Exception as e:
        logger.error(f"Failed to load candidate properties from s3://{bucket}/{jsonl_key}: {e}")
        raise


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lean v1.3 Lambda handler - only process candidate properties.
    
    Args:
        event: Lambda event containing processed data from ETL step
        context: Lambda context
        
    Returns:
        Dict containing prompt payload location and metadata
    """
    try:
        date_str = event.get('date')
        if get_config:
            bucket = event.get('bucket', get_config().get_str('OUTPUT_BUCKET'))
        else:
            bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        
        logger.info(f"Building lean prompts for candidates on {date_str}")
        
        # Get market context from snapshots
        market_context = get_snapshots_context(date_str, bucket)
        
        # Load only candidate properties
        candidates = event.get('candidates', [])
        if not candidates:
            candidates = load_candidate_properties(bucket, date_str)
        
        if not candidates:
            logger.warning("No candidate properties found - returning empty batch")
            return {
                'statusCode': 200,
                'date': date_str,
                'bucket': bucket,
                'prompt_key': None,
                'candidates_count': 0,
                'batch_requests_count': 0
            }
        
        logger.info(f"Processing {len(candidates)} candidate properties")
        
        # Build lean batch requests for candidates only
        batch_requests = build_lean_batch_requests(candidates, date_str, bucket, market_context)
        
        # Save batch requests as JSONL to S3
        prompt_key = f"ai/prompts/{date_str}/batch_requests.jsonl"
        save_batch_requests_to_s3(batch_requests, bucket, prompt_key)
        
        logger.info(f"Successfully built {len(batch_requests)} lean prompts for candidates")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'prompt_key': prompt_key,
            'candidates_count': len(candidates),
            'batch_requests_count': len(batch_requests),
            'total_images': sum(len(limit_images_to_three(candidate.get('interior_photos', []))) for candidate in candidates)
        }
        
    except Exception as e:
        logger.error(f"Lean prompt building failed: {e}")
        raise


def build_lean_batch_requests(candidates: List[Dict[str, Any]], date_str: str, 
                            bucket: str, market_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build lean batch requests for candidate properties only.
    
    Args:
        candidates: List of candidate property dictionaries
        date_str: Processing date string
        bucket: S3 bucket name
        market_context: Market context from snapshots
        
    Returns:
        List of lean batch request dictionaries
    """
    batch_requests = []
    all_properties = candidates  # For finding comparables
    
    # Load lean system prompt
    system_prompt = load_lean_system_prompt()
    
    # Initialize comparables filter if available
    max_comps = 8  # Default value
    if get_config:
        max_comps = get_config().get_int('MAX_COMPARABLES', 8)
    comp_filter = ComparablesFilter(max_comparables=max_comps) if ComparablesFilter else None
    
    for candidate in candidates:
        try:
            # Build lean prompt text for this candidate
            lean_prompt_text = build_lean_prompt(
                candidate, all_properties, market_context, bucket, comp_filter
            )
            
            # Build the complete message content (text + images)
            user_message_content = []
            
            # Add the main text content
            user_message_content.append({
                "type": "text",
                "text": lean_prompt_text
            })
            
            # Add up to 3 images
            images = limit_images_to_three(candidate.get('interior_photos', []))
            for img_url in images:
                data_url = get_image_as_base64_data_url(img_url, bucket)
                if data_url:
                    user_message_content.append({
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "low"}
                    })
            
            # Create batch request
            batch_request = {
                "custom_id": f"lean-analysis-{date_str}-{candidate.get('id', 'unknown')}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "o3",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message_content}
                    ],
                    "max_completion_tokens": 1000  # Reduced for lean output
                }
            }
            
            batch_requests.append(batch_request)
            
        except Exception as e:
            logger.error(f"Failed to build prompt for candidate {candidate.get('id', 'unknown')}: {e}")
            continue
    
    return batch_requests


def build_lean_prompt(candidate: Dict[str, Any], all_properties: List[Dict[str, Any]], 
                     market_context: Dict[str, Any], bucket: str, 
                     comp_filter: Optional[object]) -> str:
    """
    Build lean prompt content for a candidate property following structured format.
    
    Args:
        candidate: Candidate property data
        all_properties: All properties for finding comparables
        market_context: Market context from snapshots
        bucket: S3 bucket name
        comp_filter: Comparables filter instance
        
    Returns:
        Structured lean prompt string
    """
    prompt_sections = []
    
    # GLOBAL section
    global_ctx = market_context.get('global', {})
    global_text = f"MedianPPM2={global_ctx.get('median_ppm2', 0):.0f}; Active={global_ctx.get('active_properties', 0)}"
    if global_ctx.get('price_change_7d', 0) != 0:
        global_text += f"; 7dDelta={global_ctx.get('price_change_7d', 0):+.1f}%"
    
    prompt_sections.append(f"GLOBAL:\n{global_text}")
    
    # WARD section
    ward = candidate.get('ward', 'Unknown')
    ward_median = candidate.get('ward_median_price_per_sqm', global_ctx.get('median_ppm2', 0))
    ward_inventory = candidate.get('ward_inventory_count', 0)
    
    prompt_sections.append(f"WARD:\nWard={ward}; MedianPPM2={ward_median:.0f}; Inventory={ward_inventory}")
    
    # COMPARABLES section
    max_comps = 8
    if comp_filter:
        try:
            comparables = comp_filter.find_comparables(candidate, all_properties)
            comp_text = format_comparables_lean(comparables, max_comps)
        except Exception as e:
            logger.warning(f"Failed to get comparables: {e}")
            comp_text = "No comparable data available"
    else:
        comp_text = "Comparables module not available"
    
    prompt_sections.append(f"COMPARABLES:\n{comp_text}")
    
    # PROPERTY section
    property_json = extract_property_essentials(candidate)
    prompt_sections.append(f"PROPERTY:\n{json.dumps(property_json, ensure_ascii=False)}")
    
    # VISION section (≤80 tokens initially)
    vision_text = generate_vision_summary_stub(candidate, bucket, max_tokens=80) if generate_vision_summary else "Vision analysis not available"
    prompt_sections.append(f"VISION:\n{vision_text}")
    
    # TASK section
    prompt_sections.append("TASK:\nReturn ONLY JSON with keys: property_id, base_score, final_score, verdict, upside[3], risks[3], justification (≤600 chars).")
    
    # Assemble full prompt
    full_prompt = "\n\n".join(prompt_sections)
    
    # Token control logic
    estimated_tokens = estimate_token_count_from_text(full_prompt)
    
    if estimated_tokens > 1200:
        logger.warning(f"Prompt estimated at {estimated_tokens} tokens, applying token controls")
        
        # First try: reduce comparables to 6
        if comp_filter:
            try:
                comparables = comp_filter.find_comparables(candidate, all_properties)
                comp_text = format_comparables_lean(comparables, 6)  # Reduced to 6
                prompt_sections[2] = f"COMPARABLES:\n{comp_text}"
                full_prompt = "\n\n".join(prompt_sections)
                estimated_tokens = estimate_token_count_from_text(full_prompt)
            except Exception:
                pass
        
        # If still too long, truncate vision summary to 60 tokens
        if estimated_tokens > 1200:
            vision_text = generate_vision_summary_stub(candidate, bucket, max_tokens=60) if generate_vision_summary else "Vision analysis not available"
            prompt_sections[4] = f"VISION:\n{vision_text}"
            full_prompt = "\n\n".join(prompt_sections)
            estimated_tokens = estimate_token_count_from_text(full_prompt)
            logger.info(f"Applied vision truncation, final estimated tokens: {estimated_tokens}")
    
    return full_prompt


def format_comparables_lean(comparables: List[object], max_comps: int = 8) -> str:
    """Format comparables in lean table format with configurable max count."""
    if not comparables:
        return "No comparables found"
    
    lines = ["id | ppm2 | size | age | floor"]
    for comp in comparables[:max_comps]:  # Cap at max_comps
        floor_str = str(comp.floor) if hasattr(comp, 'floor') and comp.floor else "?"
        line = f"{comp.id} | {comp.price_per_sqm:.0f} | {comp.size_sqm:.0f} | {comp.age_years} | {floor_str}"
        lines.append(line)
    
    return "\n".join(lines)


def extract_property_essentials(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Extract essential property data for lean prompt."""
    return {
        'id': candidate.get('id', 'unknown'),
        'ward': candidate.get('ward', 'Unknown'),
        'price': candidate.get('price', 0),
        'price_per_sqm': candidate.get('price_per_sqm', 0),
        'size_m2': candidate.get('size_sqm', 0),
        'building_age_years': candidate.get('building_age_years', 0),
        'ward_discount_pct': candidate.get('ward_discount_pct', 0),
        'base_score': candidate.get('base_score', 0),
        'comps_count': candidate.get('num_comparables', 0)
    }


def generate_vision_summary_stub(candidate: Dict[str, Any], bucket: str, max_tokens: int = 80) -> str:
    """Generate a brief vision summary for lean prompt with token limit."""
    if generate_vision_summary:
        try:
            return generate_vision_summary(candidate, bucket, max_tokens=max_tokens)
        except:
            pass
    
    # Fallback stub analysis
    images = candidate.get('interior_photos', [])
    age = candidate.get('building_age_years', 30)
    
    if not images:
        summary = "No images available for condition assessment"
    elif age <= 10:
        summary = "Modern property with recent construction, likely good condition"
    elif age <= 25:
        summary = "Mature property, condition varies, renovation potential exists"
    else:
        summary = "Older property, expect maintenance needs, renovation likely required"
    
    # Simple token truncation (approximately 4 chars per token)
    max_chars = max_tokens * 4
    if len(summary) > max_chars:
        summary = summary[:max_chars-3] + "..."
    
    return summary


def limit_images_to_three(image_urls: List[str]) -> List[str]:
    """Limit images to first 3 for lean prompt."""
    return image_urls[:3]


def estimate_token_count(prompt_content: List[Dict[str, Any]]) -> int:
    """Rough token count estimation for prompt content."""
    total_chars = 0
    
    for item in prompt_content:
        if item.get('type') == 'text':
            total_chars += len(item.get('text', ''))
        elif item.get('type') == 'image_url':
            total_chars += 200  # Estimate for image tokens
    
    # Rough approximation: 4 chars per token
    return total_chars // 4


def estimate_token_count_from_text(text: str) -> int:
    """Rough token count estimation for text content."""
    # Rough approximation: 4 chars per token
    return len(text) // 4


def save_batch_requests_to_s3(batch_requests: List[Dict[str, Any]], bucket: str, key: str) -> None:
    """
    Save batch requests as JSONL to S3.
    
    Args:
        batch_requests: List of batch request dictionaries
        bucket: S3 bucket name
        key: S3 key for saving
    """
    try:
        # Convert to JSONL format (one JSON object per line)
        jsonl_lines = []
        for request in batch_requests:
            jsonl_lines.append(json.dumps(request, ensure_ascii=False))
        
        content = '\n'.join(jsonl_lines)
        
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType='application/x-ndjson'
        )
        
        logger.info(f"Saved {len(batch_requests)} lean batch requests to s3://{bucket}/{key}")
        
    except Exception as e:
        logger.error(f"Failed to save batch requests to S3: {e}")
        raise


def get_image_as_base64_data_url(s3_url: str, bucket: str) -> str:
    """
    Download S3 image and convert to base64 data URL for OpenAI.
    
    Args:
        s3_url: S3 URL (s3://bucket/key format)
        bucket: S3 bucket name
        
    Returns:
        Base64 data URL string or empty string if failed
    """
    try:
        # Extract key from S3 URL
        parsed = urlparse(s3_url)
        if parsed.scheme != 's3':
            logger.warning(f"Invalid S3 URL format: {s3_url}")
            return ""
        
        key = parsed.path.lstrip('/')
        
        # Download image from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        try:
            image_data = response['Body'].read()
        finally:
            response['Body'].close()
        
        # Determine MIME type from file extension
        file_ext = key.lower().split('.')[-1]
        mime_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        mime_type = mime_type_map.get(file_ext, 'image/jpeg')
        
        # Convert to base64
        base64_data = base64.b64encode(image_data).decode('utf-8')
        
        # Create data URL
        data_url = f"data:{mime_type};base64,{base64_data}"
        
        return data_url
        
    except Exception as e:
        logger.warning(f"Failed to convert S3 image to base64 data URL for {s3_url}: {e}")
        return ""


if __name__ == "__main__":
    # For local testing  
    test_event = {
        'date': '2025-07-22',
        'bucket': 'tokyo-real-estate-ai-data'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2, default=str))