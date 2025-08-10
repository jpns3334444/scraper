#!/usr/bin/env python3
"""Test script to verify image extraction fixes"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup
sys.path.insert(0, 'lambda/property_processor')
from core_scraper import collect_gallery_images, select_images_for_download
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def test_html_file(filepath):
    """Test image extraction on a single HTML file"""
    print(f"\n{'='*60}")
    print(f"Testing: {os.path.basename(filepath)}")
    print('='*60)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Test gallery image collection
    deduped_images, gallery_images = collect_gallery_images(soup, logger)
    
    # Check counts
    interior_count = gallery_images.get('interior', 0)
    exterior_count = gallery_images.get('exterior', 0)
    floorplan_count = gallery_images.get('floorplan', 0)
    
    print(f"\nImage counts from gallery:")
    print(f"  Interior: {interior_count}")
    print(f"  Exterior: {exterior_count}")
    print(f"  Floorplan: {floorplan_count}")
    print(f"  Total: {interior_count + exterior_count + floorplan_count}")
    
    # Test skip rule
    if interior_count == 0:
        print("\n❌ LISTING WOULD BE SKIPPED: No interior photos found")
        return False
    else:
        print("\n✅ LISTING WOULD BE PROCESSED: Interior photos found")
    
    # Test image selection
    selected_urls, breakdown = select_images_for_download(deduped_images, max_total=10, max_exterior=2, max_floorplan=1, logger=logger)
    selected = selected_urls  # For compatibility with rest of test
    
    print(f"\nSelected {len(selected)} images for download:")
    # Use the breakdown from the function instead of parsing URLs
    for img_type, count in breakdown.items():
        if count > 0:
            print(f"  {img_type}: {count}")
    
    # Verify limits
    if breakdown.get('floorplan', 0) > 1:
        print("  ⚠️ WARNING: More than 1 floorplan selected")
    if breakdown.get('exterior', 0) > 2:
        print("  ⚠️ WARNING: More than 2 exterior images selected")
    
    # Show sample of selected images
    print("\nSample of selected images:")
    for i, url in enumerate(selected[:5]):
        # Just show URLs since we don't have the metadata anymore
        print(f"  {i+1}. {url}")
    
    return True

def main():
    """Test both HTML files"""
    test_files = [
        'html/listingspage.html',
        'html/individual-homes-listing.html'
    ]
    
    results = []
    for filepath in test_files:
        if os.path.exists(filepath):
            result = test_html_file(filepath)
            results.append((filepath, result))
        else:
            print(f"File not found: {filepath}")
            results.append((filepath, None))
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    for filepath, result in results:
        status = "✅ PASS" if result else "❌ SKIP" if result is False else "⚠️ NOT FOUND"
        print(f"{os.path.basename(filepath)}: {status}")

if __name__ == "__main__":
    main()