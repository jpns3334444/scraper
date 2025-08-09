#!/usr/bin/env python3
"""
Property Processor Lambda - Processes unprocessed URLs from the tracking table
Scraping only - scoring handled by separate PropertyAnalyzer Lambda
"""
import os

# Load environment variables from .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, use existing environment
import time
import pandas as pd
import json
import random
import hashlib
from datetime import datetime
import boto3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import resource

# Analysis modules removed - scoring now handled by PropertyAnalyzer Lambda

def get_memory_usage():
    """Get current memory usage in MB"""
    # For Lambda, use resource module
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024  # Convert to MB

class SessionLogger:
    """Simple logger that automatically includes session_id in all messages"""
    
    def __init__(self, session_id, log_level='INFO'):
        self.session_id = session_id
        # Extract instance number if present
        self.instance_num = '1'
        if '-instance-' in session_id:
            self.instance_num = session_id.split('-instance-')[-1]
        
        import logging
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(getattr(logging, log_level.upper()))
    
    def info(self, message):
        self._logger.info(f"[{self.session_id}][Instance-{self.instance_num}] {message}")
    
    def warning(self, message):
        self._logger.warning(f"[{self.session_id}][Instance-{self.instance_num}] {message}")
    
    def error(self, message):
        self._logger.error(f"[{self.session_id}][Instance-{self.instance_num}] {message}")
    
    def debug(self, message):
        self._logger.debug(f"[{self.session_id}][Instance-{self.instance_num}] {message}")

class SessionPool:
    """Thread-safe pool of HTTP sessions with different headers"""
    
    def __init__(self, size=20):
        self.sessions = Queue(maxsize=size)
        self.lock = threading.Lock()
        self._create_sessions(size)
    
    def _create_sessions(self, size):
        """Create initial sessions with varied headers"""
        from core_scraper import create_session, BROWSER_PROFILES
        
        for i in range(size):
            session = create_session()
            
            # Vary Accept-Language headers
            lang_variations = [
                "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
                "ja,en-US;q=0.9,en;q=0.8",
                "ja-JP,ja;q=0.8,en-US;q=0.7,en;q=0.6",
                "ja,en;q=0.9,es;q=0.8"
            ]
            session.headers['Accept-Language'] = random.choice(lang_variations)
            
            # Add creation timestamp for cleanup
            session._created_at = time.time()
            
            self.sessions.put(session)
    
    def get_session(self):
        """Get a session from the pool"""
        return self.sessions.get()
    
    def return_session(self, session):
        """Return a session to the pool"""
        try:
            self.sessions.put_nowait(session)
        except:
            # Pool is full, close the session
            session.close()
    
    def get_pool_stats(self):
        """Get current pool statistics"""
        return {
            'available': self.sessions.qsize(),
            'total': self.sessions.maxsize,
            'in_use': self.sessions.maxsize - self.sessions.qsize()
        }

    def cleanup_stale_sessions(self):
        """Remove and recreate stale sessions"""
        cleaned = 0
        temp_sessions = []
        
        # Extract all sessions
        while not self.sessions.empty():
            try:
                session = self.sessions.get_nowait()
                # Check if session is still healthy (you can add more checks)
                if hasattr(session, '_created_at') and (time.time() - session._created_at) > 300:  # 5 minutes
                    session.close()
                    cleaned += 1
                else:
                    temp_sessions.append(session)
            except:
                break
        
        # Put healthy sessions back
        for session in temp_sessions:
            self.sessions.put(session)
        
        # Create new sessions to replace cleaned ones
        if cleaned > 0:
            from core_scraper import create_session
            for _ in range(cleaned):
                session = create_session()
                session._created_at = time.time()
                self.sessions.put(session)
        
        return cleaned

    def close_all(self):
        """Close all sessions in the pool"""
        while not self.sessions.empty():
            try:
                session = self.sessions.get_nowait()
                session.close()
            except:
                break

