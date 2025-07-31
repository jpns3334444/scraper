"""
Tests for Lean v1.3 evaluation schema validation.

Tests cover:
- Valid JSON passes schema validation
- Malformed JSON triggers retry/failure
- Required fields validation
- Field length constraints  
- Array size limits
- Schema loading and parsing
"""

import json
import pytest
from pathlib import Path
from jsonschema import validate, ValidationError


@pytest.fixture
def evaluation_schema():
    """Load evaluation schema from schemas directory."""
    schema_path = Path(__file__).parent.parent / 'schemas' / 'evaluation_min.json'
    with open(schema_path) as f:
        return json.load(f)


@pytest.fixture
def valid_llm_output():
    """Sample valid LLM output."""
    return {
        "upsides": [
            "Excellent location with 5-minute walk to station",
            "Recently renovated with modern fixtures and appliances",
            "Strong rental demand in this neighborhood"
        ],
        "risks": [
            "Building is 25 years old and may need maintenance",
            "Limited parking availability in the area"
        ],
        "justification": "Property offers strong value with recent renovations and prime location, though building age presents some maintenance risk."
    }


@pytest.fixture 
def invalid_llm_outputs():
    """Collection of invalid LLM outputs for testing."""
    return {
        "missing_required_field": {
            "upsides": ["Great location"],
            "risks": ["Some risk"]
            # Missing justification
        },
        "empty_upsides": {
            "upsides": [],  # Violates minItems: 1
            "risks": ["Some risk"],
            "justification": "Property has moderate potential but lacks clear advantages."
        },
        "too_many_upsides": {
            "upsides": [
                "Upside 1", "Upside 2", "Upside 3", "Upside 4"  # Violates maxItems: 3
            ],
            "risks": ["Some risk"],
            "justification": "Property has many advantages but some concerns remain."
        },
        "upside_too_short": {
            "upsides": ["Good"],  # Violates minLength: 10
            "risks": ["Building age concerns"],
            "justification": "Property shows promise despite some age-related maintenance needs."
        },
        "upside_too_long": {
            "upsides": ["This is an extremely long upside description that exceeds the maximum allowed length for upside descriptions in the schema and should be rejected during validation because it contains too many characters for the field." * 2],  # Violates maxLength: 200
            "risks": ["Some maintenance needed"],
            "justification": "Property has excellent features but requires careful consideration."
        },
        "justification_too_short": {
            "upsides": ["Excellent location and amenities"],
            "risks": ["Building age"],
            "justification": "Good value"  # Violates minLength: 50
        },
        "justification_too_long": {
            "upsides": ["Prime location with excellent transport links"],
            "risks": ["Higher maintenance costs due to building age"],
            "justification": "This property represents exceptional value in the current market with its prime location, excellent transport connectivity, recent renovations, and strong rental demand, though investors should consider the potential for higher maintenance costs and periodic capital improvements." * 2  # Violates maxLength: 300
        },
        "extra_fields": {
            "upsides": ["Great location and modern amenities"],
            "risks": ["Some building age concerns"],
            "justification": "Property offers solid investment potential with good location.",
            "extra_field": "This should not be allowed"  # Violates additionalProperties: false
        },
        "wrong_types": {
            "upsides": "Should be array not string",  # Wrong type
            "risks": ["Building maintenance needs"],
            "justification": "Property has mixed characteristics requiring careful evaluation."
        },
        "null_values": {
            "upsides": null,  # Null not allowed
            "risks": ["Maintenance concerns"],
            "justification": "Property requires careful investment consideration."
        }
    }


class TestSchemaLoading:
    """Test schema loading and structure."""
    
    def test_schema_loads_successfully(self, evaluation_schema):
        """Test that schema loads without errors."""
        assert isinstance(evaluation_schema, dict)
        assert '$schema' in evaluation_schema
        assert 'properties' in evaluation_schema
        assert 'required' in evaluation_schema
    
    def test_schema_has_required_properties(self, evaluation_schema):
        """Test schema defines required properties."""
        required_fields = evaluation_schema['required']
        assert 'upsides' in required_fields
        assert 'risks' in required_fields 
        assert 'justification' in required_fields
        
        properties = evaluation_schema['properties']
        assert 'upsides' in properties
        assert 'risks' in properties
        assert 'justification' in properties
    
    def test_schema_field_constraints(self, evaluation_schema):
        """Test schema has proper field constraints."""
        properties = evaluation_schema['properties']
        
        # Test upsides constraints
        upsides = properties['upsides']
        assert upsides['type'] == 'array'
        assert upsides['minItems'] == 1
        assert upsides['maxItems'] == 3
        assert upsides['items']['minLength'] == 10
        assert upsides['items']['maxLength'] == 200
        
        # Test risks constraints
        risks = properties['risks']
        assert risks['type'] == 'array'
        assert risks['minItems'] == 0
        assert risks['maxItems'] == 3
        assert risks['items']['minLength'] == 10
        assert risks['items']['maxLength'] == 200
        
        # Test justification constraints
        justification = properties['justification']
        assert justification['type'] == 'string'
        assert justification['minLength'] == 50
        assert justification['maxLength'] == 300
    
    def test_schema_disallows_additional_properties(self, evaluation_schema):
        """Test schema disallows additional properties."""
        assert evaluation_schema['additionalProperties'] == False


