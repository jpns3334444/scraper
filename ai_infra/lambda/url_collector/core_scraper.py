#!/usr/bin/env python3
"""
Core scraping functionality for homes.co.jp
"""
import time
import requests
import random
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    """Parse price text like '32,000万円' or '32,000' to numeric value in man-yen"""
    if not price_text:
        return 0
    
    try:
        # Remove common patterns and extract number
        price_clean = re.sub(r'[^\d,万円.]', '', str(price_text))
        
        # Handle different formats
        if '万円' in price_clean:
            # Format: "32,000万円" -> 32000
            number_part = price_clean.replace('万円', '').replace(',', '')
            return int(float(number_part))
        elif '円' in price_clean and '万円' not in price_clean:
            # Format: "320,000,000円" -> 32000 (convert from yen to man-yen)
            number_part = price_clean.replace('円', '').replace(',', '')
            return int(float(number_part) / 10000)  # Convert to man-yen
        else:
            # Format: "32,000" (assuming it's already in man-yen) -> 32000
            number_part = price_clean.replace(',', '')
            if number_part.isdigit():
                return int(number_part)
    except (ValueError, AttributeError):
        pass
    
    return 0

def normalize_ward_name(area_name):
    """Keep ward names in English for consistency"""
    # Simply return the area name as-is (already in English from URL)
    return area_name

def extract_listing_urls_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    relative_urls = re.findall(r'/mansion/b-\d+/?', html_content)
    unique_listings = set()
    
    for url in relative_urls:
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        unique_listings.add(absolute_url)
    
    return list(unique_listings)

def extract_listings_with_prices_from_html(html_content):
    """Extract listing URLs with prices from HTML structure where price number and unit are in separate elements"""
    listings = []
    seen_urls = set()
    
    # Method 1: Look for the specific HTML structure with separate price elements
    # Pattern: <td class="price"><span class="num">32,000</span>万円</td>
    price_pattern = r'<td[^>]*class="price"[^>]*><span[^>]*class="num"[^>]*>([\d,]+)</span>万円</td>'
    url_pattern = r'/mansion/b-(\d+)/?'
    
    # Find all price matches with their positions
    price_matches = list(re.finditer(price_pattern, html_content))
    url_matches = list(re.finditer(url_pattern, html_content))
    
    # For each URL, find the nearest price within reasonable distance
    for url_match in url_matches:
        url = url_match.group(0)
        url_pos = url_match.start()
        
        if url in seen_urls:
            continue
        seen_urls.add(url)
        
        # Find the closest price match (within 1000 characters)
        closest_price = None
        min_distance = float('inf')
        
        for price_match in price_matches:
            price_pos = price_match.start()
            distance = abs(price_pos - url_pos)
            
            # Price should be reasonably close to URL (within 1000 chars)
            if distance < 1000 and distance < min_distance:
                min_distance = distance
                closest_price = price_match.group(1)
        
        # Create price text and parse it
        if closest_price:
            price_text = f"{closest_price}万円"
            price = parse_price_from_text(price_text)
        else:
            price_text = ''
            price = 0
        
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        listings.append({
            'url': absolute_url,
            'price': price,
            'price_text': price_text
        })
    
    # Method 2: Fallback to simpler patterns if method 1 finds too few
    if len(listings) < 10:
        listings.clear()
        seen_urls.clear()
        
        # Try simpler proximity-based matching
        pattern = re.compile(
            r'(/mansion/b-\d+/?)[^<]*(?:<[^>]*>[^<]*)*?(\d{1,4}(?:,\d{3})*万円)',
            re.DOTALL
        )
        
        for match in pattern.finditer(html_content):
            url = match.group(1)
            price_text = match.group(2)
            
            if url not in seen_urls:
                seen_urls.add(url)
                absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
                listings.append({
                    'url': absolute_url,
                    'price': parse_price_from_text(price_text),
                    'price_text': price_text
                })
        
        # Method 3: If still too few, find all URLs and try to match prices
        if len(listings) < 10:
            listings.clear()
            seen_urls.clear()
            
            urls = re.findall(r'/mansion/b-\d+/?', html_content)
            
            for url in set(urls):
                absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
                
                # Find price after this URL (within 500 chars)
                url_pos = html_content.find(url)
                if url_pos != -1:
                    search_text = html_content[url_pos:url_pos + 500]
                    
                    # Try different price patterns
                    price_match = re.search(r'<span[^>]*class="num"[^>]*>([\d,]+)</span>万円', search_text)
                    if not price_match:
                        price_match = re.search(r'(\d{1,4}(?:,\d{3})*万円)', search_text)
                    
                    if price_match:
                        if 'num' in price_match.group(0):  # First pattern matched
                            price_text = f"{price_match.group(1)}万円"
                        else:  # Second pattern matched
                            price_text = price_match.group(1)
                        price = parse_price_from_text(price_text)
                    else:
                        price = 0
                        price_text = ''
                else:
                    price = 0
                    price_text = ''
                
                listings.append({
                    'url': absolute_url,
                    'price': price,
                    'price_text': price_text
                })
    
    return listings

