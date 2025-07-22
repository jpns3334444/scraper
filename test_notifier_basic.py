#!/usr/bin/env python3
"""
Basic verification test for the full notifier functionality.
"""

import sys
import os
sys.path.append(os.getcwd())

from unittest.mock import Mock, patch, MagicMock

# Mock the config import before importing notifier
sys.modules['ai_infra.lambda.util.config'] = Mock()

from notifications.notifier import DailyDigestGenerator

def create_mock_candidate(candidate_id, score, verdict_value, ward='Shibuya'):
    """Create a mock candidate with proper structure."""
    class MockVerdict:
        def __init__(self, val):
            self.value = val
    
    return {
        'property_id': candidate_id,
        'price': 50000000,
        'total_sqm': 60.5,
        'price_per_sqm': 826446,
        'ward': ward,
        'building_age_years': 8,
        'verdict': MockVerdict(verdict_value),
        'final_score': score,
        'ward_discount_pct': -15.0,
        'llm_analysis': {
            'upsides': ['Great location', 'Modern amenities'],
            'risks': ['High maintenance fees'],
            'justification': 'Strong investment potential'
        }
    }

def test_candidate_filtering():
    """Test candidate filtering logic."""
    print("Testing candidate filtering...")
    
    # Mock candidates
    candidates = [
        create_mock_candidate('BUY_001', 85.0, 'BUY_CANDIDATE'),
        create_mock_candidate('BUY_002', 78.0, 'BUY_CANDIDATE'),
        create_mock_candidate('WATCH_001', 68.0, 'WATCH'),
        create_mock_candidate('REJECT_001', 45.0, 'REJECT')
    ]
    
    # Mock S3 and SES clients
    with patch('boto3.client') as mock_boto3:
        mock_s3 = Mock()
        mock_ses = Mock()
        mock_boto3.return_value = mock_s3
        
        # Mock config
        with patch('notifications.notifier.get_config') as mock_config:
            config_mock = Mock()
            config_mock.get_str.return_value = 'test-bucket'
            mock_config.return_value = config_mock
            
            generator = DailyDigestGenerator()
            generator.s3_client = mock_s3
            generator.ses_client = mock_ses
            
            # Test filtering
            buy_candidates, watch_candidates = generator._filter_candidates(candidates)
            
            assert len(buy_candidates) == 2, f"Expected 2 BUY candidates, got {len(buy_candidates)}"
            assert len(watch_candidates) == 1, f"Expected 1 WATCH candidate, got {len(watch_candidates)}"
            
            # Verify sorting (higher scores first)
            assert buy_candidates[0]['final_score'] == 85.0, "BUY candidates not sorted by score"
            assert buy_candidates[1]['final_score'] == 78.0, "BUY candidates not sorted by score"
            
            print("✓ Candidate filtering works correctly")

def test_html_generation():
    """Test HTML generation with mocked data."""
    print("Testing HTML generation...")
    
    buy_candidates = [create_mock_candidate('BUY_001', 85.0, 'BUY_CANDIDATE')]
    watch_candidates = [create_mock_candidate('WATCH_001', 68.0, 'WATCH')]
    market_snapshot = {
        'median_price_per_sqm': 950000,
        'total_active': 15420,
        'seven_day_change_pp': 2.5
    }
    
    with patch('boto3.client') as mock_boto3:
        with patch('notifications.notifier.get_config') as mock_config:
            config_mock = Mock()
            config_mock.get_str.return_value = 'test-bucket'
            mock_config.return_value = config_mock
            
            generator = DailyDigestGenerator()
            
            html = generator._generate_html_digest(
                buy_candidates, watch_candidates, market_snapshot, '2025-01-22'
            )
            
            # Verify HTML structure
            assert '<html>' in html, "HTML structure missing"
            assert '<head>' in html, "HTML head missing"
            assert '<body>' in html, "HTML body missing"
            assert 'Tokyo Real Estate Daily Digest' in html, "Title missing"
            
            # Verify content
            assert 'BUY_001' in html, "BUY candidate missing from HTML"
            assert '85.0' in html, "Score missing from HTML"
            assert '¥950,000' in html, "Market median price missing"
            assert 'BUY Candidates (1 properties)' in html, "BUY section title missing"
            assert 'WATCH Summary (1 properties)' in html, "WATCH section title missing"
            
            print("✓ HTML generation works correctly")

