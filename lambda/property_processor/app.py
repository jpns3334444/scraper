#!/usr/bin/env python3
"""
Property Processor Lambda - Processes property URLs from realtor.com (US market)
Scrapes property details and saves to DynamoDB
"""
import os
import time
import json
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from decimal import Decimal
import boto3

# Import core scraper functions
from core_scraper import (
    create_session, extract_realtor_property_details,
    extract_property_id_from_url, create_property_id_key
)


def get_aws_region():
    """Get AWS region from environment or default"""
    return os.environ.get('AWS_REGION', 'us-east-1')


class SessionLogger:
    """Simple logger that includes session_id in all messages"""

    def __init__(self, session_id, log_level='INFO'):
        self.session_id = session_id
        import logging
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(getattr(logging, log_level.upper()))

    def info(self, message):
        self._logger.info(f"[{self.session_id}] {message}")

    def warning(self, message):
        self._logger.warning(f"[{self.session_id}] {message}")

    def error(self, message):
        self._logger.error(f"[{self.session_id}] {message}")

    def debug(self, message):
        self._logger.debug(f"[{self.session_id}] {message}")


class RateLimiter:
    """Thread-safe rate limiter"""

    def __init__(self, min_delay=3.0, max_delay=8.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.last_request_time = 0
        self.lock = threading.Lock()
        self.consecutive_errors = 0
        self.backoff_multiplier = 1.0

    def wait(self):
        """Wait for appropriate delay between requests"""
        with self.lock:
            current_time = time.time()
            base_delay = random.uniform(self.min_delay, self.max_delay)
            delay = base_delay * self.backoff_multiplier

            elapsed = current_time - self.last_request_time
            if elapsed < delay:
                time.sleep(delay - elapsed)

            self.last_request_time = time.time()

    def record_error(self, is_rate_limit=False):
        """Record error and increase backoff"""
        with self.lock:
            self.consecutive_errors += 1
            if is_rate_limit or self.consecutive_errors > 3:
                self.backoff_multiplier = min(self.backoff_multiplier * 1.5, 5.0)

    def record_success(self):
        """Record success and reduce backoff"""
        with self.lock:
            self.consecutive_errors = 0
            self.backoff_multiplier = max(self.backoff_multiplier * 0.9, 1.0)


def setup_dynamodb():
    """Setup DynamoDB resources"""
    region = get_aws_region()
    dynamodb = boto3.resource('dynamodb', region_name=region)

    properties_table_name = os.environ.get('DYNAMODB_TABLE', 'real-estate-ai-properties')
    url_tracking_table_name = os.environ.get('URL_TRACKING_TABLE', 'real-estate-ai-urls')

    properties_table = dynamodb.Table(properties_table_name)
    url_tracking_table = dynamodb.Table(url_tracking_table_name)

    return properties_table, url_tracking_table


def scan_unprocessed_urls(url_table, limit=100, logger=None):
    """Get unprocessed URLs from tracking table"""
    urls = []

    try:
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('processed').eq(''),
            'Limit': limit
        }

        response = url_table.scan(**scan_kwargs)
        items = response.get('Items', [])

        for item in items:
            url = item.get('url')
            if url:
                urls.append({
                    'url': url,
                    'city': item.get('city', ''),
                    'price': item.get('price', 0)
                })

        if logger:
            logger.info(f"Found {len(urls)} unprocessed URLs")

    except Exception as e:
        if logger:
            logger.error(f"Error scanning URLs: {str(e)}")

    return urls


def mark_url_processed(url, url_table, logger=None):
    """Mark URL as processed"""
    try:
        url_table.update_item(
            Key={'url': url},
            UpdateExpression="SET processed = :p",
            ExpressionAttributeValues={':p': 'Y'}
        )
        return True
    except Exception as e:
        if logger:
            logger.error(f"Error marking URL processed: {str(e)}")
        return False