class RateLimiter:
    """Thread-safe token bucket rate limiter"""
    
    def __init__(self, rate=5, burst_multiplier=2):
        self.rate = rate  # tokens per second
        self.capacity = rate * burst_multiplier  # bucket capacity
        self.tokens = self.capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def acquire(self):
        """Acquire a token, blocking if necessary"""
        with self.lock:
            now = time.time()
            # Add tokens based on elapsed time
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                return
            
            # Need to wait
            sleep_time = (1 - self.tokens) / self.rate
        
        # Sleep outside the lock
        time.sleep(sleep_time)
        self.acquire()  # Recursive call to try again

# Import from other modules
from core_scraper import create_session, extract_property_details
from dynamodb_utils import (
    setup_dynamodb_client, save_complete_properties_to_dynamodb,
    setup_url_tracking_table, scan_unprocessed_urls, mark_url_processed,
    scan_unprocessed_urls_batch, mark_urls_batch_processed,
    extract_property_id_from_url, create_property_id_key
)

def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'property-processor-{int(time.time())}')),
        'max_properties': event.get('max_properties', int(os.environ.get('MAX_PROPERTIES', '0'))),
        'output_bucket': event.get('output_bucket', os.environ.get('OUTPUT_BUCKET', '')),
        'max_runtime_minutes': event.get('max_runtime_minutes', int(os.environ.get('MAX_RUNTIME_MINUTES', '14'))),
        'dynamodb_table': event.get('dynamodb_table', os.environ.get('PROPERTIES_TABLE', 'tokyo-real-estate-ai-analysis-db')),
        'url_tracking_table': event.get('url_tracking_table', os.environ.get('URL_TRACKING_TABLE', 'tokyo-real-estate-ai-urls')),
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO')),
        'max_workers': event.get('max_workers', int(os.environ.get('MAX_WORKERS', '5'))),
        'requests_per_second': event.get('requests_per_second', int(os.environ.get('REQUESTS_PER_SECOND', '5'))),
        'batch_size': event.get('batch_size', int(os.environ.get('BATCH_SIZE', '100')))
    }

def get_processor_config(args):
    """Get property processor configuration"""
    config = {
        'session_id': args['session_id'],
        'max_properties': args['max_properties'],
        'output_bucket': args['output_bucket'],
        'max_runtime_minutes': args['max_runtime_minutes'],
        'dynamodb_table': args['dynamodb_table'],
        'url_tracking_table': args['url_tracking_table'],
        'enable_deduplication': True,
        'max_workers': args['max_workers'],
        'requests_per_second': args['requests_per_second'],
        'batch_size': args['batch_size']
    }
    
    return config

def validate_property_data(property_data):
    """Basic property data validation"""
    if not isinstance(property_data, dict):
        return False, "Invalid data type"
    
    if "url" not in property_data:
        return False, "Missing URL"
    
    if not property_data["url"].startswith("https://"):
        return False, "Invalid URL"
    
    return True, "Valid"

