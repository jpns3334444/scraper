#!/usr/bin/env python3
"""
Fix Suumo properties that have image_count > 0 but empty photo_filenames
by resetting them back to unprocessed status for reprocessing
"""
import boto3
import json
from urllib.parse import urlparse

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

# Setup DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=config['core']['AWS_REGION'])
properties_table = dynamodb.Table(config['dynamodb']['DDB_PROPERTIES'])
url_tracking_table = dynamodb.Table(config['dynamodb']['DDB_URL_TRACKING'])

def is_suumo_url(url):
    """Check if URL is from Suumo"""
    return 'suumo.jp' in url

def main():
    print("Finding Suumo properties with missing images that need reprocessing...")
    
    # Scan for all Suumo properties with image_count > 0 but empty photo_filenames
    scan_kwargs = {
        'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
    }
    
    properties_to_fix = []
    
    while True:
        response = properties_table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        for item in items:
            listing_url = item.get('listing_url', '')
            
            if is_suumo_url(listing_url):
                photo_filenames = item.get('photo_filenames', '')
                image_count = int(item.get('image_count', 0))
                
                # Properties that have image_count > 0 but empty photo_filenames are broken
                if image_count > 0 and (not photo_filenames or not photo_filenames.strip()):
                    properties_to_fix.append({
                        'property_id': item.get('property_id', ''),
                        'url': listing_url,
                        'image_count': image_count,
                        'analysis_date': item.get('analysis_date', ''),
                        'ward': item.get('ward', 'Unknown')
                    })
        
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    print(f"\n=== SUUMO PROPERTIES NEEDING IMAGE FIX ===")
    print(f"Found {len(properties_to_fix)} Suumo properties with broken images")
    
    # Group by date to understand the scope
    date_breakdown = {}
    for prop in properties_to_fix:
        analysis_date = prop['analysis_date'][:10] if prop['analysis_date'] else 'unknown'
        if analysis_date not in date_breakdown:
            date_breakdown[analysis_date] = 0
        date_breakdown[analysis_date] += 1
    
    print("\nBreakdown by analysis date:")
    for date, count in sorted(date_breakdown.items()):
        print(f"  {date}: {count} properties")
    
    # Show examples
    print(f"\nExamples of properties to fix (first 10):")
    for i, prop in enumerate(properties_to_fix[:10]):
        print(f"{i+1}. {prop['property_id']} - {prop['ward']}")
        print(f"   URL: {prop['url']}")
        print(f"   image_count: {prop['image_count']}, analysis_date: {prop['analysis_date']}")
        print()
    
    if len(properties_to_fix) == 0:
        print("No properties need fixing!")
        return
    
    # Proceed automatically with the reset
    print(f"\nProceeding to reset {len(properties_to_fix)} Suumo properties back to unprocessed status")
    print("so they can be reprocessed with proper image downloading.")
    
    print(f"\nResetting {len(properties_to_fix)} properties to unprocessed...")
    
    reset_count = 0
    error_count = 0
    
    # Reset each URL back to unprocessed
    for prop in properties_to_fix:
        try:
            url_tracking_table.update_item(
                Key={'url': prop['url']},
                UpdateExpression="SET #processed = :empty",
                ExpressionAttributeNames={'#processed': 'processed'},
                ExpressionAttributeValues={':empty': ''}
            )
            reset_count += 1
            
            if reset_count % 100 == 0:
                print(f"Progress: {reset_count}/{len(properties_to_fix)}")
                
        except Exception as e:
            print(f"Error resetting {prop['url']}: {e}")
            error_count += 1
    
    print(f"\n=== RESET COMPLETE ===")
    print(f"Successfully reset: {reset_count}")
    print(f"Errors: {error_count}")
    print(f"Total processed: {reset_count + error_count}")
    
    print(f"\nThese properties will now be reprocessed with proper Suumo image downloading.")
    print(f"Run the property processor to fix them: ./trigger-lambda.sh property_processor")

if __name__ == '__main__':
    main()