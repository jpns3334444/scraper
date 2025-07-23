"""
Tests for LLM Batch Lambda function.
"""
import json
from unittest.mock import patch, Mock, MagicMock

import pytest
import responses

# Import the LLM batch function
import sys
import os
import importlib
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
llm_module = importlib.import_module('ai_infra.lambda.llm_batch.app')
lambda_handler = llm_module.lambda_handler
create_batch_job = llm_module.create_batch_job
poll_batch_completion = llm_module.poll_batch_completion
download_batch_results = llm_module.download_batch_results



class TestLLMBatch:
    """Test cases for LLM Batch Lambda function."""
    
    def setup_method(self):
        """Set up test data."""
        self.sample_prompt_payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are an AI assistant."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Analyze these listings."}
                ]}
            ],
            "temperature": 0.2,
            "max_tokens": 4000
        }
        
        self.mock_html_response = '''<!DOCTYPE html>
<html><head><title>Tokyo Real Estate Analysis</title></head>
<body><h1>Investment Report</h1><p>Sample HTML response</p></body></html>'''
    
    @patch('app.get_openai_client')
    def test_lambda_handler_success(self, mock_get_client, mock_s3_client, environment_variables, sample_llm_event):
        """Test successful LLM batch processing."""
        # Set up prompt payload in S3
        mock_s3_client.put_object(
            Bucket='test-bucket',
            Key='prompts/2025-07-07/payload.json',
            Body=json.dumps(self.sample_prompt_payload).encode('utf-8')
        )
        
        # Mock OpenAI client and responses
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock batch creation
        mock_batch_job = Mock()
        mock_batch_job.id = 'batch_123'
        
        # Mock file creation
        mock_file = Mock()
        mock_file.id = 'file_123'
        mock_client.files.create.return_value = mock_file
        mock_client.batches.create.return_value = mock_batch_job
        
        # Mock batch completion
        mock_completed_batch = Mock()
        mock_completed_batch.id = 'batch_123'
        mock_completed_batch.status = 'completed'
        mock_completed_batch.output_file_id = 'output_file_123'
        mock_client.batches.retrieve.return_value = mock_completed_batch
        
        # Mock file download
        mock_output_content = Mock()
        mock_output_content.read.return_value = json.dumps({
            'response': {
                'body': {
                    'choices': [{
                        'message': {
                            'content': self.mock_html_response
                        }
                    }]
                }
            }
        }).encode('utf-8')
        mock_client.files.content.return_value = mock_output_content
        
        # Mock context
        mock_context = Mock()
        mock_context.get_remaining_time_in_millis.return_value = 300000  # 5 minutes
        
        with patch('app.s3_client', mock_s3_client):
            result = lambda_handler(sample_llm_event, mock_context)
        
        assert result['statusCode'] == 200
        assert result['date'] == '2025-07-07'
        assert result['batch_id'] == 'batch_123'
        assert 'result_key' in result
        assert result['batch_result'] == self.mock_html_response
        
        # Verify result was saved to S3
        response = mock_s3_client.get_object(Bucket='test-bucket', Key=result['result_key'])
        saved_result = json.loads(response['Body'].read().decode('utf-8'))
        assert saved_result['batch_id'] == 'batch_123'
        assert saved_result['parsed_result'] == self.mock_html_response
    
    @patch('app.ssm_client')
    def test_get_openai_client_from_ssm(self, mock_ssm):
        """Test OpenAI client initialization from SSM."""
        from app import get_openai_client
        
        # Mock SSM response
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': 'test-api-key'}
        }
        
        # Clear environment variable
        with patch.dict('os.environ', {}, clear=True):
            with patch.dict('os.environ', {'AWS_LAMBDA_FUNCTION_NAME': 'test-stack-llm-batch'}):
                with patch('app.OpenAI') as mock_openai:
                    get_openai_client()
                    
                    mock_openai.assert_called_once_with(api_key='test-api-key')
                    mock_ssm.get_parameter.assert_called_once_with(
                        Name='/ai-scraper/test/openai-api-key',
                        WithDecryption=True
                    )
    
    def test_get_openai_client_from_env(self, environment_variables):
        """Test OpenAI client initialization from environment."""
        from app import get_openai_client
        
        with patch('app.OpenAI') as mock_openai:
            get_openai_client()
            mock_openai.assert_called_once_with(api_key='test-openai-key')
    
    def test_create_batch_job(self):
        """Test batch job creation."""
        mock_client = Mock()
        
        # Mock file creation
        mock_file = Mock()
        mock_file.id = 'file_123'
        mock_client.files.create.return_value = mock_file
        
        # Mock batch creation
        mock_batch = Mock()
        mock_batch.id = 'batch_123'
        mock_client.batches.create.return_value = mock_batch
        
        result = create_batch_job(mock_client, self.sample_prompt_payload, '2025-07-07')
        
        assert result.id == 'batch_123'
        
        # Verify file creation call
        mock_client.files.create.assert_called_once()
        file_call_args = mock_client.files.create.call_args
        assert file_call_args[1]['purpose'] == 'batch'
        
        # Verify batch creation call
        mock_client.batches.create.assert_called_once()
        batch_call_args = mock_client.batches.create.call_args
        assert batch_call_args[1]['input_file_id'] == 'file_123'
        assert batch_call_args[1]['endpoint'] == '/v1/chat/completions'
        assert batch_call_args[1]['completion_window'] == '24h'
    
    def test_poll_batch_completion_success(self):
        """Test successful batch polling."""
        mock_client = Mock()
        
        # First call: in_progress, second call: completed
        mock_batch_in_progress = Mock()
        mock_batch_in_progress.status = 'in_progress'
        
        mock_batch_completed = Mock()
        mock_batch_completed.status = 'completed'
        
        mock_client.batches.retrieve.side_effect = [mock_batch_in_progress, mock_batch_completed]
        
        mock_context = Mock()
        mock_context.get_remaining_time_in_millis.return_value = 300000  # 5 minutes
        
        with patch('app.time.sleep'):  # Mock sleep to speed up test
            result = poll_batch_completion(mock_client, 'batch_123', mock_context)
        
        assert result.status == 'completed'
        assert mock_client.batches.retrieve.call_count == 2
    
    def test_poll_batch_completion_failed(self):
        """Test batch polling with failed status."""
        mock_client = Mock()
        
        mock_batch_failed = Mock()
        mock_batch_failed.status = 'failed'
        mock_client.batches.retrieve.return_value = mock_batch_failed
        
        mock_context = Mock()
        mock_context.get_remaining_time_in_millis.return_value = 300000
        
        with pytest.raises(Exception) as exc_info:
            poll_batch_completion(mock_client, 'batch_123', mock_context)
        
        assert 'failed with status: failed' in str(exc_info.value)
    
    def test_poll_batch_completion_timeout(self):
        """Test batch polling timeout."""
        mock_client = Mock()
        
        mock_batch_in_progress = Mock()
        mock_batch_in_progress.status = 'in_progress'
        mock_client.batches.retrieve.return_value = mock_batch_in_progress
        
        mock_context = Mock()
        mock_context.get_remaining_time_in_millis.return_value = 60000  # 1 minute (less than threshold)
        
        with pytest.raises(Exception) as exc_info:
            poll_batch_completion(mock_client, 'batch_123', mock_context)
        
        assert 'timeout approaching' in str(exc_info.value)
    
    def test_download_batch_results(self, mock_s3_client):
        """Test batch results download."""
        mock_client = Mock()
        
        mock_batch = Mock()
        mock_batch.id = 'batch_123'
        mock_batch.output_file_id = 'output_file_123'
        
        # Mock file content
        mock_output_content = Mock()
        output_data = {
            'response': {
                'body': {
                    'choices': [{
                        'message': {
                            'content': self.mock_html_response
                        }
                    }]
                }
            }
        }
        mock_output_content.read.return_value = json.dumps(output_data).encode('utf-8')
        mock_client.files.content.return_value = mock_output_content
        
        with patch('app.s3_client', mock_s3_client):
            result = download_batch_results(mock_client, mock_batch, 'test-bucket', 'output/result.json')
        
        assert result == self.mock_html_response
        
        # Verify file was saved to S3
        response = mock_s3_client.get_object(Bucket='test-bucket', Key='output/result.json')
        saved_data = json.loads(response['Body'].read().decode('utf-8'))
        assert saved_data['batch_id'] == 'batch_123'
        assert saved_data['parsed_result'] == self.mock_html_response
    
    def test_download_batch_results_no_output_file(self):
        """Test handling of missing output file."""
        mock_client = Mock()
        
        mock_batch = Mock()
        mock_batch.id = 'batch_123'
        mock_batch.output_file_id = None
        
        with pytest.raises(Exception) as exc_info:
            download_batch_results(mock_client, mock_batch, 'test-bucket', 'output/result.json')
        
        assert 'No output file available' in str(exc_info.value)
    
    @patch('app.get_openai_client')
    def test_lambda_handler_missing_prompt(self, mock_get_client, mock_s3_client, environment_variables):
        """Test handling of missing prompt file."""
        event = {
            'date': '2025-07-07',
            'bucket': 'test-bucket',
            'prompt_key': 'prompts/2025-12-31/payload.json'  # Non-existent
        }
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        with patch('app.s3_client', mock_s3_client):
            with pytest.raises(Exception):
                lambda_handler(event, None)
