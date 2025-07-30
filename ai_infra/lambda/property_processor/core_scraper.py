#!/usr/bin/env python3
"""
Core scraping functionality for homes.co.jp
"""
import time
import requests
import random
import re
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import io
import boto3

# Simplified browser profiles
BROWSER_PROFILES = [
    {
        "name": "Chrome_Windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-platform": '"Windows"',
            "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
        }
    },
    {
        "name": "Chrome_Mac",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="123", "Google Chrome";v="123", "Not-A.Brand";v="99"',
            "sec-ch-ua-platform": '"macOS"',
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
        }
    }
]

def create_session(logger=None):
    """Create HTTP session with anti-bot headers"""
    session = requests.Session()
    
    # Random browser profile
    profile = random.choice(BROWSER_PROFILES)
    base_headers = profile["headers"].copy()
    
    # Common headers
    base_headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    })
    
    session.headers.update(base_headers)
    
    if logger:
        logger.debug(f"Session created with {profile['name']}")
    
    return session

def parse_price_from_text(price_text):
    """Parse price text like '1,980万円' to numeric value in man-yen"""
    if not price_text:
        return 0
    
    try:
        # Remove common patterns and extract number
        price_clean = re.sub(r'[^\d,万円.]', '', str(price_text))
        
        # Handle different formats
        if '万円' in price_clean:
            # Format: "1,980万円" -> 1980
            number_part = price_clean.replace('万円', '').replace(',', '')
            return int(float(number_part))
        elif '円' in price_clean:
            # Format: "19,800,000円" -> 1980
            number_part = price_clean.replace('円', '').replace(',', '')
            return int(float(number_part) / 10000)  # Convert to man-yen
        else:
            # Try to extract just numbers
            number_part = price_clean.replace(',', '')
            if number_part.isdigit():
                return int(number_part)
    except (ValueError, AttributeError):
        pass
    
    return 0

def extract_listing_urls_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    relative_urls = re.findall(r'/mansion/b-\d+/?', html_content)
    unique_listings = set()
    
    for url in relative_urls:
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        unique_listings.add(absolute_url)
    
    return list(unique_listings)

def extract_listings_with_prices_from_html(html_content):
    """Extract listing URLs with prices from HTML content"""
    from bs4 import BeautifulSoup
    
    soup = BeautifulSoup(html_content, 'html.parser')
    listings = []
    
    # Look for listing containers - these may vary, so we'll try multiple selectors
    listing_selectors = [
        '.mod-mergeTable tr',  # Common table row format
        '.property-item',      # Property item containers
        '.listing-item',       # Alternative listing format
        '.searchResult-item',  # Search result items
        'tr[class*="item"]',   # Table rows with "item" in class
        '.bukken-item'         # Property (bukken) items
    ]
    
    for selector in listing_selectors:
        items = soup.select(selector)
        if items:
            for item in items:
                # Find URL
                url_link = item.find('a', href=re.compile(r'/mansion/b-\d+/?'))
                if not url_link:
                    continue
                
                relative_url = url_link.get('href')
                if not relative_url:
                    continue
                
                absolute_url = f"https://www.homes.co.jp{relative_url.rstrip('/')}"
                
                # Find price - try multiple approaches
                price = 0
                price_text = ""
                
                # Try different price selectors
                price_selectors = [
                    '.price',
                    '.price-value', 
                    '.bukken-price',
                    '.mod-price',
                    '[class*="price"]',
                    'td[class*="price"]',
                    '.searchResult-price'
                ]
                
                for price_sel in price_selectors:
                    price_elem = item.select_one(price_sel)
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        break
                
                # If no dedicated price element, search for price patterns in text
                if not price_text:
                    item_text = item.get_text()
                    price_match = re.search(r'(\d{1,4}(?:,\d{3})*万円)', item_text)
                    if price_match:
                        price_text = price_match.group(1)
                
                # Parse the price
                if price_text:
                    price = parse_price_from_text(price_text)
                
                listings.append({
                    'url': absolute_url,
                    'price': price,
                    'price_text': price_text
                })
            
            # If we found listings with this selector, use them
            if listings:
                break
    
    # Fallback to URL-only extraction if no prices found
    if not listings:
        urls = extract_listing_urls_from_html(html_content)
        listings = [{'url': url, 'price': 0, 'price_text': ''} for url in urls]
    
    return listings

def collect_area_listing_urls(area_name, max_pages=None, session=None, logger=None):
    """Collect listing URLs from a specific Tokyo area (legacy function for compatibility)"""
    listings_with_prices = collect_area_listings_with_prices(area_name, max_pages, session, logger)
    return [listing['url'] for listing in listings_with_prices]

