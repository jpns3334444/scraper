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

# Japanese to English ward mapping
JAPANESE_TO_ENGLISH_WARD = {
    '千代田区': 'chiyoda-ku',
    '中央区': 'chuo-ku',
    '港区': 'minato-ku',
    '新宿区': 'shinjuku-ku',
    '文京区': 'bunkyo-ku',
    '台東区': 'taito-ku',
    '墨田区': 'sumida-ku',
    '江東区': 'koto-ku',
    '品川区': 'shinagawa-ku',
    '目黒区': 'meguro-ku',
    '大田区': 'ota-ku',
    '世田谷区': 'setagaya-ku',
    '渋谷区': 'shibuya-ku',
    '中野区': 'nakano-ku',
    '杉並区': 'suginami-ku',
    '豊島区': 'toshima-ku',
    '北区': 'kita-ku',
    '荒川区': 'arakawa-ku',
    '板橋区': 'itabashi-ku',
    '練馬区': 'nerima-ku',
    '足立区': 'adachi-ku',
    '葛飾区': 'katsushika-ku',
    '江戸川区': 'edogawa-ku',
    # Tokyo cities
    '八王子市': 'hachioji-city',
    '立川市': 'tachikawa-city',
    '武蔵野市': 'musashino-city',
    '三鷹市': 'mitaka-city',
    '青梅市': 'ome-city',
    '府中市': 'fuchu-city',
    '昭島市': 'akishima-city',
    '調布市': 'chofu-city',
    '町田市': 'machida-city',
    '小金井市': 'koganei-city',
    '小平市': 'kodaira-city',
    '日野市': 'hino-city',
    '東村山市': 'higashimurayama-city',
    '国分寺市': 'kokubunji-city',
    '国立市': 'kunitachi-city',
    '福生市': 'fussa-city',
    '狛江市': 'komae-city',
    '東久留米市': 'higashikurume-city',
    '清瀬市': 'kiyose-city',
    '東大和市': 'higashiyamato-city',
    '武蔵村山市': 'musashimurayama-city',
    '多摩市': 'tama-city',
    '稲城市': 'inagi-city',
    '羽村市': 'hamura-city',
    'あきる野市': 'akiruno-city',
    '西東京市': 'nishitokyo-city'
}

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
    
    # Handle case where price_text is already a number
    if isinstance(price_text, (int, float)):
        return int(price_text)
    
    try:
        # Convert to string and clean up
        price_str = str(price_text).strip()
        
        # Handle complex price displays (e.g., "9,380万円支払い目安：29.3万円／月")
        # Extract just the main price part before any additional text
        main_price_match = re.search(r'(\d{1,4}(?:,\d{3})*万円)', price_str)
        if main_price_match:
            price_str = main_price_match.group(1)
        
        # Remove common patterns and extract number
        price_clean = re.sub(r'[^\d,万円.]', '', price_str)
        
        # Handle different formats
        if '万円' in price_clean:
            # Format: "1,980万円" -> 1980
            number_part = price_clean.replace('万円', '').replace(',', '')
            if number_part:
                return int(float(number_part))
        elif '円' in price_clean:
            # Format: "19,800,000円" -> 1980
            number_part = price_clean.replace('円', '').replace(',', '')
            if number_part:
                return int(float(number_part) / 10000)  # Convert to man-yen
        else:
            # Try to extract just numbers
            number_part = price_clean.replace(',', '')
            if number_part and number_part.isdigit():
                return int(number_part)
    except (ValueError, AttributeError, TypeError):
        pass
    
    return 0

def parse_numeric_field(text, default=None):
    """Parse numeric fields from Japanese text"""
    if not text or text == '-':
        return default
    
    try:
        # Extract digits and decimal points
        cleaned = re.sub(r'[^\d.,]', '', str(text).replace('，', ','))
        cleaned = cleaned.replace(',', '')
        
        if cleaned:
            return float(cleaned)
    except (ValueError, TypeError):
        pass
    
    return default

