#!/usr/bin/env python3
"""
Property Processor Lambda - Processes unprocessed URLs from the tracking table
Now includes full ETL functionality with lean scoring and enrichment
"""
import os
import time
import pandas as pd
import json
import random
from datetime import datetime
import boto3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

# Import analysis modules
try:
    from analysis.lean_scoring import LeanScoring, Verdict
    from analysis.comparables import ComparablesFilter, enrich_property_with_comparables
    from analysis.vision_stub import enrich_property_with_vision
    from util.metrics import emit_pipeline_metrics, emit_properties_processed, emit_candidates_enqueued, emit_candidates_suppressed, MetricsTimer
    from util.config import get_config as get_util_config, is_lean_mode
    LEAN_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Failed to import analysis modules: {e}")
    LEAN_MODULES_AVAILABLE = False
    # Define stubs
    LeanScoring = None
    ComparablesFilter = None
    enrich_property_with_comparables = lambda x, y: x
    enrich_property_with_vision = lambda x: x
    emit_pipeline_metrics = lambda *args: None
    emit_properties_processed = lambda *args: None
    emit_candidates_enqueued = lambda *args: None
    emit_candidates_suppressed = lambda *args: None
    get_util_config = None
    is_lean_mode = lambda: False
    class MetricsTimer:
        def __init__(self, stage): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

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
    load_recent_properties_for_comparables, calculate_ward_medians_from_dynamodb
)

