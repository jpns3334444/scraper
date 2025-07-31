#!/usr/bin/env python3
"""
Debug script to test price extraction from homes.co.jp
"""
import sys
import os
sys.path.append('/home/azure/Projects/real-estate-scraper/ai_infra/lambda/url_collector')

from core_scraper import collect_area_listings_with_prices, create_session, discover_tokyo_areas
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_price_extraction():
    """Test price extraction for a specific area"""
    session = create_session(logger)
    
    try:
        # First discover actual Tokyo areas
        logger.info("Discovering Tokyo areas...")
        areas = discover_tokyo_areas(logger)
        logger.info(f"Found {len(areas)} areas: {areas[:10]}...")  # Show first 10
        
        if not areas:
            logger.error("No areas discovered!")
            return
        
        # Use the first available area for testing
        test_area = areas[0]
        logger.info(f"Testing price extraction for area: {test_area}")
        listings = collect_area_listings_with_prices(test_area, max_pages=1, session=session, logger=logger)
        
        if not listings:
            logger.error("No working area found!")
            return
            
        logger.info(f"Found {len(listings)} listings")
        
        # Print first 5 listings to see the data structure
        for i, listing in enumerate(listings[:5]):
            logger.info(f"Listing {i+1}:")
            logger.info(f"  URL: {listing.get('url', 'N/A')}")
            logger.info(f"  Price: {listing.get('price', 'N/A')}")
            logger.info(f"  Price Text: {listing.get('price_text', 'N/A')}")
            logger.info(f"  Ward: {listing.get('ward', 'N/A')}")
            logger.info("  ---")
        
        # Count how many have prices
        with_prices = [l for l in listings if l.get('price', 0) > 0]
        logger.info(f"Listings with prices: {len(with_prices)} out of {len(listings)}")
        
        if with_prices:
            avg_price = sum(l['price'] for l in with_prices) / len(with_prices)
            logger.info(f"Average price: {avg_price:.0f} man-yen")
        
    except Exception as e:
        logger.error(f"Error during price extraction test: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    test_price_extraction()