#!/usr/bin/env python3
"""
Main entry point for Tokyo real estate scraper
"""
import os
import time
import pandas as pd
import logging
import sys
import json
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3

class SessionLogger:
    """Simple logger that automatically includes session_id in all messages"""
    
    def __init__(self, session_id, log_level='INFO'):
        self.session_id = session_id
        self._logger = logging.getLogger(__name__)
        
        # Setup logger if not already configured
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
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
    create_session, collect_area_listing_urls, extract_property_details,
    discover_tokyo_areas
)
from dynamodb_utils import (
    setup_dynamodb_client, load_all_existing_properties,
    save_complete_properties_to_dynamodb, process_listings_with_existing_check,
    extract_property_id_from_url
)


def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'lambda-{int(time.time())}')),
        'max_properties': event.get('max_properties', int(os.environ.get('MAX_PROPERTIES', '0'))),
        'output_bucket': event.get('output_bucket', os.environ.get('OUTPUT_BUCKET', '')),
        'max_threads': event.get('max_threads', int(os.environ.get('MAX_THREADS', '1'))),
        'areas': event.get('areas', os.environ.get('AREAS', '')),
        'dynamodb_table': event.get('dynamodb_table', os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db')),
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO'))
    }

def get_scraper_config(args):
    """Get scraper configuration"""
    areas = [area.strip() for area in args['areas'].split(',') if area.strip()] if args['areas'] else []
    
    config = {
        'session_id': args['session_id'],
        'max_properties': args['max_properties'],
        'areas': areas,
        'max_threads': args['max_threads'],
        'output_bucket': args['output_bucket'],
        'enable_deduplication': True,
        'dynamodb_table': args['dynamodb_table']
    }
    
    return config

def collect_urls_with_deduplication(areas, config, logger=None):
    """Collect URLs with deduplication"""
    if logger:
        logger.info(f"Starting URL collection for {len(areas)} areas")
    
    try:
        # Load existing properties
        dynamodb, table = setup_dynamodb_client(logger)
        existing_properties = load_all_existing_properties(table, logger)
        
        # Create session
        session = create_session(logger)
        
        all_new_urls = []
        all_price_unchanged_urls = []
        
        for i, area in enumerate(areas):
            if logger:
                logger.info(f"Processing area {i+1}/{len(areas)}: {area}")
            
            # Collect URLs from area
            area_urls = collect_area_listing_urls(area, max_pages=None, session=session, logger=logger)
            
            # Check against existing
            new_urls, _, unchanged_urls = process_listings_with_existing_check(
                area_urls, existing_properties, logger
            )
            
            all_new_urls.extend(new_urls)
            all_price_unchanged_urls.extend(unchanged_urls)
            
            if logger:
                logger.info(f"Area {area}: {len(new_urls)} new, {len(unchanged_urls)} existing")
        
        summary = {
            'total_urls_found': len(all_new_urls) + len(all_price_unchanged_urls),
            'new_listings': len(all_new_urls),
            'existing_listings': len(all_price_unchanged_urls)
        }
        
        if logger:
            logger.info(f"Deduplication complete: {summary['new_listings']} new URLs to process")
        
        return all_new_urls, session, summary
        
    except Exception as e:
        if logger:
            logger.error(f"Error in URL collection: {str(e)}")
        raise

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
        summary_path = "/tmp/summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
    except Exception as e:
        print(f"Failed to write summary: {e}")

