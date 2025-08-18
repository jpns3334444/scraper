#!/usr/bin/env python3
"""
URL Collector Lambda - Collects URLs from all areas and tracks new ones
"""
import os

# Import centralized configuration
try:
    from config_loader import get_config
    config = get_config()
except ImportError:
    config = None  # Fallback to environment variables
import time
import json
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3

class RateLimiter:
    """Thread-safe rate limiter for parallel requests"""
    
    def __init__(self, min_delay=1.0, max_delay=3.0):
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
    create_session, collect_area_listing_urls, collect_area_listings_with_prices, 
    discover_tokyo_areas, collect_suumo_listings_with_prices
)
from dynamodb_utils import (
    setup_dynamodb_client, load_all_existing_properties,
    extract_property_id_from_url, batch_update_price_changes,
    setup_url_tracking_table, put_urls_batch_to_tracking_table,
    load_all_urls_from_tracking_table
)

def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'url-collector-{int(time.time())}')),
        'max_concurrent_areas': event.get('max_concurrent_areas', int(os.environ.get('MAX_CONCURRENT_AREAS', '5'))),
        'areas': event.get('areas', os.environ.get('AREAS', '')),
        'dynamodb_table': event.get('dynamodb_table', config.get_env_var('DYNAMODB_TABLE') if config else os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db')),
        'url_tracking_table': event.get('url_tracking_table', config.get_env_var('URL_TRACKING_TABLE') if config else os.environ.get('URL_TRACKING_TABLE', 'tokyo-real-estate-ai-urls')),
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO')),
        'source': event.get('source', 'homes')  # Default to homes, can be 'suumo'
    }

def get_collector_config(args):
    """Get URL collector configuration"""
    areas = [area.strip() for area in args['areas'].split(',') if area.strip()] if args['areas'] else []
    
    config = {
        'session_id': args['session_id'],
        'areas': areas,
        'max_concurrent_areas': args['max_concurrent_areas'],
        'dynamodb_table': args['dynamodb_table'],
        'url_tracking_table': args['url_tracking_table']
    }
    
    return config

def collect_area_urls_parallel_worker(area, existing_properties, existing_urls, rate_limiter, logger=None):
    """Worker function for parallel area URL collection - no real-time DB updates"""
    try:
        if logger:
            logger.info(f"Starting area processing: {area}")
        
        # Apply rate limiting
        rate_limiter.wait()
        
        # Create session for this thread
        session = create_session(logger)
        
        try:
            # Collect URLs with prices from area
            area_listings = collect_area_listings_with_prices(area, max_pages=None, session=session, logger=logger)
            
            if not area_listings:
                if logger:
                    logger.warning(f"No listings found for area: {area}")
                return {
                    'area': area,
                    'success': True,
                    'new_urls': [],
                    'price_changes': [],  # Return price changes for batch processing
                    'unchanged_urls': [],
                    'already_tracked_count': 0,
                    'error': None
                }
            
            # Categorize URLs (NO database operations here)
            new_urls = []
            price_changes = []  # Collect for batch update later
            unchanged_urls = []
            already_tracked_count = 0
            
            for listing in area_listings:
                url = listing['url']
                list_page_price = listing['price']
                ward = listing.get('ward')  # Get ward from listing
                
                # First check: Is this URL already in the tracking table?
                if url in existing_urls:
                    # URL exists in tracking table, check for price changes
                    raw_property_id = extract_property_id_from_url(url)
                    if raw_property_id and raw_property_id in existing_properties:
                        # Property has been scraped, check for price changes
                        existing_property = existing_properties[raw_property_id]
                        stored_price = existing_property.get('price', 0)
                        
                        if list_page_price > 0 and stored_price > 0 and list_page_price != stored_price:
                            # Price changed
                            price_changes.append({
                                'property_id': existing_property['property_id'],
                                'url': url,
                                'old_price': stored_price,
                                'new_price': list_page_price
                            })
                        else:
                            # Price unchanged
                            unchanged_urls.append(url)
                    else:
                        # URL tracked but not yet scraped (no price comparison possible)
                        unchanged_urls.append(url)
                    
                    already_tracked_count += 1
                else:
                    # Truly new URL - not in tracking table
                    new_urls.append({
                        'url': url,
                        'ward': ward,
                        'price': list_page_price  # Include the price from listing page
                    })
            
            rate_limiter.record_success()
            
            if logger:
                logger.info(f"Area {area} completed: {len(new_urls)} new, {len(price_changes)} price changes, {len(unchanged_urls)} unchanged, {already_tracked_count} already tracked")
            
            return {
                'area': area,
                'success': True,
                'new_urls': new_urls,
                'price_changes': price_changes,  # Return for batch processing
                'unchanged_urls': unchanged_urls,
                'already_tracked_count': already_tracked_count,
                'error': None
            }
            
        except Exception as e:
            # Check if it's a rate limiting or anti-bot error
            error_msg = str(e).lower()
            is_rate_limit = any(code in error_msg for code in ['429', '403', 'rate limit', 'anti-bot'])
            
            rate_limiter.record_error(is_rate_limit)
            
            if logger:
                logger.error(f"Error processing area {area}: {str(e)}")
            
            return {
                'area': area,
                'success': False,
                'new_urls': [],
                'price_changes': [],
                'unchanged_urls': [],
                'already_tracked_count': 0,
                'error': str(e)
            }
        
        finally:
            session.close()
            
    except Exception as e:
        if logger:
            logger.error(f"Critical error in worker for area {area}: {str(e)}")
        
        return {
            'area': area,
            'success': False,
            'new_urls': [],
            'price_changes': [],
            'unchanged_urls': [],
            'already_tracked_count': 0,
            'error': f"Critical error: {str(e)}"
        }