def collect_area_listings_with_prices(area_name, max_pages=None, session=None, logger=None):
    """Collect listing URLs with prices from a specific Tokyo area"""
    base_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{area_name}/list"
    
    if session is None:
        session = create_session(logger)
        should_close_session = True
    else:
        should_close_session = False
    
    all_listings = {}  # Use dict to deduplicate by URL while keeping price info
    
    if logger:
        logger.info(f"Collecting listings with prices from {area_name}")
    
    try:
        # Get page 1
        response = session.get(base_url, timeout=15)
        
        if response.status_code != 200:
            raise Exception(f"Failed to access {area_name}: HTTP {response.status_code}")
        
        if "pardon our interruption" in response.text.lower():
            raise Exception(f"Anti-bot protection detected on {area_name}")
        
        # Parse pagination info
        soup = BeautifulSoup(response.content, 'html.parser')
        total_element = soup.select_one('.totalNum')
        total_count = int(total_element.text) if total_element else 0
        
        page_links = soup.select('a[data-page]')
        total_pages = max([int(link.get('data-page', 1)) for link in page_links]) if page_links else 1
        
        if max_pages:
            total_pages = min(total_pages, max_pages)
        
        # Extract listings with prices from page 1
        page1_listings = extract_listings_with_prices_from_html(response.text)
        for listing in page1_listings:
            all_listings[listing['url']] = listing
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Get remaining pages
        for page_num in range(2, total_pages + 1):
            # Anti-bot delay
            time.sleep(random.uniform(1, 3))
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    if logger:
                        logger.debug(f"Failed page {page_num}: HTTP {response.status_code}")
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    if logger:
                        logger.error(f"Anti-bot triggered on page {page_num}")
                    break
                
                page_listings = extract_listings_with_prices_from_html(response.text)
                for listing in page_listings:
                    all_listings[listing['url']] = listing
                
                session.headers['Referer'] = page_url
                
            except Exception as e:
                if logger:
                    logger.error(f"Error on page {page_num}: {str(e)}")
                continue
        
        area_listings_list = list(all_listings.values())
        if logger:
            logger.debug(f"Found {len(area_listings_list)} listings with prices in {area_name}")
        
        return area_listings_list
        
    except Exception as e:
        if logger:
            logger.error(f"Error collecting {area_name}: {str(e)}")
        return []
    
    finally:
        if should_close_session:
            session.close()

def extract_property_details(session, property_url, referer_url, retries=3, config=None, logger=None):
    """Extract detailed property information with retry logic"""
    last_error = None
    output_bucket = config.get('output_bucket', '') if config else ''
    
    for attempt in range(retries + 1):
        try:
            # Set referer and add delay
            session.headers['Referer'] = referer_url
            time.sleep(random.uniform(1, 2))
            
            response = session.get(property_url, timeout=15)
            
            if response.status_code != 200:
                if attempt == retries:
                    raise Exception(f"HTTP {response.status_code}")
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            
            if "pardon our interruption" in response.text.lower():
                raise Exception("Anti-bot protection detected")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {
                "url": property_url,
                "extraction_timestamp": datetime.now().isoformat()
            }
            
            # Extract property ID from URL
            property_id = "unknown"
            patterns = [
                r'/mansion/b-(\d+)/?',
                r'/b-(\d+)/?',
                r'property[_-]?id[=:](\d+)',
                r'mansion[_-]?(\d{8,})',
                r'/(\d{10,})/'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, property_url)
                if match:
                    property_id = match.group(1)
                    break
            
            data["id"] = property_id
            data["property_id"] = f"PROP#{datetime.now().strftime('%Y%m%d')}_{property_id}"
            
            # Extract title
            h1_elements = soup.select('h1')
            for h1 in h1_elements:
                if h1.text.strip() and ('マンション' in h1.text or '万円' in h1.text):
                    data["title"] = h1.text.strip()
                    break
            
            # Extract price
            price_pattern = re.search(r'(\d{1,4}(?:,\d{3})*万円)', response.text)
            if price_pattern:
                data["price"] = price_pattern.group(1)
            
            # Extract property details from tables
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 10:
                    for row in rows:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            key = cells[0].text.strip()
                            value = cells[1].text.strip()
                            if key and value and len(key) < 30:
                                data[key] = value
                    break
            
            # Extract images
            try:
                s3_keys = extract_property_images(
                    soup, session, "https://www.homes.co.jp", 
                    bucket=output_bucket, property_id=property_id,
                    config=config, logger=logger
                )
                if s3_keys:
                    data["photo_filenames"] = "|".join(s3_keys)
                    data["image_count"] = len(s3_keys)
                    
            except Exception as e:
                if logger:
                    logger.debug(f"Image extraction failed: {str(e)}")
            
            return data
            
        except Exception as e:
            last_error = e
            if logger:
                logger.debug(f"Attempt {attempt + 1} failed: {str(e)}")
            
            if attempt == retries:
                break
                
            # Exponential backoff
            time.sleep((2 ** attempt) + random.uniform(0, 1))
    
    if last_error:
        raise last_error
    else:
        raise Exception("Max retries exceeded")

