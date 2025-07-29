#!/usr/bin/env python3
"""
URL Collector Lambda - Collects URLs from all areas and tracks new ones
"""
import os
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
    create_session, collect_area_listing_urls, discover_tokyo_areas
)
from dynamodb_utils import (
    setup_dynamodb_client, load_all_existing_properties,
    extract_property_id_from_url, update_listing_with_price_change,
    setup_url_tracking_table, put_urls_batch_to_tracking_table
)

def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'url-collector-{int(time.time())}')),
        'max_concurrent_areas': event.get('max_concurrent_areas', int(os.environ.get('MAX_CONCURRENT_AREAS', '5'))),
        'areas': event.get('areas', os.environ.get('AREAS', '')),
        'dynamodb_table': event.get('dynamodb_table', os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db')),
        'url_tracking_table': event.get('url_tracking_table', os.environ.get('URL_TRACKING_TABLE', 'tokyo-real-estate-urls')),
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO'))
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

def collect_area_urls_parallel_worker(area, existing_properties, url_tracking_table, rate_limiter, logger=None):
    """Worker function for parallel area URL collection"""
    try:
        if logger:
            logger.info(f"Starting area processing: {area}")
        
        # Apply rate limiting
        rate_limiter.wait()
        
        # Create session for this thread
        session = create_session(logger)
        
        try:
            # Collect URLs from area
            area_urls = collect_area_listing_urls(area, max_pages=None, session=session, logger=logger)
            
            if not area_urls:
                if logger:
                    logger.warning(f"No URLs found for area: {area}")
                return {
                    'area': area,
                    'success': True,
                    'new_urls': [],
                    'price_changed_urls': [],
                    'unchanged_urls': [],
                    'error': None
                }
            
            # Check against existing properties and categorize URLs
            new_urls = []
            price_changed_urls = []
            unchanged_urls = []
            
            for url in area_urls:
                raw_property_id = extract_property_id_from_url(url)
                if not raw_property_id:
                    new_urls.append(url)
                    continue
                
                if raw_property_id in existing_properties:
                    # For existing properties, treat as unchanged for now
                    # Could implement price checking here in the future if needed
                    unchanged_urls.append(url)
                else:
                    new_urls.append(url)
            
            # Add new URLs to tracking table
            if new_urls:
                urls_added = put_urls_batch_to_tracking_table(new_urls, url_tracking_table, logger)
                if logger:
                    logger.debug(f"Added {urls_added} new URLs from {area} to tracking table")
            
            rate_limiter.record_success()
            
            if logger:
                logger.info(f"Area {area} completed: {len(new_urls)} new, {len(unchanged_urls)} existing")
            
            return {
                'area': area,
                'success': True,
                'new_urls': new_urls,
                'price_changed_urls': price_changed_urls,
                'unchanged_urls': unchanged_urls,
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
                'price_changed_urls': [],
                'unchanged_urls': [],
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
            'price_changed_urls': [],
            'unchanged_urls': [],
            'error': f"Critical error: {str(e)}"
        }

def collect_urls_and_track_new(areas, config, logger=None):
    """Collect URLs from all areas and track new ones in URL tracking table"""
    if logger:
        logger.info(f"Starting parallel URL collection for {len(areas)} areas")
    
    try:
        # Load existing properties (thread-safe read-only access)
        dynamodb, table = setup_dynamodb_client(logger)
        existing_properties = load_all_existing_properties(table, logger)
        
        # Setup URL tracking table
        _, url_tracking_table = setup_url_tracking_table(config['url_tracking_table'], logger)
        
        # Get parallel processing configuration
        max_concurrent = config.get('max_concurrent_areas', 5)
        if logger:
            logger.info(f"Using {max_concurrent} concurrent workers for area processing")
        
        # Create shared rate limiter
        rate_limiter = RateLimiter(min_delay=1.0, max_delay=3.0)
        
        # Collect results
        all_new_urls = []
        all_price_changed_urls = []
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
                    url_tracking_table,
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
                        all_price_changed_urls.extend(result['price_changed_urls'])
                        all_unchanged_urls.extend(result['unchanged_urls'])
                        
                        if logger:
                            progress_pct = (completed_count / len(areas)) * 100
                            logger.info(f"Progress: {completed_count}/{len(areas)} ({progress_pct:.1f}%) - {area}: {len(result['new_urls'])} new, {len(result['unchanged_urls'])} existing")
                    else:
                        failed_areas.append({'area': area, 'error': result['error']})
                        if logger:
                            logger.error(f"Area {area} failed: {result['error']}")
                
                except Exception as e:
                    failed_areas.append({'area': area, 'error': str(e)})
                    if logger:
                        logger.error(f"Exception processing result for area {area}: {str(e)}")
        
        # Report results
        success_count = len(areas) - len(failed_areas)
        if logger:
            logger.info(f"Parallel processing complete: {success_count}/{len(areas)} areas successful")
            if failed_areas:
                logger.warning(f"Failed areas: {[f['area'] for f in failed_areas]}")
        
        summary = {
            'total_urls_found': len(all_new_urls) + len(all_unchanged_urls),
            'new_urls_tracked': len(all_new_urls),
            'existing_listings': len(all_unchanged_urls),
            'price_changed_listings': len(all_price_changed_urls),
            'successful_areas': success_count,
            'failed_areas': len(failed_areas),
            'failed_area_details': failed_areas
        }
        
        if logger:
            logger.info(f"URL collection complete: {summary['new_urls_tracked']} new URLs added to tracking table")
        
        return summary
        
    except Exception as e:
        if logger:
            logger.error(f"Error in parallel URL collection: {str(e)}")
        raise

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
            "status": "SUCCESS" if collection_summary.get('new_urls_tracked', 0) >= 0 else "FAILED"
        }
        
        write_job_summary(summary_data)
        
        logger.info(f"URL collection completed!")
        logger.info(f"Results: {summary_data['new_urls_tracked']} new URLs tracked, {summary_data['existing_listings']} existing")
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