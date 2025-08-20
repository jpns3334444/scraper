#!/usr/bin/env python3
"""
Check Suumo properties in DynamoDB to see which ones have images vs which ones don't
"""
import boto3
import json
from urllib.parse import urlparse

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

# Setup DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=config['core']['AWS_REGION'])
table = dynamodb.Table(config['dynamodb']['DDB_PROPERTIES'])

def is_suumo_url(url):
    """Check if URL is from Suumo"""
    return 'suumo.jp' in url

def main():
    print("Checking Suumo properties for image status...")
    
    # Scan for all properties
    scan_kwargs = {
        'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
    }
    
    suumo_total = 0
    suumo_with_images = 0
    suumo_without_images = 0
    suumo_with_filenames = 0
    suumo_with_empty_filenames = 0
    
    properties_without_images = []
    properties_with_images = []
    
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        for item in items:
            listing_url = item.get('listing_url', '')
            
            if is_suumo_url(listing_url):
                suumo_total += 1
                property_id = item.get('property_id', '')
                photo_filenames = item.get('photo_filenames', '')
                image_count = int(item.get('image_count', 0))
                
                property_info = {
                    'property_id': property_id,
                    'url': listing_url,
                    'photo_filenames': photo_filenames,
                    'image_count': image_count,
                    'ward': item.get('ward', 'Unknown')
                }
                
                if photo_filenames and photo_filenames.strip():
                    suumo_with_filenames += 1
                    if image_count > 0:
                        suumo_with_images += 1
                        properties_with_images.append(property_info)
                    else:
                        suumo_without_images += 1
                        properties_without_images.append(property_info)
                else:
                    suumo_with_empty_filenames += 1
                    suumo_without_images += 1
                    properties_without_images.append(property_info)
        
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    print(f"\n=== SUUMO PROPERTIES IMAGE ANALYSIS ===")
    print(f"Total Suumo properties: {suumo_total}")
    print(f"Properties with images: {suumo_with_images} ({(suumo_with_images/suumo_total*100):.1f}%)")
    print(f"Properties without images: {suumo_without_images} ({(suumo_without_images/suumo_total*100):.1f}%)")
    print(f"Properties with photo_filenames field: {suumo_with_filenames}")
    print(f"Properties with empty photo_filenames: {suumo_with_empty_filenames}")
    
    # Show some examples of properties without images
    print(f"\n=== EXAMPLES OF PROPERTIES WITHOUT IMAGES ===")
    for i, prop in enumerate(properties_without_images[:10]):
        print(f"{i+1}. {prop['property_id']} - {prop['ward']}")
        print(f"   URL: {prop['url']}")
        print(f"   photo_filenames: '{prop['photo_filenames']}'")
        print(f"   image_count: {prop['image_count']}")
        print()
    
    # Show some examples of properties with images
    if properties_with_images:
        print(f"\n=== EXAMPLES OF PROPERTIES WITH IMAGES ===")
        for i, prop in enumerate(properties_with_images[:5]):
            print(f"{i+1}. {prop['property_id']} - {prop['ward']}")
            print(f"   URL: {prop['url']}")
            print(f"   photo_filenames: '{prop['photo_filenames'][:100]}...'")
            print(f"   image_count: {prop['image_count']}")
            print()
    
    # Check for pattern in URLs without images
    print(f"\n=== URL PATTERN ANALYSIS FOR MISSING IMAGES ===")
    no_image_urls = [prop['url'] for prop in properties_without_images[:20]]
    with_image_urls = [prop['url'] for prop in properties_with_images[:20]]
    
    print("URLs without images (first 20):")
    for url in no_image_urls:
        print(f"  {url}")
    
    if with_image_urls:
        print(f"\nURLs with images (first 20):")
        for url in with_image_urls:
            print(f"  {url}")

if __name__ == '__main__':
    main()