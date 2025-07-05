#!/usr/bin/env python3
"""
HTTP-based scraper for homes.co.jp using session management
Replaces Chrome/Selenium with fast, reliable HTTP requests
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

def create_session():
    """Create HTTP session with proper headers for homes.co.jp"""
    session = requests.Session()
    
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ja-JP,ja;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    }
    
    session.headers.update(headers)
    return session

def extract_listings_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    # Extract relative URLs like /mansion/b-1234567890/
    relative_urls = re.findall(r'/mansion/b-\d+/', html_content)
    
    # Convert to absolute URLs and remove duplicates
    unique_listings = set()
    for url in relative_urls:
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        unique_listings.add(absolute_url)
    
    return list(unique_listings)

def get_listing_links_with_session(base_url, max_pages=10):
    """Get all listing links using session-based pagination"""
    session = create_session()
    all_links = set()
    
    log_structured_message("INFO", "Starting listing collection", base_url=base_url)
    
    try:
        # Step 1: Get page 1 to establish session
        print(f"=== Fetching page 1 to establish session ===")
        response = session.get(base_url, timeout=15)
        
        if response.status_code != 200:
            log_structured_message("ERROR", "Failed to access page 1", status_code=response.status_code)
            return []
        
        # Check for anti-bot protection
        if "pardon our interruption" in response.text.lower():
            log_structured_message("ERROR", "Anti-bot protection detected on page 1")
            return []
        
        # Parse pagination info
        soup = BeautifulSoup(response.content, 'html.parser')
        total_element = soup.select_one('.totalNum')
        total_count = int(total_element.text) if total_element else 0
        
        page_links = soup.select('a[data-page]')
        max_page = max([int(link.get('data-page', 1)) for link in page_links]) if page_links else 1
        max_page = min(max_page, max_pages)  # Respect max_pages limit
        
        log_structured_message("INFO", "Pagination info parsed", 
                             total_listings=total_count, max_page=max_page)
        
        # Extract listings from page 1
        page1_listings = extract_listings_from_html(response.text)
        all_links.update(page1_listings)
        print(f"Page 1: Found {len(page1_listings)} listings")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages
        for page_num in range(2, max_page + 1):
            print(f"=== Fetching page {page_num} ===")
            
            # Respectful delay between requests
            time.sleep(random.uniform(2, 4))
            
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    log_structured_message("WARNING", "Failed to access page", 
                                         page=page_num, status_code=response.status_code)
                    continue
                
                # Check for anti-bot protection
                if "pardon our interruption" in response.text.lower():
                    log_structured_message("ERROR", "Anti-bot protection triggered", page=page_num)
                    break
                
                # Extract listings
                page_listings = extract_listings_from_html(response.text)
                all_links.update(page_listings)
                print(f"Page {page_num}: Found {len(page_listings)} listings")
                
                # Update referer for next request
                session.headers['Referer'] = page_url
                
                # Log progress
                log_structured_message("INFO", "Page scraped successfully", 
                                     page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                log_structured_message("ERROR", "Error fetching page", 
                                     page=page_num, error=str(e))
                continue
        
        all_links_list = list(all_links)
        log_structured_message("INFO", "Listing collection completed", 
                             total_unique_links=len(all_links_list))
        
        return all_links_list
        
    except Exception as e:
        log_structured_message("ERROR", "Error in listing collection", error=str(e))
        return []
    finally:
        session.close()

def scrape_listing_details(url, retries=2):
    """Scrape detailed information from a listing URL"""
    session = create_session()
    
    for attempt in range(retries + 1):
        try:
            print(f"Scraping: {url}")
            
            # Add delay to be respectful
            time.sleep(random.uniform(1, 2))
            
            response = session.get(url, timeout=15)
            
            if response.status_code != 200:
                if attempt == retries:
                    return {"url": url, "title": None, "price": None, "error": f"HTTP {response.status_code}"}
                continue
            
            # Check for anti-bot protection
            if "pardon our interruption" in response.text.lower():
                return {"url": url, "title": None, "price": None, "error": "Anti-bot protection"}
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {"url": url}
            
            # Extract title
            try:
                title_elem = soup.select_one("h1")
                data["title"] = title_elem.text.strip() if title_elem else None
            except:
                data["title"] = None
            
            # Extract price
            try:
                price_elem = soup.select_one("div.price-main em")
                data["price"] = price_elem.text.strip() if price_elem else None
            except:
                data["price"] = None
            
            # Extract property details from summary table
            try:
                rows = soup.select("table.mod-tableSummary tr")
                for row in rows:
                    try:
                        key_elem = row.select_one("th")
                        val_elem = row.select_one("td")
                        if key_elem and val_elem:
                            key = key_elem.text.strip()
                            val = val_elem.text.strip()
                            data[key] = val
                    except:
                        continue
            except:
                pass
            
            session.close()
            return data
            
        except Exception as e:
            print(f"[Attempt {attempt + 1}] Error scraping {url}: {e}")
            if attempt == retries:
                session.close()
                return {"url": url, "title": None, "price": None, "error": str(e)}
            time.sleep(2)
    
    session.close()
    return {"url": url, "title": None, "price": None, "error": "Max retries exceeded"}

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
    """Main scraper function using HTTP requests"""
    job_start_time = datetime.now()
    log_structured_message("INFO", "Starting HTTP scraper job", start_time=job_start_time.isoformat())
    
    error_count = 0
    success_count = 0
    
    try:
        # Configuration
        BASE_URL = "https://www.homes.co.jp/mansion/chuko/tokyo/chofu-city/list"
        max_pages = 10  # Adjust as needed
        
        # Step 1: Collect all listing links using session management
        print("\n🔗 Collecting listing links...")
        all_links = get_listing_links_with_session(BASE_URL, max_pages)
        
        if not all_links:
            raise Exception("No listing links found - possible anti-bot protection or site issue")
        
        log_structured_message("INFO", "Link collection completed", total_links=len(all_links))
        
        # Step 2: Scrape details from each listing
        print(f"\n📋 Scraping details from {len(all_links)} listings...")
        listings_data = []
        max_threads = 3  # Conservative threading for respectful scraping
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(scrape_listing_details, url): url for url in all_links}
            
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                    listings_data.append(result)
                    
                    if result.get("title") and result.get("price") and not result.get("error"):
                        success_count += 1
                    else:
                        error_count += 1
                        
                except Exception as e:
                    log_structured_message("ERROR", "Error scraping listing", url=url, error=str(e))
                    error_count += 1
                    listings_data.append({"url": url, "title": None, "price": None, "error": str(e)})
        
        # Step 3: Save data
        df = pd.DataFrame(listings_data)
        
        # Save locally
        filename = f"chofu-city-list-{datetime.now().strftime('%Y-%m-%d')}.csv"
        
        # Try desktop first, fallback to current directory
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
        
        if output_bucket:
            s3_key = f"scraper-output/{filename}"
            s3_upload_success = upload_to_s3(local_path, output_bucket, s3_key)
        else:
            log_structured_message("WARNING", "OUTPUT_BUCKET environment variable not set")
        
        # Step 5: Generate job summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP",
            "total_links_found": len(all_links),
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
            "scraper_type": "HTTP",
            "status": "ERROR",
            "error": str(e)
        }
        
        write_job_summary(summary_data)
        log_structured_message("ERROR", "HTTP scraper job failed", **summary_data)
        print(f"\n❌ Scraping failed: {e}")
        raise

if __name__ == "__main__":
    main()