def convert_floats_to_decimal(obj):
    """Convert floats to Decimal for DynamoDB"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(i) for i in obj]
    return obj


def save_property_to_dynamodb(property_data, table, logger=None):
    """Save property data to DynamoDB"""
    try:
        if 'error' in property_data:
            return False

        if not property_data.get('property_id'):
            if logger:
                logger.warning("No property_id, skipping save")
            return False

        # Build DynamoDB record
        now = datetime.now()
        record = {
            'property_id': property_data['property_id'],
            'sort_key': 'META',
            'listing_url': property_data.get('listing_url', ''),
            'listing_status': 'active',
            'analysis_date': now.isoformat(),
            'first_seen_date': now.isoformat(),

            # Core property fields
            'price': property_data.get('price', 0),
            'price_per_sqft': property_data.get('price_per_sqft', 0),
            'size_sqft': property_data.get('size_sqft', 0),
            'beds': property_data.get('beds', 0),
            'baths': property_data.get('baths', 0),
            'lot_size_sqft': property_data.get('lot_size_sqft', 0),
            'lot_size_acres': property_data.get('lot_size_acres', 0),
            'year_built': property_data.get('year_built', 0),
            'property_type': property_data.get('property_type', ''),

            # Location
            'address': property_data.get('address', ''),
            'city': property_data.get('city', ''),
            'state': property_data.get('state', ''),
            'zip_code': property_data.get('zip_code', ''),

            # US-specific
            'hoa_fee': property_data.get('hoa_fee', 0),
            'mls_id': property_data.get('mls_id', ''),

            # Media
            'image_count': property_data.get('image_count', 0),
            'image_urls': property_data.get('image_urls', [])[:5],  # Store first 5

            # Metadata
            'extraction_timestamp': property_data.get('extraction_timestamp', now.isoformat()),
        }

        # Remove empty values and convert floats to Decimal
        record = {k: v for k, v in record.items() if v is not None and v != '' and v != 0}
        record = convert_floats_to_decimal(record)

        # Ensure required keys are present
        record['property_id'] = property_data['property_id']
        record['sort_key'] = 'META'

        table.put_item(Item=record)

        if logger:
            logger.debug(f"Saved property {property_data['property_id']}")

        return True

    except Exception as e:
        if logger:
            logger.error(f"Error saving property: {str(e)}")
        return False


def process_single_url(url_info, session, rate_limiter, properties_table, url_table, logger=None):
    """Process a single URL"""
    url = url_info['url']

    try:
        # Rate limit
        rate_limiter.wait()

        # Extract property details
        property_data = extract_realtor_property_details(url, session, logger)

        if property_data and 'error' not in property_data:
            # Add city from tracking table if not extracted
            if not property_data.get('city') and url_info.get('city'):
                property_data['city'] = url_info['city']

            # Save to DynamoDB
            saved = save_property_to_dynamodb(property_data, properties_table, logger)

            if saved:
                rate_limiter.record_success()
                mark_url_processed(url, url_table, logger)
                return {'success': True, 'url': url}
            else:
                return {'success': False, 'url': url, 'error': 'Failed to save'}

        else:
            error = property_data.get('error', 'Unknown error') if property_data else 'No data'
            if '403' in str(error):
                rate_limiter.record_error(is_rate_limit=True)
            else:
                rate_limiter.record_error()
            return {'success': False, 'url': url, 'error': error}

    except Exception as e:
        rate_limiter.record_error()
        if logger:
            logger.error(f"Error processing {url}: {str(e)}")
        return {'success': False, 'url': url, 'error': str(e)}


def process_urls(urls, config, logger=None):
    """Process multiple URLs"""
    if not urls:
        return {'processed': 0, 'success': 0, 'failed': 0}

    properties_table, url_table = setup_dynamodb()

    rate_limiter = RateLimiter(
        min_delay=config.get('min_delay', 3.0),
        max_delay=config.get('max_delay', 8.0)
    )

    session = create_session(logger)
    results = {'processed': 0, 'success': 0, 'failed': 0, 'errors': []}

    max_runtime = config.get('max_runtime_seconds', 840)  # 14 minutes default
    start_time = time.time()

    try:
        for url_info in urls:
            # Check runtime
            elapsed = time.time() - start_time
            if elapsed > max_runtime:
                if logger:
                    logger.info(f"Max runtime reached ({elapsed:.0f}s), stopping")
                break

            result = process_single_url(
                url_info, session, rate_limiter,
                properties_table, url_table, logger
            )

            results['processed'] += 1

            if result.get('success'):
                results['success'] += 1
                if logger:
                    logger.info(f"Processed {results['processed']}/{len(urls)}: {url_info['url'][:50]}...")
            else:
                results['failed'] += 1
                results['errors'].append({
                    'url': result['url'],
                    'error': result.get('error', 'Unknown')
                })

    finally:
        session.close()

    return results


def lambda_handler(event, context):
    """AWS Lambda handler"""
    session_id = event.get('session_id', f'processor-{int(time.time())}')
    log_level = event.get('log_level', 'INFO')
    logger = SessionLogger(session_id, log_level=log_level)

    logger.info("Property Processor Lambda started")

    try:
        # Setup
        _, url_table = setup_dynamodb()

        # Get configuration
        config = {
            'min_delay': float(os.environ.get('MIN_DELAY', 3)),
            'max_delay': float(os.environ.get('MAX_DELAY', 8)),
            'max_runtime_seconds': int(os.environ.get('MAX_RUNTIME_MINUTES', 14)) * 60,
            'batch_size': int(os.environ.get('BATCH_SIZE', 50))
        }

        # Get unprocessed URLs
        urls = scan_unprocessed_urls(url_table, limit=config['batch_size'], logger=logger)

        if not urls:
            logger.info("No unprocessed URLs found")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No URLs to process',
                    'session_id': session_id
                })
            }

        # Process URLs
        results = process_urls(urls, config, logger)

        logger.info(f"Processing complete: {results['success']} success, {results['failed']} failed")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Processing complete',
                'session_id': session_id,
                'processed': results['processed'],
                'success': results['success'],
                'failed': results['failed'],
                'timestamp': datetime.now().isoformat()
            })
        }

    except Exception as e:
        logger.error(f"Lambda failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'session_id': session_id
            })
        }


if __name__ == "__main__":
    # Local testing
    lambda_handler({}, None)
