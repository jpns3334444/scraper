"""
Tests for ETL Lambda function.
"""
import json
import os
from unittest.mock import patch

import pytest
import boto3

# Import the ETL function
import sys
sys.path.append('/mnt/c/Users/azure/Desktop/scraper/lambda/etl')
from app import lambda_handler, process_listings, process_single_listing, process_photos


class TestETL:
    """Test cases for ETL Lambda function."""
    
    def test_lambda_handler_success(self, mock_s3_client, environment_variables, sample_etl_event):
        """Test successful ETL processing."""
        with patch('app.s3_client', mock_s3_client):
            result = lambda_handler(sample_etl_event, None)
        
        assert result['statusCode'] == 200
        assert result['date'] == '2025-07-07'
        assert result['bucket'] == 'test-bucket'
        assert result['listings_count'] == 3
        assert 'jsonl_key' in result
        
        # Verify JSONL was saved to S3
        response = mock_s3_client.get_object(Bucket='test-bucket', Key=result['jsonl_key'])
        jsonl_content = response['Body'].read().decode('utf-8')
        lines = jsonl_content.strip().split('\n')
        assert len(lines) == 3
        
        # Verify first listing
        first_listing = json.loads(lines[0])
        assert first_listing['id'] == 'listing1'
        assert first_listing['price_per_m2'] == pytest.approx(381679.39, rel=1e-2)
        assert first_listing['age_years'] == 15
        assert len(first_listing['interior_photos']) == 3
    
    def test_lambda_handler_missing_csv(self, mock_s3_client, environment_variables):
        """Test handling of missing CSV file."""
        event = {'date': '2025-12-31'}  # Non-existent date
        
        with patch('app.s3_client', mock_s3_client):
            with pytest.raises(Exception):
                lambda_handler(event, None)
    
    def test_process_photos(self):
        """Test photo processing and categorization."""
        photo_filenames = "living_room.jpg|bedroom_main.jpg|exterior_view.jpg|kitchen_area.jpg"
        bucket = "test-bucket"
        date_str = "2025-07-07"
        
        photo_urls, interior_photos = process_photos(photo_filenames, bucket, date_str)
        
        assert len(photo_urls) == 4
        assert len(interior_photos) == 3  # living_room, bedroom_main, kitchen_area
        
        # Check S3 URLs format
        for url in photo_urls:
            assert url.startswith(f"s3://{bucket}/raw/{date_str}/images/")
        
        # Check interior photo detection
        interior_filenames = [url.split('/')[-1] for url in interior_photos]
        assert 'living_room.jpg' in interior_filenames
        assert 'bedroom_main.jpg' in interior_filenames
        assert 'kitchen_area.jpg' in interior_filenames
        assert 'exterior_view.jpg' not in interior_filenames
    
    def test_process_photos_empty(self):
        """Test handling of empty photo filenames."""
        for empty_value in ["", "nan", "none", None]:
            photo_urls, interior_photos = process_photos(str(empty_value) if empty_value else "", "bucket", "date")
            assert photo_urls == []
            assert interior_photos == []
    
    def test_process_single_listing_valid(self):
        """Test processing a valid listing."""
        import pandas as pd
        
        row = pd.Series({
            'id': 'test123',
            'headline': 'Test Property',
            'price_yen': 30000000,
            'area_m2': 75.0,
            'year_built': 2018,
            'walk_mins_station': 12,
            'ward': 'Shibuya',
            'photo_filenames': 'living.jpg|kitchen.jpg'
        })
        
        result = process_single_listing(row, 'test-bucket', '2025-07-07')
        
        assert result['id'] == 'test123'
        assert result['price_per_m2'] == 400000.0
        assert result['age_years'] == 7  # 2025 - 2018
        assert len(result['interior_photos']) == 2
    
    def test_process_single_listing_invalid(self):
        """Test handling of invalid listing data."""
        import pandas as pd
        
        # Missing critical data
        row = pd.Series({
            'id': '',
            'headline': 'Test Property',
            'price_yen': 0,
            'area_m2': 0,
            'year_built': 2018,
            'walk_mins_station': 12,
            'ward': 'Shibuya',
            'photo_filenames': 'living.jpg'
        })
        
        result = process_single_listing(row, 'test-bucket', '2025-07-07')
        assert result is None
    
    def test_date_handling(self, mock_s3_client, environment_variables):
        """Test different date input formats."""
        # ISO datetime format (from EventBridge)
        event = {'date': '2025-07-07T18:00:00Z'}
        
        with patch('app.s3_client', mock_s3_client):
            result = lambda_handler(event, None)
        
        assert result['date'] == '2025-07-07'
    
    def test_no_date_provided(self, mock_s3_client, environment_variables):
        """Test handling when no date is provided."""
        event = {}
        
        with patch('app.s3_client', mock_s3_client), \
             patch('app.datetime') as mock_datetime:
            
            # Mock current date
            mock_datetime.now.return_value.strftime.return_value = '2025-07-07'
            
            # This should fail because we don't have CSV for current date
            with pytest.raises(Exception):
                lambda_handler(event, None)