def main(event=None):
    """Main scraper function"""
    if event is None:
        event = {}
    
    args = parse_lambda_event(event)
    logger = SessionLogger(args['session_id'], log_level=args['log_level'])
    
    job_start_time = datetime.now()
    config = get_scraper_config(args)
    
    max_properties_limit = config['max_properties'] if config['max_properties'] > 0 else 0
    is_local_testing = not config['output_bucket']
    
    if is_local_testing and max_properties_limit == 0:
        max_properties_limit = 5
        logger.info("LOCAL TESTING - Limited to 5 properties")
    
    logger.info(f"Starting scraper - Session: {config['session_id']}")
    
    error_count = 0
    success_count = 0
    session = None
    
    try:
        # Determine areas to process
        if config['areas']:
            session_areas = config['areas']
            logger.info(f"Using specified areas: {session_areas}")
        elif is_local_testing:
            session_areas = ["chofu-city"]
            logger.info(f"Local testing - Using single area: {session_areas}")
        else:
            # Discover all Tokyo areas
            logger.info("Discovering all Tokyo areas...")
            all_tokyo_areas = discover_tokyo_areas(logger)
            
            if not all_tokyo_areas:
                raise Exception("No Tokyo areas discovered")
            
            session_areas = all_tokyo_areas
            logger.info(f"Processing {len(session_areas)} Tokyo areas")
        
        # Collect URLs with deduplication
        logger.info(f"Collecting URLs from {len(session_areas)} areas...")
        
        all_urls, session, dedup_summary = collect_urls_with_deduplication(
            session_areas, config, logger
        )
        
        if not all_urls:
            if dedup_summary:
                logger.info("All listings up-to-date, no new properties to process")
                summary_data = {
                    "status": "SUCCESS_NO_NEW_PROPERTIES",
                    "total_urls_found": dedup_summary.get('total_urls_found', 0),
                    "new_listings": 0,
                    "existing_listings": dedup_summary.get('existing_listings', 0)
                }
                write_job_summary(summary_data)
                return
            else:
                raise Exception("No listing URLs found")
        
        # Apply limits
        if max_properties_limit > 0:
            all_urls = all_urls[:max_properties_limit]
            logger.info(f"Limited to {len(all_urls)} properties")
        else:
            logger.info(f"Processing all {len(all_urls)} properties")
        
        # Extract property details
        logger.info(f"Extracting details from {len(all_urls)} properties...")
        listings_data = []
        
        # Single-threaded for anti-bot protection
        base_url = "https://www.homes.co.jp"
        
        for idx, url in enumerate(all_urls):
            if idx % 10 == 0:
                progress_pct = (idx / len(all_urls)) * 100
                logger.info(f"Progress: {idx}/{len(all_urls)} ({progress_pct:.1f}%)")
            
            try:
                result = extract_property_details(
                    session, url, base_url, config=config, logger=logger
                )
                
                # Validate data
                is_valid, msg = validate_property_data(result)
                if is_valid:
                    success_count += 1
                else:
                    result["validation_error"] = msg
                    error_count += 1
                
                listings_data.append(result)
                    
            except Exception as e:
                logger.error(f"Error processing {url}: {str(e)}")
                error_count += 1
                listings_data.append({
                    "url": url, 
                    "error": str(e)
                })
        
        # Save to DynamoDB
        if config.get('enable_deduplication') and listings_data:
            dynamodb_saved = save_complete_properties_to_dynamodb(listings_data, config, logger)
            logger.info(f"DynamoDB: {dynamodb_saved} properties saved")
        
        # Save to CSV
        df = pd.DataFrame(listings_data)
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        if len(session_areas) == 1:
            filename = f"{session_areas[0]}-listings-{date_str}.csv"
        else:
            filename = f"tokyo-listings-{date_str}.csv"
        
        local_path = os.path.join("/tmp", filename)
        df.to_csv(local_path, index=False)
        logger.info(f"Saved to {local_path}")
        
        # Upload to S3
        s3_upload_success = False
        if config['output_bucket'] and not is_local_testing:
            s3_key = f"scraper-output/{filename}"
            s3_upload_success = upload_to_s3(local_path, config['output_bucket'], s3_key, logger)
        
        # Generate summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "session_id": config['session_id'],
            "total_urls_found": len(all_urls),
            "successful_scrapes": success_count,
            "failed_scrapes": error_count,
            "output_file": filename,
            "s3_upload_success": s3_upload_success,
            "status": "SUCCESS" if success_count > 0 else "FAILED"
        }
        
        if dedup_summary:
            summary_data.update({
                "total_urls_discovered": dedup_summary.get('total_urls_found', 0),
                "new_listings_found": dedup_summary.get('new_listings', 0),
                "existing_listings_found": dedup_summary.get('existing_listings', 0)
            })
        
        write_job_summary(summary_data)
        
        logger.info(f"Scraping completed!")
        logger.info(f"Results: {success_count} successful, {error_count} failed")
        logger.info(f"Duration: {duration:.1f} seconds")
        
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        
        summary_data = {
            "status": "ERROR",
            "error": str(e)
        }
        write_job_summary(summary_data)
        raise
    
    finally:
        if session:
            session.close()

def lambda_handler(event, context):
    """AWS Lambda handler"""
    session_id = event.get('session_id', f'lambda-{int(time.time())}')
    log_level = event.get('log_level', 'INFO')
    logger = SessionLogger(session_id, log_level=log_level)
    
    logger.info("Lambda execution started")
    logger.debug(f"Event: {json.dumps(event, indent=2)}")
    
    try:
        main(event)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Scraper completed successfully',
                'session_id': event.get('session_id', 'unknown'),
                'timestamp': datetime.now().isoformat()
            })
        }
    except Exception as e:
        logger.error(f"Lambda failed: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }

if __name__ == "__main__":
    main()