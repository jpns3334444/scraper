#!/usr/bin/env python3
"""
Delete all Suumo URLs from the URL tracking table
"""
import boto3
from boto3.dynamodb.conditions import Attr

def delete_suumo_urls():
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    table = dynamodb.Table('tokyo-real-estate-ai-urls')
    
    print("Scanning for Suumo URLs in tracking table...")
    
    # Scan for all items with Suumo URLs
    scan_kwargs = {
        'FilterExpression': Attr('url').contains('suumo')
    }
    
    total_deleted = 0
    batch_count = 0
    
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        if items:
            batch_count += 1
            print(f"\nBatch {batch_count}: Found {len(items)} Suumo URLs to delete...")
            
            # Delete items in batches
            with table.batch_writer() as batch:
                for item in items:
                    # Delete using the primary key (url)
                    batch.delete_item(Key={
                        'url': item['url']
                    })
                    total_deleted += 1
                    
                    if total_deleted % 100 == 0:
                        print(f"  Deleted {total_deleted} URLs...")
        
        # Check if there are more items to scan
        if 'LastEvaluatedKey' not in response:
            break
        
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    print(f"\n✅ Successfully deleted {total_deleted} Suumo URLs from tracking table")
    return total_deleted

if __name__ == "__main__":
    delete_suumo_urls()