def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'property-processor-{int(time.time())}')),
        'max_properties': event.get('max_properties', int(os.environ.get('MAX_PROPERTIES', '0'))),
        'output_bucket': event.get('output_bucket', os.environ.get('OUTPUT_BUCKET', '')),
        'max_runtime_minutes': event.get('max_runtime_minutes', int(os.environ.get('MAX_RUNTIME_MINUTES', '14'))),
        'dynamodb_table': event.get('dynamodb_table', os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db')),
        'url_tracking_table': event.get('url_tracking_table', os.environ.get('URL_TRACKING_TABLE', 'tokyo-real-estate-urls')),
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

def process_single_url(url, session_pool, rate_limiter, url_tracking_table, config, logger, image_rate_limiter, enrichment_context=None):
    """Process a single URL with rate limiting, error handling, and enrichment"""
    session = None
    try:
        # Acquire rate limit token
        rate_limiter.acquire()
        
        # Get session from pool
        session = session_pool.get_session()
        
        # Add random jitter delay
        jitter_delay = random.uniform(0.5, 2.0)
        time.sleep(jitter_delay)
        
        # Extract property details with session pool for images
        result = extract_property_details(
            session, url, "https://www.homes.co.jp", 
            config=config, logger=logger,
            session_pool=session_pool, image_rate_limiter=image_rate_limiter
        )
        
        # Validate data
        is_valid, msg = validate_property_data(result)
        if not is_valid:
            result["validation_error"] = msg
            # Mark URL as processed even if validation failed
            mark_url_processed(url, url_tracking_table, logger)
            return result
        
        # Apply enrichment if lean mode is enabled and modules are available
        if enrichment_context and enrichment_context.get('lean_mode_enabled') and LEAN_MODULES_AVAILABLE:
            try:
                # Enrich with comparables
                result = enrich_property_with_comparables(result, enrichment_context.get('all_properties', []))
                
                # Enrich with vision analysis
                result = enrich_property_with_vision(result)
                
                # Add ward median data
                ward = result.get('ward', 'unknown')
                ward_medians = enrichment_context.get('ward_medians', {})
                if ward in ward_medians:
                    result.update(ward_medians[ward])
                
                # Add building median data
                building_name = result.get('building_name', 'unknown')
                building_medians = enrichment_context.get('building_medians', {})
                if building_name in building_medians:
                    result.update(building_medians[building_name])
                
                # Calculate score
                scorer = enrichment_context.get('scorer')
                if scorer:
                    scoring_components = scorer.calculate_score(result)
                    
                    # Add scoring results
                    result.update({
                        'final_score': scoring_components.final_score,
                        'base_score': scoring_components.base_score,
                        'addon_score': scoring_components.addon_score,
                        'adjustment_score': scoring_components.adjustment_score,
                        'verdict': scoring_components.verdict.value,
                        'ward_discount_pct': scoring_components.ward_discount_pct,
                        'data_quality_penalty': scoring_components.data_quality_penalty,
                        'scoring_components': {
                            'ward_discount': scoring_components.ward_discount,
                            'building_discount': scoring_components.building_discount,
                            'comps_consistency': scoring_components.comps_consistency,
                            'condition': scoring_components.condition,
                            'size_efficiency': scoring_components.size_efficiency,
                            'carry_cost': scoring_components.carry_cost,
                            'price_cut': scoring_components.price_cut,
                            'renovation_potential': scoring_components.renovation_potential,
                            'access': scoring_components.access,
                            'vision_positive': scoring_components.vision_positive,
                            'vision_negative': scoring_components.vision_negative,
                            'overstated_discount_penalty': scoring_components.overstated_discount_penalty
                        }
                    })
                    
                    # Apply candidate gating logic
                    is_candidate_eligible = (
                        scoring_components.base_score >= 70 and
                        scoring_components.ward_discount_pct <= -8 and
                        scoring_components.data_quality_penalty > -5
                    )
                    result['is_candidate'] = is_candidate_eligible
                    
                    if is_candidate_eligible:
                        logger.debug(f"Property {result.get('id', 'unknown')} qualified as candidate ")
                else:
                    result['is_candidate'] = False
                    
            except Exception as e:
                logger.warning(f"Enrichment failed for {url}: {str(e)}")
                # Continue without enrichment
                result['is_candidate'] = False
        else:
            # No enrichment - mark as non-candidate
            result['is_candidate'] = False
        
        # Mark URL as processed in tracking table
        mark_url_processed(url, url_tracking_table, logger)
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing {url}: {str(e)}")
        
        # Still mark as processed to avoid retry loops
        try:
            mark_url_processed(url, url_tracking_table, logger)
        except:
            pass
        
        return {"url": url, "error": str(e)}
    
    finally:
        # Return session to pool
        if session:
            session_pool.return_session(session)

def process_urls_parallel(urls, config, logger, job_start_time, max_runtime_seconds, enrichment_context=None):
    """Process URLs in parallel with configurable concurrency and enrichment"""
    max_workers = config['max_workers']
    requests_per_second = config['requests_per_second']
    
    # Setup parallel processing infrastructure
    session_pool = SessionPool(size=max_workers * 2)  # 2x workers for better utilization
    rate_limiter = RateLimiter(rate=requests_per_second)
    
    # Create separate rate limiter for images with higher rate (for burst downloads per property)
    image_requests_per_second = requests_per_second * 2  # Allow 2x rate for images
    image_rate_limiter = RateLimiter(rate=image_requests_per_second, burst_multiplier=3)
    
    # Setup URL tracking table
    _, url_tracking_table = setup_url_tracking_table(config['url_tracking_table'], logger)
    
    results = []
    completed_count = 0
    
    try:
        logger.info(f"Starting parallel processing: {max_workers} workers, {requests_per_second} req/s (property), {image_requests_per_second} req/s (images)")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_url = {}
            for url in urls:
                future = executor.submit(
                    process_single_url, 
                    url, session_pool, rate_limiter, url_tracking_table, config, logger, image_rate_limiter, enrichment_context
                )
                future_to_url[future] = url
            
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
                
                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                    completed_count += 1
                    
                    # Log progress every 10 URLs
                    if completed_count % 10 == 0:
                        elapsed = (datetime.now() - job_start_time).total_seconds()
                        rate = completed_count / elapsed if elapsed > 0 else 0
                        progress_pct = (completed_count / len(urls)) * 100
                        logger.info(f"Progress: {completed_count}/{len(urls)} ({progress_pct:.1f}%) - {rate:.1f} req/s")
                
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
    """Process URLs in batches with enrichment context for lean scoring"""
    batch_size = config['batch_size']
    all_results = []
    failed_saves = []  # Track failed DynamoDB saves for retries
    total_saved = 0
    
    # Setup enrichment context if lean mode is enabled
    enrichment_context = None
    if LEAN_MODULES_AVAILABLE:
        try:
            # Check if lean mode is enabled
            lean_mode_enabled = is_lean_mode()
            if not lean_mode_enabled:
                # Try environment variable fallback
                lean_mode_enabled = os.environ.get('LEAN_MODE', '0').lower() in ('1', 'true', 'yes', 'on', 'enabled')
            
            if lean_mode_enabled:
                logger.info("Lean mode enabled - setting up enrichment context")
                
                # Setup DynamoDB for loading comparables
                _, main_table = setup_dynamodb_client(logger)
                
                # Load recent properties for comparables
                recent_properties = load_recent_properties_for_comparables(main_table, limit=500, logger=logger)
                
                # Calculate ward medians
                ward_medians = calculate_ward_medians_from_dynamodb(main_table, logger)
                
                # Calculate building medians from recent properties
                building_data = {}
                for prop in recent_properties:
                    building_name = prop.get('building_name', 'unknown')
                    price_per_sqm = prop.get('price_per_sqm')
                    if building_name != 'unknown' and price_per_sqm:
                        if building_name not in building_data:
                            building_data[building_name] = []
                        building_data[building_name].append(price_per_sqm)
                
                building_medians = {}
                for building, prices in building_data.items():
                    if len(prices) >= 2:
                        sorted_prices = sorted(prices)
                        median_idx = len(sorted_prices) // 2
                        building_medians[building] = {
                            'building_median_price_per_sqm': sorted_prices[median_idx],
                            'building_property_count': len(prices)
                        }
                
                # Initialize scorer
                scorer = LeanScoring()
                
                # Create enrichment context
                enrichment_context = {
                    'lean_mode_enabled': True,
                    'all_properties': recent_properties,
                    'ward_medians': ward_medians,
                    'building_medians': building_medians,
                    'scorer': scorer
                }
                
                logger.info(f"Enrichment context ready: {len(recent_properties)} comparables, "
                          f"{len(ward_medians)} ward medians, {len(building_medians)} building medians")
            else:
                logger.info("Lean mode disabled - processing without enrichment")
                
        except Exception as e:
            logger.error(f"Failed to setup enrichment context: {str(e)}")
            logger.info("Continuing without enrichment")
    
    logger.info(f"Processing {len(urls)} URLs in batches of {batch_size}")
    
    # Metrics tracking
    metrics = {
        'PropertiesProcessed': 0,
        'CandidatesEnqueued': 0,
        'CandidatesSuppressed': 0,
        'ProcessingErrors': 0,
        'ScoreDistribution': {'BUY_CANDIDATE': 0, 'WATCH': 0, 'REJECT': 0}
    }
    candidates = []
    max_candidates_per_day = int(os.environ.get('MAX_CANDIDATES_PER_DAY', '50'))
    
    for batch_start in range(0, len(urls), batch_size):
        batch_end = min(batch_start + batch_size, len(urls))
        batch_urls = urls[batch_start:batch_end]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(urls) + batch_size - 1) // batch_size
        
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_urls)} URLs)")
        
        # Process batch in parallel with enrichment context
        batch_results = process_urls_parallel(
            batch_urls, config, logger, job_start_time, max_runtime_seconds, enrichment_context
        )
        
        # Update enrichment context with new properties for better comparables
        if enrichment_context:
            for result in batch_results:
                if 'error' not in result and result.get('price_per_sqm'):
                    enrichment_context['all_properties'].append(result)
        
        # Track metrics and candidates
        for result in batch_results:
            if 'error' in result:
                metrics['ProcessingErrors'] += 1
            else:
                metrics['PropertiesProcessed'] += 1
                
                # Track score distribution
                verdict = result.get('verdict', '')
                if verdict in ['buy_candidate', 'watch', 'reject']:
                    metrics['ScoreDistribution'][verdict.upper()] += 1
                
                # Track candidates
                if result.get('is_candidate', False):
                    if len(candidates) < max_candidates_per_day:
                        candidates.append(result)
                        metrics['CandidatesEnqueued'] += 1
                    else:
                        metrics['CandidatesSuppressed'] += 1
        
        all_results.extend(batch_results)
        
        # Save batch results to DynamoDB immediately with error tracking
        if config.get('enable_deduplication') and batch_results:
            try:
                successful_properties = [p for p in batch_results if 'error' not in p]
                if successful_properties:
                    batch_saved = save_complete_properties_to_dynamodb(successful_properties, config, logger)
                    total_saved += batch_saved
                    
                    # Check if all properties were saved
                    if batch_saved < len(successful_properties):
                        unsaved_count = len(successful_properties) - batch_saved
                        logger.warning(f"Batch {batch_num}: {unsaved_count} properties failed to save, adding to retry list")
                        failed_saves.extend(successful_properties[batch_saved:])  # Add unsaved items to retry list
                    
                    logger.info(f"Batch {batch_num}: {batch_saved}/{len(successful_properties)} properties saved to DynamoDB (total: {total_saved})")
                else:
                    logger.info(f"Batch {batch_num}: No successful properties to save")
                    
            except Exception as e:
                logger.error(f"Batch {batch_num}: DynamoDB save failed completely: {str(e)}")
                # Add all successful properties to retry list
                successful_properties = [p for p in batch_results if 'error' not in p]
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
    logger = SessionLogger(args['session_id'], log_level=args['log_level'])
    
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
        
        # Get unprocessed URLs
        logger.info("Scanning for unprocessed URLs...")
        unprocessed_urls = scan_unprocessed_urls(url_tracking_table, logger)
        
        if not unprocessed_urls:
            logger.info("No unprocessed URLs found")
            summary_data = {
                "status": "SUCCESS_NO_URLS",
                "unprocessed_urls_found": 0,
                "processed_count": 0
            }
            write_job_summary(summary_data)
            return summary_data
        
        logger.info(f"Found {len(unprocessed_urls)} unprocessed URLs")
        
        # Apply limits
        urls_to_process = unprocessed_urls
        if max_properties_limit > 0:
            urls_to_process = urls_to_process[:max_properties_limit]
            logger.info(f"Limited to {len(urls_to_process)} properties")
        
        # Process URLs using parallel processing
        logger.info(f"Processing {len(urls_to_process)} properties with parallel execution...")
        logger.info(f"Configuration: {config['max_workers']} workers, {config['requests_per_second']} req/s, {config['batch_size']} batch size")
        
        listings_data = process_urls_in_batches(
            urls_to_process, config, logger, job_start_time, max_runtime_seconds
        )
        
        # Calculate statistics from results
        success_count = len([r for r in listings_data if 'error' not in r and 'validation_error' not in r])
        error_count = len([r for r in listings_data if 'error' in r or 'validation_error' in r])
        processed_urls = len(listings_data)
        
        # Count total DynamoDB saves (batch processing handles saves internally)
        dynamodb_saved = len([r for r in listings_data if 'error' not in r and 'validation_error' not in r])
        logger.info(f"DynamoDB processing completed during batch execution")
        
        # Emit metrics if available
        if LEAN_MODULES_AVAILABLE and hasattr(listings_data, '__len__'):
            try:
                # Extract metrics from batch processing
                total_candidates = len([r for r in listings_data if r.get('is_candidate', False)])
                emit_properties_processed(success_count)
                emit_candidates_enqueued(total_candidates)
                logger.info(f"Emitted metrics: {success_count} processed, {total_candidates} candidates")
            except Exception as e:
                logger.warning(f"Failed to emit metrics: {e}")
        
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
            "unprocessed_urls_found": len(unprocessed_urls),
            "urls_attempted": len(urls_to_process),
            "successful_extractions": success_count,
            "failed_extractions": error_count, 
            "urls_marked_processed": processed_urls,
            "dynamodb_saves": dynamodb_saved,
            "output_file": output_filename,
            "s3_upload_success": s3_upload_success,
            "status": "SUCCESS" if success_count > 0 else "NO_SUCCESS"
        }
        
        write_job_summary(summary_data)
        
        logger.info(f"Property processing completed!")
        logger.info(f"Results: {success_count} successful, {error_count} failed, {processed_urls} URLs marked processed")
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