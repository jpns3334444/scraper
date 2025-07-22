"""
Tests for Lean v1.3 prompt assembly functionality.

Tests cover:
- Prompt structure and key components
- Comparable limits and formatting
- Image prioritization logic  
- Text truncation for token control
- Input validation and error handling
"""

import json
import pytest
from pathlib import Path


@pytest.fixture
def sample_properties():
    """Load sample properties from fixtures."""
    fixture_path = Path(__file__).parent / 'fixtures' / 'sample_properties.json'
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def mock_s3_client():
    """Mock S3 client for image operations."""
    with patch('ai_infra.lambda.prompt_builder.app.s3_client') as mock_client:
        # Mock successful image download
        mock_client.get_object.return_value = {
            'Body': Mock(read=lambda: b'fake_image_data')
        }
        yield mock_client


class TestPromptStructure:
    """Test prompt structure and content."""
    
    @patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url')
    def test_individual_listing_content_structure(self, mock_image_func, sample_properties, mock_s3_client):
        """Test individual listing content has correct structure."""
        mock_image_func.return_value = "data:image/jpeg;base64,fake_data"
        
        listing = sample_properties[0]  # PROP_001
        listing['interior_photos'] = [
            's3://test-bucket/images/living_room.jpg',
            's3://test-bucket/images/bedroom.jpg'
        ]
        
        content = build_individual_listing_content(listing, '2025-07-22', 'test-bucket')
        
        # Should be a list of content items
        assert isinstance(content, list)
        assert len(content) > 0
        
        # Check for required sections
        content_text = ' '.join([
            item['text'] for item in content 
            if item.get('type') == 'text'
        ])
        
        assert "Analyze this individual real estate listing" in content_text
        assert "LISTING DATA" in content_text
        assert "property images" in content_text
        assert "return the full JSON object" in content_text
        
        # Check for image content items
        image_items = [item for item in content if item.get('type') == 'image_url']
        assert len(image_items) <= 3  # Should respect image limit
    
    def test_system_prompt_loading(self):
        """Test system prompt loading functionality."""
        with patch('ai_infra.lambda.prompt_builder.app.Path.exists', return_value=False):
            # Should fall back to inline prompt
            prompt = load_system_prompt()
            assert isinstance(prompt, str)
            assert len(prompt) > 0
            assert "real estate" in prompt.lower()
    
    def test_batch_request_structure(self, sample_properties):
        """Test batch request structure."""
        with patch('ai_infra.lambda.prompt_builder.app.load_system_prompt') as mock_prompt:
            mock_prompt.return_value = "Test system prompt"
            with patch('ai_infra.lambda.prompt_builder.app.build_individual_listing_content') as mock_content:
                mock_content.return_value = [{"type": "text", "text": "Test content"}]
                
                requests = build_batch_requests(
                    sample_properties[:2], 
                    '2025-07-22', 
                    'test-bucket',
                    {}
                )
                
                assert isinstance(requests, list)
                assert len(requests) == 2
                
                for request in requests:
                    assert 'custom_id' in request
                    assert 'method' in request
                    assert 'url' in request
                    assert 'body' in request
                    
                    # Check body structure
                    body = request['body']
                    assert 'model' in body
                    assert 'messages' in body
                    assert 'max_completion_tokens' in body
                    
                    # Check messages structure
                    messages = body['messages']
                    assert len(messages) >= 2  # System + user
                    assert messages[0]['role'] == 'system'
                    assert messages[1]['role'] == 'user'


