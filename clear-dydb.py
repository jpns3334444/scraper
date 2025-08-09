#!/usr/bin/env python3
"""
Script to delete all data from DynamoDB tables
WARNING: This will permanently delete all data!
"""
import boto3
from boto3.dynamodb.conditions import Key
import time
import sys
from pathlib import Path

# Add scripts directory to path and load config
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
from load_config import load_config
config = load_config()

def clear_dynamodb_table(table_name, region=None):
    """Delete all items from a DynamoDB table"""
    
    region = region or config.get('AWS_REGION', 'ap-northeast-1')
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    print(f"\n{'='*60}")
    print(f"WARNING: About to delete ALL data from table: {table_name}")
    print(f"{'='*60}")
    
    # Get confirmation
    confirmation = input(f"Type 'Y' to confirm: ")
    if confirmation != "Y":
        print("Deletion cancelled.")
        return
    
    print(f"\nDeleting all items from {table_name}...")
    
    deleted_count = 0
    scan_kwargs = {}
    
    try:
        # Scan and delete in batches
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            if not items:
                break
            
            # Delete items in batches of 25 (DynamoDB limit)
            with table.batch_writer() as batch:
                for item in items:
                    # Get the key fields for this table
                    if table_name == config.get('DDB_URL_TRACKING', 'tokyo-real-estate-ai-urls'):
                        # URL tracking table has 'url' as primary key
                        batch.delete_item(Key={'url': item['url']})
                    else:
                        # Main table has composite key
                        batch.delete_item(Key={
                            'property_id': item['property_id'],
                            'sort_key': item['sort_key']
                        })
                    deleted_count += 1
                    
                    if deleted_count % 100 == 0:
                        print(f"  Deleted {deleted_count} items...")
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' in response:
                scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            else:
                break
            
            # Small delay to avoid throttling
            time.sleep(0.1)
        
        print(f"\n✓ Successfully deleted {deleted_count} items from {table_name}")
        
    except Exception as e:
        print(f"\n✗ Error deleting from {table_name}: {str(e)}")
        return False
    
    return True

def main():
    """Main function to clear tables"""
    
    print("\nDynamoDB Table Cleanup Script")
    print("=============================")
    
    # Define tables from config
    tables = [
        config.get('DDB_URL_TRACKING', 'tokyo-real-estate-ai-urls'),
        config.get('DDB_PROPERTIES', 'tokyo-real-estate-ai-analysis-db')
    ]
    
    print("\nThis script will delete ALL data from the following tables:")
    for table in tables:
        print(f"  - {table}")
    
    print("\n⚠️  THIS ACTION CANNOT BE UNDONE! ⚠️")
    
    
    # Clear each table
    for table_name in tables:
        clear_dynamodb_table(table_name)
    
    print("\n✅ Table cleanup complete!")
    print("\nNext steps:")
    print("1. Run the URL collector Lambda to populate fresh URLs with ward data")
    print("2. Run the property processor Lambda to scrape properties")
    print("3. Run the property analyzer Lambda to score properties")

if __name__ == "__main__":
    main()