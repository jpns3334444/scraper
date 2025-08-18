#!/usr/bin/env python3
"""
Reset processing status of Suumo URLs to allow reprocessing
"""
import boto3
from boto3.dynamodb.conditions import Attr

def reset_suumo_urls():
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    table = dynamodb.Table('tokyo-real-estate-ai-urls')
    
    print("Scanning for Suumo URLs to reset processing status...")
    
    # Scan for all items with Suumo URLs
    scan_kwargs = {
        'FilterExpression': Attr('url').contains('suumo')
    }
    
    total_reset = 0
    batch_count = 0
    
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        if items:
            batch_count += 1
            print(f"\nBatch {batch_count}: Found {len(items)} Suumo URLs to reset...")
            
            # Reset processing status in batches
            with table.batch_writer() as batch:
                for item in items:
                    # Update the item to remove processed status
                    batch.put_item(Item={
                        'url': item['url'],
                        'ward': item.get('ward', 'suumo'),
                        'first_seen': item.get('first_seen', ''),
                        'price': item.get('price', 0),
                        'price_text': item.get('price_text', ''),
                        # Remove 'processed' field or set to None to mark as unprocessed
                        'last_updated': item.get('last_updated', '')
                    })
                    total_reset += 1
                    
                    if total_reset % 100 == 0:
                        print(f"  Reset {total_reset} URLs...")
        
        # Check if there are more items to scan
        if 'LastEvaluatedKey' not in response:
            break
        
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    print(f"\n✅ Successfully reset {total_reset} Suumo URLs for reprocessing")
    return total_reset

if __name__ == "__main__":
    reset_suumo_urls()