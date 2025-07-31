#!/usr/bin/env python3
"""
Test script to verify that prices are being stored in the tracking table
"""
import sys
import os
sys.path.append('/home/azure/Projects/real-estate-scraper/ai_infra/lambda/url_collector')

from dynamodb_utils import setup_url_tracking_table, put_urls_batch_to_tracking_table, scan_unprocessed_urls
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_price_storage():
    """Test that prices can be stored and retrieved from tracking table"""
    
    try:
        # Setup tracking table
        logger.info("Setting up URL tracking table...")
        _, url_tracking_table = setup_url_tracking_table('tokyo-real-estate-ai-urls', logger)
        
        # Test data with prices
        test_urls = [
            {
                'url': 'https://www.homes.co.jp/mansion/b-test1',
                'price': 5000
            },
            {
                'url': 'https://www.homes.co.jp/mansion/b-test2', 
                'price': 7500
            },
            {
                'url': 'https://www.homes.co.jp/mansion/b-test3',
                'price': 0  # No price
            }
        ]
        
        # Store test URLs with prices
        logger.info("Storing test URLs with prices...")
        count = put_urls_batch_to_tracking_table(test_urls, url_tracking_table, ward='test-ward', logger=logger)
        logger.info(f"Stored {count} URLs")
        
        # Try to retrieve them
        logger.info("Retrieving unprocessed URLs...")
        unprocessed = scan_unprocessed_urls(url_tracking_table, logger)
        
        # Filter for our test URLs
        test_retrieved = [item for item in unprocessed if 'test' in item.get('url', '')]
        
        logger.info(f"Retrieved {len(test_retrieved)} test URLs:")
        for item in test_retrieved:
            logger.info(f"  URL: {item.get('url', 'N/A')}")
            logger.info(f"  Price: {item.get('price', 'N/A')}")
            logger.info(f"  Ward: {item.get('ward', 'N/A')}")
            logger.info("  ---")
        
        # Also check what's in the real table
        logger.info("Checking sample of real URLs...")
        real_urls = [item for item in unprocessed[:5] if 'test' not in item.get('url', '')]
        for item in real_urls:
            logger.info(f"  URL: {item.get('url', 'N/A')}")
            logger.info(f"  Price: {item.get('price', 'N/A')}")
            logger.info(f"  Ward: {item.get('ward', 'N/A')}")
            logger.info("  ---")
        
        # Clean up test data
        logger.info("Cleaning up test data...")
        for test_url in test_urls:
            try:
                url_tracking_table.delete_item(Key={'url': test_url['url']})
            except Exception as e:
                logger.warning(f"Failed to clean up {test_url['url']}: {e}")
        
        logger.info("Test completed successfully!")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")

if __name__ == "__main__":
    test_price_storage()