def upload_to_s3(file_path, bucket, s3_key, logger=None):
    """Upload file to S3"""
    try:
        s3 = boto3.client("s3")
        s3.upload_file(file_path, bucket, s3_key)
        if logger:
            logger.info(f"Uploaded to s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"S3 upload failed: {e}")
        return False

def write_job_summary(summary_data):
    """Write job summary to JSON file"""
    try:
        summary_path = "/tmp/property_processor_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
    except Exception as e:
        print(f"Failed to write summary: {e}")

def process_single_url(url_data, session_pool, rate_limiter, url_tracking_table, config, logger, image_rate_limiter, processed_urls=None):
    """Process a single URL with ward information and rate limiting - scraping only"""
    session = None
    if processed_urls is None:
        processed_urls = set()
    
    # Extract URL, ward, and price
    if isinstance(url_data, dict):
        url = url_data.get('url')
        ward = url_data.get('ward')
        listing_price = url_data.get('price', 0)  # Get price from tracking table
    else:
        # Backward compatibility
        url = url_data
        ward = None
        listing_price = 0
    
    try:
        # Acquire rate limit token
        rate_limiter.acquire()
        
        # Get session from pool
        session = session_pool.get_session()
        
        # Add random jitter delay
        jitter_delay = random.uniform(0.5, 2.0)
        time.sleep(jitter_delay)
        
        # Extract property details with session pool for images, ward info, and listing price
        result = extract_property_details(
            session, url, "https://www.homes.co.jp", 
            config=config, logger=logger,
            session_pool=session_pool, 
            image_rate_limiter=image_rate_limiter,
            ward=ward,
            listing_price=listing_price  # Pass the listing price
        )
        
        # Validate data
        is_valid, msg = validate_property_data(result)
        if not is_valid:
            result["validation_error"] = msg
            logger.warning(f"Property validation failed for {url}: {msg}")
            # URL is already marked as processed before batch processing starts
            return result
        
        # Check for interior photos (excluding floor plans)
        has_interior_photos = result.get('has_interior_photos', False)
        if not has_interior_photos:
            result['skip_reason'] = 'no_interior_photos'
            logger.warning(f"Skipping property {url}: No interior photos found")
            return result
        
        # Additional data quality checks
        quality_issues = []
        if not result.get('price') or result.get('price') == 0:
            quality_issues.append('missing_price')
        if not result.get('size_sqm') or result.get('size_sqm') == 0:
            quality_issues.append('missing_size')
        if not result.get('ward'):
            quality_issues.append('missing_ward')
        if not result.get('address'):
            quality_issues.append('missing_address')
            
        if quality_issues:
            logger.warning(f"Data quality issues for {url}: {', '.join(quality_issues)}")
            result['data_quality_issues'] = quality_issues
        
        
        # URL is already marked as processed before batch processing starts
        
        return result
        
    except Exception as e:
        # Duplicate error prevention
        if url not in processed_urls:
            logger.error(f"Error processing {url}: {str(e)}")
            processed_urls.add(url)
        
        # URL is already marked as processed before batch processing starts
        
        return {"url": url, "error": str(e)}
    
    finally:
        # Return session to pool
        if session:
            session_pool.return_session(session)

def process_urls_parallel(urls, config, logger, job_start_time, max_runtime_seconds):
    """Process URLs in parallel with configurable concurrency"""
    max_workers = config['max_workers']
    requests_per_second = config['requests_per_second']
    
    # Setup parallel processing infrastructure
    session_pool = SessionPool(size=max_workers * 2)  # 2x workers for better utilization
    rate_limiter = RateLimiter(rate=requests_per_second)
    last_cleanup_time = time.time()
    processed_urls = set()  # Track processed URLs to prevent duplicate error logs
    
    # Create separate rate limiter for images with higher rate (for burst downloads per property)
    image_requests_per_second = requests_per_second * 2  # Allow 2x rate for images
    image_rate_limiter = RateLimiter(rate=image_requests_per_second, burst_multiplier=3)
    
    # Setup URL tracking table
    _, url_tracking_table = setup_url_tracking_table(config['url_tracking_table'], logger)
    
    results = []
    completed_count = 0
    last_cleanup_time = time.time()
    
    try:
        logger.info(f"Starting parallel processing: {max_workers} workers, {requests_per_second} req/s (property), {image_requests_per_second} req/s (images)")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_url = {}
            for url_item in urls:
                future = executor.submit(
                    process_single_url, 
                    url_item, session_pool, rate_limiter, url_tracking_table, config, logger, image_rate_limiter, processed_urls
                )
                future_to_url[future] = url_item
            
            # Process completed tasks
            for future in as_completed(future_to_url):
                # Check runtime limit
                elapsed_time = (datetime.now() - job_start_time).total_seconds()
                if elapsed_time > (max_runtime_seconds - 30):
                    logger.warning(f"Approaching runtime limit, stopping after {completed_count} properties")
                    # Cancel remaining futures
                    for remaining_future in future_to_url:
                        if not remaining_future.done():
                            remaining_future.cancel()
                    break
                
                url_item = future_to_url[future]
                url = url_item.get('url') if isinstance(url_item, dict) else url_item
                try:
                    result = future.result()
                    results.append(result)
                    completed_count += 1
                    
                    # Log progress every 10 URLs
                    if completed_count % 10 == 0:
                        elapsed = (datetime.now() - job_start_time).total_seconds()
                        rate = completed_count / elapsed if elapsed > 0 else 0
                        progress_pct = (completed_count / len(urls)) * 100
                        
                        # Get pool stats
                        pool_stats = session_pool.get_pool_stats()
                        
                        # Periodic session cleanup
                        if time.time() - last_cleanup_time > 60:  # Every minute
                            cleaned = session_pool.cleanup_stale_sessions()
                            if cleaned > 0:
                                logger.info(f"Cleaned {cleaned} stale sessions")
                            last_cleanup_time = time.time()
                        
                        # Enhanced progress logging
                        eta_seconds = int((len(urls) - completed_count) / rate) if rate > 0 else 0
                        eta_str = f"{eta_seconds//60}m {eta_seconds%60}s" if eta_seconds > 0 else "calculating..."
                        
                        logger.info(f"Progress: {completed_count}/{len(urls)} ({progress_pct:.1f}%) - "
                                   f"{rate:.1f} req/s - ETA: {eta_str} - "
                                   f"Sessions: {pool_stats['in_use']}/{pool_stats['total']} in use")
                        
                        # Memory monitoring every 50 URLs
                        if completed_count % 50 == 0:
                            memory_mb = get_memory_usage()
                            logger.info(f"Memory usage: {memory_mb:.1f} MB")
                
                except Exception as e:
                    logger.error(f"Future failed for {url}: {str(e)}")
                    results.append({"url": url, "error": str(e)})
                    completed_count += 1
        
        # Final statistics
        elapsed = (datetime.now() - job_start_time).total_seconds()
        effective_rate = completed_count / elapsed if elapsed > 0 else 0
        logger.info(f"Parallel processing completed: {completed_count} URLs in {elapsed:.1f}s ({effective_rate:.1f} req/s)")
        
        return results
        
    finally:
        session_pool.close_all()

def process_urls_in_batches(urls, config, logger, job_start_time, max_runtime_seconds):
    """Process URLs in batches - scraping only, no scoring"""
    batch_size = config['batch_size']
    all_results = []
    failed_saves = []  # Track failed DynamoDB saves for retries
    total_saved = 0
    
    # Add error and skip tracking at the beginning of the function
    error_stats = {
        'http_404': 0,
        'http_other': 0,
        'dynamodb_errors': 0,
        'parse_errors': 0,
        'timeout_errors': 0,
        'total_errors': 0
    }
    
    skip_stats = {
        'no_interior_photos': 0,
        'total_skipped': 0
    }
    
    logger.info(f"Processing {len(urls)} URLs in batches of {batch_size} (scraping only)")
    
    for batch_start in range(0, len(urls), batch_size):
        batch_end = min(batch_start + batch_size, len(urls))
        batch_urls = urls[batch_start:batch_end]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(urls) + batch_size - 1) // batch_size
        
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_urls)} URLs)")
        
        # Process batch in parallel
        batch_results = process_urls_parallel(
            batch_urls, config, logger, job_start_time, max_runtime_seconds
        )
        
        # Data quality summary for the batch
        batch_quality_summary = {
            'total_properties': len(batch_results),
            'properties_with_price': 0,
            'properties_with_size': 0,
            'properties_with_ward': 0,
            'properties_with_comparables': 0,
            'validation_errors': 0
        }
        
        # Count data quality metrics
        for result in batch_results:
            if 'error' not in result:
                if result.get('price', 0) > 0:
                    batch_quality_summary['properties_with_price'] += 1
                if result.get('size_sqm', 0) > 0:
                    batch_quality_summary['properties_with_size'] += 1
                if result.get('ward'):
                    batch_quality_summary['properties_with_ward'] += 1
                if 'validation_error' in result:
                    batch_quality_summary['validation_errors'] += 1
                        
        # Log batch quality summary
        logger.info(f"Batch {batch_num} data quality: {batch_quality_summary['properties_with_price']}/{batch_quality_summary['total_properties']} with price, "
                   f"{batch_quality_summary['properties_with_size']}/{batch_quality_summary['total_properties']} with size, "
                   f"{batch_quality_summary['properties_with_ward']}/{batch_quality_summary['total_properties']} with ward")
        
        # Track results with enhanced error and skip categorization
        success_count = 0
        error_count = 0
        skip_count = 0
        
        for result in batch_results:
            if 'error' in result:
                error_msg = str(result.get('error', '')).lower()
                error_stats['total_errors'] += 1
                
                if 'http 404' in error_msg:
                    error_stats['http_404'] += 1
                elif 'http' in error_msg:
                    error_stats['http_other'] += 1
                elif 'timeout' in error_msg:
                    error_stats['timeout_errors'] += 1
                else:
                    error_stats['parse_errors'] += 1
                    
                error_count += 1
            elif 'skip_reason' in result:
                skip_reason = result.get('skip_reason', '')
                skip_stats['total_skipped'] += 1
                
                if skip_reason == 'no_interior_photos':
                    skip_stats['no_interior_photos'] += 1
                
                skip_count += 1
            else:
                success_count += 1
        
        all_results.extend(batch_results)
        
        # Save batch results to DynamoDB immediately with error tracking
        if config.get('enable_deduplication') and batch_results:
            try:
                successful_properties = [p for p in batch_results if 'error' not in p and 'skip_reason' not in p]
                if successful_properties:
                    batch_saved = save_complete_properties_to_dynamodb(successful_properties, config, logger)
                    total_saved += batch_saved
                    
                    # Check if all properties were saved
                    if batch_saved < len(successful_properties):
                        unsaved_count = len(successful_properties) - batch_saved
                        logger.warning(f"Batch {batch_num}: {unsaved_count} properties failed to save, adding to retry list")
                        failed_saves.extend(successful_properties[batch_saved:])  # Add unsaved items to retry list
                    
                    logger.info(f"Batch {batch_num} complete: "
                               f"{success_count} success, {error_count} errors, {skip_count} skipped "
                               f"(404: {error_stats['http_404']}, HTTP: {error_stats['http_other']}, "
                               f"Timeout: {error_stats['timeout_errors']}, Parse: {error_stats['parse_errors']}, "
                               f"No interior photos: {skip_stats['no_interior_photos']}) - "
                               f"{batch_saved}/{len(successful_properties)} saved to DynamoDB (total: {total_saved})")
                else:
                    logger.info(f"Batch {batch_num} complete: "
                               f"{success_count} success, {error_count} errors, {skip_count} skipped "
                               f"(404: {error_stats['http_404']}, HTTP: {error_stats['http_other']}, "
                               f"Timeout: {error_stats['timeout_errors']}, Parse: {error_stats['parse_errors']}, "
                               f"No interior photos: {skip_stats['no_interior_photos']}) - "
                               f"No successful properties to save")
                    
            except Exception as e:
                logger.error(f"Batch {batch_num}: DynamoDB save failed completely: {str(e)}")
                # Add all successful properties to retry list (excluding skipped)
                successful_properties = [p for p in batch_results if 'error' not in p and 'skip_reason' not in p]
                failed_saves.extend(successful_properties)
        
        # Check runtime limit
        elapsed_time = (datetime.now() - job_start_time).total_seconds()
        if elapsed_time > (max_runtime_seconds - 60):  # 1 minute buffer for cleanup
            logger.warning(f"Approaching runtime limit, stopping after batch {batch_num}")
            break
    
    # Retry failed saves if we have time
    if failed_saves:
        elapsed_time = (datetime.now() - job_start_time).total_seconds()
        if elapsed_time < (max_runtime_seconds - 30):  # 30 second buffer
            logger.info(f"Retrying {len(failed_saves)} failed DynamoDB saves...")
            try:
                retry_saved = save_complete_properties_to_dynamodb(failed_saves, config, logger)
                total_saved += retry_saved
                logger.info(f"Retry: {retry_saved}/{len(failed_saves)} properties saved (final total: {total_saved})")
                
                # Remove successfully saved items from failed list
                if retry_saved < len(failed_saves):
                    remaining_failed = len(failed_saves) - retry_saved  
                    logger.warning(f"{remaining_failed} properties still failed to save after retry")
                    
            except Exception as e:
                logger.error(f"Retry DynamoDB save failed: {str(e)}")
        else:
            logger.warning(f"No time for retrying {len(failed_saves)} failed saves")
    
    # Add save statistics to results metadata
    if hasattr(all_results, 'append'):
        save_stats = {
            'total_processed': len(all_results),
            'total_saved_to_dynamodb': total_saved,
            'failed_saves': len(failed_saves)
        }
        logger.info(f"Final batch processing stats: {save_stats}")
    
    return all_results

