"""
Pytest configuration and fixtures for testing AI scraper components.
"""
import json
import os
from typing import Dict, Any
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_s3, mock_ssm, mock_ses


@pytest.fixture
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def mock_s3_client(aws_credentials):
    """Mock S3 client with sample bucket and data."""
    with mock_s3():
        s3 = boto3.client('s3', region_name='us-east-1')
        bucket_name = 'test-bucket'
        s3.create_bucket(Bucket=bucket_name)
        
        # Create sample CSV data
        sample_csv = """id,headline,price_yen,area_m2,year_built,walk_mins_station,ward,photo_filenames
listing1,"Spacious apartment in Shibuya",25000000,65.5,2010,8,Shibuya,living_room.jpg|bedroom.jpg|kitchen.jpg
listing2,"Cozy studio in Harajuku",18000000,35.2,2015,5,Shibuya,interior_shot.jpg|balcony.jpg
listing3,"Family home in Setagaya",45000000,95.0,2005,15,Setagaya,living_area.jpg|dining.jpg|exterior.jpg"""
        
        s3.put_object(
            Bucket=bucket_name,
            Key='raw/2025-07-07/listings.csv',
            Body=sample_csv.encode('utf-8')
        )
        
        # Create sample image objects
        for filename in ['living_room.jpg', 'bedroom.jpg', 'kitchen.jpg', 'interior_shot.jpg', 'balcony.jpg', 'living_area.jpg', 'dining.jpg', 'exterior.jpg']:
            s3.put_object(
                Bucket=bucket_name,
                Key=f'raw/2025-07-07/images/{filename}',
                Body=b'fake_image_data'
            )
        
        yield s3


@pytest.fixture
def mock_ssm_client(aws_credentials):
    """Mock SSM client with parameters."""
    with mock_ssm():
        ssm = boto3.client('ssm', region_name='us-east-1')
        
        # Create test parameters
        ssm.put_parameter(
            Name='/ai-scraper/test-stack/openai-api-key',
            Value='test-openai-key',
            Type='SecureString'
        )
        
        yield ssm


@pytest.fixture
def mock_ses_client(aws_credentials):
    """Mock SES client."""
    with mock_ses():
        ses = boto3.client('ses', region_name='us-east-1')
        yield ses


@pytest.fixture
def sample_etl_event():
    """Sample ETL Lambda event."""
    return {
        'date': '2025-07-07'
    }


@pytest.fixture
def sample_prompt_event():
    """Sample prompt builder event."""
    return {
        'date': '2025-07-07',
        'bucket': 'test-bucket',
        'jsonl_key': 'clean/2025-07-07/listings.jsonl'
    }


@pytest.fixture
def sample_llm_event():
    """Sample LLM batch event."""
    return {
        'date': '2025-07-07',
        'bucket': 'test-bucket',
        'prompt_key': 'prompts/2025-07-07/payload.json'
    }


@pytest.fixture
def sample_report_event():
    """Sample report sender event."""
    return {
        'date': '2025-07-07',
        'bucket': 'test-bucket',
        'result_key': 'batch_output/2025-07-07/response.json',
        'batch_result': {
            'top_picks': [
                {
                    'id': 'listing1',
                    'score': 85,
                    'why': 'Great value in prime location',
                    'red_flags': ['Minor wear on floors'],
                    'price_yen': 25000000,
                    'area_m2': 65.5,
                    'price_per_m2': 381679,
                    'age_years': 15,
                    'walk_mins_station': 8,
                    'ward': 'Shibuya'
                }
            ],
            'runners_up': [
                {
                    'id': 'listing2',
                    'score': 72,
                    'why': 'Compact but well-designed',
                    'red_flags': [],
                    'price_yen': 18000000,
                    'area_m2': 35.2,
                    'price_per_m2': 511364,
                    'age_years': 10,
                    'walk_mins_station': 5,
                    'ward': 'Shibuya'
                }
            ],
            'market_notes': 'Strong demand in central Tokyo areas'
        }
    }


@pytest.fixture
def sample_jsonl_data():
    """Sample JSONL data for testing."""
    return [
        {
            'id': 'listing1',
            'headline': 'Spacious apartment in Shibuya',
            'price_yen': 25000000,
            'area_m2': 65.5,
            'year_built': 2010,
            'walk_mins_station': 8.0,
            'ward': 'Shibuya',
            'price_per_m2': 381679.39,
            'age_years': 15,
            'photo_urls': [
                's3://test-bucket/raw/2025-07-07/images/living_room.jpg',
                's3://test-bucket/raw/2025-07-07/images/bedroom.jpg',
                's3://test-bucket/raw/2025-07-07/images/kitchen.jpg'
            ],
            'interior_photos': [
                's3://test-bucket/raw/2025-07-07/images/living_room.jpg',
                's3://test-bucket/raw/2025-07-07/images/bedroom.jpg',
                's3://test-bucket/raw/2025-07-07/images/kitchen.jpg'
            ],
            'photo_count': 3,
            'interior_photo_count': 3
        },
        {
            'id': 'listing2',
            'headline': 'Cozy studio in Harajuku',
            'price_yen': 18000000,
            'area_m2': 35.2,
            'year_built': 2015,
            'walk_mins_station': 5.0,
            'ward': 'Shibuya',
            'price_per_m2': 511363.64,
            'age_years': 10,
            'photo_urls': [
                's3://test-bucket/raw/2025-07-07/images/interior_shot.jpg',
                's3://test-bucket/raw/2025-07-07/images/balcony.jpg'
            ],
            'interior_photos': [
                's3://test-bucket/raw/2025-07-07/images/interior_shot.jpg'
            ],
            'photo_count': 2,
            'interior_photo_count': 1
        }
    ]


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response."""
    return {
        'top_picks': [
            {
                'id': 'listing1',
                'score': 85,
                'why': 'Excellent price per square meter in desirable Shibuya location',
                'red_flags': ['Minor wear visible on hardwood floors']
            }
        ],
        'runners_up': [
            {
                'id': 'listing2',
                'score': 72,
                'why': 'Compact but efficient use of space',
                'red_flags': []
            }
        ],
        'market_notes': 'Central Tokyo market remains strong with high demand'
    }


@pytest.fixture
def environment_variables():
    """Set up environment variables for testing."""
    env_vars = {
        'OUTPUT_BUCKET': 'test-bucket',
        'AWS_LAMBDA_FUNCTION_NAME': 'test-stack-etl',
        'EMAIL_FROM': 'test@example.com',
        'EMAIL_TO': 'recipient@example.com',
        'OPENAI_API_KEY': 'test-openai-key',
    }
    
    with patch.dict(os.environ, env_vars):
        yield env_vars
