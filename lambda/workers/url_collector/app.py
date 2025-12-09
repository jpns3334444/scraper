#!/usr/bin/env python3
"""
URL Collector Lambda - Collects property URLs from Redfin (US market)
Uses curl_cffi for browser impersonation to bypass bot detection
"""
import os
import time
import json
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3

# Import centralized configuration
try:
    from config_loader import get_config
    config = get_config()
except ImportError:
    config = None  # Fallback to environment variables


class RateLimiter:
    """Thread-safe rate limiter for parallel requests"""

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

            elapsed_since_last = current_time - self.last_request_time
            if elapsed_since_last < delay:
                sleep_time = delay - elapsed_since_last
                time.sleep(sleep_time)

            self.last_request_time = time.time()

    def record_error(self, is_rate_limit=False):
        """Record an error and increase backoff if needed"""
        with self.lock:
            self.consecutive_errors += 1
            if is_rate_limit or self.consecutive_errors > 3:
                self.backoff_multiplier = min(self.backoff_multiplier * 1.5, 5.0)

    def record_success(self):
        """Record successful request and reset backoff"""
        with self.lock:
            self.consecutive_errors = 0
            self.backoff_multiplier = max(self.backoff_multiplier * 0.9, 1.0)


class SessionLogger:
    """Simple logger that automatically includes session_id in all messages"""

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


# Import from other modules
from core_scraper import (
    create_session, collect_redfin_listings, get_target_cities
)
from dynamodb_utils import (
    setup_dynamodb_client, load_all_existing_properties,
    extract_property_id_from_url, batch_update_price_changes,
    setup_url_tracking_table, put_urls_batch_to_tracking_table,
    load_all_urls_from_tracking_table
)


def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    # Load config for table names
    redfin_config = {}
    scraper_config = {}

    if config:
        try:
            full_config = config.load_config()
            # Check for redfin config first, fall back to realtor for compatibility
            redfin_config = full_config.get('redfin', full_config.get('realtor', {}))
            scraper_config = full_config.get('scraper', {})
        except Exception:
            pass

    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'url-collector-{int(time.time())}')),
        'dynamodb_table': event.get('dynamodb_table', config.get_env_var('DYNAMODB_TABLE') if config else os.environ.get('DYNAMODB_TABLE', 'real-estate-ai-properties')),
        'url_tracking_table': event.get('url_tracking_table', config.get_env_var('URL_TRACKING_TABLE') if config else os.environ.get('URL_TRACKING_TABLE', 'real-estate-ai-urls')),
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO')),
        'target_city': event.get('target_city', redfin_config.get('TARGET_CITY', os.environ.get('TARGET_CITY', 'Paonia'))),
        'target_state': event.get('target_state', redfin_config.get('TARGET_STATE', os.environ.get('TARGET_STATE', 'CO'))),
        'city_id': event.get('city_id', int(redfin_config.get('CITY_ID', os.environ.get('CITY_ID', '14856')))),
        'max_pages': event.get('max_pages', int(redfin_config.get('MAX_PAGES', os.environ.get('MAX_PAGES', '10')))),
        'min_delay': float(scraper_config.get('MIN_DELAY_SECONDS', 3)),
        'max_delay': float(scraper_config.get('MAX_DELAY_SECONDS', 8))
    }


def get_collector_config(args):
    """Get URL collector configuration"""
    return {
        'session_id': args['session_id'],
        'dynamodb_table': args['dynamodb_table'],
        'url_tracking_table': args['url_tracking_table'],
        'target_city': args['target_city'],
        'target_state': args['target_state'],
        'city_id': args['city_id'],
        'max_pages': args['max_pages'],
        'min_delay': args['min_delay'],
        'max_delay': args['max_delay']
    }