def main(event=None):
    """Main property processor function"""
    if event is None:
        event = {}
    
    args = parse_lambda_event(event)
    # Force DEBUG log level for testing
    actual_log_level = 'DEBUG' if args.get('log_level') == 'DEBUG' else args['log_level']
    logger = SessionLogger(args['session_id'], log_level=actual_log_level)
    
    job_start_time = datetime.now()
    config = get_processor_config(args)
    
    max_properties_limit = config['max_properties'] if config['max_properties'] > 0 else 0
    max_runtime_seconds = config['max_runtime_minutes'] * 60
    is_local_testing = not config['output_bucket']
    
    if is_local_testing and max_properties_limit == 0:
        max_properties_limit = 5
        logger.info("LOCAL TESTING - Limited to 5 properties")
    
    logger.info(f"Starting property processor - Session: {config['session_id']}")
    logger.info(f"Max runtime: {config['max_runtime_minutes']} minutes")
    
    error_count = 0
    success_count = 0
    processed_urls = 0
    
    try:
        # Setup URL tracking table
        _, url_tracking_table = setup_url_tracking_table(config['url_tracking_table'], logger)
        
        # Add Lambda instance identifier for debugging parallel execution
        lambda_instance_id = f"instance-{os.environ.get('AWS_LAMBDA_LOG_STREAM_NAME', 'local')[-8:]}"
        logger.info(f"Lambda instance ID: {lambda_instance_id}")
        
        # New batch processing loop - scan and claim URLs in small batches
        all_listings_data = []
        total_urls_claimed = 0
        batch_number = 0
        
        logger.info("Starting batch URL claiming and processing...")
        logger.info(f"Configuration: {config['max_workers']} workers, {config['requests_per_second']} req/s, batch size {config['batch_size']}")
        
        while True:
            batch_number += 1
            
            # Check runtime limit before each batch
            elapsed_time = (datetime.now() - job_start_time).total_seconds()
            if elapsed_time > (max_runtime_seconds - 60):
                logger.warning(f"Approaching runtime limit, stopping after {batch_number-1} batches")
                break
            
            # Get a small batch of unprocessed URLs
            logger.info(f"Batch {batch_number}: Scanning for unprocessed URLs...")
            batch_items = scan_unprocessed_urls_batch(url_tracking_table, batch_size=100, logger=logger)
            
            if not batch_items:
                logger.info("No more unprocessed URLs found")
                break
                
            # Apply max properties limit if set
            if max_properties_limit > 0 and (total_urls_claimed + len(batch_items)) > max_properties_limit:
                remaining_limit = max_properties_limit - total_urls_claimed
                batch_items = batch_items[:remaining_limit]
                logger.info(f"Limited batch to {len(batch_items)} URLs due to max properties limit")
            
            # Immediately mark this batch as processed to claim them
            logger.info(f"Batch {batch_number}: Claiming {len(batch_items)} URLs...")
            urls_marked = mark_urls_batch_processed(batch_items, url_tracking_table, logger)
            
            if not urls_marked:
                logger.warning(f"Batch {batch_number}: Failed to claim any URLs, stopping")
                break
            
            logger.info(f"Batch {batch_number}: Successfully claimed {len(urls_marked)} URLs for processing")
            total_urls_claimed += len(urls_marked)
            
            # Process the successfully marked URLs
            batch_listings = process_urls_in_batches(
                urls_marked, config, logger, job_start_time, max_runtime_seconds
            )
            
            all_listings_data.extend(batch_listings)
            
            logger.info(f"Batch {batch_number}: Processed {len(batch_listings)} URLs "
                       f"(Total claimed: {total_urls_claimed}, Total processed: {len(all_listings_data)})")
            
            # Check if we've hit the max properties limit
            if max_properties_limit > 0 and total_urls_claimed >= max_properties_limit:
                logger.info(f"Reached max properties limit of {max_properties_limit}")
                break
            
            # Check runtime limit again
            elapsed_time = (datetime.now() - job_start_time).total_seconds()
            if elapsed_time > (max_runtime_seconds - 60):
                logger.warning(f"Approaching runtime limit, stopping after batch {batch_number}")
                break
        
        listings_data = all_listings_data
        
        if not listings_data:
            logger.info("No URLs were processed")
            summary_data = {
                "status": "SUCCESS_NO_URLS",
                "unprocessed_urls_found": 0,
                "processed_count": 0,
                "total_batches": batch_number - 1,
                "total_urls_claimed": total_urls_claimed
            }
            write_job_summary(summary_data)
            return summary_data
        
        logger.info(f"Completed parallel batch processing: {len(listings_data)} URLs processed across {batch_number-1} batches")
        
        # Calculate statistics from results
        success_count = len([r for r in listings_data if 'error' not in r and 'validation_error' not in r and 'skip_reason' not in r])
        error_count = len([r for r in listings_data if 'error' in r or 'validation_error' in r])
        skipped_count = len([r for r in listings_data if 'skip_reason' in r])
        processed_urls = len(listings_data)
        
        # Count total DynamoDB saves (batch processing handles saves internally, excluding skipped)
        dynamodb_saved = len([r for r in listings_data if 'error' not in r and 'validation_error' not in r and 'skip_reason' not in r])
        
        # Final skip statistics
        interior_photo_skipped = len([r for r in listings_data if r.get('skip_reason') == 'no_interior_photos'])
        
        logger.info(f"DynamoDB processing completed during batch execution")
        logger.info(f"Final statistics: {success_count} processed, {skipped_count} skipped ({interior_photo_skipped} due to no interior photos)")
        
        # Calculate and log overall data quality metrics
        properties_with_valid_price = len([r for r in listings_data if r.get('price', 0) > 0])
        properties_with_valid_size = len([r for r in listings_data if r.get('size_sqm', 0) > 0])
        properties_with_ward = len([r for r in listings_data if r.get('ward') and r.get('ward') != 'unknown'])
        properties_with_images = len([r for r in listings_data if r.get('image_count', 0) > 0])
        
        logger.info(f"=== FINAL DATA QUALITY SUMMARY ===")
        logger.info(f"Properties with valid price: {properties_with_valid_price}/{len(listings_data)} ({properties_with_valid_price/len(listings_data)*100:.1f}%)" if listings_data else "N/A")
        logger.info(f"Properties with valid size: {properties_with_valid_size}/{len(listings_data)} ({properties_with_valid_size/len(listings_data)*100:.1f}%)" if listings_data else "N/A")
        logger.info(f"Properties with ward data: {properties_with_ward}/{len(listings_data)} ({properties_with_ward/len(listings_data)*100:.1f}%)" if listings_data else "N/A")
        logger.info(f"Properties with images: {properties_with_images}/{len(listings_data)} ({properties_with_images/len(listings_data)*100:.1f}%)" if listings_data else "N/A")

        # Metrics emission removed - handled by PropertyAnalyzer Lambda
        
        # Save to CSV
        output_filename = None
        s3_upload_success = False
        
        if listings_data:
            df = pd.DataFrame(listings_data)
            date_str = datetime.now().strftime('%Y-%m-%d')
            session_short = config['session_id'][-8:] if len(config['session_id']) > 8 else config['session_id']
            
            output_filename = f"property-batch-{date_str}-{session_short}.csv"
            local_path = os.path.join("/tmp", output_filename)
            df.to_csv(local_path, index=False)
            logger.info(f"Saved to {local_path}")
            
            # Upload to S3
            if config['output_bucket'] and not is_local_testing:
                s3_key = f"processor-output/{output_filename}"
                s3_upload_success = upload_to_s3(local_path, config['output_bucket'], s3_key, logger)
        
        # Generate summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "session_id": config['session_id'],
            "total_batches_processed": batch_number - 1,
            "total_urls_claimed": total_urls_claimed,
            "urls_attempted": len(listings_data),
            "successful_extractions": success_count,
            "failed_extractions": error_count, 
            "urls_marked_processed": processed_urls,
            "dynamodb_saves": dynamodb_saved,
            "output_file": output_filename,
            "s3_upload_success": s3_upload_success,
            "lambda_instance_id": lambda_instance_id,
            "status": "SUCCESS" if success_count > 0 else "NO_SUCCESS"
        }
        
        write_job_summary(summary_data)
        
        logger.info(f"Property processing completed!")
        logger.info(f"Results: {success_count} successful, {error_count} failed, {skipped_count} skipped ({interior_photo_skipped} no interior photos), {processed_urls} URLs marked processed")
        logger.info(f"Duration: {duration:.1f} seconds")
        
        return summary_data
        
    except Exception as e:
        logger.error(f"Property processing failed: {e}")
        
        summary_data = {
            "status": "ERROR",
            "error": str(e),
            "session_id": config['session_id']
        }
        write_job_summary(summary_data)
        raise