def collect_urls_and_track_new(areas, config, logger=None):
    """Collect URLs from all areas and batch update everything at the end"""
    if logger:
        logger.info(f"Starting parallel URL collection for {len(areas)} areas")
    
    try:
        # Load existing properties (for price comparison)
        dynamodb, table = setup_dynamodb_client(logger)
        existing_properties = load_all_existing_properties(table, logger)
        
        # Setup URL tracking table
        _, url_tracking_table = setup_url_tracking_table(config['url_tracking_table'], logger)
        
        # Load existing URLs from tracking table (for new URL detection) - exclude Suumo URLs
        existing_urls = load_all_urls_from_tracking_table(url_tracking_table, logger, exclude_ward="suumo")
        
        # Get parallel processing configuration
        max_concurrent = config.get('max_concurrent_areas', 5)
        if logger:
            logger.info(f"Using {max_concurrent} concurrent workers for area processing")
        
        # Create shared rate limiter
        rate_limiter = RateLimiter(min_delay=1.0, max_delay=3.0)
        
        # Collect results
        all_new_urls = []
        all_price_changes = []  # Collect all price changes
        all_unchanged_urls = []
        failed_areas = []
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit all areas for processing
            future_to_area = {
                executor.submit(
                    collect_area_urls_parallel_worker, 
                    area, 
                    existing_properties, 
                    existing_urls,
                    rate_limiter, 
                    logger
                ): area for area in areas
            }
            
            # Process results as they complete
            completed_count = 0
            for future in as_completed(future_to_area):
                area = future_to_area[future]
                completed_count += 1
                
                try:
                    result = future.result()
                    
                    if result['success']:
                        all_new_urls.extend(result['new_urls'])
                        all_price_changes.extend(result['price_changes'])  # Collect price changes
                        all_unchanged_urls.extend(result['unchanged_urls'])
                        
                        if logger:
                            progress_pct = (completed_count / len(areas)) * 100
                            logger.info(f"Progress: {completed_count}/{len(areas)} ({progress_pct:.1f}%) - {area}: {len(result['new_urls'])} new, {len(result['price_changes'])} price changes, {len(result['unchanged_urls'])} unchanged")
                    else:
                        failed_areas.append({'area': area, 'error': result['error']})
                        if logger:
                            logger.error(f"Area {area} failed: {result['error']}")
                
                except Exception as e:
                    failed_areas.append({'area': area, 'error': str(e)})
                    if logger:
                        logger.error(f"Exception processing result for area {area}: {str(e)}")
        
        # BATCH OPERATIONS START HERE
        if logger:
            logger.info("Starting batch database operations...")
        
        # Batch 1: Add new URLs to tracking table with ward information
        if all_new_urls:
            # Group URLs by ward for efficient batch operations
            urls_by_ward = {}
            for url_info in all_new_urls:
                url = url_info['url']
                ward = url_info.get('ward')
                price = url_info.get('price', 0)  # Get price from URL info
                
                if ward not in urls_by_ward:
                    urls_by_ward[ward] = []
                
                # Store as dict with url and price
                urls_by_ward[ward].append({
                    'url': url,
                    'price': price
                })
            
            total_urls_added = 0
            for ward, urls in urls_by_ward.items():
                urls_added = put_urls_batch_to_tracking_table(urls, url_tracking_table, ward=ward, logger=logger)
                total_urls_added += urls_added
                if logger and ward:
                    logger.debug(f"Added {urls_added} URLs for ward {ward}")
            
            if logger:
                logger.info(f"Batch added {total_urls_added} new URLs to tracking table across {len(urls_by_ward)} wards")
        
        # Batch 2: Update all price changes at once
        if all_price_changes:
            if logger:
                logger.info(f"Batch updating {len(all_price_changes)} price changes...")
            
            price_updates_successful = batch_update_price_changes(all_price_changes, table, logger)
            
            if logger:
                logger.info(f"Successfully updated {price_updates_successful} prices")
        
        # Report results
        success_count = len(areas) - len(failed_areas)
        if logger:
            logger.info(f"Parallel processing complete: {success_count}/{len(areas)} areas successful")
            if failed_areas:
                logger.warning(f"Failed areas: {[f['area'] for f in failed_areas]}")
        
        summary = {
            'total_urls_found': len(all_new_urls) + len(all_price_changes) + len(all_unchanged_urls),
            'new_urls_tracked': len(all_new_urls),
            'existing_listings': len(all_unchanged_urls),
            'price_changed_listings': len(all_price_changes),
            'successful_areas': success_count,
            'failed_areas': len(failed_areas),
            'failed_area_details': failed_areas
        }
        
        if logger:
            logger.info(f"URL collection complete: {summary['new_urls_tracked']} new URLs added to tracking table, {summary['price_changed_listings']} price changes detected")
        
        return summary
        
    except Exception as e:
        if logger:
            logger.error(f"Error in parallel URL collection: {str(e)}")
        raise