def extract_property_images(soup, session, base_url, bucket=None, property_id=None, config=None, logger=None):
    """Extract property images and upload to S3"""
    s3_keys = []
    image_urls = set()
    
    try:
        # Image selectors
        selectors = [
            '.mainPhoto img',
            '.detailPhoto img', 
            '.gallery-item img',
            '.photo-gallery img',
            '.property-photos img',
            '.mansion-photos img',
            'img[src*="/photo/"]',
            'img[src*="/image/"]',
            'img[data-src*="photo"]',
            '[class*="photo"] img'
        ]
        
        for selector in selectors:
            for img in soup.select(selector):
                src = (img.get('src') or 
                      img.get('data-src') or 
                      img.get('data-original') or 
                      img.get('data-lazy-src'))
                
                if src:
                    # Convert to absolute URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = base_url + src
                    elif not src.startswith('http'):
                        src = base_url + '/' + src.lstrip('/')
                    
                    # Filter out non-property images
                    exclude_patterns = ['icon', 'logo', 'btn', 'button', 'arrow', 'banner']
                    if any(pattern in src.lower() for pattern in exclude_patterns):
                        continue
                        
                    if any(pattern in src.lower() for pattern in ['photo', 'image', 'pic', 'img']):
                        image_urls.add(src)
        
        # Limit to 5 images per property (reduced from 10 for better performance)
        urls = list(image_urls)[:5]
        
        # Download and process images in parallel
        s3_keys = download_images_parallel(urls, session, bucket, property_id, logger)

        return s3_keys
        
    except Exception as e:
        if logger:
            logger.error(f"Image extraction error: {str(e)}")
        return []

def download_single_image(session, img_url, index, bucket, property_id, logger):
    """Download and process a single image"""
    try:
        img_response = session.get(img_url, timeout=10)
        if img_response.status_code == 200:
            content_type = img_response.headers.get('content-type', 'image/jpeg')
            
            if 'image' in content_type:
                # Skip tiny images
                if len(img_response.content) < 1000:
                    return None
                
                # Convert and resize image
                img = Image.open(io.BytesIO(img_response.content))
                
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                
                output_buffer = io.BytesIO()
                img.save(output_buffer, format='JPEG', quality=85, optimize=True)
                output_buffer.seek(0)
                processed_image_bytes = output_buffer.getvalue()
                
                # Upload to S3
                if bucket and property_id:
                    s3_key = upload_image_to_s3(
                        processed_image_bytes, 
                        bucket, 
                        property_id, 
                        index, 
                        logger=logger
                    )
                    return s3_key
        
        return None
        
    except Exception as e:
        if logger:
            logger.debug(f"Failed to download image {index}: {str(e)}")
        return None

def download_images_parallel(image_urls, session, bucket, property_id, logger):
    """Download images in parallel with limited concurrency"""
    if not image_urls:
        return []
    
    s3_keys = []
    max_workers = min(3, len(image_urls))  # Limit to 3-5 concurrent downloads as requested
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all download tasks
            future_to_index = {}
            for i, img_url in enumerate(image_urls):
                future = executor.submit(
                    download_single_image, 
                    session, img_url, i, bucket, property_id, logger
                )
                future_to_index[future] = i
            
            # Collect results as they complete
            for future in as_completed(future_to_index):
                try:
                    s3_key = future.result()
                    if s3_key:
                        s3_keys.append(s3_key)
                except Exception as e:
                    if logger:
                        logger.debug(f"Image download future failed: {str(e)}")
    
    except Exception as e:
        if logger:
            logger.debug(f"Parallel image download failed: {str(e)}")
    
    return s3_keys

def upload_image_to_s3(image_content, bucket, property_id, image_index, logger=None):
    """Upload image to S3"""
    try:
        date_str = datetime.now().strftime('%Y-%m-%d')
        s3_key = f"raw/{date_str}/images/{property_id}_{image_index}.jpg"
        
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=image_content,
            ContentType='image/jpeg'
        )
        
        return s3_key
        
    except Exception as e:
        if logger:
            logger.debug(f"S3 upload failed: {str(e)}")
        return None

def discover_tokyo_areas(logger=None):
    """Discover all Tokyo area URLs"""
    session = create_session(logger)
    city_listing_url = "https://www.homes.co.jp/mansion/chuko/tokyo/city/"
    
    try:
        response = session.get(city_listing_url, timeout=15)
        if response.status_code != 200:
            raise Exception(f"Failed to access city listing: HTTP {response.status_code}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        area_links = []
        
        # Find area links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/mansion/chuko/tokyo/' in href and href.endswith('/list/'):
                area_part = href.split('/mansion/chuko/tokyo/')[-1].replace('/list/', '')
                if area_part and area_part != 'city':
                    area_links.append(area_part)
        
        # Use fallback list if no links found
        if not area_links:
            area_links = [
                'shibuya-ku', 'shinjuku-ku', 'minato-ku', 'chiyoda-ku', 'chuo-ku',
                'setagaya-ku', 'nerima-ku', 'suginami-ku', 'nakano-ku', 'itabashi-ku',
                'chofu-city', 'mitaka-city', 'musashino-city', 'tachikawa-city'
            ]
        
        valid_areas = sorted(list(set(area_links)))
        
        if logger:
            logger.debug(f"Discovered {len(valid_areas)} Tokyo areas")
        
        return valid_areas
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to discover areas: {str(e)}")
        
        # Return fallback list
        return ['chofu-city', 'shibuya-ku', 'shinjuku-ku', 'setagaya-ku']
    
    finally:
        session.close()