class TestValidLLMOutput:
    """Test validation of valid LLM outputs."""
    
    def test_valid_output_passes(self, evaluation_schema, valid_llm_output):
        """Test that valid LLM output passes validation."""
        # Should not raise any exception
        validate(instance=valid_llm_output, schema=evaluation_schema)
    
    def test_minimal_valid_output(self, evaluation_schema):
        """Test minimal valid output passes."""
        minimal_output = {
            "upsides": ["Property has good location and transport links"],
            "risks": [],  # Empty risks array is allowed (minItems: 0)
            "justification": "Property offers reasonable value in current market conditions."
        }
        
        validate(instance=minimal_output, schema=evaluation_schema)
    
    def test_maximal_valid_output(self, evaluation_schema):
        """Test output with maximum allowed items passes."""
        maximal_output = {
            "upsides": [
                "Excellent location with easy access to multiple stations and shopping",
                "Recently renovated with high-quality fixtures and modern appliances", 
                "Strong rental demand and good appreciation potential in this area"
            ],
            "risks": [
                "Building is approaching 30 years old and may require major maintenance",
                "Limited parking spaces could affect resale value in the future",
                "Market saturation with similar properties could impact rental rates"
            ],
            "justification": "This property represents solid investment potential with its prime location and recent renovations, though investors should factor in potential maintenance costs and market competition when making decisions."
        }
        
        validate(instance=maximal_output, schema=evaluation_schema)


class TestInvalidLLMOutput:
    """Test validation of invalid LLM outputs."""
    
    def test_missing_required_fields(self, evaluation_schema, invalid_llm_outputs):
        """Test that missing required fields trigger validation error."""
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['missing_required_field'], 
                schema=evaluation_schema
            )
    
    def test_empty_upsides_array(self, evaluation_schema, invalid_llm_outputs):
        """Test that empty upsides array fails validation."""
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['empty_upsides'],
                schema=evaluation_schema
            )
    
    def test_too_many_upsides(self, evaluation_schema, invalid_llm_outputs):
        """Test that too many upsides fail validation."""
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['too_many_upsides'],
                schema=evaluation_schema
            )
    
    def test_upside_length_constraints(self, evaluation_schema, invalid_llm_outputs):
        """Test upside length constraints."""
        # Too short
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['upside_too_short'],
                schema=evaluation_schema
            )
        
        # Too long
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['upside_too_long'],
                schema=evaluation_schema
            )
    
    def test_justification_length_constraints(self, evaluation_schema, invalid_llm_outputs):
        """Test justification length constraints."""
        # Too short
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['justification_too_short'],
                schema=evaluation_schema
            )
        
        # Too long  
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['justification_too_long'],
                schema=evaluation_schema
            )
    
    def test_additional_properties_rejected(self, evaluation_schema, invalid_llm_outputs):
        """Test that additional properties are rejected."""
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['extra_fields'],
                schema=evaluation_schema
            )
    
    def test_wrong_field_types(self, evaluation_schema, invalid_llm_outputs):
        """Test that wrong field types are rejected."""
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['wrong_types'],
                schema=evaluation_schema
            )
    
    def test_null_values_rejected(self, evaluation_schema, invalid_llm_outputs):
        """Test that null values are rejected."""
        with pytest.raises(ValidationError):
            validate(
                instance=invalid_llm_outputs['null_values'],
                schema=evaluation_schema
            )