def collect_area_listing_urls(area_name, max_pages=None, session=None, logger=None):
    """Collect listing URLs from a specific Tokyo area (legacy function for compatibility)"""
    listings_with_prices = collect_area_listings_with_prices(area_name, max_pages, session, logger)
    return [listing['url'] for listing in listings_with_prices]

def collect_area_listings_with_prices(area_name, max_pages=None, session=None, logger=None):
    """Collect listing URLs with prices from a specific Tokyo area"""
    # Validate area_name to prevent malformed URLs
    if not area_name or not area_name.strip():
        raise ValueError(f"Invalid area_name: '{area_name}' - area_name cannot be empty or None")
    
    area_name = area_name.strip()
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
        
        # Parse pagination info using regex
        # Extract total count
        total_count_match = re.search(r'<span[^>]*class="totalNum"[^>]*>(\d+)</span>', response.text)
        total_count = int(total_count_match.group(1)) if total_count_match else 0

        # Extract page numbers from data-page attributes
        page_numbers = re.findall(r'data-page="(\d+)"', response.text)
        total_pages = max([int(p) for p in page_numbers]) if page_numbers else 1

        # Alternative: Look for the last page link
        if not page_numbers:
            # Try to find pagination links with page numbers in href
            page_href_matches = re.findall(r'[?&]page=(\d+)', response.text)
            if page_href_matches:
                total_pages = max([int(p) for p in page_href_matches])
            else:
                total_pages = 1
        
        if max_pages:
            total_pages = min(total_pages, max_pages)
        
        # Normalize ward name from area_name
        ward = normalize_ward_name(area_name)
        
        # Extract listings with prices from page 1
        page1_listings = extract_listings_with_prices_from_html(response.text)
        for listing in page1_listings:
            listing['ward'] = ward  # Add ward to each listing
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
                    listing['ward'] = ward  # Add ward to each listing
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




def discover_tokyo_areas(logger=None):
    """Discover all Tokyo area URLs using regex"""
    session = create_session(logger)
    city_listing_url = "https://www.homes.co.jp/mansion/chuko/tokyo/city/"
    
    try:
        response = session.get(city_listing_url, timeout=15)
        if response.status_code != 200:
            raise Exception(f"Failed to access city listing: HTTP {response.status_code}")
        
        area_links = []
        
        # Find area links using regex
        # Pattern: /mansion/chuko/tokyo/AREA_NAME/list/
        pattern = re.compile(r'/mansion/chuko/tokyo/([^/]+)/list/')
        matches = pattern.findall(response.text)
        
        for area_name in matches:
            # Clean and validate area name
            area_name = area_name.strip()
            # Skip invalid entries
            if (area_name and 
                area_name != 'city' and 
                not area_name.startswith('.') and
                not area_name.startswith('#') and
                len(area_name) < 50):  # Reasonable length limit
                area_links.append(area_name)
        
        # Remove duplicates and sort
        area_links = sorted(list(set(area_links)))
        
        # Use fallback list if no links found or too few
        if len(area_links) < 10:
            if logger:
                logger.warning(f"Only found {len(area_links)} areas, using fallback list")
            area_links = [
                'adachi-city', 'akiruno-city', 'akishima-city', 'arakawa-city',
                'bunkyo-city', 'chiyoda-city', 'chofu-city', 'chuo-city',
                'edogawa-city', 'fuchu-city', 'fussa-city', 'hachioji-city',
                'hamura-city', 'higashikurume-city', 'higashimurayama-city',
                'higashiyamato-city', 'hino-city', 'hinode-town', 'hinohara-village',
                'inagi-city', 'itabashi-city', 'katsushika-city', 'kita-city',
                'kiyose-city', 'kodaira-city', 'koganei-city', 'kokubunji-city',
                'komae-city', 'koto-city', 'kunitachi-city', 'machida-city',
                'meguro-city', 'minato-city', 'mitaka-city', 'mizuho-town',
                'musashimurayama-city', 'musashino-city', 'nakano-city',
                'nerima-city', 'nishitokyo-city', 'ome-city', 'ota-city',
                'okutama-town', 'setagaya-city', 'shibuya-city', 'shinagawa-city',
                'shinjuku-city', 'suginami-city', 'sumida-city', 'tachikawa-city',
                'taito-city', 'tama-city', 'toshima-city'
            ]
        
        if logger:
            logger.debug(f"Discovered {len(area_links)} Tokyo areas")
        
        return area_links
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to discover areas: {str(e)}")
        
        # Return comprehensive fallback list
        return [
            'chofu-city', 'shibuya-city', 'shinjuku-city', 'setagaya-city',
            'minato-city', 'chiyoda-city', 'chuo-city', 'meguro-city',
            'ota-city', 'shinagawa-city', 'nerima-city', 'suginami-city'
        ]
    
    finally:
        session.close()