def collect_suumo_urls(config, logger=None):
    """Collect URLs from Suumo and track them"""
    if logger:
        logger.info("Starting Suumo URL collection")
    
    try:
        # Setup DynamoDB
        dynamodb, table = setup_dynamodb_client(logger)
        existing_properties = load_all_existing_properties(table, logger)
        if logger:
            logger.info(f"Loaded {len(existing_properties)} existing properties")
        
        # Setup URL tracking table
        dynamodb, url_tracking_table = setup_url_tracking_table(config['url_tracking_table'], logger)
        existing_urls = load_all_urls_from_tracking_table(url_tracking_table, logger, ward="suumo")
        if logger:
            logger.info(f"Loaded {len(existing_urls)} existing Suumo URLs")
        
        # Create rate limiter
        rate_limiter = RateLimiter(min_delay=1.0, max_delay=3.0)
        
        # Collect Suumo listings
        session = create_session(logger)
        try:
            listings = collect_suumo_listings_with_prices(
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
                list_page_price = listing['price']
                
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
                        'ward': 'suumo',  # Use 'suumo' as ward identifier
                        'price': list_page_price,
                        'source': 'suumo'
                    })
            
            # Batch update new URLs to tracking table
            if new_urls:
                put_urls_batch_to_tracking_table(new_urls, url_tracking_table, ward="suumo", logger=logger)
            
            # Batch update price changes
            if price_changes:
                batch_update_price_changes(price_changes, table, logger)
            
            if logger:
                logger.info(f"Suumo collection complete: {len(new_urls)} new, {len(price_changes)} price changes, {len(unchanged_urls)} unchanged")
            
            return {
                'total_urls_found': len(listings),
                'new_urls_tracked': len(new_urls),
                'existing_listings': len(unchanged_urls),
                'price_changed_listings': len(price_changes),
                'successful_areas': 1,  # Suumo is one "area"
                'failed_areas': 0
            }
            
        finally:
            session.close()
            
    except Exception as e:
        if logger:
            logger.error(f"Error collecting Suumo URLs: {str(e)}")
        return {
            'total_urls_found': 0,
            'new_urls_tracked': 0,
            'existing_listings': 0,
            'price_changed_listings': 0,
            'successful_areas': 0,
            'failed_areas': 1
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
    config = get_collector_config(args)
    
    logger.info(f"Starting URL collector - Session: {config['session_id']}")
    
    try:
        # Initialize variables for both paths
        session_areas = []
        
        # Check if we're collecting from Suumo
        if args.get('source') == 'suumo':
            logger.info("Collecting URLs from Suumo...")
            collection_summary = collect_suumo_urls(config, logger)
            session_areas = ["suumo"]  # For reporting purposes
        else:
            # Original Homes.co.jp logic
            # Determine areas to process
            if config['areas']:
                session_areas = config['areas']
                logger.info(f"Using specified areas: {session_areas}")
            else:
                # Discover all Tokyo areas
                logger.info("Discovering all Tokyo areas...")
                all_tokyo_areas = discover_tokyo_areas(logger)
                
                if not all_tokyo_areas:
                    raise Exception("No Tokyo areas discovered")
                
                session_areas = all_tokyo_areas
                logger.info(f"Processing {len(session_areas)} Tokyo areas")
            
            # Collect URLs and track new ones
            logger.info(f"Collecting URLs from {len(session_areas)} areas...")
            
            collection_summary = collect_urls_and_track_new(session_areas, config, logger)
        
        # Generate summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "session_id": config['session_id'],
            "areas_processed": len(session_areas),
            "successful_areas": collection_summary.get('successful_areas', 0),
            "failed_areas": collection_summary.get('failed_areas', 0),
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
            "session_id": config['session_id']
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