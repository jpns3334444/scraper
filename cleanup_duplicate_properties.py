#!/usr/bin/env python3
"""
Clean up duplicate Suumo properties by removing old entries without images
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
    print("Finding duplicate Suumo properties to clean up...")
    
    # Dictionary to track properties by their raw ID
    properties_by_raw_id = defaultdict(list)
    
    # Scan for all properties
    scan_kwargs = {
        'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
    }
    
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        for item in items:
            listing_url = item.get('listing_url', '')
            
            if is_suumo_url(listing_url):
                property_id = item.get('property_id', '')
                
                # Extract raw ID without date prefix
                if property_id and '#' in property_id and '_' in property_id:
                    parts = property_id.split('#')[1].split('_')
                    date_part = parts[0]
                    raw_id = parts[1]
                    
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
    
    # Find properties to delete (old versions without images where new version has images)
    properties_to_delete = []
    
    for raw_id, entries in properties_by_raw_id.items():
        if len(entries) > 1:
            sorted_entries = sorted(entries, key=lambda x: x['date'])
            
            # Check each pair of duplicates
            for i in range(len(sorted_entries) - 1):
                old = sorted_entries[i]
                new = sorted_entries[i + 1]
                
                # Delete old version if it has no images and new version has images
                if not old['photo_filenames'] and new['photo_filenames']:
                    properties_to_delete.append(old['property_id'])
                # Also delete old version if both have no images (no point keeping duplicates)
                elif not old['photo_filenames'] and not new['photo_filenames']:
                    properties_to_delete.append(old['property_id'])
    
    print(f"\n=== CLEANUP SUMMARY ===")
    print(f"Properties to delete: {len(properties_to_delete)}")
    
    if properties_to_delete:
        print(f"\nExamples of properties to delete (first 10):")
        for prop_id in properties_to_delete[:10]:
            print(f"  - {prop_id}")
        
        print(f"\nProceeding to delete {len(properties_to_delete)} duplicate entries...")
        
        deleted_count = 0
        error_count = 0
        
        for prop_id in properties_to_delete:
            try:
                # Delete the META record
                table.delete_item(
                    Key={
                        'property_id': prop_id,
                        'sort_key': 'META'
                    }
                )
                deleted_count += 1
                
                if deleted_count % 100 == 0:
                    print(f"Progress: {deleted_count}/{len(properties_to_delete)}")
                    
            except Exception as e:
                print(f"Error deleting {prop_id}: {e}")
                error_count += 1
        
        print(f"\n=== CLEANUP COMPLETE ===")
        print(f"Successfully deleted: {deleted_count}")
        print(f"Errors: {error_count}")
        print(f"Total processed: {deleted_count + error_count}")
        
    else:
        print("No properties need to be deleted!")

if __name__ == '__main__':
    main()