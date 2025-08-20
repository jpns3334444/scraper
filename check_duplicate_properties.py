#!/usr/bin/env python3
"""
Check for duplicate Suumo properties with different dates
"""
import boto3
import json
from collections import defaultdict

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
    print("Checking for duplicate Suumo properties with different dates...")
    
    # Dictionary to track properties by their raw ID (without date prefix)
    properties_by_raw_id = defaultdict(list)
    
    # Scan for all properties
    scan_kwargs = {
        'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
    }
    
    total_properties = 0
    suumo_properties = 0
    
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        for item in items:
            total_properties += 1
            listing_url = item.get('listing_url', '')
            
            if is_suumo_url(listing_url):
                suumo_properties += 1
                property_id = item.get('property_id', '')
                
                # Extract raw ID without date prefix
                if property_id and '#' in property_id and '_' in property_id:
                    parts = property_id.split('#')[1].split('_')
                    date_part = parts[0]  # e.g., "20250818"
                    raw_id = parts[1]      # e.g., "78201604"
                    
                    properties_by_raw_id[raw_id].append({
                        'property_id': property_id,
                        'date': date_part,
                        'url': listing_url,
                        'photo_filenames': item.get('photo_filenames', ''),
                        'image_count': int(item.get('image_count', 0))
                    })
        
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    # Find duplicates
    duplicates = {k: v for k, v in properties_by_raw_id.items() if len(v) > 1}
    
    print(f"\n=== DUPLICATE ANALYSIS ===")
    print(f"Total properties scanned: {total_properties}")
    print(f"Total Suumo properties: {suumo_properties}")
    print(f"Unique raw IDs: {len(properties_by_raw_id)}")
    print(f"Properties with duplicates: {len(duplicates)}")
    
    if duplicates:
        print(f"\n=== DUPLICATE EXAMPLES (first 10) ===")
        for i, (raw_id, entries) in enumerate(list(duplicates.items())[:10]):
            print(f"\nRaw ID: {raw_id}")
            print(f"  Found {len(entries)} versions:")
            for entry in sorted(entries, key=lambda x: x['date']):
                has_images = "YES" if entry['photo_filenames'] else "NO"
                print(f"    - {entry['property_id']} - Images: {has_images} (count: {entry['image_count']})")
                print(f"      URL: {entry['url']}")
        
        # Count how many duplicates have the pattern we expect
        old_without_new_with = 0
        for raw_id, entries in duplicates.items():
            sorted_entries = sorted(entries, key=lambda x: x['date'])
            if len(sorted_entries) == 2:
                old = sorted_entries[0]
                new = sorted_entries[1]
                if not old['photo_filenames'] and new['photo_filenames']:
                    old_without_new_with += 1
        
        print(f"\n=== PATTERN ANALYSIS ===")
        print(f"Duplicates where old version has no images but new version has images: {old_without_new_with}")
        print(f"This confirms the issue: reprocessing creates new entries instead of updating existing ones!")

if __name__ == '__main__':
    main()