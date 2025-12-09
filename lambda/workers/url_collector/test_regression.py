#!/usr/bin/env python3
from pathlib import Path
from core_scraper import extract_listings_with_prices_from_html

# Check if the test HTML file exists
html_path = Path('../../listingspage.html')
if html_path.exists():
    html = html_path.read_text(encoding='utf-8')
    data = extract_listings_with_prices_from_html(html)
    bad = [d for d in data if d['price'] == 0]
    print(f'Total rows: {len(data)}, zero-price rows: {len(bad)}')
    
    # Calculate percentage
    if data:
        percentage = (len(bad) / len(data)) * 100
        print(f'Zero-price percentage: {percentage:.1f}%')
        
        # Check for duplicate URLs
        urls = [d['url'] for d in data]
        unique_urls = set(urls)
        if len(urls) != len(unique_urls):
            print(f'WARNING: Found duplicate URLs! {len(urls)} total, {len(unique_urls)} unique')
        else:
            print(f'All {len(urls)} URLs are unique')
            
        # Show a few examples of extracted data
        print('\nFirst 5 listings:')
        for i, d in enumerate(data[:5]):
            print(f'  {i+1}. URL: {d["url"]}')
            print(f'     Price: {d["price"]} ({d["price_text"]})')
else:
    print('Error: listingspage.html not found in current directory')
    print('Current directory:', Path.cwd())
    print('Files in directory:', list(Path('.').glob('*.html'))[:5])