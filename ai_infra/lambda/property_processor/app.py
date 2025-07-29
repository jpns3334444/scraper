#!/usr/bin/env python3
"""
Property Processor Lambda - Processes unprocessed URLs from the tracking table
"""
import os
import time
import pandas as pd
import json
import random
from datetime import datetime
import boto3

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
from core_scraper import create_session, extract_property_details
from dynamodb_utils import (
    setup_dynamodb_client, save_complete_properties_to_dynamodb,
    setup_url_tracking_table, scan_unprocessed_urls, mark_url_processed
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
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO'))
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
        'enable_deduplication': True
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
    session = None
    
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
        
        # Create session for property extraction
        session = create_session(logger)
        
        # Extract property details
        logger.info(f"Processing {len(urls_to_process)} properties...")
        listings_data = []
        
        base_url = "https://www.homes.co.jp"
        
        for idx, url in enumerate(urls_to_process):
            # Check runtime limit (stop processing with 30 seconds buffer)
            elapsed_time = (datetime.now() - job_start_time).total_seconds()
            if elapsed_time > (max_runtime_seconds - 30):
                logger.warning(f"Approaching runtime limit, stopping after {idx} properties")
                break
            
            if idx % 10 == 0:
                progress_pct = (idx / len(urls_to_process)) * 100
                logger.info(f"Progress: {idx}/{len(urls_to_process)} ({progress_pct:.1f}%)")
            
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
                
                # Mark URL as processed in tracking table
                if mark_url_processed(url, url_tracking_table, logger):
                    processed_urls += 1
                
                # Add small delay between requests
                time.sleep(random.uniform(1, 2))
                    
            except Exception as e:
                logger.error(f"Error processing {url}: {str(e)}")
                error_count += 1
                
                # Still mark as processed to avoid retry loops
                if mark_url_processed(url, url_tracking_table, logger):
                    processed_urls += 1
                
                listings_data.append({
                    "url": url, 
                    "error": str(e)
                })
        
        # Save to DynamoDB
        dynamodb_saved = 0
        if config.get('enable_deduplication') and listings_data:
            dynamodb_saved = save_complete_properties_to_dynamodb(listings_data, config, logger)
            logger.info(f"DynamoDB: {dynamodb_saved} properties saved")
        
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
    
    finally:
        if session:
            session.close()

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