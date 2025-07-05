import time
import pandas as pd
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth
from concurrent.futures import ThreadPoolExecutor, as_completed
import types
import random
import boto3
from datetime import datetime
import json

# === Optional: rotating user agents ===
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def patch_driver_del(driver):
    def safe_del(self):
        try:
            self.service.stop()
        except:
            pass
    driver.__del__ = types.MethodType(safe_del, driver)

def create_driver():
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("disable-blink-features=AutomationControlled")
    ua = random.choice(USER_AGENTS)
    options.add_argument(f"user-agent={ua}")

    driver = uc.Chrome(options=options)
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
    )
    patch_driver_del(driver)
    return driver

BASE_URL = "https://www.homes.co.jp/mansion/chuko/tokyo/chofu-city/list"

def get_listing_links_from_page(page):
    url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"
    print(f"\n=== Scraping listing links from page {page} ===")
    print(f"Loading URL: {url}")
    driver = create_driver()
    wait = WebDriverWait(driver, 10)

    try:
        driver.get(url)
        time.sleep(random.uniform(2.5, 4))

        if "Pardon Our Interruption" in driver.title:
            print("🚫 Bot challenge hit. Save HTML + rotate IP before retrying.")
            with open(f"page_{page}_captcha.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            driver.quit()
            return []

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*=mod-listKks]")))
        print("✅ Listing container appeared!")

        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        listings = driver.find_elements(By.CSS_SELECTOR, "a[href*='/mansion/b-']")
        links = {
            href for href in [a.get_attribute("href") for a in listings]
            if href and href.startswith("https://www.homes.co.jp/mansion/b-") and href.rstrip('/').count('/') == 4
        }
        print(f"Found {len(links)} links on page {page}")

        driver.quit()
        return list(links)

    except Exception as e:
        print(f"❌ Error on page {page}: {e}")
        driver.quit()
        return []

def scrape_listing_details(url, retries=2):
    for attempt in range(retries + 1):
        try:
            driver = create_driver()
            wait = WebDriverWait(driver, 10)
            print(f"Scraping: {url}")
            driver.get(url)
            time.sleep(2)
            data = {"url": url}

            try:
                title_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
                data["title"] = title_elem.text.strip()
            except:
                data["title"] = None

            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.price-main em")))
                price_elem = driver.find_element(By.CSS_SELECTOR, "div.price-main em")
                data["price"] = price_elem.text.strip()
            except:
                data["price"] = None

            try:
                rows = driver.find_elements(By.CSS_SELECTOR, "table.mod-tableSummary tr")
                for row in rows:
                    try:
                        key = row.find_element(By.TAG_NAME, "th").text.strip()
                        val = row.find_element(By.TAG_NAME, "td").text.strip()
                        data[key] = val
                    except:
                        continue
            except:
                pass

            driver.quit()
            return data

        except Exception as e:
            print(f"[Attempt {attempt + 1}] Error scraping {url}: {e}")
            time.sleep(3)
            if attempt == retries:
                return {"url": url, "title": None, "price": None}

def upload_to_s3(file_path, bucket, s3_key):
    try:
        s3 = boto3.client("s3")
        s3.upload_file(file_path, bucket, s3_key)
        print(f"📤 Uploaded to s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        print(f"❌ S3 upload failed: {e}")
        return False

def write_job_summary(summary_data):
    try:
        summary_path = "/var/log/scraper/summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
        print(f"📋 Job summary written to {summary_path}")
    except Exception as e:
        print(f"❌ Failed to write job summary: {e}")

def log_structured_message(level, message, **kwargs):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        **kwargs
    }
    print(json.dumps(log_entry))

def main():
    job_start_time = datetime.now()
    log_structured_message("INFO", "Starting scraper job", start_time=job_start_time.isoformat())
    
    all_links = set()
    error_count = 0
    success_count = 0

    try:
        # === Step 1: collect links with fresh sessions ===
        for page in range(1, 10):  # Scrape up to 9 pages (adjust as needed)
            links = get_listing_links_from_page(page)
            if not links:
                log_structured_message("WARNING", "No links found or blocked", page=page)
                error_count += 1
                break
            all_links.update(links)
            log_structured_message("INFO", "Page scraped successfully", page=page, links_found=len(links))
            print("💤 Sleep before IP rotation...")
            time.sleep(10)

        all_links = list(all_links)
        log_structured_message("INFO", "Link collection completed", total_links=len(all_links))

        # === Step 2: parallel scrape details ===
        listings_data = []
        max_threads = 5

        log_structured_message("INFO", "Starting parallel scraping", max_threads=max_threads)
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(scrape_listing_details, url): url for url in all_links}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                    listings_data.append(result)
                    if result.get("title") and result.get("price"):
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    log_structured_message("ERROR", "Error scraping listing", url=url, error=str(e))
                    error_count += 1

        df = pd.DataFrame(listings_data)

        # === Save to desktop
        filename = f"chofu-city-list-{datetime.now().strftime('%Y-%m-%d')}.csv"
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", filename)
        df.to_csv(desktop_path, index=False)
        log_structured_message("INFO", "Data saved locally", file_path=desktop_path)

        # === Upload to S3
        s3_upload_success = False
        output_bucket = os.environ.get("OUTPUT_BUCKET")
        if output_bucket:
            s3_key = f"scraper-output/{filename}"
            s3_upload_success = upload_to_s3(desktop_path, output_bucket, s3_key)
        else:
            log_structured_message("WARNING", "OUTPUT_BUCKET environment variable not set")

        # === Generate job summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "total_links_found": len(all_links),
            "successful_scrapes": success_count,
            "failed_scrapes": error_count,
            "total_records": len(listings_data),
            "output_file": filename,
            "s3_upload_success": s3_upload_success,
            "s3_key": s3_key if output_bucket else None,
            "status": "SUCCESS" if success_count > 0 else "FAILED"
        }
        
        write_job_summary(summary_data)
        log_structured_message("INFO", "Job completed successfully", **summary_data)
        
    except Exception as e:
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "status": "ERROR",
            "error": str(e)
        }
        
        write_job_summary(summary_data)
        log_structured_message("ERROR", "Job failed with exception", **summary_data)
        raise

if __name__ == "__main__":
    main()