class TestImageHandling:
    """Test image prioritization and handling."""
    
    def test_image_prioritization_empty_list(self):
        """Test image prioritization with empty list."""
        result = prioritize_images([])
        assert result == []
    
    def test_image_prioritization_categorization(self):
        """Test image prioritization categorizes correctly."""
        image_urls = [
            's3://bucket/exterior_view.jpg',
            's3://bucket/living_room.jpg',  
            's3://bucket/kitchen.jpg',
            's3://bucket/bedroom_1.jpg',
            's3://bucket/bathroom.jpg',
            's3://bucket/other_photo.jpg'
        ]
        
        prioritized = prioritize_images(image_urls)
        
        # Should return all images (under limit)
        assert len(prioritized) == len(image_urls)
        
        # Exterior should be first (based on prioritization logic)
        assert 'exterior' in prioritized[0]
    
    def test_image_prioritization_limits(self):
        """Test image prioritization respects category limits."""
        # Create many images of each type
        image_urls = []
        
        # Add many exterior images (should be limited to 2)
        for i in range(5):
            image_urls.append(f's3://bucket/exterior_{i}.jpg')
        
        # Add many living space images (should be limited to 8)
        for i in range(12):
            image_urls.append(f's3://bucket/living_room_{i}.jpg')
        
        # Add many kitchen/bath images (should be limited to 4)
        for i in range(8):
            image_urls.append(f's3://bucket/kitchen_{i}.jpg')
        
        # Add many other images (should be limited to 6)
        for i in range(10):
            image_urls.append(f's3://bucket/other_{i}.jpg')
        
        prioritized = prioritize_images(image_urls)
        
        # Should respect total limit of 20
        assert len(prioritized) <= 20
        
        # Count by category
        exterior_count = sum(1 for url in prioritized if 'exterior' in url)
        living_count = sum(1 for url in prioritized if 'living_room' in url)
        kitchen_count = sum(1 for url in prioritized if 'kitchen' in url)
        other_count = sum(1 for url in prioritized if 'other' in url)
        
        assert exterior_count <= 2
        assert living_count <= 8
        assert kitchen_count <= 4
        assert other_count <= 6
    
    @patch('ai_infra.lambda.prompt_builder.app.s3_client')
    def test_image_base64_conversion(self, mock_s3_client):
        """Test image to base64 conversion."""
        from ai_infra.lambda.prompt_builder.app import get_image_as_base64_data_url
        
        # Mock successful S3 response
        mock_s3_client.get_object.return_value = {
            'Body': Mock(read=lambda: b'fake_image_data')
        }
        
        result = get_image_as_base64_data_url(
            's3://test-bucket/test_image.jpg', 
            'test-bucket'
        )
        
        assert result.startswith('data:image/jpeg;base64,')
        assert len(result) > 30  # Should have base64 content
    
    @patch('ai_infra.lambda.prompt_builder.app.s3_client')
    def test_image_conversion_error_handling(self, mock_s3_client):
        """Test image conversion error handling."""
        from ai_infra.lambda.prompt_builder.app import get_image_as_base64_data_url
        
        # Mock S3 error
        mock_s3_client.get_object.side_effect = Exception("S3 error")
        
        result = get_image_as_base64_data_url(
            's3://test-bucket/missing_image.jpg', 
            'test-bucket'
        )
        
        assert result == ""  # Should return empty string on error


class TestPromptTokenEstimation:
    """Test prompt size and token estimation."""
    
    @patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url')
    def test_prompt_size_reasonable(self, mock_image_func, sample_properties):
        """Test that prompt size is reasonable (target ≤1200 tokens)."""
        mock_image_func.return_value = "data:image/jpeg;base64," + "x" * 1000  # Small fake image
        
        listing = sample_properties[0]
        listing['interior_photos'] = [
            's3://bucket/img1.jpg',
            's3://bucket/img2.jpg',
            's3://bucket/img3.jpg'
        ]
        
        content = build_individual_listing_content(listing, '2025-07-22', 'test-bucket')
        
        # Calculate text content size (rough token estimation: ~4 chars per token)
        text_content = ' '.join([
            item.get('text', '') for item in content 
            if item.get('type') == 'text'
        ])
        
        estimated_tokens = len(text_content) / 4
        
        # Should be reasonable size (allowing for images which have different token cost)
        assert estimated_tokens < 2000  # Conservative upper bound
        
        # Should have limited number of images to control token usage
        image_count = sum(1 for item in content if item.get('type') == 'image_url')
        assert image_count <= 3
    
    def test_listing_data_truncation(self, sample_properties):
        """Test handling of very large listing data."""
        # Create a property with very large text fields
        large_listing = sample_properties[0].copy()
        large_listing['description'] = "Very long description. " * 1000  # Very long text
        large_listing['features'] = ["Feature " + str(i) for i in range(500)]  # Many features
        
        with patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url') as mock_image:
            mock_image.return_value = ""  # No images to focus on text
            
            content = build_individual_listing_content(large_listing, '2025-07-22', 'test-bucket')
            
            # Should still produce valid content without crashing
            assert isinstance(content, list)
            assert len(content) > 0
            
            # Text content should be manageable
            total_text_length = sum(
                len(item.get('text', '')) for item in content 
                if item.get('type') == 'text'
            )
            
            # Should not be excessively long
            assert total_text_length < 50000  # Reasonable upper bound