def parse_building_age(text):
    """Parse building age from 築年月 field with enhanced era and format support"""
    if not text:
        return None
    
    try:
        # Pattern 1: "築25年" -> 25
        age_match = re.search(r'築(\d+)年', text)
        if age_match:
            return int(age_match.group(1))
        
        # Pattern 2: "1999年3月" -> calculate from year
        year_match = re.search(r'(\d{4})年', text)
        if year_match:
            built_year = int(year_match.group(1))
            current_year = datetime.now().year
            age = current_year - built_year
            return age if age >= 0 else None
        
        # Pattern 3: Japanese era years (平成, 昭和, 令和)
        # 平成 era: 1989-2019 (平成1年 = 1989)
        heisei_match = re.search(r'平成(\d+)年', text)
        if heisei_match:
            heisei_year = int(heisei_match.group(1))
            built_year = 1988 + heisei_year  # 平成1年 = 1989
            current_year = datetime.now().year
            age = current_year - built_year
            return age if age >= 0 else None
        
        # 昭和 era: 1926-1989 (昭和1年 = 1926)
        showa_match = re.search(r'昭和(\d+)年', text)
        if showa_match:
            showa_year = int(showa_match.group(1))
            built_year = 1925 + showa_year  # 昭和1年 = 1926
            current_year = datetime.now().year
            age = current_year - built_year
            return age if age >= 0 else None
        
        # 令和 era: 2019-present (令和1年 = 2019)
        reiwa_match = re.search(r'令和(\d+)年', text)
        if reiwa_match:
            reiwa_year = int(reiwa_match.group(1))
            built_year = 2018 + reiwa_year  # 令和1年 = 2019
            current_year = datetime.now().year
            age = current_year - built_year
            return age if age >= 0 else None
            
    except (ValueError, TypeError):
        pass
    
    return None

def parse_floor_info(text):
    """Parse floor information from '3階/10階建' format"""
    if not text:
        return None, None
    
    try:
        # Pattern: "3階/10階建" or "3階/10階"
        match = re.search(r'(\d+)階[^\d]*(\d+)階', text)
        if match:
            floor = int(match.group(1))
            total_floors = int(match.group(2))
            return floor, total_floors
        
        # Pattern: just "3階"
        floor_match = re.search(r'(\d+)階', text)
        if floor_match:
            return int(floor_match.group(1)), None
    except (ValueError, TypeError):
        pass
    
    return None, None

def extract_ward_and_district(address_text, provided_ward=None, logger=None):
    """Extract ward and district from Japanese address with improved fallback patterns"""
    if not address_text:
        return provided_ward, None
    
    # Clean up the address text
    address_clean = address_text.strip()
    
    # If a ward was provided from URL collection, use it and just extract district
    if provided_ward:
        if logger:
            logger.debug(f"Using provided ward from URL collection: {provided_ward}")
        
        # Extract district from address
        district = None
        # Try to find district after parsing address
        # Remove common patterns and look for area names
        district_match = re.search(r'([^\d０-９]{2,})', address_clean)
        if district_match:
            raw_district = district_match.group(1).strip()
            # Clean up district name
            raw_district = re.sub(r'[丁目・ー・・T第区市\s]*$', '', raw_district).strip()
            if raw_district and len(raw_district) > 0 and raw_district not in provided_ward:
                district = raw_district
        
        return provided_ward, district
    
    # If no ward provided, extract from address and convert to English
    # Tokyo 23 wards list with romaji variations
    tokyo_wards = [
        '千代田区', '中央区', '港区', '新宿区', '文京区', '台東区',
        '墨田区', '江東区', '品川区', '目黒区', '大田区', '世田谷区',
        '渋谷区', '中野区', '杉並区', '豊島区', '北区', '荒川区',
        '板橋区', '練馬区', '足立区', '葛飾区', '江戸川区'
    ]
    
    # Tokyo cities/municipalities (Tama area)
    tokyo_cities = [
        '八王子市', '立川市', '武蔵野市', '三鷹市', '青梅市', '府中市', '昭島市', '調布市',
        '町田市', '日野市', '国分寺市', '国立市', '福生市', '狛江市', '東久留米市',
        '武蔵村山市', '多摩市', '稲城市', '羽村市', 'あきる野市', '西東京市',
        '清瀬市', '東村山市', '小平市'
    ]
    
    ward = None
    district = None
    
    if logger:
        logger.debug(f"Extracting ward from address: '{address_clean}'")
    
    # First try to find Tokyo 23 wards (prioritize full names with 区)
    for w in tokyo_wards:
        if w in address_clean:
            # Convert to English using mapping
            ward = JAPANESE_TO_ENGLISH_WARD.get(w, w)
            if logger:
                logger.debug(f"Found ward: {w} -> {ward}")
            # Extract district (text after ward, before first number)
            try:
                after_ward = address_clean.split(w)[1]
                # Clean district extraction - handle various formats
                district_match = re.search(r'^([^\d０-９]+)', after_ward)
                if district_match:
                    raw_district = district_match.group(1).strip()
                    # Clean up district name
                    raw_district = re.sub(r'[丁目・ー・・T第]*$', '', raw_district).strip()
                    if raw_district and len(raw_district) > 0:
                        district = raw_district
            except (IndexError, AttributeError):
                pass
            break
    
    # If no ward found, try Tokyo cities
    if not ward:
        for city in tokyo_cities:
            if city in address_clean:
                # Convert to English using mapping
                ward = JAPANESE_TO_ENGLISH_WARD.get(city, city)
                if logger:
                    logger.debug(f"Found city as ward: {city} -> {ward}")
                # Extract district/area within the city
                try:
                    after_city = address_clean.split(city)[1]
                    district_match = re.search(r'^([^\d０-９]+)', after_city)
                    if district_match:
                        raw_district = district_match.group(1).strip()
                        raw_district = re.sub(r'[丁目・ー・・T第]*$', '', raw_district).strip()
                        if raw_district and len(raw_district) > 0:
                            district = raw_district
                except (IndexError, AttributeError):
                    pass
                break
    
    # Final cleanup
    if district:
        # Remove common suffixes and clean up
        district = re.sub(r'[丁目・ー・・T第\s]*$', '', district).strip()
        if not district or len(district) == 0:
            district = None
    
    if logger and not ward:
        logger.warning(f"Failed to extract ward from address: '{address_clean}'")
    
    return ward, district

