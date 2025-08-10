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
    """Load all existing properties from DynamoDB with robust ID extraction"""
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
                raw_property_id = None
                
                # Method 1: Extract from property_id field (format: PROP#YYYYMMDD_123456)
                if property_id and '#' in property_id and '_' in property_id:
                    try:
                        # Split on '#' and then on '_' to get the raw ID
                        parts = property_id.split('#')
                        if len(parts) >= 2:
                            date_and_id = parts[1]  # Get "YYYYMMDD_123456"
                            if '_' in date_and_id:
                                raw_property_id = date_and_id.split('_', 1)[1]  # Get "123456"
                    except (IndexError, ValueError):
                        pass
                
                # Method 2: Fallback to extracting from listing_url if property_id extraction failed
                if not raw_property_id:
                    listing_url = item.get('listing_url', '')
                    if listing_url:
                        raw_property_id = extract_property_id_from_url(listing_url)
                
                # If we successfully extracted an ID, add it to the dictionary
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
            # Debug: Show sample IDs being loaded
            sample_ids = list(existing_properties.keys())[:10]
            logger.debug(f"Sample existing IDs: {sample_ids}")
        
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

def setup_url_tracking_table(table_name='tokyo-real-estate-ai-urls', logger=None):
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

def put_url_to_tracking_table(url, table, ward=None, logger=None):
    """Add URL to tracking table with ward information"""
    try:
        item = {
            'url': url,
            'processed': '',
        }
        if ward:
            item['ward'] = ward
        
        table.put_item(Item=item)
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to put URL {url}: {str(e)}")
        return False

def put_urls_batch_to_tracking_table(urls, table, ward=None, logger=None):
    """Add multiple URLs to tracking table in batch with ward and price information"""
    if not urls:
        return 0
    
    try:
        saved_count = 0
        
        with table.batch_writer() as batch:
            for url_item in urls:
                try:
                    # Handle both string URLs and dict URLs
                    if isinstance(url_item, dict):
                        url = url_item.get('url')
                        price = url_item.get('price', 0)
                    else:
                        url = url_item
                        price = 0
                    
                    item = {
                        'url': url,
                        'processed': '',
                        'price': price  # Add price to tracking table
                    }
                    if ward:
                        item['ward'] = ward
                    
                    batch.put_item(Item=item)
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