def test_csv_generation():
    """Test CSV generation with mocked data."""
    print("Testing CSV generation...")
    
    candidates = [
        create_mock_candidate('CSV_001', 85.0, 'BUY_CANDIDATE'),
        create_mock_candidate('CSV_002', 68.0, 'WATCH')
    ]
    
    with patch('boto3.client') as mock_boto3:
        with patch('notifications.notifier.get_config') as mock_config:
            config_mock = Mock()
            config_mock.get_str.return_value = 'test-bucket'
            mock_config.return_value = config_mock
            
            generator = DailyDigestGenerator()
            
            csv_content = generator._generate_csv_digest(candidates)
            
            # Verify CSV structure
            lines = csv_content.strip().split('\n')
            assert len(lines) >= 3, f"Expected at least 3 lines, got {len(lines)}"
            
            # Verify headers
            headers = lines[0].split(',')
            expected_headers = ['property_id', 'verdict', 'final_score', 'price']
            for header in expected_headers:
                assert header in headers, f"Header '{header}' missing from CSV"
            
            # Verify data
            assert 'CSV_001' in csv_content, "CSV_001 missing from CSV"
            assert 'CSV_002' in csv_content, "CSV_002 missing from CSV"
            assert 'BUY_CANDIDATE' in csv_content, "BUY_CANDIDATE verdict missing"
            assert 'WATCH' in csv_content, "WATCH verdict missing"
            
            print("✓ CSV generation works correctly")

def test_error_handling():
    """Test error handling in digest generation."""
    print("Testing error handling...")
    
    with patch('boto3.client') as mock_boto3:
        with patch('notifications.notifier.get_config') as mock_config:
            config_mock = Mock()
            config_mock.get_str.return_value = 'test-bucket'
            config_mock.is_lean_mode.return_value = True
            mock_config.return_value = config_mock
            
            # Mock S3 client to raise exception
            mock_s3 = Mock()
            mock_s3.list_objects_v2.side_effect = Exception("S3 connection failed")
            mock_boto3.return_value = mock_s3
            
            generator = DailyDigestGenerator()
            
            # This should handle the error gracefully
            result = generator.generate_and_send_digest('2025-01-22')
            
            assert 'error_count' in result['metrics'], "Error count not tracked"
            assert result['metrics']['error_count'] > 0, "Error not counted"
            assert not result['digest_generated'], "Digest should not be marked as generated"
            assert not result['email_sent'], "Email should not be marked as sent"
            
            print("✓ Error handling works correctly")

def test_config_integration():
    """Test integration with config system."""
    print("Testing config integration...")
    
    with patch('notifications.notifier.get_config') as mock_config:
        config_mock = Mock()
        config_mock.get_str.return_value = 'test-value'
        config_mock.is_lean_mode.return_value = True
        mock_config.return_value = config_mock
        
        with patch('boto3.client') as mock_boto3:
            generator = DailyDigestGenerator()
            
            # Verify config is being used
            assert generator.s3_bucket == 'test-value', "S3 bucket not set from config"
            
            # Verify config calls
            config_mock.get_str.assert_called()
            
            print("✓ Config integration works correctly")

def run_all_tests():
    """Run all tests."""
    print("Running Daily Digest Notifier Tests...\n")
    
    tests = [
        test_candidate_filtering,
        test_html_generation,
        test_csv_generation,
        test_error_handling,
        test_config_integration
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()
    
    print(f"Test Results: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)