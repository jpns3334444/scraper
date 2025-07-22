"""
Schema validation utilities for Lean v1.3 LLM output.

This module provides strict JSON schema validation for LLM responses
using the evaluation_min.json schema.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import jsonschema
    from jsonschema import Draft7Validator
except ImportError:
    jsonschema = None
    Draft7Validator = None

logger = logging.getLogger(__name__)

# Load schema on module import
SCHEMA_PATH = Path(__file__).parent / 'evaluation_min.json'
EVALUATION_SCHEMA = None

if SCHEMA_PATH.exists():
    try:
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            EVALUATION_SCHEMA = json.load(f)
        logger.info("Loaded evaluation_min.json schema")
    except Exception as e:
        logger.error(f"Failed to load evaluation schema: {e}")
        EVALUATION_SCHEMA = None
else:
    logger.warning("evaluation_min.json schema file not found")


def validate_llm_output(llm_response: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validate LLM output against the evaluation_min.json schema.
    
    Args:
        llm_response: Raw LLM response string
        
    Returns:
        Tuple of (is_valid, parsed_data, error_message)
        - is_valid: Boolean indicating if validation passed
        - parsed_data: Parsed JSON data if valid, None otherwise  
        - error_message: Error description if validation failed
    """
    if not jsonschema or not EVALUATION_SCHEMA:
        logger.error("jsonschema not available or schema not loaded")
        return False, None, "Schema validation not available"
    
    # Try to extract and parse JSON from potentially messy response
    json_str = extract_json_from_response(llm_response)
    if not json_str:
        # Fallback to direct parsing
        json_str = llm_response.strip()
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON: {e}"
        logger.warning(error_msg)
        return False, None, error_msg
    
    # Validate against schema
    try:
        validator = Draft7Validator(EVALUATION_SCHEMA)
        validator.validate(data)
        
        # Additional business logic validation
        validation_error = _validate_business_rules(data)
        if validation_error:
            return False, None, validation_error
        
        logger.info(f"Successfully validated LLM output for property {data.get('property_id', 'unknown')}")
        return True, data, None
        
    except jsonschema.ValidationError as e:
        error_msg = f"Schema validation failed: {e.message} at {'.'.join(str(p) for p in e.path)}"
        logger.warning(error_msg)
        return False, None, error_msg
    except Exception as e:
        error_msg = f"Unexpected validation error: {e}"
        logger.error(error_msg)
        return False, None, error_msg


def _validate_business_rules(data: Dict[str, Any]) -> Optional[str]:
    """
    Apply additional business logic validation beyond schema.
    
    Args:
        data: Parsed LLM output data
        
    Returns:
        Error message if validation fails, None if passes
    """
    # Check that upsides/risks arrays have expected items with content
    upsides = data.get('upsides', [])
    risks = data.get('risks', [])
    
    # Upsides must have 1-3 items (schema requirement)
    if len(upsides) < 1 or len(upsides) > 3:
        return f"upsides must have 1-3 items, got {len(upsides)}"
    
    # Risks can have 0-3 items (schema requirement)  
    if len(risks) > 3:
        return f"risks must have 0-3 items, got {len(risks)}"
    
    # Check that all upsides items have content
    for i, item in enumerate(upsides):
        if not item or not item.strip():
            return f"upsides[{i}] is empty or whitespace only"
        if len(item.strip()) < 10:
            return f"upsides[{i}] too short (minimum 10 characters)"
    
    # Check that all risks items have content
    for i, item in enumerate(risks):
        if not item or not item.strip():
            return f"risks[{i}] is empty or whitespace only"
        if len(item.strip()) < 10:
            return f"risks[{i}] too short (minimum 10 characters)"
    
    # Check justification has content
    justification = data.get('justification', '')
    if not justification or not justification.strip():
        return "justification is empty or whitespace only"
    
    # Check justification length meets schema requirements
    if len(justification.strip()) < 50:
        return f"justification too short (minimum 50 characters, got {len(justification.strip())})"
    
    return None


def create_fallback_evaluation(property_id: str, base_score: int, 
                             final_score: int, verdict: str = "REJECT") -> Dict[str, Any]:
    """
    Create a fallback evaluation when LLM output fails validation.
    
    Args:
        property_id: Property identifier
        base_score: Deterministic base score
        final_score: Final score after adjustments
        verdict: Investment verdict
        
    Returns:
        Valid evaluation dictionary matching evaluation_min.json schema
    """
    return {
        "upsides": [
            "Property meets basic investment criteria",
            "Location has acceptable market fundamentals", 
            "Price analysis completed successfully"
        ],
        "risks": [
            "LLM analysis failed - limited qualitative insights",
            "Market conditions require manual verification",
            "Property details need additional validation"
        ],
        "justification": "Automated fallback evaluation due to LLM validation failure. Scores computed deterministically but qualitative analysis unavailable. Recommend manual review before investment decision."
    }


def truncate_response_for_logging(response: str, max_length: int = 1500) -> str:
    """
    Truncate LLM response for logging purposes.
    
    Args:
        response: Full LLM response
        max_length: Maximum characters to keep
        
    Returns:
        Truncated response with indicator if truncated
    """
    if len(response) <= max_length:
        return response
    
    return response[:max_length] + f"... [truncated, original length: {len(response)}]"


def extract_json_from_response(response: str) -> Optional[str]:
    """
    Extract JSON from LLM response that might contain extra text.
    
    Args:
        response: Raw LLM response
        
    Returns:
        Extracted JSON string or None if not found
    """
    response = response.strip()
    
    # Look for JSON object boundaries
    start_idx = response.find('{')
    if start_idx == -1:
        return None
    
    # Find matching closing brace
    brace_count = 0
    end_idx = -1
    
    for i in range(start_idx, len(response)):
        if response[i] == '{':
            brace_count += 1
        elif response[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i
                break
    
    if end_idx == -1:
        return None
    
    return response[start_idx:end_idx + 1]


# For backward compatibility
def validate_evaluation(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Legacy validation function for backward compatibility.
    
    Args:
        data: Evaluation data dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not jsonschema or not EVALUATION_SCHEMA:
        return False, "Schema validation not available"
    
    try:
        validator = Draft7Validator(EVALUATION_SCHEMA)
        validator.validate(data)
        
        validation_error = _validate_business_rules(data)
        if validation_error:
            return False, validation_error
        
        return True, None
        
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"
    except Exception as e:
        return False, f"Unexpected validation error: {e}"