class TestLeanModeCompliance:
    """Test compliance with Lean v1.3 specifications."""
    
    def test_comparables_limit(self, sample_properties):
        """Test that comparables are limited as per Lean spec."""
        listing = sample_properties[0].copy()
        
        # Add many comparables to test limiting
        listing['comparables'] = []
        for i in range(15):
            listing['comparables'].append({
                'id': f'COMP_{i}',
                'price_per_sqm': 900000 + i * 10000,
                'size_sqm': 60.0,
                'age_years': 10
            })
        
        with patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url') as mock_image:
            mock_image.return_value = ""
            
            content = build_individual_listing_content(listing, '2025-07-22', 'test-bucket')
            
            # Check that comparables text doesn't contain too many entries
            comparables_text = None
            for item in content:
                if item.get('type') == 'text' and 'comparables' in item.get('text', '').lower():
                    comparables_text = item['text']
                    break
            
            if comparables_text:
                # Count comparable entries (rough estimation)
                comp_lines = comparables_text.count('COMP_')
                assert comp_lines <= 8  # Should be limited
    
    def test_candidate_properties_only(self, sample_properties):
        """Test that only candidate properties generate prompts."""
        # This test assumes we're only processing pre-filtered candidates
        # The filtering should happen before prompt building
        
        listing = sample_properties[0]  # Should be a good candidate
        
        with patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url') as mock_image:
            mock_image.return_value = ""
            
            content = build_individual_listing_content(listing, '2025-07-22', 'test-bucket')
            
            # Should generate content for candidates
            assert len(content) > 0
            
            # Content should focus on investment analysis
            content_text = ' '.join([
                item.get('text', '') for item in content 
                if item.get('type') == 'text'
            ])
            
            assert 'analyze' in content_text.lower() or 'analysis' in content_text.lower()
    
    def test_minimal_prompt_structure(self, sample_properties):
        """Test prompt follows minimal Lean structure."""
        listing = sample_properties[0]
        listing['interior_photos'] = ['s3://bucket/img1.jpg']  # One image
        
        with patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url') as mock_image:
            mock_image.return_value = "data:image/jpeg;base64,fake"
            
            content = build_individual_listing_content(listing, '2025-07-22', 'test-bucket')
            
            # Should have expected sections
            has_listing_data = False
            has_images = False
            has_instruction = False
            
            for item in content:
                if item.get('type') == 'text':
                    text = item.get('text', '')
                    if 'LISTING DATA' in text:
                        has_listing_data = True
                    elif 'property images' in text:
                        has_images = True
                    elif 'JSON object' in text:
                        has_instruction = True
                elif item.get('type') == 'image_url':
                    has_images = True
            
            assert has_listing_data, "Should include listing data section"
            assert has_images, "Should include images section"  
            assert has_instruction, "Should include analysis instruction"


class TestErrorHandling:
    """Test error handling in prompt building."""
    
    def test_missing_listing_data(self):
        """Test handling of missing or minimal listing data."""
        minimal_listing = {'id': 'TEST_ID'}
        
        with patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url') as mock_image:
            mock_image.return_value = ""
            
            content = build_individual_listing_content(minimal_listing, '2025-07-22', 'test-bucket')
            
            # Should still produce valid content
            assert isinstance(content, list)
            assert len(content) > 0
    
    def test_invalid_image_urls(self, sample_properties):
        """Test handling of invalid image URLs."""
        listing = sample_properties[0].copy()
        listing['interior_photos'] = [
            'invalid://not-s3/image.jpg',
            's3://bucket/valid_image.jpg'
        ]
        
        with patch('ai_infra.lambda.prompt_builder.app.get_image_as_base64_data_url') as mock_image:
            def mock_image_conversion(url, bucket):
                if 'invalid' in url:
                    return ""  # Invalid URL returns empty
                return "data:image/jpeg;base64,fake"
            
            mock_image.side_effect = mock_image_conversion
            
            content = build_individual_listing_content(listing, '2025-07-22', 'test-bucket')
            
            # Should still work and include only valid images
            image_items = [item for item in content if item.get('type') == 'image_url']
            assert len(image_items) == 1  # Only valid image included


if __name__ == "__main__":
    pytest.main([__file__, "-v"])