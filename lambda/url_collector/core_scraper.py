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
import boto3

INQUIRE_SUBSTRING = "/inquire/"      # marketing / brochure / visit links

def _is_inquiry_url(url: str) -> bool:
    """Return True for brochure / visit enquiry URLs we don't want to scrape."""
    return INQUIRE_SUBSTRING in url

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
        return None
    
    # Ignore inquiry phrases and garbage like "3件万円"
    if any(token in price_text for token in ('件', '問い合わせ', '未定', '相談')):
        return None
    
    # Extract the first "<number>万円" pattern — ignore trailing floor-plan text
    m = re.search(r'([\d,]+)\s*万円', str(price_text))
    if m:
        return int(m.group(1).replace(',', ''))
    
    try:
        # Strip nuisance characters before digit test
        price_clean = re.sub(r'[^\d,円万円〜台以上.]', '', str(price_text))
        
        # Check if cleaned string contains digits
        if not re.search(r'\d', price_clean):
            return None
        
        # Handle ranges by taking the lower bound
        if '〜' in str(price_text):
            # Split on 〜 and take the first part
            price_parts = str(price_text).split('〜')
            if price_parts and price_parts[0]:
                price_clean = re.sub(r'[^\d,円万円.]', '', price_parts[0])
                price_clean = price_clean.replace('〜', '')
        
        # Handle high-end prices like "1億2,880万円"
        if '億' in price_clean:
            oku_part, man_part = price_clean.split('億', 1)
            oku_val = int(oku_part.replace(',', '')) * 10000  # 1 億 = 10,000 万
            man_val = parse_price_from_text(man_part or '0万円') or 0
            return oku_val + man_val
        
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
    
    return None

def normalize_ward_name(area_name):
    """Keep ward names in English for consistency"""
    # Simply return the area name as-is (already in English from URL)
    return area_name

def extract_listing_urls_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    soup = BeautifulSoup(html_content, 'lxml')
    
    # Select tags that directly carry the link
    tag_candidates = soup.select(
        '[href*="/mansion/b-"], [data-linkurl*="/mansion/b-"], [onclick*="/mansion/b-"]'
    )
    
    BASE_URL = "https://www.homes.co.jp"
    seen_urls = set()
    results = []
    
    for tag in tag_candidates:
        # 1️⃣ pull out the raw link
        # pull out the raw link once
        onclick_match = re.search(r"/mansion/b-\d+[^\s\"'>]*",
                                  tag.get("onclick", ""))
        href = (
            tag.get("href")
            or tag.get("data-linkurl")
            or (onclick_match.group(0) if onclick_match else None)
        )
        
        # skip if we somehow didn't extract
        if not href:
            continue
        
        if _is_inquiry_url(href):
            continue  # skip brochure / visit links
        
        # 2️⃣ canonicalise to absolute URL
        absolute_url = href if href.startswith('http') else f"{BASE_URL}{href}"
        
        # 3️⃣ dedupe on the whole URL
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        results.append(absolute_url)
    
    return results

def _find_price(node):
    """
    Given a BeautifulSoup tag associated with a listing's <a>,
    return (price_value_int, price_text_str) or (None, None).
    """
    # Search order:
    # a. Card layout – sibling <div class="price">
    sibling_price = node.find_next_sibling(class_='price')
    if sibling_price:
        price_text = sibling_price.get_text(strip=True)
        price_value = parse_price_from_text(price_text)
        if price_value and price_value > 0:
            return (price_value, price_text)
    
    # NEW: look forward anywhere inside the same card for a .price element
    deep_price = node.find_next(class_=re.compile('price'))
    if deep_price:
        price_text = deep_price.get_text(strip=True)
        price_value = parse_price_from_text(price_text)
        if price_value and price_value > 0:
            return (price_value, price_text)
    
    # NEW-2: if we still have nothing, look *within the same card* for any span.num
    deepest_num = node.find_next('span', class_='num')
    if deepest_num:
        # sometimes the surrounding tag holds "万円" outside <span class="num">
        parent_text = deepest_num.parent.get_text(strip=True)
        price_text = deepest_num.text + ('' if '万円' in parent_text else '万円')
        price_value = parse_price_from_text(price_text)
        if price_value and price_value > 0:
            return (price_value, price_text)
    
    # b. Table layout – the enclosing <tr> → the <td class*="price">
    tr = node.find_parent('tr')
    if tr:
        price_cell = tr.find('td', class_=re.compile('price'))
        if price_cell:
            price_span = price_cell.find('span', class_='num')
            if price_span and '万円' in price_cell.text:
                price_num = price_span.text.strip()
                price_text = f"{price_num}万円"
                price_value = parse_price_from_text(price_text)
                if price_value and price_value > 0:
                    return (price_value, price_text)
    
    # c. Generic climb – first ancestor that contains ".price" in its classes
    # or has a child <span class="num">
    container = node
    for _ in range(10):  # Look up to 10 levels
        parent = container.parent
        if not parent:
            break
        
        # Check for price class
        if hasattr(parent, 'get'):
            parent_classes = parent.get('class', [])
            if parent_classes and any('price' in str(c) for c in parent_classes):
                price_text = parent.get_text(strip=True)
                price_value = parse_price_from_text(price_text)
                if price_value and price_value > 0:
                    return (price_value, price_text)
        
        # Check for child with price
        price_elem = parent.find(class_=re.compile('price'))
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price_value = parse_price_from_text(price_text)
            if price_value and price_value > 0:
                return (price_value, price_text)
        
        container = parent
    
    return (None, None)

# Alternative: Hybrid approach - use regex for URLs, BeautifulSoup for prices
def extract_listings_with_prices_from_html(html_content):
    """Hybrid approach: regex for URLs (fast), BeautifulSoup for price extraction (reliable)"""
    soup = BeautifulSoup(html_content, 'lxml')
    
    # Select tags that directly carry the link
    tag_candidates = soup.select(
        '[href*="/mansion/b-"], [data-linkurl*="/mansion/b-"], [onclick*="/mansion/b-"]'
    )
    
    BASE_URL = "https://www.homes.co.jp"
    listings, seen_urls, zero_price_count = [], set(), 0
    
    for tag in tag_candidates:
        # 1️⃣ pull out the raw link
        # pull out the raw link once
        onclick_match = re.search(r"/mansion/b-\d+[^\s\"'>]*",
                                  tag.get("onclick", ""))
        href = (
            tag.get("href")
            or tag.get("data-linkurl")
            or (onclick_match.group(0) if onclick_match else None)
        )
        
        # skip if we somehow didn't extract
        if not href or _is_inquiry_url(href):
            continue    # skip empty or inquiry links
        
        # 2️⃣ canonicalise to absolute URL
        absolute_url = href if href.startswith('http') else f"{BASE_URL}{href}"
        
        # 3️⃣ dedupe on the whole URL
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        
        # 4️⃣ find nearest price
        price_value, price_text = _find_price(tag)
        
        if price_value is not None:
            listings.append({'url': absolute_url,
                             'price': price_value,
                             'price_text': price_text})
        else:
            listings.append({'url': absolute_url,
                             'price': 0,
                             'price_text': ''})
            zero_price_count += 1
    
    # Log warning if more than 5% of rows have zero price
    if listings:
        zero_price_percentage = (zero_price_count / len(listings)) * 100
        if zero_price_percentage > 5:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"High zero-price rate: {zero_price_percentage:.1f}% ({zero_price_count}/{len(listings)}) rows have no price")
    
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