class TestRealWorldScenarios:
    """Test real-world LLM output scenarios."""
    
    def test_typical_chatgpt_output(self, evaluation_schema):
        """Test typical ChatGPT/Claude output format."""
        typical_output = {
            "upsides": [
                "Prime Shibuya location with 3-minute walk to station provides excellent transport connectivity",
                "Recent full renovation includes modern kitchen, updated bathrooms, and new flooring throughout"
            ],
            "risks": [
                "Building constructed in 1995 may require significant maintenance within next 5-10 years",
                "High monthly management fees at ¥35,000 reduce net rental yield"
            ],
            "justification": "Strong investment opportunity with premium location offsetting building age concerns. Expected 4.2% gross yield with good appreciation potential."
        }
        
        validate(instance=typical_output, schema=evaluation_schema)
    
    def test_edge_case_lengths(self, evaluation_schema):
        """Test edge cases for string lengths."""
        # Exactly at boundaries
        boundary_output = {
            "upsides": [
                "1234567890"  # Exactly 10 characters (minimum)
            ],
            "risks": [
                "1234567890" + "x" * 190  # Exactly 200 characters (maximum)
            ],
            "justification": "12345678901234567890123456789012345678901234567890"  # Exactly 50 chars (minimum)
        }
        
        validate(instance=boundary_output, schema=evaluation_schema)
    
    def test_japanese_characters(self, evaluation_schema):
        """Test validation with Japanese characters."""
        japanese_output = {
            "upsides": [
                "駅から徒歩3分の好立地で交通の便が非常に良い物件です",
                "最近リノベーションされており、設備が新しく魅力的"
            ],
            "risks": [
                "築年数が古く、将来的に大規模修繕が必要になる可能性"
            ],
            "justification": "立地の良さとリノベーション済みという点で投資価値が高いが、築年数による修繕リスクを考慮する必要がある。"
        }
        
        validate(instance=japanese_output, schema=evaluation_schema)
    
    def test_mixed_language_output(self, evaluation_schema):
        """Test validation with mixed Japanese/English content."""
        mixed_output = {
            "upsides": [
                "Prime location in Shibuya with 駅から徒歩5分 access",
                "Newly renovated 2LDK with modern facilities and 南向き windows"
            ],
            "risks": [
                "Building age of 20 years may require maintenance soon"
            ],
            "justification": "Excellent investment potential combining prime Shibuya location with modern amenities, though building age requires consideration for future maintenance costs."
        }
        
        validate(instance=mixed_output, schema=evaluation_schema)


class TestValidationHelpers:
    """Test validation helper functions."""
    
    def test_validation_error_details(self, evaluation_schema):
        """Test that validation errors provide useful details."""
        invalid_output = {
            "upsides": ["Too short"],  # Violates minLength
            "risks": [],
            "justification": "Also too short"  # Violates minLength
        }
        
        try:
            validate(instance=invalid_output, schema=evaluation_schema)
            assert False, "Should have raised ValidationError"
        except ValidationError as e:
            # Should provide details about what failed
            assert 'minLength' in str(e) or 'too short' in str(e).lower()
            assert hasattr(e, 'path') or hasattr(e, 'absolute_path')
    
    def test_multiple_validation_errors(self, evaluation_schema):
        """Test handling multiple validation errors."""
        # Note: jsonschema typically stops at first error, but we can test different invalid structures
        severely_invalid = {
            "upsides": [],  # Empty array
            "risks": ["1", "2", "3", "4"],  # Too many items
            # Missing justification entirely
        }
        
        with pytest.raises(ValidationError):
            validate(instance=severely_invalid, schema=evaluation_schema)
    
    def test_schema_validation_performance(self, evaluation_schema, valid_llm_output):
        """Test that schema validation is performant."""
        import time
        
        start_time = time.time()
        
        # Validate the same output multiple times
        for _ in range(100):
            validate(instance=valid_llm_output, schema=evaluation_schema)
        
        elapsed_time = time.time() - start_time
        
        # Should be very fast (less than 1 second for 100 validations)
        assert elapsed_time < 1.0


class TestSchemaEvolution:
    """Test schema evolution and backward compatibility."""
    
    def test_schema_version_compatibility(self, evaluation_schema):
        """Test schema version and compatibility markers."""
        # Should use JSON Schema draft-07
        assert evaluation_schema['$schema'] == 'http://json-schema.org/draft-07/schema#'
        
        # Should have title and description
        assert 'title' in evaluation_schema
        assert 'Lean v1.3' in evaluation_schema['title']
        assert 'description' in evaluation_schema
    
    def test_future_schema_extensibility(self, evaluation_schema):
        """Test that schema structure allows for future extensions."""
        # Current schema should be strict (additionalProperties: false)
        # This is intentional for Lean v1.3 to enforce minimal output
        assert evaluation_schema['additionalProperties'] == False
        
        # But structure should be clear for future modifications
        assert isinstance(evaluation_schema['properties'], dict)
        assert isinstance(evaluation_schema['required'], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])