def parse_station_distance(text):
    """Parse station distance from 交通 field with enhanced patterns"""
    if not text:
        return None
    
    try:
        # Multiple patterns for station distance extraction
        patterns = [
            r'[徒歩]+(\d+)分',              # "徒歩5分"
            r'[歩]+(\d+)分',               # "歩5分"  
            r'駅まで[^\d]*(\d+)分',        # "駅まで徒歩5分"
            r'駅から[^\d]*(\d+)分',        # "駅から徒歩5分"
            r'(?:最寄|最寄り)[^\d]*(\d+)分', # "最寄駅徒歩5分"
            r'(?:駅|Station)[^\d]*(\d+)分', # "XX駅徒歩5分"
            r'(\d+)分[^\d]*(?:駅|歩行)',    # "5分で駅"
            r'(\d+)分',                   # Just "5分" as fallback
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                distance = int(match.group(1))
                # Sanity check: reasonable walking distance (1-30 minutes)
                if 1 <= distance <= 30:
                    return distance
        
    except (ValueError, TypeError):
        pass
    
    return None

def parse_layout_type(text):
    """Parse layout type and extract number of bedrooms"""
    if not text:
        return None, None
    
    layout_type = text.strip()
    num_bedrooms = None
    
    try:
        # Extract number from patterns like "2LDK", "3DK", "1K"
        match = re.search(r'(\d+)[LDKS]', text)
        if match:
            num_bedrooms = int(match.group(1))
    except (ValueError, TypeError):
        pass
    
    return layout_type, num_bedrooms

def extract_building_year(text):
    """Extract building year from 築年月 or building age text"""
    if not text:
        return None
    
    try:
        # Direct year pattern: "1999年3月" -> 1999
        year_match = re.search(r'(\d{4})年', text)
        if year_match:
            return int(year_match.group(1))
        
        # Calculate from age: "築25年" -> current_year - 25
        age_match = re.search(r'築(\d+)年', text)
        if age_match:
            age = int(age_match.group(1))
            return datetime.now().year - age
        
        # Japanese era years
        # 平成 era: 1989-2019 (平成1年 = 1989)
        heisei_match = re.search(r'平成(\d+)年', text)
        if heisei_match:
            heisei_year = int(heisei_match.group(1))
            return 1988 + heisei_year
        
        # 昭和 era: 1926-1989 (昭和1年 = 1926)
        showa_match = re.search(r'昭和(\d+)年', text)
        if showa_match:
            showa_year = int(showa_match.group(1))
            return 1925 + showa_year
        
        # 令和 era: 2019-present (令和1年 = 2019)
        reiwa_match = re.search(r'令和(\d+)年', text)
        if reiwa_match:
            reiwa_year = int(reiwa_match.group(1))
            return 2018 + reiwa_year
            
    except (ValueError, TypeError):
        pass
    
    return None

def extract_area_details(text):
    """Extract usable area and total area from size text"""
    areas = {}
    if not text:
        return areas
    
    try:
        # Look for patterns like "専有面積：50.5m²（壁芯）" or "専有面積：45.3m²（内法）"
        # 壁芯 = total registered area, 内法 = usable area
        
        # Total area (壁芯)
        total_match = re.search(r'(\d+\.?\d*)[m²㎡].*?壁芯', text)
        if total_match:
            areas['total_area'] = float(total_match.group(1))
        
        # Usable area (内法)
        usable_match = re.search(r'(\d+\.?\d*)[m²㎡].*?内法', text)
        if usable_match:
            areas['usable_area'] = float(usable_match.group(1))
        
        # If no specific type mentioned, use as general area
        if not areas:
            general_match = re.search(r'(\d+\.?\d*)[m²㎡]', text)
            if general_match:
                # Assume it's total area if not specified
                areas['total_area'] = float(general_match.group(1))
    
    except (ValueError, TypeError):
        pass
    
    return areas

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

def extract_property_details(session, property_url, referer_url, retries=3, config=None, logger=None, session_pool=None, image_rate_limiter=None, ward=None, listing_price=None):
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
            
            # ===== ADD WAIT HERE FOR IMAGES TO LOAD =====
            # This is the key spot - after we get the page but before parsing
            if logger:
                logger.debug(f"Waiting 2-3 seconds for JavaScript to load images...")
            time.sleep(random.uniform(2.0, 3.0))  # Wait 2-3 seconds for JS to execute
            
            # Some sites need a second request to get fully loaded content
            # Try getting the page again after the wait
            response = session.get(property_url, timeout=15)
            
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
            
            # Extract property details from tables with field mapping
            field_mappings = {
                '価格': 'price_text',
                '専有面積': 'size_sqm_text',
                '築年月': 'building_age_text',
                '所在階': 'floor_text',
                '所在地': 'address',
                '管理費': 'management_fee_text',
                '修繕積立金': 'repair_reserve_fee_text',
                '交通': 'station_info',
                '向き': 'direction_facing',
                '間取り': 'layout_text',
                '建物名': 'building_name',
                'バルコニー': 'balcony_area_text',
                'バルコニー面積': 'balcony_area_text',
                'ベランダ': 'balcony_area_text',
                '総戸数': 'total_units_text',
                # Additional variations for fees
                '管理費等': 'management_fee_text',
                '管理費（月額）': 'management_fee_text',
                '月額管理費': 'management_fee_text',
                '修繕費': 'repair_reserve_fee_text',
                '修繕積立金（月額）': 'repair_reserve_fee_text',
                '積立金': 'repair_reserve_fee_text',
                '月額修繕積立金': 'repair_reserve_fee_text',
                # Additional transportation patterns
                '最寄駅': 'station_info',
                'アクセス': 'station_info',
                '交通アクセス': 'station_info',
            }
            
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 5:  # Reduced threshold for better detection
                    for row in rows:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            key = cells[0].text.strip()
                            value = cells[1].text.strip()
                            if key and value and len(key) < 30:
                                # Store raw value
                                data[key] = value
                                # Store mapped field if exists
                                if key in field_mappings:
                                    data[field_mappings[key]] = value
            
            # Parse extracted fields
            # Price processing with listing price as primary source
            price_numeric = 0
            
            # Initialize price_sources for both branches
            price_sources = []
            if 'price' in data:  # From regex pattern
                price_sources.append(('regex_price', data['price']))
            if 'price_text' in data:  # From table field '価格'
                price_sources.append(('table_price', data['price_text']))
            if '価格' in data:  # Direct Japanese field
                price_sources.append(('japanese_price', data['価格']))
            
            # First, try to use the listing price if provided
            if listing_price and listing_price > 0:
                price_numeric = listing_price
                if logger:
                    logger.debug(f"Using price from listing page: {listing_price}")
            else:
                # Fall back to extracting from detail page (existing logic)
                # Try each price source until we get a valid result
                for source_name, price_value in price_sources:
                    if price_value:
                        parsed_price = parse_price_from_text(price_value)
                        if parsed_price > 0:
                            price_numeric = parsed_price
                            if logger:
                                logger.debug(f"Price extracted from detail page {source_name}: {price_value} -> {parsed_price}")
                            break
            
            # Store the numeric price
            data['price'] = price_numeric
            
            # Keep the original price display for reference
            if price_sources:
                data['price_display'] = price_sources[0][1]  # Store the first price text found
            
            # Size in square meters
            if 'size_sqm_text' in data:
                size_sqm = parse_numeric_field(data['size_sqm_text'].replace('m²', '').replace('㎡', ''))
                if size_sqm:
                    data['size_sqm'] = size_sqm
                    # Calculate price per sqm if we have both
                    if data.get('price') and data['price'] > 0:
                        calculated_price_per_sqm = (data['price'] * 10000) / size_sqm  # Convert man-yen to yen
                        data['price_per_sqm'] = calculated_price_per_sqm
                        if logger:
                            logger.debug(f"Calculated price_per_sqm: {calculated_price_per_sqm:.0f} yen/sqm (price={data['price']} man-yen, size={size_sqm} sqm)")
                        
                        # Validation: ensure calculation was successful
                        if calculated_price_per_sqm == 0:
                            if logger:
                                logger.warning(f"Price per sqm calculation resulted in 0: price={data['price']}, size={size_sqm}")
                    elif data.get('price') and size_sqm:
                        if logger:
                            logger.warning(f"Price per sqm not calculated: price={data.get('price')}, size={size_sqm}")
                elif logger:
                    logger.debug(f"Failed to parse size from: '{data['size_sqm_text']}'")
            elif logger:
                logger.debug("No size_sqm_text field found")
            
            # Building age
            if 'building_age_text' in data:
                age = parse_building_age(data['building_age_text'])
                if age is not None:
                    data['building_age_years'] = age
            
            # Floor information (enhanced for enrichment)
            if 'floor_text' in data:
                floor, total_floors = parse_floor_info(data['floor_text'])
                if floor is not None:
                    data['floor'] = floor
                if total_floors is not None:
                    data['building_floors'] = total_floors  # Add building_floors field for enrichment
                    data['total_floors'] = total_floors  # Keep total_floors for compatibility
            
            # Ward and district - use provided ward or extract from address
            extracted_ward, district = None, None
            
            # Use ward from URL collection if provided
            if ward:
                data['ward'] = ward
                if logger:
                    logger.debug(f"Using ward from URL collection: {ward}")
            else:
                # Fall back to extraction from address only if ward not provided
                address_sources = []
                
                if 'address' in data:
                    address_sources.append(('address', data['address']))
                if 'building_name' in data:
                    address_sources.append(('building_name', data['building_name']))
                if 'title' in data:
                    address_sources.append(('title', data['title']))
                
                # Try each source until we find ward info
                for source_name, address_text in address_sources:
                    if address_text:
                        ward_result, district_result = extract_ward_and_district(address_text, None, logger)
                        if ward_result:
                            extracted_ward, district = ward_result, district_result
                            if logger:
                                logger.debug(f"Ward extracted from {source_name}: {extracted_ward}")
                            break
                
                if extracted_ward:
                    data['ward'] = extracted_ward
            
            # Always try to extract district from address
            if not district and 'address' in data:
                _, district_result = extract_ward_and_district(data['address'], data.get('ward'), logger)
                if district_result:
                    district = district_result
            
            if district:
                data['district'] = district
            
            # Management and repair fees
            if 'management_fee_text' in data:
                fee = parse_numeric_field(data['management_fee_text'])
                if fee is not None:
                    data['management_fee'] = fee
            
            if 'repair_reserve_fee_text' in data:
                fee = parse_numeric_field(data['repair_reserve_fee_text'])
                if fee is not None:
                    data['repair_reserve_fee'] = fee
            
            # Calculate total monthly costs
            monthly_costs = 0
            if data.get('management_fee'):
                monthly_costs += data['management_fee']
            if data.get('repair_reserve_fee'):
                monthly_costs += data['repair_reserve_fee']
            if monthly_costs > 0:
                data['monthly_costs'] = monthly_costs
                data['total_monthly_costs'] = monthly_costs
            
            # Station distance
            if 'station_info' in data:
                distance = parse_station_distance(data['station_info'])
                if distance is not None:
                    data['station_distance_minutes'] = distance
            
            # Layout type and bedrooms
            if 'layout_text' in data:
                layout, bedrooms = parse_layout_type(data['layout_text'])
                if layout:
                    data['layout_type'] = layout
                if bedrooms is not None:
                    data['num_bedrooms'] = bedrooms
            
            # Direction facing / Orientation
            if 'direction_facing' in data:
                data['direction_facing'] = data['direction_facing']
                data['orientation'] = data['direction_facing']  # Add orientation field for enrichment
            
            # Extract enrichment-specific fields from raw HTML content
            html_text = response.text.lower() if response else ""
            
            # View obstruction detection
            view_obstruction_keywords = ['眺望悪い', '前建てあり', '抜け感なし', '眺望不良', '景観悪い']
            data['view_obstructed'] = any(keyword in html_text for keyword in view_obstruction_keywords)
            
            # Light/sunlight detection
            light_keywords = ['日当たり良好', '陽当たり良い', '日当たり良', '採光良好', '日照良好', '明るい']
            data['light'] = any(keyword in html_text for keyword in light_keywords)
            
            # Fire hatch detection
            fire_hatch_keywords = ['避難ハッチ', '非常口', '緊急避難', '避難設備']
            data['has_fire_hatch'] = any(keyword in html_text for keyword in fire_hatch_keywords)
            
            # Extract building year from building_age_text or築年月
            building_year = None
            if 'building_age_text' in data and data['building_age_text']:
                building_year = extract_building_year(data['building_age_text'])
            if not building_year and '築年月' in data and data['築年月']:
                building_year = extract_building_year(data['築年月'])
            if building_year:
                data['building_year'] = building_year
            
            # Extract usable area and total area
            if 'size_sqm_text' in data:
                areas = extract_area_details(data['size_sqm_text'])
                if areas.get('usable_area'):
                    data['usable_area'] = areas['usable_area']
                if areas.get('total_area'):
                    data['total_area'] = areas['total_area']
            
            # Extract balcony size
            if 'balcony_area_text' in data:
                balcony_size = parse_numeric_field(data['balcony_area_text'].replace('m²', '').replace('㎡', ''))
                if balcony_size:
                    data['balcony_size_sqm'] = balcony_size
            
            # Check if this is the first time seeing this property (add first_seen_date)
            data['first_seen_date'] = datetime.now().isoformat()
            
            # Additional fields for compatibility
            data['source'] = 'homes_scraper'
            data['processed_date'] = datetime.now().strftime('%Y-%m-%d')
            
            # Final price validation and fallback
            if not data.get('price') or data.get('price') == 0:
                # Try one more time with the title if it contains price info
                if 'title' in data and '万円' in data['title']:
                    title_price = parse_price_from_text(data['title'])
                    if title_price > 0:
                        data['price'] = title_price
                        if logger:
                            logger.debug(f"Price extracted from title: {data['title']} -> {title_price}")
                
                # If still no price, log warning but continue processing
                if not data.get('price') or data.get('price') == 0:
                    if logger:
                        logger.warning(f"No valid price found for {property_url}. Available price fields: {[k for k in data.keys() if 'price' in k.lower() or '価格' in k]}")
            
            # Extract images with enhanced debugging
            try:
                # Debug: Check if bucket is configured
                if logger:
                    logger.info(f"=== IMAGE PROCESSING DEBUG for {property_id} ===")
                    logger.info(f"Output bucket configured: {output_bucket}")
                    logger.info(f"Config object: {config}")
                    logger.info(f"Session pool available: {session_pool is not None}")
                    logger.info(f"Image rate limiter available: {image_rate_limiter is not None}")
                
                s3_keys = extract_property_images(
                    soup, session, "https://www.homes.co.jp", 
                    bucket=output_bucket, property_id=property_id,
                    config=config, logger=logger,
                    session_pool=session_pool, image_rate_limiter=image_rate_limiter
                )
                
                if logger:
                    logger.info(f"Image extraction returned {len(s3_keys) if s3_keys else 0} S3 keys")
                    if s3_keys:
                        logger.info(f"S3 keys: {s3_keys[:3]}...")  # Show first 3
                
                if s3_keys:
                    data["photo_filenames"] = "|".join(s3_keys)
                    data["image_count"] = len(s3_keys)
                    if logger:
                        logger.info(f"Successfully stored {len(s3_keys)} images for property {property_id}")
                else:
                    if logger:
                        logger.warning(f"No images processed for property {property_id}")
                    data["image_count"] = 0
                    
            except Exception as e:
                if logger:
                    logger.error(f"Image extraction failed for {property_id}: {str(e)}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                data["image_count"] = 0
            
            # Success! Return the data
            return data
            
        except Exception as e:
            last_error = e
            if logger:
                logger.debug(f"Attempt {attempt + 1} failed: {str(e)}")
            
            if attempt == retries:
                break
                
            # Exponential backoff
            time.sleep((2 ** attempt) + random.uniform(0, 1))
    
    # All retries failed
    if last_error:
        raise last_error
    else:
        raise Exception("Max retries exceeded")

# Enhanced extract_property_images function in core_scraper.py:
def extract_property_images(soup, session, base_url, bucket=None, property_id=None, config=None, logger=None, session_pool=None, image_rate_limiter=None):
    """Extract property images - fixed to handle homes.jp image URLs correctly"""
    s3_keys = []
    image_urls = set()
    
    if logger:
        logger.debug(f"=== Starting image extraction for property {property_id} ===")
        logger.debug(f"Bucket: {bucket}")
    
    try:
        # Find all img tags
        all_imgs = soup.find_all('img')
        if logger:
            logger.debug(f"Total img tags found in page: {len(all_imgs)}")
        
        # Process all images
        for img in all_imgs:
            # Get image source (try multiple attributes)
            src = (img.get('src') or 
                  img.get('data-src') or 
                  img.get('data-original') or 
                  img.get('data-lazy-src'))
            
            if not src:
                continue
            
            # Skip obvious non-property images
            skip_patterns = ['icon', 'logo', 'btn', 'button', 'arrow', 'banner', 
                            'lifull.com/lh/', 'header-footer', 'temprano/assets', 
                            'qr-code']  # Added qr-code to skip list
            
            if any(pattern in src.lower() for pattern in skip_patterns):
                continue
            
            # IMPORTANT: Accept homes.jp image URLs
            # These are valid property images even though they go through image.php
            if any(domain in src for domain in ['image.homes.jp', 'image1.homes.jp', 
                                                'image2.homes.jp', 'image3.homes.jp', 
                                                'image4.homes.jp', 'img.homes.jp']):
                # This is a valid property image!
                if src.startswith('//'):
                    src = 'https:' + src
                elif not src.startswith('http'):
                    src = 'https:' + src
                
                image_urls.add(src)
                if logger:
                    logger.debug(f"Added homes.jp image: {src[:100]}...")
            
            # Also check for other image patterns
            elif (any(pattern in src.lower() for pattern in ['photo', 'image', 'pic', 'img', 
                                                             'mansion', 'bukken', 'property']) or
                  any(src.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp'])):
                # Convert to absolute URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = base_url + src
                elif not src.startswith('http'):
                    src = base_url + '/' + src.lstrip('/')
                
                image_urls.add(src)
                if logger:
                    logger.debug(f"Added other image: {src[:100]}...")
        
        # Log what we found
        if logger:
            logger.info(f"Found {len(image_urls)} valid image URLs for property {property_id}")
            if image_urls:
                for i, url in enumerate(list(image_urls)[:3]):
                    logger.info(f"  Image {i}: {url[:100]}...")
            else:
                logger.warning(f"No valid images found for property {property_id}")
                # Log some sample images that were skipped
                sample_count = 0
                for img in all_imgs[:10]:
                    src = img.get('src', '')
                    if src and sample_count < 3:
                        logger.debug(f"  Skipped: {src[:100]}...")
                        sample_count += 1
        
        # Check if bucket is configured
        if not bucket:
            if logger:
                logger.warning(f"No S3 bucket configured! Cannot save images.")
            return []
        
        # Limit to 5 images per property
        urls = list(image_urls)[:5]
        
        if not urls:
            if logger:
                logger.info("No images to process")
            return []
        
        # Download and process images
        if logger:
            logger.info(f"Processing {len(urls)} images for upload to S3")
        
        if session_pool and image_rate_limiter:
            s3_keys = download_images_parallel(urls, session_pool, bucket, property_id, logger, image_rate_limiter)
        else:
            s3_keys = download_images_parallel_fallback(urls, session, bucket, property_id, logger)
        
        if logger:
            logger.info(f"Image processing complete: {len(s3_keys)} images saved to S3")
            if len(s3_keys) < len(urls):
                logger.warning(f"Some images failed to upload: {len(urls) - len(s3_keys)} out of {len(urls)}")

        return s3_keys
        
    except Exception as e:
        if logger:
            logger.error(f"Image extraction error: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        return []

# Also update the download function to handle the image.php URLs better
def download_single_image(session_pool, img_url, index, bucket, property_id, logger, rate_limiter=None):
    """Download and process a single image - handles homes.jp image.php URLs"""
    session = None
    try:
        if logger:
            logger.debug(f"Downloading image {index}: {img_url[:100]}...")
        
        # Apply rate limiting if provided
        if rate_limiter:
            rate_limiter.acquire()
        
        # Get session from pool
        session = session_pool.get_session()
        
        # For homes.jp image.php URLs, we might need to handle redirects
        img_response = session.get(img_url, timeout=10, allow_redirects=True)
        
        if logger:
            logger.debug(f"Image {index} response: status={img_response.status_code}, "
                        f"content-type={img_response.headers.get('content-type', 'unknown')}, "
                        f"size={len(img_response.content)} bytes")
        
        if img_response.status_code == 200:
            content_type = img_response.headers.get('content-type', 'image/jpeg')
            
            # Be more permissive with content types
            if 'image' in content_type or img_response.content[:4] in [b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\x89PNG']:
                # Skip tiny images
                if len(img_response.content) < 1000:
                    if logger:
                        logger.debug(f"Skipping tiny image {index}: {len(img_response.content)} bytes")
                    return None
                
                try:
                    # Convert and resize image
                    img = Image.open(io.BytesIO(img_response.content))
                    
                    if logger:
                        logger.debug(f"Image {index} opened: size={img.size}, mode={img.mode}")
                    
                    if img.mode not in ('RGB', 'L'):
                        img = img.convert('RGB')
                    
                    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    
                    output_buffer = io.BytesIO()
                    img.save(output_buffer, format='JPEG', quality=85, optimize=True)
                    output_buffer.seek(0)
                    processed_image_bytes = output_buffer.getvalue()
                    
                    if logger:
                        logger.debug(f"Image {index} processed: final size={len(processed_image_bytes)} bytes")
                    
                    # Upload to S3
                    if bucket and property_id:
                        s3_key = upload_image_to_s3(
                            processed_image_bytes, 
                            bucket, 
                            property_id, 
                            index, 
                            logger=logger
                        )
                        if s3_key and logger:
                            logger.debug(f"Image {index} uploaded to S3: {s3_key}")
                        return s3_key
                except Exception as e:
                    if logger:
                        logger.error(f"Failed to process image {index}: {str(e)}")
                    return None
            else:
                if logger:
                    logger.debug(f"Skipping non-image content type for image {index}: {content_type}")
        else:
            if logger:
                logger.warning(f"Failed to download image {index}: HTTP {img_response.status_code}")
        
        return None
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to download image {index}: {str(e)}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
        return None
    
    finally:
        # Return session to pool
        if session and session_pool:
            session_pool.return_session(session)

def download_single_image_fallback(session, img_url, index, bucket, property_id, logger):
    """Download and process a single image (fallback for backward compatibility)"""
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

def download_images_parallel(image_urls, session_pool, bucket, property_id, logger, image_rate_limiter):
    """Download images in parallel with session pool and rate limiting"""
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
                    session_pool, img_url, i, bucket, property_id, logger, image_rate_limiter
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

def download_images_parallel_fallback(image_urls, session, bucket, property_id, logger):
    """Download images in parallel with single session (fallback)"""
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
                    download_single_image_fallback, 
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

# Enhanced upload_image_to_s3 in core_scraper.py:
def upload_image_to_s3(image_content, bucket, property_id, image_index, logger=None):
    """Enhanced version with debug logging"""
    try:
        if logger:
            logger.debug(f"Uploading image to S3: bucket={bucket}, property_id={property_id}, index={image_index}")
        
        date_str = datetime.now().strftime('%Y-%m-%d')
        s3_key = f"raw/{date_str}/images/{property_id}_{image_index}.jpg"
        
        s3 = boto3.client("s3")
        
        # Check if bucket exists and we have access
        try:
            s3.head_bucket(Bucket=bucket)
            if logger:
                logger.debug(f"S3 bucket '{bucket}' is accessible")
        except Exception as e:
            if logger:
                logger.error(f"S3 bucket '{bucket}' is not accessible: {str(e)}")
            return None
        
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=image_content,
            ContentType='image/jpeg'
        )
        
        if logger:
            logger.debug(f"Successfully uploaded image to S3: {s3_key}")
        
        return s3_key
        
    except Exception as e:
        if logger:
            logger.error(f"S3 upload failed for image {image_index}: {str(e)}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
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