def lambda_handler(event, context):
    """AWS Lambda handler"""
    session_id = event.get('session_id', f'property-processor-{int(time.time())}')
    log_level = event.get('log_level', 'INFO')
    logger = SessionLogger(session_id, log_level=log_level)
    
    logger.info("Property Processor Lambda execution started")
    logger.debug(f"Event: {json.dumps(event, indent=2)}")
    
    # Auto-spawn parallel instances if called from Step Functions
    if event.get('source') == 'step-function' and not event.get('is_parallel_child'):
        logger.info("Detected Step Function execution, spawning 2 additional parallel instances")
        
        lambda_client = boto3.client('lambda')
        for i in range(2, 4):  # Spawn instances 2 and 3 (current is instance 1)
            parallel_event = event.copy()
            parallel_event['session_id'] = f"{session_id}-instance-{i}"
            parallel_event['is_parallel_child'] = True
            
            try:
                lambda_client.invoke(
                    FunctionName=context.function_name,
                    InvocationType='Event',
                    Payload=json.dumps(parallel_event)
                )
                logger.info(f"Spawned parallel instance {i}")
            except Exception as e:
                logger.warning(f"Failed to spawn parallel instance {i}: {str(e)}")
    
    try:
        result = main(event)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Property processing completed successfully',
                'session_id': session_id,
                'successful_extractions': result.get('successful_extractions', 0),
                'failed_extractions': result.get('failed_extractions', 0),
                'urls_marked_processed': result.get('urls_marked_processed', 0),
                'timestamp': datetime.now().isoformat()
            })
        }
    except Exception as e:
        logger.error(f"Property Processor Lambda failed: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }

if __name__ == "__main__":
    main()