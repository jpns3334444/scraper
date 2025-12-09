"""
Fix for property_id generation to reuse existing IDs instead of creating duplicates
"""
import boto3
from datetime import datetime

def get_existing_property_id(raw_property_id, table, logger=None):
    """Check if property already exists and return its existing property_id"""
    try:
        # Scan for any property with this raw ID (regardless of date prefix)
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('sort_key').eq('META'),
            ProjectionExpression='property_id'
        )
        
        for item in response.get('Items', []):
            existing_id = item.get('property_id', '')
            if existing_id and '#' in existing_id and '_' in existing_id:
                parts = existing_id.split('#')[1].split('_')
                if len(parts) > 1 and parts[1] == raw_property_id:
                    if logger:
                        logger.debug(f"Found existing property_id: {existing_id} for raw ID: {raw_property_id}")
                    return existing_id
        
        # Continue scanning if there are more pages
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('sort_key').eq('META'),
                ProjectionExpression='property_id',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            
            for item in response.get('Items', []):
                existing_id = item.get('property_id', '')
                if existing_id and '#' in existing_id and '_' in existing_id:
                    parts = existing_id.split('#')[1].split('_')
                    if len(parts) > 1 and parts[1] == raw_property_id:
                        if logger:
                            logger.debug(f"Found existing property_id: {existing_id} for raw ID: {raw_property_id}")
                        return existing_id
    
    except Exception as e:
        if logger:
            logger.warning(f"Error checking for existing property: {e}")
    
    return None

def create_or_get_property_id(raw_property_id, table=None, logger=None):
    """Create new property_id or return existing one to avoid duplicates"""
    # First check if property already exists
    if table:
        existing_id = get_existing_property_id(raw_property_id, table, logger)
        if existing_id:
            return existing_id
    
    # If not found, create new with current date
    date_str = datetime.now().strftime('%Y%m%d')
    return f"PROP#{date_str}_{raw_property_id}"