def collect_urls_and_track_new(collector_config, logger=None):
    """Collect URLs from Redfin and track new ones"""
    if logger:
        logger.info(f"Starting URL collection for {collector_config['target_city']}, {collector_config['target_state']}")

    try:
        # Load existing properties (for price comparison)
        dynamodb, table = setup_dynamodb_client(logger)
        existing_properties = load_all_existing_properties(table, logger)

        # Setup URL tracking table
        _, url_tracking_table = setup_url_tracking_table(collector_config['url_tracking_table'], logger)

        # Load existing URLs from tracking table
        existing_urls = load_all_urls_from_tracking_table(url_tracking_table, logger)

        if logger:
            logger.info(f"Loaded {len(existing_properties)} existing properties, {len(existing_urls)} tracked URLs")

        # Create rate limiter with configured delays
        rate_limiter = RateLimiter(
            min_delay=collector_config['min_delay'],
            max_delay=collector_config['max_delay']
        )

        # Create session
        session = create_session(logger)

        try:
            # Collect listings from Redfin
            listings = collect_redfin_listings(
                city=collector_config['target_city'],
                state=collector_config['target_state'],
                max_pages=collector_config['max_pages'],
                city_id=collector_config.get('city_id', 0),
                session=session,
                logger=logger,
                rate_limiter=rate_limiter
            )

            # Categorize URLs
            new_urls = []
            price_changes = []
            unchanged_urls = []

            for listing in listings:
                url = listing['url']
                list_page_price = listing.get('price', 0)
                city = listing.get('city', collector_config['target_city'])

                if url in existing_urls:
                    # URL exists, check for price changes
                    raw_property_id = extract_property_id_from_url(url)
                    if raw_property_id and raw_property_id in existing_properties:
                        existing_property = existing_properties[raw_property_id]
                        stored_price = existing_property.get('price', 0)

                        if list_page_price > 0 and stored_price > 0 and list_page_price != stored_price:
                            price_changes.append({
                                'property_id': existing_property['property_id'],
                                'url': url,
                                'old_price': stored_price,
                                'new_price': list_page_price
                            })
                        else:
                            unchanged_urls.append(url)
                    else:
                        unchanged_urls.append(url)
                else:
                    # New URL
                    new_urls.append({
                        'url': url,
                        'city': city,
                        'price': list_page_price
                    })

            # Batch update new URLs to tracking table
            if new_urls:
                put_urls_batch_to_tracking_table(
                    new_urls,
                    url_tracking_table,
                    city=collector_config['target_city'],
                    logger=logger
                )

            # Batch update price changes
            if price_changes:
                batch_update_price_changes(price_changes, table, logger)

            if logger:
                logger.info(f"Collection complete: {len(new_urls)} new, {len(price_changes)} price changes, {len(unchanged_urls)} unchanged")

            return {
                'total_urls_found': len(listings),
                'new_urls_tracked': len(new_urls),
                'existing_listings': len(unchanged_urls),
                'price_changed_listings': len(price_changes),
                'successful_cities': 1,
                'failed_cities': 0
            }

        finally:
            session.close()

    except Exception as e:
        if logger:
            logger.error(f"Error collecting URLs: {str(e)}")
        return {
            'total_urls_found': 0,
            'new_urls_tracked': 0,
            'existing_listings': 0,
            'price_changed_listings': 0,
            'successful_cities': 0,
            'failed_cities': 1,
            'error': str(e)
        }


def write_job_summary(summary_data):
    """Write job summary to JSON file"""
    try:
        summary_path = "/tmp/url_collector_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
    except Exception as e:
        print(f"Failed to write summary: {e}")


def main(event=None):
    """Main URL collector function"""
    if event is None:
        event = {}

    args = parse_lambda_event(event)
    logger = SessionLogger(args['session_id'], log_level=args['log_level'])

    job_start_time = datetime.now()
    collector_config = get_collector_config(args)

    logger.info(f"Starting URL collector - Session: {collector_config['session_id']}")
    logger.info(f"Target: {collector_config['target_city']}, {collector_config['target_state']}")

    try:
        # Collect URLs
        collection_summary = collect_urls_and_track_new(collector_config, logger)

        # Generate summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()

        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "session_id": collector_config['session_id'],
            "target_city": collector_config['target_city'],
            "target_state": collector_config['target_state'],
            "total_urls_found": collection_summary.get('total_urls_found', 0),
            "new_urls_tracked": collection_summary.get('new_urls_tracked', 0),
            "existing_listings": collection_summary.get('existing_listings', 0),
            "price_changed_listings": collection_summary.get('price_changed_listings', 0),
            "status": "SUCCESS" if collection_summary.get('new_urls_tracked', 0) >= 0 else "FAILED"
        }

        write_job_summary(summary_data)

        logger.info(f"URL collection completed!")
        logger.info(f"Results: {summary_data['new_urls_tracked']} new URLs tracked, {summary_data['price_changed_listings']} price changes, {summary_data['existing_listings']} unchanged")
        logger.info(f"Duration: {duration:.1f} seconds")

        return summary_data

    except Exception as e:
        logger.error(f"URL collection failed: {e}")

        summary_data = {
            "status": "ERROR",
            "error": str(e),
            "session_id": collector_config['session_id']
        }
        write_job_summary(summary_data)
        raise


def lambda_handler(event, context):
    """AWS Lambda handler"""
    session_id = event.get('session_id', f'url-collector-{int(time.time())}')
    log_level = event.get('log_level', 'INFO')
    logger = SessionLogger(session_id, log_level=log_level)

    logger.info("URL Collector Lambda execution started")
    logger.debug(f"Event: {json.dumps(event, indent=2)}")

    try:
        result = main(event)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'URL collection completed successfully',
                'session_id': session_id,
                'new_urls_tracked': result.get('new_urls_tracked', 0),
                'existing_listings': result.get('existing_listings', 0),
                'price_changed_listings': result.get('price_changed_listings', 0),
                'timestamp': datetime.now().isoformat()
            })
        }
    except Exception as e:
        logger.error(f"URL Collector Lambda failed: {str(e)}")

        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }


if __name__ == "__main__":
    main()
