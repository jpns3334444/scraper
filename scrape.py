#!/usr/bin/env python3
"""
HTTP-based scraper for homes.co.jp with session management and complete data extraction
Replaces Chrome/Selenium with fast, reliable HTTP requests + session flow
"""
import time
import pandas as pd
import os
import requests
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import boto3
from datetime import datetime
import json

# Realistic user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def create_enhanced_session():
    """Create HTTP session with enhanced browser-like headers"""
    session = requests.Session()
    
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    }
    
    session.headers.update(headers)
    return session

def extract_listing_urls_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    relative_urls = re.findall(r'/mansion/b-\d+/', html_content)
    unique_listings = set()
    
    for url in relative_urls:
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        unique_listings.add(absolute_url)
    
    return list(unique_listings)

def collect_all_listing_urls(base_url, max_pages=10):
    """Collect all listing URLs using session-based pagination"""
    session = create_enhanced_session()
    all_links = set()
    
    log_structured_message("INFO", "Starting listing URL collection", base_url=base_url)
    
    try:
        # Step 1: Get page 1 to establish session
        print(f"=== Collecting listing URLs from page 1 ===")
        response = session.get(base_url, timeout=15)
        
        if response.status_code != 200:
            raise Exception(f"Failed to access page 1: HTTP {response.status_code}")
        
        if "pardon our interruption" in response.text.lower():
            raise Exception("Anti-bot protection detected on page 1")
        
        # Parse pagination info
        soup = BeautifulSoup(response.content, 'html.parser')
        total_element = soup.select_one('.totalNum')
        total_count = int(total_element.text) if total_element else 0
        
        page_links = soup.select('a[data-page]')
        max_page = max([int(link.get('data-page', 1)) for link in page_links]) if page_links else 1
        max_page = min(max_page, max_pages)
        
        log_structured_message("INFO", "Pagination info parsed", 
                             total_listings=total_count, max_page=max_page)
        
        # Extract listings from page 1
        page1_listings = extract_listing_urls_from_html(response.text)
        all_links.update(page1_listings)
        print(f"Page 1: Found {len(page1_listings)} listings")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages
        for page_num in range(2, max_page + 1):
            print(f"=== Collecting listings from page {page_num} ===")
            
            time.sleep(random.uniform(2, 4))
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    log_structured_message("WARNING", "Failed to access page", 
                                         page=page_num, status_code=response.status_code)
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    log_structured_message("ERROR", "Anti-bot protection triggered", page=page_num)
                    break
                
                page_listings = extract_listing_urls_from_html(response.text)
                all_links.update(page_listings)
                print(f"Page {page_num}: Found {len(page_listings)} listings")
                
                session.headers['Referer'] = page_url
                log_structured_message("INFO", "Page scraped successfully", 
                                     page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                log_structured_message("ERROR", "Error fetching page", 
                                     page=page_num, error=str(e))
                continue
        
        all_links_list = list(all_links)
        log_structured_message("INFO", "URL collection completed", 
                             total_unique_links=len(all_links_list))
        
        return all_links_list, session
        
    except Exception as e:
        log_structured_message("ERROR", "Error in URL collection", error=str(e))
        session.close()
        raise

def extract_property_details(session, property_url, referer_url, retries=2):
    """Extract detailed property information using session flow"""
    for attempt in range(retries + 1):
        try:
            # Set proper referer and add realistic delay
            session.headers['Referer'] = referer_url
            time.sleep(random.uniform(2, 5))
            
            print(f"Scraping: {property_url}")
            response = session.get(property_url, timeout=15)
            
            if response.status_code != 200:
                if attempt == retries:
                    return {"url": property_url, "error": f"HTTP {response.status_code}"}
                time.sleep(3)
                continue
            
            if "pardon our interruption" in response.text.lower():
                return {"url": property_url, "error": "Anti-bot protection"}
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {"url": property_url}
            
            # Extract title from h1 elements
            h1_elements = soup.select('h1')
            for h1 in h1_elements:
                if h1.text.strip() and ('マンション' in h1.text or '万円' in h1.text):
                    data["title"] = h1.text.strip()
                    break
            
            # Extract price using regex from content
            price_pattern = re.search(r'(\d{1,4}(?:,\d{3})*万円)', response.text)
            if price_pattern:
                data["price"] = price_pattern.group(1)
            
            # Extract detailed property information from tables
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 10:  # Main property details table
                    for row in rows:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            key = cells[0].text.strip()
                            value = cells[1].text.strip()
                            if key and value and len(key) < 30:  # Reasonable key length
                                data[key] = value
                    break
            
            return data
            
        except Exception as e:
            print(f"[Attempt {attempt + 1}] Error scraping {property_url}: {e}")
            if attempt == retries:
                return {"url": property_url, "error": str(e)}
            time.sleep(2)
    
    return {"url": property_url, "error": "Max retries exceeded"}

def upload_to_s3(file_path, bucket, s3_key):
    """Upload file to S3"""
    try:
        s3 = boto3.client("s3")
        s3.upload_file(file_path, bucket, s3_key)
        print(f"📤 Uploaded to s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        print(f"❌ S3 upload failed: {e}")
        return False

def write_job_summary(summary_data):
    """Write job summary to JSON file"""
    try:
        summary_path = "/var/log/scraper/summary.json"
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
        print(f"📋 Job summary written to {summary_path}")
    except Exception as e:
        # Fallback to current directory if /var/log/scraper not accessible
        try:
            with open("summary.json", "w") as f:
                json.dump(summary_data, f, indent=2)
            print(f"📋 Job summary written to summary.json")
        except:
            print(f"❌ Failed to write job summary: {e}")

def log_structured_message(level, message, **kwargs):
    """Log structured message in JSON format"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        **kwargs
    }
    print(json.dumps(log_entry))

def main():
    """Main scraper function using HTTP with session flow"""
    job_start_time = datetime.now()
    
    # Detect local testing mode
    is_local_testing = not os.environ.get("OUTPUT_BUCKET")
    if is_local_testing:
        log_structured_message("INFO", "LOCAL TESTING MODE: Limited to 5 listings", start_time=job_start_time.isoformat())
        print("🧪 LOCAL TESTING MODE - Processing only 5 listings for quick testing")
    else:
        log_structured_message("INFO", "Starting HTTP scraper job", start_time=job_start_time.isoformat())
    
    error_count = 0
    success_count = 0
    session = None
    
    try:
        # Configuration
        BASE_URL = "https://www.homes.co.jp/mansion/chuko/tokyo/chofu-city/list"
        max_pages = 1 if is_local_testing else 10
        
        # Step 1: Collect all listing URLs
        print("\n🔗 Collecting all listing URLs...")
        all_urls, session = collect_all_listing_urls(BASE_URL, max_pages)
        
        if not all_urls:
            raise Exception("No listing URLs found")
        
        # Limit URLs for local testing
        if is_local_testing:
            all_urls = all_urls[:5]  # Only process first 5 listings
            print(f"🧪 LIMITED TO {len(all_urls)} LISTINGS FOR LOCAL TESTING")
        
        log_structured_message("INFO", "URL collection completed", total_urls=len(all_urls))
        
        # Step 2: Extract detailed information from each property
        print(f"\n📋 Extracting details from {len(all_urls)} properties...")
        listings_data = []
        
        # Use conservative threading to respect rate limits
        max_threads = 2
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            # Submit all tasks
            futures = {
                executor.submit(extract_property_details, session, url, BASE_URL): url 
                for url in all_urls
            }
            
            # Collect results
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                    listings_data.append(result)
                    
                    if "error" not in result and result.get("title"):
                        success_count += 1
                    else:
                        error_count += 1
                        
                except Exception as e:
                    log_structured_message("ERROR", "Error processing property", url=url, error=str(e))
                    error_count += 1
                    listings_data.append({"url": url, "error": str(e)})
        
        # Step 3: Save data
        df = pd.DataFrame(listings_data)
        
        # Generate filename
        filename = f"chofu-city-listings-{datetime.now().strftime('%Y-%m-%d')}.csv"
        
        # Save locally (try desktop first, fallback to current directory)
        try:
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", filename)
            df.to_csv(desktop_path, index=False)
            local_path = desktop_path
        except:
            local_path = filename
            df.to_csv(local_path, index=False)
        
        log_structured_message("INFO", "Data saved locally", file_path=local_path)
        
        # Step 4: Upload to S3
        s3_upload_success = False
        output_bucket = os.environ.get("OUTPUT_BUCKET")
        s3_key = None
        
        if output_bucket and not is_local_testing:
            s3_key = f"scraper-output/{filename}"
            s3_upload_success = upload_to_s3(local_path, output_bucket, s3_key)
        elif is_local_testing:
            print("🧪 LOCAL TESTING: Skipping S3 upload")
            log_structured_message("INFO", "LOCAL TESTING: S3 upload skipped")
        else:
            log_structured_message("WARNING", "OUTPUT_BUCKET environment variable not set")
        
        # Step 5: Generate job summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP_SESSION_FLOW",
            "testing_mode": "LOCAL" if is_local_testing else "PRODUCTION",
            "total_urls_found": len(all_urls),
            "successful_scrapes": success_count,
            "failed_scrapes": error_count,
            "total_records": len(listings_data),
            "output_file": filename,
            "s3_upload_success": s3_upload_success,
            "s3_key": s3_key,
            "status": "SUCCESS" if success_count > 0 else "FAILED"
        }
        
        write_job_summary(summary_data)
        log_structured_message("INFO", "HTTP scraper job completed successfully", **summary_data)
        
        print(f"\n✅ Scraping completed successfully!")
        print(f"📊 Results: {success_count} successful, {error_count} failed")
        print(f"⏱️ Duration: {duration:.1f} seconds")
        print(f"💾 Output: {local_path}")
        if s3_upload_success:
            print(f"☁️ S3: s3://{output_bucket}/{s3_key}")
        
    except Exception as e:
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP_SESSION_FLOW",
            "status": "ERROR",
            "error": str(e)
        }
        
        write_job_summary(summary_data)
        log_structured_message("ERROR", "HTTP scraper job failed", **summary_data)
        print(f"\n❌ Scraping failed: {e}")
        raise
    
    finally:
        if session:
            session.close()

if __name__ == "__main__":
    main()