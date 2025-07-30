#!/usr/bin/env python3
"""
DynamoDB utilities for deduplication and data persistence
"""
import boto3
import re
from datetime import datetime
import time

def setup_dynamodb_client(logger=None):
    """Setup DynamoDB client and table reference"""
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table_name = 'tokyo-real-estate-ai-analysis-db'
        table = dynamodb.Table(table_name)
        
        # Test connection
        table.load()
        
        if logger:
            logger.debug(f"DynamoDB connected: {table_name}")
        
        return dynamodb, table
        
    except Exception as e:
        if logger:
            logger.error(f"DynamoDB setup failed: {str(e)}")
        raise

def extract_property_id_from_url(url):
    """Extract property ID from listing URL"""
    patterns = [
        r'/mansion/b-(\d+)/?$',
        r'/b-(\d+)/?$',
        r'property[_-]?id[=:](\d+)',
        r'mansion[_-]?(\d{8,})',
        r'/(\d{10,})/?$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None

def create_property_id_key(raw_property_id, date_str=None):
    """Create property_id key for DynamoDB"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    return f"PROP#{date_str}_{raw_property_id}"

def load_all_existing_properties(table, logger=None):
    """Load all existing properties from DynamoDB"""
    if logger:
        logger.info("Loading existing properties from DynamoDB...")
    
    existing_properties = {}
    
    try:
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        }
        
        items_processed = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                property_id = item.get('property_id', '')
                if property_id and '#' in property_id and '_' in property_id:
                    raw_property_id = property_id.split('#')[1].split('_')[1]
                    if raw_property_id:
                        existing_properties[raw_property_id] = {
                            'property_id': item.get('property_id'),
                            'price': int(item.get('price', 0)),
                            'listing_url': item.get('listing_url', ''),
                            'analysis_date': item.get('analysis_date', '')
                        }
                        items_processed += 1
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Loaded {items_processed} existing properties")
        
        return existing_properties
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to load properties: {str(e)}")
        return {}

def save_complete_properties_to_dynamodb(properties_data, config, logger=None):
    """Save successfully scraped properties to DynamoDB"""
    if not properties_data:
        return 0
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table_name = config.get('dynamodb_table', 'tokyo-real-estate-ai-analysis-db')
        table = dynamodb.Table(table_name)
        
        saved_count = 0
        error_count = 0
        
        # Filter out properties with errors
        successful_properties = [p for p in properties_data if 'error' not in p]
        
        if logger:
            logger.info(f"Saving {len(successful_properties)} properties to DynamoDB...")
        
        # Save in batches
        with table.batch_writer() as batch:
            for property_data in successful_properties:
                try:
                    record = create_complete_property_record(property_data, config, logger)
                    
                    if record and record.get('property_id') and record.get('sort_key'):
                        batch.put_item(Item=record)
                        saved_count += 1
                        
                        if saved_count % 25 == 0:
                            if logger:
                                logger.debug(f"Progress: {saved_count}/{len(successful_properties)}")
                    else:
                        error_count += 1
                        
                except Exception as e:
                    error_count += 1
                    if logger:
                        logger.error(f"Error saving property: {str(e)}")
        
        if logger:
            logger.debug(f"DynamoDB save complete: {saved_count} saved, {error_count} errors")
        
        return saved_count
        
    except Exception as e:
        if logger:
            logger.error(f"Fatal DynamoDB error: {str(e)}")
        return 0

def create_complete_property_record(property_data, config, logger=None):
    """Create a complete property record"""
    try:
        # Extract property ID
        if not property_data.get('property_id'):
            raw_property_id = extract_property_id_from_url(property_data.get('url', ''))
            if raw_property_id:
                property_data['property_id'] = create_property_id_key(raw_property_id)
        
        property_id = property_data.get('property_id')
        if not property_id:
            return None
        
        now = datetime.now()
        
        # Create record
        record = {
            'property_id': property_id,
            'sort_key': 'META',
            'listing_url': property_data.get('url', ''),
            'listing_status': 'scraped',
            'scraped_date': now.isoformat(),
            'analysis_date': now.isoformat(),
            'data_source': 'scraper_complete',
            'analysis_yymm': now.strftime('%Y-%m'),
            'invest_partition': 'SCRAPED',
            
            # Property details
            'price': property_data.get('price', 0),
            'price_display': property_data.get('価格', ''),
            'title': property_data.get('title', ''),
            'address': property_data.get('所在地', ''),
            'transportation': property_data.get('交通', ''),
            'building_age': property_data.get('築年月', ''),
            'floor_area': property_data.get('専有面積', ''),
            'balcony_area': property_data.get('バルコニー', ''),
            'floor_number': property_data.get('所在階', ''),
            'total_units': property_data.get('総戸数', ''),
            'layout': property_data.get('間取り', ''),
            'management_company': property_data.get('管理会社', ''),
            'management_fee': property_data.get('管理費', ''),
            'repair_fund': property_data.get('修繕積立金', ''),
            
            # Image data
            'photo_filenames': property_data.get('photo_filenames', ''),
            'image_count': property_data.get('image_count', 0),
            
            # Metadata
            'extraction_timestamp': property_data.get('extraction_timestamp', now.isoformat()),
            'scraper_session': config.get('session_id', 'unknown')
        }
        
        # Remove empty values
        record = {k: v for k, v in record.items() if v is not None and v != ''}
        
        return record
        
    except Exception as e:
        if logger:
            logger.error(f"Error creating record: {str(e)}")
        return None

def update_listing_with_price_change(existing_record, new_price, table, logger=None):
    """Update existing listing with new price"""
    try:
        property_id = existing_record['property_id']
        old_price = existing_record.get('price', 0)
        now = datetime.now()
        
        # Update META record
        table.update_item(
            Key={'property_id': property_id, 'sort_key': 'META'},
            UpdateExpression="SET price = :new_price, analysis_date = :now, listing_status = :status",
            ExpressionAttributeValues={
                ':new_price': new_price,
                ':now': now.isoformat(),
                ':status': 'price_updated'
            }
        )
        
        # Create price history record
        price_change = new_price - old_price
        price_change_pct = (price_change / old_price * 100) if old_price > 0 else 0
        
        hist_record = {
            'property_id': property_id,
            'sort_key': f"HIST#{now.strftime('%Y-%m-%d_%H:%M:%S')}",
            'price': new_price,
            'previous_price': old_price,
            'price_change_amount': price_change,
            'price_drop_pct': price_change_pct,
            'listing_status': 'price_updated',
            'analysis_date': now.isoformat(),
            'ttl_epoch': int(time.time()) + 60*60*24*365  # 1 year TTL
        }
        
        table.put_item(Item=hist_record)
        
        if logger:
            logger.debug(f"Updated price: {old_price:,} -> {new_price:,}")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to update price: {str(e)}")
        return False

def process_listings_with_existing_check(listings, existing_properties, logger=None):
    """Process listings to categorize as new, price changed, or unchanged"""
    new_urls = []
    price_changed_urls = []
    price_unchanged_urls = []
    
    for url in listings:
        raw_property_id = extract_property_id_from_url(url)
        if not raw_property_id:
            new_urls.append(url)
            continue
        
        if raw_property_id in existing_properties:
            # For now, treat all existing as unchanged
            # Price comparison would require fetching the listing page
            price_unchanged_urls.append(url)
        else:
            new_urls.append(url)
    
    return new_urls, price_changed_urls, price_unchanged_urls

# URL Tracking Table (DYDB2) Functions

def setup_url_tracking_table(table_name='tokyo-real-estate-urls', logger=None):
    """Setup URL tracking table reference"""
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table = dynamodb.Table(table_name)
        
        # Test connection
        table.load()
        
        if logger:
            logger.debug(f"URL tracking table connected: {table_name}")
        
        return dynamodb, table
        
    except Exception as e:
        if logger:
            logger.error(f"URL tracking table setup failed: {str(e)}")
        raise

def put_url_to_tracking_table(url, table, logger=None):
    """Add URL to tracking table with processed = empty"""
    try:
        table.put_item(
            Item={
                'url': url,
                'processed': ''
            }
        )
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to put URL {url}: {str(e)}")
        return False

def put_urls_batch_to_tracking_table(urls, table, logger=None):
    """Add multiple URLs to tracking table in batch"""
    if not urls:
        return 0
    
    try:
        saved_count = 0
        
        with table.batch_writer() as batch:
            for url in urls:
                try:
                    batch.put_item(
                        Item={
                            'url': url,
                            'processed': ''
                        }
                    )
                    saved_count += 1
                except Exception as e:
                    if logger:
                        logger.error(f"Failed to batch write URL {url}: {str(e)}")
        
        if logger:
            logger.debug(f"Batch wrote {saved_count} URLs to tracking table")
        
        return saved_count
        
    except Exception as e:
        if logger:
            logger.error(f"Batch write failed: {str(e)}")
        return 0

def scan_unprocessed_urls(table, logger=None):
    """Scan for all URLs where processed is empty"""
    unprocessed_urls = []
    
    try:
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('processed').eq('')
        }
        
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                url = item.get('url')
                if url:
                    unprocessed_urls.append(url)
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Found {len(unprocessed_urls)} unprocessed URLs")
        
        return unprocessed_urls
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to scan unprocessed URLs: {str(e)}")
        return []

def load_all_urls_from_tracking_table(table, logger=None):
    """Load ALL URLs from tracking table into a set for fast lookups"""
    if logger:
        logger.info("Loading all URLs from tracking table...")
    
    tracking_urls = set()
    
    try:
        scan_kwargs = {}
        
        items_processed = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                url = item.get('url')
                if url:
                    tracking_urls.add(url)
                    items_processed += 1
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Loaded {items_processed} URLs from tracking table")
        
        return tracking_urls
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to load URLs from tracking table: {str(e)}")
        return set()

def mark_url_processed(url, table, logger=None):
    """Mark URL as processed by setting processed = 'Y'"""
    try:
        table.update_item(
            Key={'url': url},
            UpdateExpression="SET processed = :processed",
            ExpressionAttributeValues={
                ':processed': 'Y'
            }
        )
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to mark URL processed {url}: {str(e)}")
        return False