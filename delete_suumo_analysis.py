#!/usr/bin/env python3
"""
Delete all Suumo items from the analysis table
"""
import boto3
from boto3.dynamodb.conditions import Attr

def delete_suumo_analysis():
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    table = dynamodb.Table('tokyo-real-estate-ai-analysis-db')
    
    print("Scanning for Suumo items in analysis table...")
    
    # Scan for all items with Suumo URLs
    scan_kwargs = {
        'FilterExpression': Attr('listing_url').contains('suumo')
    }
    
    total_deleted = 0
    batch_count = 0
    
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        if items:
            batch_count += 1
            print(f"\nBatch {batch_count}: Found {len(items)} Suumo items to delete...")
            
            # Delete items in batches
            with table.batch_writer() as batch:
                for item in items:
                    # Delete using the primary key
                    batch.delete_item(Key={
                        'property_id': item['property_id'],
                        'sort_key': item['sort_key']
                    })
                    total_deleted += 1
                    
                    if total_deleted % 50 == 0:
                        print(f"  Deleted {total_deleted} items...")
        
        # Check if there are more items to scan
        if 'LastEvaluatedKey' not in response:
            break
        
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    print(f"\n✅ Successfully deleted {total_deleted} Suumo items from analysis table")
    return total_deleted

if __name__ == "__main__":
    delete_suumo_analysis()