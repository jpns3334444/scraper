#!/usr/bin/env python3
"""
DynamoDB utilities for deduplication and data persistence (US market)
"""
import boto3
import os
import re
from datetime import datetime
import time
from decimal import Decimal


def get_aws_region():
    """Get AWS region from environment or default"""
    return os.environ.get('AWS_REGION', 'us-east-1')


def setup_dynamodb_client(logger=None):
    """Setup DynamoDB client and table reference"""
    try:
        region = get_aws_region()
        dynamodb = boto3.resource('dynamodb', region_name=region)
        table_name = os.environ.get('DYNAMODB_TABLE', 'real-estate-ai-properties')
        table = dynamodb.Table(table_name)

        # Test connection
        table.load()

        if logger:
            logger.debug(f"DynamoDB connected: {table_name} (region: {region})")

        return dynamodb, table

    except Exception as e:
        if logger:
            logger.error(f"DynamoDB setup failed: {str(e)}")
        raise


def extract_property_id_from_url(url):
    """
    Extract property ID from realtor.com listing URL

    URL formats:
    - /realestateandhomes-detail/123-Main-St_Paonia_CO_81428_M12345-67890
    - /realestateandhomes-detail/address_M12345-67890
    """
    patterns = [
        # Realtor.com MLS ID pattern (M followed by numbers)
        r'_M(\d+-\d+)$',
        r'_M(\d+)$',
        # Property slug with ID at end
        r'/realestateandhomes-detail/[^/]+_([A-Z0-9-]+)$',
        # Fallback: any trailing ID-like pattern
        r'/([A-Z0-9]+-[0-9]+)/?$',
        r'property[_-]?id[=:]([A-Za-z0-9-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)

    # If no pattern matched, use a hash of the URL as ID
    # This ensures we can still track the property
    if '/realestateandhomes-detail/' in url:
        # Extract the property slug portion
        slug_match = re.search(r'/realestateandhomes-detail/([^?]+)', url)
        if slug_match:
            return slug_match.group(1).replace('/', '_')[:100]  # Limit length

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

                # Method 1: Extract from property_id field
                if property_id and '#' in property_id:
                    try:
                        parts = property_id.split('#')
                        if len(parts) >= 2:
                            id_part = parts[1]  # Get everything after #
                            if '_' in id_part:
                                # Format: PROP#YYYYMMDD_123456
                                raw_property_id = id_part.split('_', 1)[1]
                            else:
                                # Format: PROP#123456
                                raw_property_id = id_part
                    except (IndexError, ValueError):
                        pass

                # Method 2: Fallback to extracting from listing_url
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

        return existing_properties

    except Exception as e:
        if logger:
            logger.error(f"Failed to load properties: {str(e)}")
        return {}


# URL Tracking Table Functions

def setup_url_tracking_table(table_name=None, logger=None):
    """Setup URL tracking table reference"""
    try:
        region = get_aws_region()
        dynamodb = boto3.resource('dynamodb', region_name=region)

        if not table_name:
            table_name = os.environ.get('URL_TRACKING_TABLE', 'real-estate-ai-urls')

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


def put_url_to_tracking_table(url, table, city=None, logger=None):
    """Add URL to tracking table with city information"""
    try:
        item = {
            'url': url,
            'processed': '',
        }
        if city:
            item['city'] = city

        table.put_item(Item=item)
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to put URL {url}: {str(e)}")
        return False


def put_urls_batch_to_tracking_table(urls, table, city=None, logger=None):
    """Add multiple URLs to tracking table in batch with city and price information"""
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
                        item_city = url_item.get('city', city)
                    else:
                        url = url_item
                        price = 0
                        item_city = city

                    item = {
                        'url': url,
                        'processed': '',
                        'price': price
                    }
                    if item_city:
                        item['city'] = item_city

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


def load_all_urls_from_tracking_table(table, logger=None, city=None, exclude_city=None):
    """
    Load URLs from tracking table into a set for fast lookups.
    If city is specified, only load URLs from that city.
    If exclude_city is specified, exclude URLs from that city.
    """
    if city:
        if logger:
            logger.info(f"Loading URLs for city '{city}' from tracking table...")
    elif exclude_city:
        if logger:
            logger.info(f"Loading URLs excluding city '{exclude_city}' from tracking table...")
    else:
        if logger:
            logger.info("Loading all URLs from tracking table...")

    tracking_urls = set()

    try:
        scan_kwargs = {}

        # Add filter expression based on parameters
        if city:
            scan_kwargs['FilterExpression'] = boto3.dynamodb.conditions.Attr('city').eq(city)
        elif exclude_city:
            scan_kwargs['FilterExpression'] = boto3.dynamodb.conditions.Attr('city').ne(exclude_city)

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
    Batch update all price changes - simplified version with price tracking fields.

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

            # Get the current record to check for original_price
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
                    ':original_price': Decimal(str(old_price)),
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

            # Update the property record
            try:
                table.update_item(
                    Key={
                        'property_id': property_id,
                        'sort_key': 'META'
                    },
                    UpdateExpression=update_expression,
                    ExpressionAttributeValues=expression_values,
                    ConditionExpression="attribute_exists(property_id)"
                )

                successful_updates += 1

                if logger:
                    direction = "+" if price_change_amt > 0 else ""
                    logger.info(f"Price updated for {property_id}: ${old_price:,} -> ${new_price:,} "
                               f"({direction}{price_change_pct:.1f}%)")

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
        logger.info(f"Price update complete: {successful_updates} successful, {failed_updates} failed")

    return successful_updates
