"""
Tests for Prompt Builder Lambda function.
"""
import json
from unittest.mock import patch, Mock

import pytest
import boto3

# Import the prompt builder function
import sys
sys.path.append('/mnt/c/Users/azure/Desktop/scraper/lambda/prompt_builder')
from app import lambda_handler, sort_and_filter_listings, build_vision_prompt, generate_presigned_url


class TestPromptBuilder:
    """Test cases for Prompt Builder Lambda function."""
    
    def setup_method(self):
        """Set up test data."""
        self.sample_jsonl_data = [
            {
                'id': 'listing1',
                'headline': 'Spacious apartment',
                'price_yen': 25000000,
                'area_m2': 65.5,
                'price_per_m2': 381679.39,
                'age_years': 15,
                'walk_mins_station': 8.0,
                'ward': 'Shibuya',
                'interior_photos': [
                    's3://test-bucket/raw/2025-07-07/images/living_room.jpg',
                    's3://test-bucket/raw/2025-07-07/images/bedroom.jpg'
                ]
            },
            {
                'id': 'listing2',
                'headline': 'Cozy studio',
                'price_yen': 18000000,
                'area_m2': 35.2,
                'price_per_m2': 511363.64,
                'age_years': 10,
                'walk_mins_station': 5.0,
                'ward': 'Shibuya',
                'interior_photos': [
                    's3://test-bucket/raw/2025-07-07/images/interior_shot.jpg'
                ]
            },
            {
                'id': 'listing3',
                'headline': 'Family home',
                'price_yen': 45000000,
                'area_m2': 95.0,
                'price_per_m2': 473684.21,
                'age_years': 20,
                'walk_mins_station': 15.0,
                'ward': 'Setagaya',
                'interior_photos': []
            }
        ]
    
    def test_lambda_handler_success(self, mock_s3_client, environment_variables, sample_prompt_event):
        """Test successful prompt building."""
        # Set up JSONL data in S3
        jsonl_content = '\n'.join(json.dumps(item) for item in self.sample_jsonl_data)
        mock_s3_client.put_object(
            Bucket='test-bucket',
            Key='clean/2025-07-07/listings.jsonl',
            Body=jsonl_content.encode('utf-8')
        )
        
        # Mock presigned URL generation
        with patch('app.s3_client', mock_s3_client), \
             patch('app.generate_presigned_url', return_value='https://presigned-url.com/image.jpg'):
            
            result = lambda_handler(sample_prompt_event, None)
        
        assert result['statusCode'] == 200
        assert result['date'] == '2025-07-07'
        assert result['listings_count'] == 3
        assert result['total_images'] == 3  # 2 + 1 + 0
        
        # Verify prompt was saved to S3
        response = mock_s3_client.get_object(Bucket='test-bucket', Key=result['prompt_key'])
        prompt_content = json.loads(response['Body'].read().decode('utf-8'))
        
        assert prompt_content['model'] == 'gpt-4o'
        assert prompt_content['temperature'] == 0.2
        assert len(prompt_content['messages']) == 2
        assert prompt_content['messages'][0]['role'] == 'system'
        assert prompt_content['messages'][1]['role'] == 'user'
    
    def test_sort_and_filter_listings(self):
        """Test sorting and filtering of listings."""
        # Add more listings to test sorting and filtering
        many_listings = []
        for i in range(150):
            listing = {
                'id': f'listing{i}',
                'price_per_m2': 500000 + (i * 1000),  # Increasing prices
                'price_yen': 30000000,
                'area_m2': 60.0
            }
            many_listings.append(listing)
        
        # Add one with invalid price_per_m2
        many_listings.append({
            'id': 'invalid',
            'price_per_m2': 0,
            'price_yen': 30000000,
            'area_m2': 60.0
        })
        
        result = sort_and_filter_listings(many_listings)
        
        # Should filter out invalid and keep only top 100
        assert len(result) == 100
        
        # Should be sorted by price_per_m2 ascending
        assert result[0]['id'] == 'listing0'  # Lowest price_per_m2
        assert result[-1]['id'] == 'listing99'  # 100th lowest price_per_m2
        
        # Verify sorting order
        for i in range(len(result) - 1):
            assert result[i]['price_per_m2'] <= result[i + 1]['price_per_m2']
    
    def test_sort_and_filter_listings_empty(self):
        """Test handling of empty or invalid listings."""
        # Empty list
        assert sort_and_filter_listings([]) == []
        
        # All invalid listings
        invalid_listings = [
            {'id': 'invalid1', 'price_per_m2': 0},
            {'id': 'invalid2', 'price_per_m2': -100},
            {'id': 'invalid3'}  # Missing price_per_m2
        ]
        assert sort_and_filter_listings(invalid_listings) == []
    
    def test_build_vision_prompt(self):
        """Test vision prompt building."""
        with patch('app.generate_presigned_url', return_value='https://presigned-url.com/image.jpg'):
            prompt = build_vision_prompt(self.sample_jsonl_data[:2], '2025-07-07', 'test-bucket')
        
        assert prompt['model'] == 'gpt-4o'
        assert prompt['temperature'] == 0.2
        assert prompt['response_format']['type'] == 'json_object'
        assert prompt['max_tokens'] == 4000
        
        messages = prompt['messages']
        assert len(messages) == 2
        assert messages[0]['role'] == 'system'
        assert 'aggressive Tokyo condo investor' in messages[0]['content']
        
        user_content = messages[1]['content']
        assert isinstance(user_content, list)
        
        # Check content structure
        text_items = [item for item in user_content if item['type'] == 'text']
        image_items = [item for item in user_content if item['type'] == 'image_url']
        
        assert len(text_items) >= 3  # Header + 2 listings
        assert len(image_items) == 3  # 2 + 1 interior photos
        
        # Verify first text item is header
        assert 'Listings scraped on 2025-07-07' in text_items[0]['text']
        
        # Verify image items have correct structure
        for image_item in image_items:
            assert 'image_url' in image_item
            assert 'url' in image_item['image_url']
            assert image_item['image_url']['detail'] == 'low'
    
    def test_generate_presigned_url_success(self, mock_s3_client):
        """Test successful presigned URL generation."""
        s3_url = 's3://test-bucket/raw/2025-07-07/images/test.jpg'
        
        with patch('app.s3_client', mock_s3_client):
            # Mock the generate_presigned_url method
            mock_s3_client.generate_presigned_url = Mock(return_value='https://presigned-url.com/test.jpg')
            
            result = generate_presigned_url(s3_url, 'test-bucket')
        
        assert result == 'https://presigned-url.com/test.jpg'
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': 'raw/2025-07-07/images/test.jpg'},
            ExpiresIn=28800
        )
    
    def test_generate_presigned_url_invalid(self):
        """Test handling of invalid S3 URLs."""
        # Invalid URL format
        result = generate_presigned_url('http://example.com/image.jpg', 'test-bucket')
        assert result == ""
        
        # Empty URL
        result = generate_presigned_url('', 'test-bucket')
        assert result == ""
    
    def test_generate_presigned_url_exception(self, mock_s3_client):
        """Test handling of S3 exceptions."""
        s3_url = 's3://test-bucket/raw/2025-07-07/images/test.jpg'
        
        with patch('app.s3_client', mock_s3_client):
            # Mock the generate_presigned_url method to raise exception
            mock_s3_client.generate_presigned_url = Mock(side_effect=Exception('S3 error'))
            
            result = generate_presigned_url(s3_url, 'test-bucket')
        
        assert result == ""
    
    def test_lambda_handler_missing_jsonl(self, mock_s3_client, environment_variables):
        """Test handling of missing JSONL file."""
        event = {
            'date': '2025-07-07',
            'bucket': 'test-bucket',
            'jsonl_key': 'clean/2025-12-31/listings.jsonl'  # Non-existent
        }
        
        with patch('app.s3_client', mock_s3_client):
            with pytest.raises(Exception):
                lambda_handler(event, None)
    
    def test_lambda_handler_empty_jsonl(self, mock_s3_client, environment_variables, sample_prompt_event):
        """Test handling of empty JSONL file."""
        # Put empty JSONL file
        mock_s3_client.put_object(
            Bucket='test-bucket',
            Key='clean/2025-07-07/listings.jsonl',
            Body=b''
        )
        
        with patch('app.s3_client', mock_s3_client):
            result = lambda_handler(sample_prompt_event, None)
        
        assert result['statusCode'] == 200
        assert result['listings_count'] == 0
        assert result['total_images'] == 0