def batch_update_price_changes(price_changes, table, logger=None):
    """
    Batch update all price changes - simplified version with no history records.
    Just updates the main property record with price tracking fields.
    
    Price tracking fields added/updated:
    - price: Current price (updated)
    - original_price: First price ever seen (set once, never changes)
    - previous_price: Price before this change
    - last_price_change: Amount of this specific change ($)
    - last_price_change_pct: Percentage of this specific change (%)
    - total_price_change: Total change from original price ($)
    - total_price_change_pct: Total change from original price (%)
    - price_update_count: Number of times price has been updated
    - last_price_update: Timestamp of this price update
    - price_history: Simple list of {date, price} entries
    
    Args:
        price_changes: List of dicts with structure:
            {
                'property_id': 'PROP#20241220_123456',
                'url': 'https://...',
                'old_price': 1000,
                'new_price': 950
            }
        table: DynamoDB table resource
        logger: Optional logger instance
    
    Returns:
        Number of successful updates
    """
    successful_updates = 0
    failed_updates = 0
    now = datetime.now()
    
    if not price_changes:
        return 0
    
    for change in price_changes:
        try:
            property_id = change['property_id']
            old_price = change['old_price']
            new_price = change['new_price']
            
            # Calculate price change metrics
            price_change_amt = new_price - old_price
            price_change_pct = (price_change_amt / old_price * 100) if old_price > 0 else 0
            
            # First, get the current record to check for original_price
            # We need this to calculate total change from original
            try:
                response = table.get_item(
                    Key={
                        'property_id': property_id,
                        'sort_key': 'META'
                    },
                    ProjectionExpression='original_price, price_update_count'
                )
                
                if 'Item' not in response:
                    if logger:
                        logger.warning(f"Property {property_id} not found in database")
                    failed_updates += 1
                    continue
                
                existing_item = response['Item']
                existing_original_price = existing_item.get('original_price')
                existing_update_count = int(existing_item.get('price_update_count', 0))
                
            except Exception as e:
                if logger:
                    logger.error(f"Failed to get existing record for {property_id}: {str(e)}")
                failed_updates += 1
                continue
            
            # Build the update expression based on whether original_price exists
            if existing_original_price is None:
                # First time tracking price - set original_price to the old price
                original_price = old_price
                total_change = new_price - original_price
                total_change_pct = (total_change / original_price * 100) if original_price > 0 else 0
                
                update_expression = """
                    SET price = :new_price,
                        original_price = :original_price,
                        previous_price = :old_price,
                        last_price_change = :last_change,
                        last_price_change_pct = :last_change_pct,
                        total_price_change = :total_change,
                        total_price_change_pct = :total_change_pct,
                        price_update_count = :update_count,
                        last_price_update = :now,
                        price_history = list_append(if_not_exists(price_history, :empty_list), :price_entry)
                """
                
                expression_values = {
                    ':new_price': Decimal(str(new_price)),
                    ':original_price': Decimal(str(old_price)),  # Set original to the old price
                    ':old_price': Decimal(str(old_price)),
                    ':last_change': Decimal(str(price_change_amt)),
                    ':last_change_pct': Decimal(str(round(price_change_pct, 2))),
                    ':total_change': Decimal(str(total_change)),
                    ':total_change_pct': Decimal(str(round(total_change_pct, 2))),
                    ':update_count': existing_update_count + 1,
                    ':now': now.isoformat(),
                    ':empty_list': [],
                    ':price_entry': [{
                        'date': now.strftime('%Y-%m-%d'),
                        'price': Decimal(str(new_price))
                    }]
                }
            else:
                # Original price already exists - calculate total change from original
                original_price = float(existing_original_price)
                total_change = new_price - original_price
                total_change_pct = (total_change / original_price * 100) if original_price > 0 else 0
                
                update_expression = """
                    SET price = :new_price,
                        previous_price = :old_price,
                        last_price_change = :last_change,
                        last_price_change_pct = :last_change_pct,
                        total_price_change = :total_change,
                        total_price_change_pct = :total_change_pct,
                        price_update_count = :update_count,
                        last_price_update = :now,
                        price_history = list_append(if_not_exists(price_history, :empty_list), :price_entry)
                """
                
                expression_values = {
                    ':new_price': Decimal(str(new_price)),
                    ':old_price': Decimal(str(old_price)),
                    ':last_change': Decimal(str(price_change_amt)),
                    ':last_change_pct': Decimal(str(round(price_change_pct, 2))),
                    ':total_change': Decimal(str(total_change)),
                    ':total_change_pct': Decimal(str(round(total_change_pct, 2))),
                    ':update_count': existing_update_count + 1,
                    ':now': now.isoformat(),
                    ':empty_list': [],
                    ':price_entry': [{
                        'date': now.strftime('%Y-%m-%d'),
                        'price': Decimal(str(new_price))
                    }]
                }
            
            # Update the property record (non-destructively)
            try:
                table.update_item(
                    Key={
                        'property_id': property_id,
                        'sort_key': 'META'
                    },
                    UpdateExpression=update_expression,
                    ExpressionAttributeValues=expression_values,
                    ConditionExpression="attribute_exists(property_id)"  # Only update if exists
                )
                
                successful_updates += 1
                
                if logger:
                    direction = "↑" if price_change_amt > 0 else "↓"
                    logger.info(f"Price updated for {property_id}: {old_price:,} → {new_price:,} "
                               f"({direction}{abs(price_change_pct):.1f}%) | "
                               f"Total from original: {direction}{abs(total_change_pct):.1f}%")
                
            except Exception as e:
                if 'ConditionalCheckFailedException' in str(e):
                    if logger:
                        logger.warning(f"Property {property_id} not found in database")
                else:
                    if logger:
                        logger.error(f"Failed to update price for {property_id}: {str(e)}")
                failed_updates += 1
                
        except Exception as e:
            failed_updates += 1
            if logger:
                logger.error(f"Error processing price change: {str(e)}")
    
    # Summary logging
    if logger:
        logger.info(f"Price update complete: {successful_updates} successful, {failed_updates} failed out of {len(price_changes)} total")
        
        if successful_updates > 0:
            increases = sum(1 for c in price_changes[:successful_updates] if c['new_price'] > c['old_price'])
            decreases = sum(1 for c in price_changes[:successful_updates] if c['new_price'] < c['old_price'])
            logger.info(f"Price movements: {increases} increases, {decreases} decreases")
    
    return successful_updates
