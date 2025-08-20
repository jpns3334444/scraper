#!/usr/bin/env python3
"""
DynamoDB utilities for deduplication and data persistence
"""
import boto3
import re
from datetime import datetime
import time
from decimal import Decimal

def convert_to_decimal(value):
    """Convert numeric values to Decimal for DynamoDB"""
    if isinstance(value, float):
        # Convert float to string first to avoid precision issues
        return Decimal(str(value))
    elif isinstance(value, int):
        return Decimal(value)
    return value

def prepare_for_dynamodb(record):
    """Recursively convert all numeric values to Decimal for DynamoDB"""
    def convert_value(v):
        if isinstance(v, float):
            return Decimal(str(v))
        elif isinstance(v, int):
            return Decimal(v)
        elif isinstance(v, dict):
            return {k: convert_value(val) for k, val in v.items()}
        elif isinstance(v, list):
            return [convert_value(item) for item in v]
        return v
    
    return {k: convert_value(v) for k, v in record.items()}

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
        r'/mansion/b-(\d+)',  # Homes.co.jp format
        r'/b-(\d+)',          # Homes.co.jp format (flexible)
        r'/nc_(\d+)',         # Suumo format: /nc_78166592/
        r'property[_-]?id[=:](\d+)',
        r'mansion[_-]?(\d{8,})',
        r'/(\d{10,})'         # Generic long number format
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    # Debug: print URL if no match found (only first few to avoid spam)
    import random
    if random.random() < 0.1:  # Only log 10% of failures to avoid spam
        print(f"DEBUG: Could not extract property ID from URL: {url}")
    return None

def create_property_id_key(raw_property_id, date_str=None):
    """Create property_id key for DynamoDB"""
    # Simplified: just use raw ID without date to prevent duplicates
    return f"PROP#{raw_property_id}"

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
                if property_id and '#' in property_id:
                    # Handle both old format (PROP#date_id) and new format (PROP#id)
                    parts = property_id.split('#')[1]
                    if '_' in parts:
                        raw_property_id = parts.split('_')[1]  # Old format
                    else:
                        raw_property_id = parts  # New format
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
        
        # Filter out properties with errors or skip reasons
        successful_properties = [p for p in properties_data if 'error' not in p and 'skip_reason' not in p]
        
        if logger:
            logger.info(f"Saving {len(successful_properties)} properties to DynamoDB...")
        
        # Load existing properties for price change tracking
        existing_properties = load_all_existing_properties(table, logger)
        
        # Save in batches  
        if logger:
            logger.debug(f"Starting DynamoDB batch write for {len(successful_properties)} properties")
        
        # Check for duplicate property_ids before saving
        property_ids = []
        for prop in successful_properties:
            pid = prop.get('property_id')
            if pid:
                property_ids.append(pid)
        
        unique_ids = set(property_ids)
        if len(unique_ids) != len(property_ids):
            if logger:
                logger.warning(f"Found duplicate property_ids! {len(property_ids)} total vs {len(unique_ids)} unique")
                # Find duplicates
                seen = set()
                duplicates = set()
                for pid in property_ids:
                    if pid in seen:
                        duplicates.add(pid)
                    seen.add(pid)
                logger.warning(f"Duplicate property_ids: {list(duplicates)}")
        
        with table.batch_writer() as batch:
            for property_data in successful_properties:
                try:
                    extras = property_data.pop('_extras', None)
                    record = create_complete_property_record(property_data, config, logger, existing_properties, extras)
                    
                    if record and record.get('property_id') and record.get('sort_key'):
                        # Ensure all values are DynamoDB-compatible
                        record = prepare_for_dynamodb(record)
                        batch.put_item(Item=record)
                        saved_count += 1
                        
                        if saved_count % 25 == 0:
                            if logger:
                                logger.debug(f"Progress: {saved_count}/{len(successful_properties)}")
                    else:
                        error_count += 1
                        if logger:
                            url = property_data.get('url', 'unknown')
                            property_id = property_data.get('property_id', 'missing')
                            logger.error(f"Failed to create valid record for {url} - property_id: {property_id}, record: {record is not None}")
                        
                except Exception as e:
                    error_count += 1
                    url = property_data.get('url', 'unknown')
                    if logger:
                        logger.error(f"Error saving property {url}: {str(e)}")
        
        if logger:
            logger.debug(f"DynamoDB save complete: {saved_count} saved, {error_count} errors")
        
        return saved_count
        
    except Exception as e:
        if logger:
            logger.error(f"Fatal DynamoDB error: {str(e)}")
        return 0

