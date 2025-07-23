
#!/usr/bin/env python3
"""
Unit tests for the scraper functionality
"""
import unittest
import os
import tempfile
import json
import time
import threading
from unittest.mock import Mock, patch, MagicMock
import sys
import importlib.util
import argparse
import logging
from pathlib import Path

# Import the scraper module
ROOT_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "scrape",
    str(ROOT_DIR / "scraper" / "scrape.py")
)
scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraper)

class TestScraperFunctions(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_property_data = {
            "url": "https://www.homes.co.jp/mansion/b-1234567890/",
            "title": "テストマンション",
            "price": "3,500万円",
            "間取り": "2LDK",
            "専有面積": "65.5m²"
        }
    
    def test_validate_property_data_valid(self):
        """Test data validation with valid property data"""
        data = self.test_property_data.copy()
        is_valid, message = scraper.validate_property_data(data)
        self.assertTrue(is_valid)
        self.assertEqual(message, "Data validation passed")
    
    def test_validate_property_data_missing_url(self):
        """Test data validation with missing URL"""
        data = self.test_property_data.copy()
        del data["url"]
        is_valid, message = scraper.validate_property_data(data)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: url", message)
    
    def test_validate_property_data_invalid_url(self):
        """Test data validation with invalid URL format"""
        data = self.test_property_data.copy()
        data["url"] = "http://invalid-url.com"
        is_valid, message = scraper.validate_property_data(data)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Invalid URL format")
    
    def test_validate_property_data_invalid_price(self):
        """Test data validation with invalid price format"""
        data = self.test_property_data.copy()
        data["price"] = "invalid price"
        is_valid, message = scraper.validate_property_data(data)
        self.assertFalse(is_valid)
        self.assertIn("Invalid price format", message)
    
    def test_validate_property_data_title_too_short(self):
        """Test data validation with title too short"""
        data = self.test_property_data.copy()
        data["title"] = "短い"
        is_valid, message = scraper.validate_property_data(data)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Title too short")
    
    def test_validate_property_data_title_truncation(self):
        """Test data validation with long title truncation"""
        data = self.test_property_data.copy()
        data["title"] = "A" * 250  # Very long title
        is_valid, message = scraper.validate_property_data(data)
        self.assertTrue(is_valid)
        self.assertTrue(data["title"].endswith("..."))
        self.assertEqual(len(data["title"]), 203)  # 200 + "..."
    
    @patch('logging.Logger.handle')
    def test_log_structured_message(self, mock_handle):
        """Test structured logging output"""
        logger = scraper.setup_logging()
        scraper.log_structured_message(logger, "INFO", "Test message", test_field="test_value")
        
        # Verify handle was called
        mock_handle.assert_called_once()
        
        # Verify the logged message is valid JSON
        log_record = mock_handle.call_args[0][0]
        self.assertEqual(log_record.levelno, logging.INFO)
        self.assertEqual(log_record.getMessage(), "Test message")
    
    def test_create_enhanced_session(self):
        """Test session creation with proper headers"""
        session = scraper.create_enhanced_session()
        
        # Check that essential headers are present
        self.assertIn('User-Agent', session.headers)
        self.assertIn('Accept', session.headers)
        self.assertIn('Accept-Language', session.headers)
        self.assertTrue(session.headers['Accept-Language'].startswith('ja-JP'))
    
    def test_write_job_summary(self):
        """Test job summary writing"""
        test_summary = {
            "status": "SUCCESS",
            "total_records": 10,
            "successful_scrapes": 8,
            "failed_scrapes": 2
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock the summary path to use temp directory
            with patch('os.makedirs'),                 patch('builtins.open', mock_open()) as mock_file,                 patch('json.dump') as mock_json_dump:
                
                scraper.write_job_summary(test_summary)
                
                # Verify file operations
                mock_file.assert_called()
                mock_json_dump.assert_called_once_with(test_summary, mock_file.return_value.__enter__.return_value, indent=2)
    
    @patch('boto3.client')
    def test_send_cloudwatch_metrics(self, mock_boto3_client):
        """Test CloudWatch metrics sending"""
        mock_cloudwatch = Mock()
        mock_boto3_client.return_value = mock_cloudwatch
        
        success_count = 8
        error_count = 2
        duration_seconds = 120.5
        total_properties = 10
        
        result = scraper.send_cloudwatch_metrics(success_count, error_count, duration_seconds, total_properties)
        
        # Verify boto3 client was called correctly
        mock_boto3_client.assert_called_once_with('cloudwatch')
        
        # Verify put_metric_data was called
        mock_cloudwatch.put_metric_data.assert_called_once()
        
        # Verify the call arguments
        call_args = mock_cloudwatch.put_metric_data.call_args
        self.assertEqual(call_args[1]['Namespace'], 'ScraperMetrics')
        self.assertEqual(len(call_args[1]['MetricData']), 4)  # 4 metrics
        
        # Check metric names
        metric_names = [metric['MetricName'] for metric in call_args[1]['MetricData']]
        expected_metrics = ['PropertiesScraped', 'ScrapingErrors', 'JobDuration', 'SuccessRate']
        self.assertEqual(set(metric_names), set(expected_metrics))
        
        self.assertTrue(result)
    
    @patch('boto3.client')
    def test_send_cloudwatch_metrics_failure(self, mock_boto3_client):
        """Test CloudWatch metrics sending failure"""
        mock_cloudwatch = Mock()
        mock_cloudwatch.put_metric_data.side_effect = Exception("CloudWatch error")
        mock_boto3_client.return_value = mock_cloudwatch
        
        result = scraper.send_cloudwatch_metrics(8, 2, 120.5, 10)
        
        self.assertFalse(result)
    
    @patch('boto3.client')
    def test_upload_to_s3_success(self, mock_boto3_client):
        """Test successful S3 upload"""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        result = scraper.upload_to_s3("test.csv", "test-bucket", "test-key")
        
        mock_boto3_client.assert_called_once_with("s3")
        mock_s3.upload_file.assert_called_once_with("test.csv", "test-bucket", "test-key")
        self.assertTrue(result)
    
    @patch('boto3.client')
    def test_upload_to_s3_failure(self, mock_boto3_client):
        """Test failed S3 upload"""
        mock_s3 = Mock()
        mock_s3.upload_file.side_effect = Exception("S3 error")
        mock_boto3_client.return_value = mock_s3
        
        result = scraper.upload_to_s3("test.csv", "test-bucket", "test-key")
        
        self.assertFalse(result)


class TestCircuitBreaker(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.circuit_breaker = scraper.CircuitBreaker(failure_threshold=3, recovery_timeout=1)
    
    def test_circuit_breaker_closed_state(self):
        """Test circuit breaker starts in CLOSED state"""
        self.assertEqual(self.circuit_breaker.get_state(), scraper.CircuitBreakerState.CLOSED)
    
    def test_circuit_breaker_successful_call(self):
        """Test successful calls keep circuit breaker closed"""
        def successful_function():
            return "success"
        
        result = self.circuit_breaker.call(successful_function)
        self.assertEqual(result, "success")
        self.assertEqual(self.circuit_breaker.get_state(), scraper.CircuitBreakerState.CLOSED)
    
    def test_circuit_breaker_opens_on_failures(self):
        """Test circuit breaker opens after threshold failures"""
        def failing_function():
            raise Exception("Test failure")
        
        # Fail 3 times to reach threshold
        for i in range(3):
            with self.assertRaises(Exception):
                self.circuit_breaker.call(failing_function)
        
        # Circuit breaker should now be open
        self.assertEqual(self.circuit_breaker.get_state(), scraper.CircuitBreakerState.OPEN)
        
        # Next call should fail immediately
        with self.assertRaises(Exception) as context:
            self.circuit_breaker.call(failing_function)
        self.assertIn("Circuit breaker is OPEN", str(context.exception))
    
    def test_circuit_breaker_half_open_transition(self):
        """Test circuit breaker transitions to half-open after timeout"""
        def failing_function():
            raise Exception("Test failure")
        
        # Open the circuit breaker
        for i in range(3):
            with self.assertRaises(Exception):
                self.circuit_breaker.call(failing_function)
        
        # Verify it's open
        self.assertEqual(self.circuit_breaker.get_state(), scraper.CircuitBreakerState.OPEN)
        
        # Wait for recovery timeout
        time.sleep(1.1)
        
        # Mock a successful function for half-open test
        def successful_function():
            return "success"
        
        # First successful call should transition to half-open, then need more successes to close
        result1 = self.circuit_breaker.call(successful_function)
        self.assertEqual(result1, "success")
        # Should be half-open after first success
        self.assertEqual(self.circuit_breaker.get_state(), scraper.CircuitBreakerState.HALF_OPEN)
        
        # Need more successes (threshold=3) to transition to closed
        result2 = self.circuit_breaker.call(successful_function)
        result3 = self.circuit_breaker.call(successful_function)
        self.assertEqual(result2, "success")
        self.assertEqual(result3, "success")
        self.assertEqual(self.circuit_breaker.get_state(), scraper.CircuitBreakerState.CLOSED)


class TestSessionPool(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.session_pool = scraper.SessionPool(pool_size=2)
    
    def tearDown(self):
        """Clean up after tests"""
        self.session_pool.close_all()
    
    def test_session_pool_initialization(self):
        """Test session pool initializes with correct size"""
        self.assertEqual(self.session_pool.pool_size, 2)
        self.assertFalse(self.session_pool.pool.empty())
    
    def test_get_and_return_session(self):
        """Test getting and returning sessions"""
        session1 = self.session_pool.get_session()
        session2 = self.session_pool.get_session()
        
        self.assertIsNotNone(session1)
        self.assertIsNotNone(session2)
        self.assertNotEqual(session1, session2)
        
        # Return sessions
        self.session_pool.return_session(session1)
        self.session_pool.return_session(session2)
    
    def test_session_pool_exhaustion(self):
        """Test session pool creates new session when exhausted"""
        # Get all sessions from pool
        sessions = []
        for _ in range(3):  # More than pool size
            session = self.session_pool.get_session()
            sessions.append(session)
        
        # Should have created extra session
        self.assertEqual(len(sessions), 3)
        
        # Clean up
        for session in sessions:
            self.session_pool.return_session(session)
    
    def test_session_age_management(self):
        """Test old sessions are replaced"""
        # Create a session pool with very short max age
        short_lived_pool = scraper.SessionPool(pool_size=1, max_age_seconds=0.1)
        
        try:
            session1 = short_lived_pool.get_session()
            session1_id = id(session1)
            short_lived_pool.return_session(session1)
            
            # Wait for session to age out
            time.sleep(0.2)
            
            session2 = short_lived_pool.get_session()
            session2_id = id(session2)
            
            # Should be different sessions
            self.assertNotEqual(session1_id, session2_id)
            
            short_lived_pool.return_session(session2)
        finally:
            short_lived_pool.close_all()


class TestErrorCategorization(unittest.TestCase):
    
    def test_categorize_network_errors(self):
        """Test network error categorization"""
        import requests
        
        connection_error = requests.exceptions.ConnectionError("Connection failed")
        category = scraper.categorize_error(connection_error)
        self.assertEqual(category, scraper.ErrorCategory.NETWORK)
        
        timeout_error = requests.exceptions.Timeout("Request timed out")
        category = scraper.categorize_error(timeout_error)
        self.assertEqual(category, scraper.ErrorCategory.NETWORK)
    
    def test_categorize_http_errors(self):
        """Test HTTP error categorization"""
        import requests
        
        http_error = requests.exceptions.HTTPError("404 Not Found")
        category = scraper.categorize_error(http_error)
        self.assertEqual(category, scraper.ErrorCategory.HTTP_ERROR)
    
    def test_categorize_anti_bot_errors(self):
        """Test anti-bot error categorization"""
        anti_bot_error = Exception("pardon our interruption")
        category = scraper.categorize_error(anti_bot_error)
        self.assertEqual(category, scraper.ErrorCategory.ANTI_BOT)
    
    def test_categorize_unknown_errors(self):
        """Test unknown error categorization"""
        unknown_error = Exception("Some unknown error")
        category = scraper.categorize_error(unknown_error)
        self.assertEqual(category, scraper.ErrorCategory.UNKNOWN)


class TestCircuitBreakerIntegration(unittest.TestCase):
    
    def test_extract_property_details_with_circuit_breaker(self):
        """Test property extraction with circuit breaker"""
        # Mock the session pool to return a mock session
        scraper.session_pool = scraper.SessionPool(pool_size=1)
        with patch.object(scraper.session_pool, 'get_session') as mock_get_session,             patch.object(scraper.session_pool, 'return_session') as mock_return_session:
            
            mock_session = Mock()
            mock_get_session.return_value = mock_session
            
            # Mock the core function to return success
            with patch.object(scraper, '_extract_property_details_core') as mock_core:
                mock_core.return_value = {"url": "test-url", "title": "Test Property"}
                
                result = scraper.extract_property_details_with_circuit_breaker(
                    "test-url", "referer-url"
                )
                
                self.assertEqual(result["url"], "test-url")
                self.assertEqual(result["title"], "Test Property")
                mock_get_session.assert_called_once()
                mock_return_session.assert_called_once_with(mock_session)
    
    def test_extract_property_details_circuit_breaker_failure(self):
        """Test property extraction when circuit breaker fails"""
        # Mock the session pool
        scraper.session_pool = scraper.SessionPool(pool_size=1)
        with patch.object(scraper.session_pool, 'get_session') as mock_get_session,             patch.object(scraper.session_pool, 'return_session') as mock_return_session:
            
            mock_session = Mock()
            mock_get_session.return_value = mock_session
            
            # Mock the circuit breaker to raise exception
            with patch.object(scraper.circuit_breaker, 'call') as mock_circuit_call:
                mock_circuit_call.side_effect = Exception("Circuit breaker test failure")
                
                result = scraper.extract_property_details_with_circuit_breaker(
                    "test-url", "referer-url"
                )
                
                self.assertIn("error", result)
                self.assertIn("error_category", result)
                self.assertIn("circuit_breaker_state", result)
                mock_return_session.assert_called_once_with(mock_session)


def mock_open():
    """Helper function to create a mock open context manager"""
    mock_file = MagicMock()
    mock_file.__enter__ = Mock(return_value=mock_file)
    mock_file.__exit__ = Mock(return_value=None)
    return mock_file

class TestScrapingLogic(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures"""
        # Load mock HTML content from files
        with open("/mnt/c/Users/azure/Desktop/scraper/scraper/mock_listing_page.html", "r") as f:
            self.mock_listing_html = f.read()
        with open("/mnt/c/Users/azure/Desktop/scraper/scraper/mock_property_page.html", "r") as f:
            self.mock_property_html = f.read()

    def test_extract_listing_urls_from_html(self):
        """Test that listing URLs are correctly extracted from HTML"""
        urls = scraper.extract_listing_urls_from_html(self.mock_listing_html)
        self.assertEqual(len(urls), 2)
        self.assertIn("https://www.homes.co.jp/mansion/b-12345", urls)
        self.assertIn("https://www.homes.co.jp/mansion/b-67890", urls)

    @patch('requests.Session.get')
    def test_extract_property_details_from_html(self, mock_get):
        """Test that property details are correctly extracted from HTML"""
        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = self.mock_property_html
        mock_response.content = self.mock_property_html.encode('utf-8')
        mock_get.return_value = mock_response

        # Create a mock session
        session = scraper.create_stealth_session()

        # Call the function to test
        details = scraper._extract_property_details_core(session, "http://example.com/property", "http://example.com")

        # Assertions
        self.assertEqual(details['price'], '3,500万円')
        self.assertEqual(details['所在地'], '東京都調布市')
        self.assertEqual(details['間取り'], '2LDK')

    @patch('requests.Session.get')
    @patch('pandas.DataFrame.to_csv')
    def test_end_to_end_scraping_flow(self, mock_to_csv, mock_get):
        """Test the end-to-end scraping flow with mock data"""
        # Mock the responses for listing and property pages
        mock_listing_response = Mock()
        mock_listing_response.status_code = 200
        mock_listing_response.text = self.mock_listing_html
        mock_listing_response.content = self.mock_listing_html.encode('utf-8')

        mock_property_response = Mock()
        mock_property_response.status_code = 200
        mock_property_response.text = self.mock_property_html
        mock_property_response.content = self.mock_property_html.encode('utf-8')

        # Set up the mock to return different responses based on the URL
        def get_side_effect(url, timeout=None):
            if "list" in url:
                return mock_listing_response
            else:
                return mock_property_response
        mock_get.side_effect = get_side_effect

        # Run the main scraping function with test parameters
        with patch('argparse.ArgumentParser.parse_args') as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(mode='testing', max_properties=2, areas='mock-area', output_bucket='', max_threads=2)
            
            scraper.main()
            # Check that the output file was written
            mock_to_csv.assert_called_once()

class TestAreaDiscovery(unittest.TestCase):

    @patch('requests.Session.get')
    def test_discover_tokyo_areas(self, mock_get):
        """Test the Tokyo area discovery function"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'''
        <a href="/mansion/chuko/tokyo/shibuya-ku/list/">Shibuya</a>
        <a href="/mansion/chuko/tokyo/shinjuku-ku/list/">Shinjuku</a>
        '''
        mock_get.return_value = mock_response

        areas = scraper.discover_tokyo_areas()
        self.assertEqual(len(areas), 2)
        self.assertIn('shibuya-ku', areas)
        self.assertIn('shinjuku-ku', areas)

    def test_daily_distribution(self):
        """Test the daily area distribution across sessions"""
        areas = ['shibuya-ku', 'shinjuku-ku', 'chofu-city', 'mitaka-city', 
                  'setagaya-ku', 'nerima-ku', 'minato-ku', 'chiyoda-ku']
        date_key = '2025-01-01'
        sessions = ['morning-1', 'morning-2', 'afternoon-1', 'afternoon-2', 
                    'evening-1', 'evening-2', 'night-1', 'night-2']
        
        all_assigned_areas = set()
        for session_id in sessions:
            assigned_areas = scraper.get_daily_area_distribution(areas, session_id, date_key)
            all_assigned_areas.update(assigned_areas)
        
        self.assertEqual(set(areas), all_assigned_areas)

if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