def create_complete_property_record(property_data, config, logger=None, existing_properties=None, extras=None):
    """Create a complete property record with all enriched fields and price tracking"""
    try:
        # Extract property ID - use existing if available
        property_id = property_data.get('property_id')
        raw_property_id = None
        
        if not property_id:
            raw_property_id = extract_property_id_from_url(property_data.get('url', ''))
            if raw_property_id:
                property_id = create_property_id_key(raw_property_id)
                property_data['property_id'] = property_id
            else:
                if logger:
                    url = property_data.get('url', 'unknown')
                    logger.error(f"No property_id could be created for URL: {url}")
                return None
        else:
            # Extract raw_property_id from existing property_id
            if '#' in property_id:
                raw_property_id = property_id.split('#')[1]
        
        # Check for existing property to track price changes
        current_price = int(property_data.get('price', 0)) if property_data.get('price') else 0
        previous_price = None
        
        if existing_properties and raw_property_id and raw_property_id in existing_properties:
            existing_data = existing_properties[raw_property_id]
            existing_price = existing_data.get('price', 0)
            
            # Only set previous_price if there's actually a price change
            if existing_price != current_price and existing_price > 0:
                previous_price = existing_price
                if logger:
                    logger.debug(f"Price change detected for {raw_property_id}: {existing_price} -> {current_price}")
            elif logger:
                logger.debug(f"No price change for {raw_property_id}: {existing_price}")
        
        # Remove verbose debug logging - only log errors
        # if logger:
        #     logger.debug(f"Using property_id: {property_id} for URL: {property_data.get('url', 'unknown')}")
        
        now = datetime.now()
        
        # Create district key for GSI
        ward = property_data.get('ward', '')
        district_key = f"DIST#{ward}" if ward else None
        
        # Create record with essential fields only (cleaned up from 50+ to ~30 fields)
        record = {
            # Primary key
            'property_id': property_id,
            'sort_key': 'META',
            
            # Core property data
            'listing_url': property_data.get('url', ''),
            'title': property_data.get('title', ''),
            'address': property_data.get('address') or property_data.get('所在地', ''),
            
            # Core numeric fields (normalized)
            'price': current_price,
            'size_sqm': float(property_data.get('size_sqm', 0)) if property_data.get('size_sqm') else 0,
            'price_per_sqm': float(property_data.get('price_per_sqm', 0)) if property_data.get('price_per_sqm') else 0,
            'building_age_years': int(property_data.get('building_age_years', 0)) if property_data.get('building_age_years') is not None else None,
            'floor': int(property_data.get('floor', 0)) if property_data.get('floor') is not None else None,
            # Remove total_floors - using building_floors instead
            'management_fee': float(property_data.get('management_fee', 0)) if property_data.get('management_fee') else 0,
            'repair_reserve_fee': float(property_data.get('repair_reserve_fee', 0)) if property_data.get('repair_reserve_fee') else 0,
            'total_monthly_costs': float(property_data.get('total_monthly_costs', 0)) if property_data.get('total_monthly_costs') else 0,
            'station_distance_minutes': int(property_data.get('station_distance_minutes', 0)) if property_data.get('station_distance_minutes') is not None else None,
            'num_bedrooms': int(property_data.get('num_bedrooms', 0)) if property_data.get('num_bedrooms') is not None else None,
            
            # Location fields
            'ward': ward,
            'district': property_data.get('district', ''),
            'district_key': district_key,  # For GSI queries
            
            # Building details (essential only)
            'building_name': property_data.get('building_name') or property_data.get('建物名', ''),
            'direction_facing': property_data.get('direction_facing') or property_data.get('向き', ''),
            'primary_light': property_data.get('primary_light', ''),
            'closest_station': property_data.get('closest_station', ''),
            
            # Image data (essential only)
            'photo_filenames': property_data.get('photo_filenames', ''),
            'image_count': property_data.get('image_count', 0),
            
            # === ENRICHMENT FIELDS ===
            # Building structure fields
            'building_floors': int(property_data.get('building_floors', 0)) if property_data.get('building_floors') is not None else None,
            'building_year': int(property_data.get('building_year', 0)) if property_data.get('building_year') is not None else None,
            
            # Remove usable_area and total_area fields - only use size_sqm
            'balcony_size_sqm': float(property_data.get('balcony_size_sqm', 0)) if property_data.get('balcony_size_sqm') else None,
            
            # View and light fields
            'orientation': property_data.get('orientation') or property_data.get('direction_facing') or property_data.get('向き', ''),
            'view_obstructed': property_data.get('view_obstructed', False),
            'good_lighting': property_data.get('good_lighting', False),
            
            # Remove safety fields - has_fire_hatch not providing value
            
            # Tracking fields
            'first_seen_date': property_data.get('first_seen_date') or datetime.now().isoformat(),
            
            # Single timestamp for all analysis
            'analysis_date': now.isoformat(),
        }
        
        # Add new fields from NEW_FIELD_MAP (zoning, land_rights, etc.)
        new_fields = {
            'zoning': property_data.get('zoning') or property_data.get('用途地域', ''),
            'land_rights': property_data.get('land_rights') or property_data.get('土地権利', ''),
            'national_land_use_notification': property_data.get('national_land_use_notification') or property_data.get('国土法届出', ''),
            'transaction_type': property_data.get('transaction_type') or property_data.get('取引態様', ''),
            'current_occupancy': property_data.get('current_occupancy') or property_data.get('現況', ''),
            'handover_timing': property_data.get('handover_timing') or property_data.get('引渡し', '')
        }
        
        # Add non-empty new fields to the record
        for field_name, field_value in new_fields.items():
            if field_value and field_value.strip():  # Only add if not empty
                record[field_name] = field_value.strip()
        
        # Add previous_price if there was a price change
        if previous_price is not None:
            record['previous_price'] = previous_price
        
        # Merge extras into the META dict
        if extras:
            for k, v in extras.items():
                if v is None: 
                    continue
                # Don't overwrite existing non-null values
                if k in record and record[k] not in (None, "", [], {}):
                    continue
                record[k] = v
        
        # Improved filtering to preserve important fields
        filtered_record = {}
        for k, v in record.items():
            # Always include these fields even if 0 or False
            preserve_zero_fields = [
                'floor', 'building_floors', 'price', 'size_sqm', 'price_per_sqm',
                'management_fee', 'repair_reserve_fee', 'total_monthly_costs',
                'station_distance_minutes', 'num_bedrooms', 'building_age_years',
                'building_year', 'image_count', 'good_lighting', 'view_obstructed'
            ]
            
            if k in preserve_zero_fields:
                # Keep these fields even if 0 or False, but filter out None
                if v is not None:
                    filtered_record[k] = v
            else:
                # For other fields, filter out None, empty strings, and empty lists
                if v is not None and v != '' and v != []:
                    filtered_record[k] = v
        
        record = filtered_record
        
        # Convert all numeric values to Decimal before returning
        return prepare_for_dynamodb(record)
        
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
    """Add multiple URLs to tracking table in batch with ward information"""
    if not urls:
        return 0
    
    try:
        saved_count = 0
        
        with table.batch_writer() as batch:
            for url in urls:
                try:
                    item = {
                        'url': url,
                        'processed': ''
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
    """Scan for all URLs where processed is empty, including ward and price data"""
    unprocessed_items = []
    
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
                    # Return full item with ward and price if available
                    unprocessed_items.append({
                        'url': url,
                        'ward': item.get('ward'),
                        'price': int(item.get('price', 0))  # Include price
                    })
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Found {len(unprocessed_items)} unprocessed URLs")
        
        return unprocessed_items
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to scan unprocessed URLs: {str(e)}")
        return []

def scan_unprocessed_urls_batch(table, batch_size=100, logger=None):
    """Scan for a limited batch of unprocessed URLs with proper pagination"""
    unprocessed_items = []
    total_items_scanned = 0
    
    try:
        # Filter for URLs that are either empty string or don't have processed attribute
        filter_expression = boto3.dynamodb.conditions.Attr('processed').eq('') | boto3.dynamodb.conditions.Attr('processed').not_exists()
        
        scan_kwargs = {
            'FilterExpression': filter_expression
        }
        
        # Keep scanning until we have enough unprocessed URLs or reach end of table
        while len(unprocessed_items) < batch_size:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            total_items_scanned += len(items)
            
            # Process items in this scan response
            for item in items:
                url = item.get('url')
                if url:
                    # Return full item with ward and price if available
                    unprocessed_items.append({
                        'url': url,
                        'ward': item.get('ward'),
                        'price': int(item.get('price', 0))  # Include price
                    })
                    
                    # Stop if we've collected enough URLs
                    if len(unprocessed_items) >= batch_size:
                        break
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' not in response:
                # Reached end of table
                break
            
            # Continue scanning from where we left off
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.debug(f"Found {len(unprocessed_items)} unprocessed URLs after scanning {total_items_scanned} total items")
        
        return unprocessed_items
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to scan unprocessed URLs batch: {str(e)}")
        return []

def mark_urls_batch_processed(url_items, table, logger=None):
    """Mark multiple URLs as processed and return successfully marked ones"""
    successfully_marked = []
    
    if not url_items:
        return successfully_marked
    
    # Since BatchWriter doesn't support update_item, use individual update calls
    for url_item in url_items:
        try:
            url = url_item.get('url') if isinstance(url_item, dict) else url_item
            table.update_item(
                Key={'url': url},
                UpdateExpression="SET #processed = :processed",
                ExpressionAttributeNames={'#processed': 'processed'},
                ExpressionAttributeValues={':processed': 'Y'}
            )
            successfully_marked.append(url_item)
        except Exception as e:
            if logger:
                logger.warning(f"Failed to mark URL {url} as processed: {str(e)}")
    
    if logger:
        logger.debug(f"Successfully marked {len(successfully_marked)}/{len(url_items)} URLs as processed")
    
    return successfully_marked

def mark_url_processed(url, table, logger=None):
    """Mark URL as processed by setting processed = 'Y'"""
    try:
        table.update_item(
            Key={'url': url},
            UpdateExpression="SET #processed = :processed",
            ExpressionAttributeNames={
                '#processed': 'processed'
            },
            ExpressionAttributeValues={
                ':processed': 'Y'
            }
        )
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to mark URL processed {url}: {str(e)}")
        return False

def load_recent_properties_for_comparables(table, ward=None, limit=200, logger=None):
    """Load recent properties for comparables calculation"""
    if logger:
        logger.info(f"Loading recent properties for comparables (ward: {ward}, limit: {limit})")
    
    properties = []
    
    try:
        if ward and ward != 'unknown':
            # Use GSI to query by ward (more efficient)
            district_key = f"DIST#{ward}"
            try:
                response = table.query(
                    IndexName='district-index',
                    KeyConditionExpression='district_key = :dk',
                    ExpressionAttributeValues={
                        ':dk': district_key
                    },
                    Limit=limit,
                    ScanIndexForward=False  # Most recent first
                )
                properties.extend(response.get('Items', []))
            except:
                # GSI doesn't exist, fall back to scan
                if logger:
                    logger.debug("GSI query failed, falling back to scan")
        
        # If no ward specified or GSI failed, do a general scan
        if not properties:
            scan_kwargs = {
                'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META'),
                'Limit': limit
            }
            
            response = table.scan(**scan_kwargs)
            properties = response.get('Items', [])
        
        # Convert DynamoDB items to dict format
        converted_properties = []
        for prop in properties:
            # Only include properties with required fields for comparables
            if prop.get('price_per_sqm') and prop.get('size_sqm'):
                converted_properties.append({
                    'property_id': prop.get('property_id'),
                    'price': float(prop.get('price', 0)),
                    'size_sqm': float(prop.get('size_sqm', 0)),
                    'price_per_sqm': float(prop.get('price_per_sqm', 0)),
                    'ward': prop.get('ward', 'unknown'),
                    'district': prop.get('district', ''),
                    'building_name': prop.get('building_name', ''),
                    'building_age_years': int(prop.get('building_age_years', 0)) if prop.get('building_age_years') else None,
                    'floor': int(prop.get('floor', 0)) if prop.get('floor') else None,
                    'station_distance_minutes': int(prop.get('station_distance_minutes', 0)) if prop.get('station_distance_minutes') else None,
                    'layout_type': prop.get('layout_type', ''),
                    'analysis_date': prop.get('analysis_date', '')
                })
        
        if logger:
            logger.debug(f"Loaded {len(converted_properties)} properties for comparables")
        
        return converted_properties
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to load properties for comparables: {str(e)}")
        return []

def calculate_ward_medians_from_dynamodb(table, logger=None):
    """Calculate ward median prices from recent DynamoDB data"""
    if logger:
        logger.info("Calculating ward medians from DynamoDB")
    
    ward_data = {}
    
    try:
        # Scan recent properties
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        }
        
        items_processed = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                ward = item.get('ward', 'unknown')
                price_per_sqm = item.get('price_per_sqm')
                
                if ward and ward != 'unknown' and price_per_sqm:
                    if ward not in ward_data:
                        ward_data[ward] = []
                    ward_data[ward].append(float(price_per_sqm))
                    items_processed += 1
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Calculate medians
        ward_medians = {}
        for ward, prices in ward_data.items():
            if len(prices) >= 3:  # Need at least 3 properties for median
                sorted_prices = sorted(prices)
                median_idx = len(sorted_prices) // 2
                median_price = sorted_prices[median_idx]
                
                ward_medians[ward] = {
                    'ward_avg_price_per_sqm': median_price,
                    'ward_property_count': len(prices)
                }
        
        if logger:
            logger.info(f"Calculated medians for {len(ward_medians)} wards from {items_processed} properties")
        
        return ward_medians
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to calculate ward medians: {str(e)}")
        return {}