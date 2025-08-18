#!/usr/bin/env python3
"""
Core scraping functionality for homes.co.jp
Fixed version - restores working extraction logic while keeping interior photo detection
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
import os
import hashlib
from urllib.parse import urlparse
from dynamodb_utils import extract_property_id_from_url, create_property_id_key

# Overview field mapping for deterministic parsing
OVERVIEW_FIELD_MAP = {
    "所在地": "address",
    "価格": "price_text",
    "所在階 / 階数": "floor_info",
    "所在階": "floor_info",
    "階数": "floor_info",
    "主要採光面": "primary_light",
    "向き": "primary_light",
    "方角": "primary_light",
    "建物構造": "structure",
    "築年月": "built_text",
    "築年数": "built_text",
    "専有面積": "size_text",
    "間取り": "layout_text",
    "管理費": "management_fee_text",
    "修繕積立金": "repair_reserve_fee_text",
    "交通": "station_info",
    "最寄駅": "station_info",
    "アクセス": "station_info",
    "バルコニー面積": "balcony_area_text",
    "駐車場": "parking_text",
    "総戸数": "total_units_text",
}

# New field mapping for additional property attributes
NEW_FIELD_MAP = {
    '用途地域': 'zoning',
    '土地権利': 'land_rights',
    '国土法届出': 'national_land_use_notification',
    '取引態様': 'transaction_type',
    '現況': 'current_occupancy',
    '引渡し': 'handover_timing',
}

# Japanese to English ward mapping
JAPANESE_TO_ENGLISH_WARD = {
    '千代田区': 'chiyoda-city',
    '中央区': 'chuo-city',
    '港区': 'minato-city',
    '新宿区': 'shinjuku-city',
    '文京区': 'bunkyo-city',
    '台東区': 'taito-city',
    '墨田区': 'sumida-city',
    '江東区': 'koto-city',
    '品川区': 'shinagawa-city',
    '目黒区': 'meguro-city',
    '大田区': 'ota-city',
    '世田谷区': 'setagaya-city',
    '渋谷区': 'shibuya-city',
    '中野区': 'nakano-city',
    '杉並区': 'suginami-city',
    '豊島区': 'toshima-city',
    '北区': 'kita-city',
    '荒川区': 'arakawa-city',
    '板橋区': 'itabashi-city',
    '練馬区': 'nerima-city',
    '足立区': 'adachi-city',
    '葛飾区': 'katsushika-city',
    '江戸川区': 'edogawa-city',
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


def _safe_name(url: str, idx: int, property_id: str) -> str:
    # keep extension if present, otherwise default .jpg
    parsed = urlparse(url)
    base = os.path.basename(parsed.path) or f"img_{idx}.jpg"
    if "." not in base:
        base = f"{base}.jpg"
    # short hash to avoid collisions
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    # match your historical key style: {property_id}/NN_hash_name
    return f"{property_id}/{idx:02d}_{h}_{base}"

def _download_one(url, session, timeout, rate_limiter=None, logger=None):
    if rate_limiter:
        # simple token bucket: call() blocks until allowed
        try:
            rate_limiter()
        except Exception:
            pass
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        content = resp.content
        # Optional lightweight sanity check with Pillow if available
        try:
            from PIL import Image
            Image.open(io.BytesIO(content)).verify()
        except Exception:
            # not fatal—some floorplan PNGs can be weird; keep bytes
            pass
        return content
    except Exception as e:
        if logger:
            logger.warning(f"Download failed: {url} :: {e}")
        return None

def download_images_parallel(urls, session_pool, output_bucket, property_id, logger=None, rate_limiter=None, timeout=15, max_workers=8):
    """
    Parallel downloader used by the fast path.
    Returns a list of 'filenames' (S3 keys if uploaded, otherwise local-style keys).
    """
    # Lazy import to avoid hard dep if you're not using S3
    s3 = None
    if output_bucket:
        try:
            import boto3
            s3 = boto3.client("s3")
        except Exception as e:
            if logger:
                logger.warning(f"S3 client unavailable: {e}")

    results = []
    # borrow sessions from the pool for concurrency, but limit to avoid pool exhaustion
    # Never take more than half the remaining sessions to avoid deadlock with main processing
    max_image_sessions = min(max_workers, len(urls), 3)  # Cap at 3 sessions for images
    sessions = [session_pool.get_session() for _ in range(max_image_sessions)] if session_pool else [requests.Session()]
    try:
        with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
            futs = {}
            for idx, url in enumerate(urls):
                # round-robin a session
                sess = sessions[idx % len(sessions)]
                fut = executor.submit(_download_one, url, sess, timeout, rate_limiter, logger)
                futs[fut] = (idx, url)

            for fut in as_completed(futs):
                idx, url = futs[fut]
                content = fut.result()
                if not content:
                    continue
                key = _safe_name(url, idx, property_id or "unknown")
                # Upload to S3 if configured, otherwise just pretend-key
                if s3 and output_bucket:
                    try:
                        s3.put_object(Bucket=output_bucket, Key=key, Body=content)
                    except Exception as e:
                        if logger:
                            logger.warning(f"S3 put_object failed for {key}: {e}")
                        # still return the key so downstream logic keeps working
                results.append(key)
    finally:
        # return sessions to the pool
        if session_pool:
            for sess in sessions:
                session_pool.return_session(sess)
        else:
            try:
                sessions[0].close()
            except Exception:
                pass

    if logger:
        logger.info(f"Downloaded {len(results)}/{len(urls)} images")
    return results

def download_images_parallel_fallback(urls, session, output_bucket, property_id, logger=None, timeout=15):
    """
    Sequential fallback used when no session pool is available.
    Mirrors the return shape of download_images_parallel.
    """
    s3 = None
    if output_bucket:
        try:
            import boto3
            s3 = boto3.client("s3")
        except Exception as e:
            if logger:
                logger.warning(f"S3 client unavailable: {e}")

    results = []
    for idx, url in enumerate(urls):
        content = _download_one(url, session, timeout, None, logger)
        if not content:
            continue
        key = _safe_name(url, idx, property_id or "unknown")
        if s3 and output_bucket:
            try:
                s3.put_object(Bucket=output_bucket, Key=key, Body=content)
            except Exception as e:
                if logger:
                    logger.warning(f"S3 put_object failed for {key}: {e}")
        results.append(key)

    if logger:
        logger.info(f"(fallback) Downloaded {len(results)}/{len(urls)} images")
    return results

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

def yen_to_int(s):
    """Convert yen string to integer value"""
    if not s:
        return None
    m = re.search(r'([\d,]+)\s*円', s)
    return int(m.group(1).replace(',', '')) if m else None

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
    """Parse floor information from various Japanese floor formats"""
    if not text:
        return None, None
    
    try:
        # Pattern 1: "5階 / 10階建 (地下1階)" - extract main building info
        match = re.search(r'(\d+)階\s*/\s*(\d+)階建', text)
        if match:
            floor = int(match.group(1))
            total_floors = int(match.group(2))
            return floor, total_floors
        
        # Pattern 2: "3階/10階" (alternative format without 建)
        match2 = re.search(r'(\d+)階[^\d]*(\d+)階(?!建)', text)
        if match2:
            floor = int(match2.group(1))
            # This might be "3階/10階" where second number is total floors
            # Let's assume it's total floors
            total_floors = int(match2.group(2))
            return floor, total_floors
        
        # Pattern 3: "10階建" alone (building has 10 floors, but property floor unknown)
        building_match = re.search(r'(\d+)階建', text)
        if building_match:
            total_floors = int(building_match.group(1))
            return None, total_floors
        
        # Pattern 4: just "3階" (property is on 3rd floor)
        floor_match = re.search(r'(\d+)階', text)
        if floor_match:
            floor = int(floor_match.group(1))
            return floor, None
        
        # Pattern 5: "地上3階" (above ground 3rd floor)
        ground_match = re.search(r'地上(\d+)階', text)
        if ground_match:
            floor = int(ground_match.group(1))
            return floor, None
            
        # Pattern 6: "B1階" (basement)
        basement_match = re.search(r'B(\d+)階', text)
        if basement_match:
            floor = -int(basement_match.group(1))  # Negative for basement
            return floor, None
            
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
        # Look for the first station with walking time (homes.co.jp format)
        # Example: "JR高崎線 尾久駅 徒歩7分"
        first_station_match = re.search(r'徒歩(\d+)分', text)
        if first_station_match:
            distance = int(first_station_match.group(1))
            # Sanity check: reasonable walking distance (1-30 minutes)
            if 1 <= distance <= 30:
                return distance
        
        # Fallback patterns
        patterns = [
            r'[歩]+(\d+)分',               # "歩5分"  
            r'駅まで[^\d]*(\d+)分',        # "駅まで徒歩5分"
            r'駅から[^\d]*(\d+)分',        # "駅から徒歩5分"
            r'(?:最寄|最寄り)[^\d]*(\d+)分', # "最寄駅徒歩5分"
            r'(?:駅|Station)[^\d]*(\d+)分', # "XX駅徒歩5分"
            r'(\d+)分[^\d]*(?:駅|歩行)',    # "5分で駅"
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

def parse_closest_station(text):
    """Extract the closest station name from 交通 or 備考 text"""
    if not text:
        return None
    
    try:
        # Pattern 1: "JR高崎線 尾久駅 徒歩7分" -> 尾久駅 (extract station name before walking time)
        station_match = re.search(r'([^\u3000\s]+駅)\s*徒歩(\d+)分', text)
        if station_match:
            return station_match.group(1)
        
        # Pattern 2: Look for first proper station name (2-6 characters + 駅)
        # But avoid generic words like "最寄駅" or phrases
        station_match2 = re.search(r'([ぁ-ん一-龯]{2,6}駅)', text)
        if station_match2:
            station_name = station_match2.group(1)
            # Skip generic terms
            if station_name not in ['最寄駅', '最寄り駅', '近隣駅']:
                return station_name
        
    except (ValueError, TypeError):
        pass
    
    return None

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

def parse_overview_section(soup):
    """Parse property overview from CSS Grid structure and extract detailed info from text patterns"""
    overview = {}
    
    try:
        # Method 1: Look for CSS Grid containers that hold property details
        grid_selectors = [
            'div.grid.grid-cols-max1fr',  # Primary CSS Grid selector
            'div[class*="grid"][class*="grid-cols"]',  # Alternative grid patterns
            'div[class*="gap-x"][class*="gap-y"]'  # Grid with gaps
        ]
        
        for selector in grid_selectors:
            grid_containers = soup.select(selector)
            
            for container in grid_containers:
                # Find span elements that contain property labels and values
                spans = container.find_all('span')
                divs = container.find_all('div')
                all_elements = spans + divs
                
                # Process pairs of elements (label, value)
                for i in range(0, len(all_elements) - 1, 2):
                    label_elem = all_elements[i]
                    value_elem = all_elements[i + 1]
                    
                    if not label_elem or not value_elem:
                        continue
                    
                    label = label_elem.get_text(strip=True)
                    value = value_elem.get_text(" ", strip=True)
                    
                    if label and value and len(label) < 30:
                        overview[label] = value
        
        # Method 2: Extract detailed property info from text patterns (fallback for missing grid data)
        all_text = soup.get_text()
        
        # Extract floor information from text patterns
        floor_patterns = [
            r'所在階\s*/\s*階数([\d階\s/建（）地下]+)',  # "所在階 / 階数 7階 / 10階建"
            r'(階数[\d階\s/建（）地下]+)',  # "階数7階 / 10階建"
            r'(\d+階\s*/\s*\d+階建)',  # "7階 / 10階建"
        ]
        
        for pattern in floor_patterns:
            match = re.search(pattern, all_text)
            if match:
                overview['所在階 / 階数'] = match.group(1).strip()
                break
        
        # Extract primary light information
        light_patterns = [
            r'主要採光面([^　\s建物構造]{1,4})',  # "主要採光面南東"
        ]
        
        for pattern in light_patterns:
            match = re.search(pattern, all_text)
            if match:
                overview['主要採光面'] = match.group(1).strip()
                break
        
        # Extract station information (get the first/closest station)
        station_patterns = [
            r'([^　\s]{2,8}駅)\s*徒歩(\d+)分',  # "桜台駅 徒歩4分"
        ]
        
        for pattern in station_patterns:
            match = re.search(pattern, all_text)
            if match:
                station_name = match.group(1)
                distance = match.group(2)
                # Store both station name and create formatted transport info
                overview['最寄駅'] = station_name
                overview['交通'] = f"{station_name} 徒歩{distance}分"
                break
        
        # Method 3: Look for specific data-component attributes
        component_selectors = [
            '[data-component="occupiedArea"]',  # Floor area
            '[data-component="floorplan"]',     # Room layout
            '[data-component="buildingAge"]',   # Building age
            '[data-component="balconyArea"]',   # Balcony area
        ]
        
        for selector in component_selectors:
            elements = soup.select(selector)
            for elem in elements:
                # Try to get the label from previous sibling or parent context
                label = None
                value = elem.get_text(strip=True)
                
                # Look for label in previous sibling
                prev_elem = elem.find_previous_sibling()
                if prev_elem:
                    potential_label = prev_elem.get_text(strip=True)
                    if len(potential_label) < 30 and potential_label:
                        label = potential_label
                
                if label and value:
                    overview[label] = value
                elif 'occupiedArea' in selector:
                    overview['専有面積'] = value
                elif 'floorplan' in selector:
                    overview['間取り'] = value
                elif 'buildingAge' in selector:
                    overview['築年数'] = value
                elif 'balconyArea' in selector:
                    overview['バルコニー面積'] = value
        
    except Exception as e:
        # Fallback to empty dict on any parsing error
        pass
    
    return overview

def normalize_overview(overview):
    """Convert Japanese property labels to normalized English field names and parse values"""
    mapped = {}
    
    # Map Japanese labels to English field names
    for japanese_key, english_key in OVERVIEW_FIELD_MAP.items():
        if japanese_key in overview:
            mapped[english_key] = overview[japanese_key]
    
    # Parse primary light direction if found
    if 'primary_light' in mapped:
        light_text = mapped['primary_light'].strip() if mapped['primary_light'] else ''
        # Keep the Japanese direction as-is for primary_light field
        mapped['primary_light'] = light_text
    
    # Parse floor information if found
    if 'floor_info' in mapped:
        floor, building_floors = parse_floor_info(mapped['floor_info'])
        if floor is not None:
            mapped['floor'] = floor
        if building_floors is not None:
            mapped['building_floors'] = building_floors
    
    return mapped

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

def normalize_url(url):
    """Normalize URL by removing tracking parameters"""
    from urllib.parse import urlparse, parse_qs, urlunparse
    
    parsed = urlparse(url)
    # Remove common tracking parameters
    query_params = parse_qs(parsed.query)
    
    # Remove tracking params (add more as needed)
    tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'ref', 'source'}
    cleaned_params = {k: v for k, v in query_params.items() if k not in tracking_params}
    
    # Rebuild query string
    from urllib.parse import urlencode
    clean_query = urlencode(cleaned_params, doseq=True) if cleaned_params else ''
    
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, parsed.fragment))

def normalize_category(category):
    """Normalize category names"""
    SELECTABLE_CATS = ('floorplan', 'exterior', 'interior', 'facility', 'other')
    
    if category == 'surround':
        return 'other'
    return category if category in SELECTABLE_CATS else 'other'

def collect_gallery_images(soup, logger=None):
    """Collect images from gallery sections, dedupe, and classify"""
    # Step 1: Collect all images with their categories
    raw_images = []  # List of (url, category, alt) tuples
    
    # Primary method: Find the photo-viewer list structure
    gallery_list = soup.select_one('div[data-target="photo-viewer.list"]')
    
    if gallery_list:
        # Process each section in the gallery
        sections = [
            ('image-menu-floorplan', 'floorplan'),
            ('image-menu-interior', 'interior'),
            ('image-menu-exterior', 'exterior'),
            ('image-menu-facility', 'facility'),
            ('image-menu-surround', 'surround'),  # 周辺環境
            ('image-menu-other', 'other')
        ]
        
        for section_id, category in sections:
            # Find the section containing the section ID
            section = None
            # First try to find the h2 with the ID and get its parent section
            header = gallery_list.select_one(f'#{section_id}')
            if header:
                section = header.find_parent('section')
            
            # Alternative: find section that contains the ID element
            if not section:
                for s in gallery_list.select('section'):
                    if s.select_one(f'#{section_id}'):
                        section = s
                        break
            
            if section:
                # Find all images in this section
                imgs = section.select('img')
                for img in imgs:
                    src = (img.get('src') or 
                          img.get('data-src') or 
                          img.get('data-original') or 
                          img.get('data-lazy-src'))
                    
                    if src:
                        # Convert to absolute URL
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = 'https://www.homes.co.jp' + src
                        elif not src.startswith('http'):
                            src = 'https://www.homes.co.jp/' + src.lstrip('/')
                        
                        # Only keep images from HOME'S domains
                        if any(domain in src for domain in ['image.homes.jp', 'image1.homes.jp', 
                                                            'image2.homes.jp', 'image3.homes.jp', 
                                                            'image4.homes.jp', 'img.homes.jp']):
                            raw_images.append((src, category, img.get('alt', '')))
                            if logger:
                                logger.debug(f"Found {category} image in section {section_id}: {img.get('alt', '')}")
    else:
        # Fallback: Use thumbnail rail if gallery sections not found
        if logger:
            logger.info("Gallery sections not found, using thumbnail fallback")
        
        # Look for photo-slider-photo thumbnails
        thumbnails = soup.select('photo-slider-photo img')
        
        for img in thumbnails:
            src = (img.get('src') or 
                  img.get('data-src') or 
                  img.get('data-original') or 
                  img.get('data-lazy-src'))
            
            if not src:
                continue
            
            # Convert to absolute URL
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = 'https://www.homes.co.jp' + src
            elif not src.startswith('http'):
                src = 'https://www.homes.co.jp/' + src.lstrip('/')
            
            # Only keep images from HOME'S domains
            if any(domain in src for domain in ['image.homes.jp', 'image1.homes.jp', 
                                                'image2.homes.jp', 'image3.homes.jp', 
                                                'image4.homes.jp', 'img.homes.jp']):
                # Classify using fallback method
                image_type = classify_image_fallback(img, src, logger)
                raw_images.append((src, image_type, img.get('alt', '')))
    
    # Step 2: Deduplicate by normalized URL, keeping first occurrence
    seen_urls = set()
    deduped_images = []
    
    for url, category, alt in raw_images:
        normalized_url = normalize_url(url)
        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            deduped_images.append((url, normalize_category(category), alt))
    
    # Step 3: Count by normalized category (post-dedupe)
    counts = {
        'floorplan': 0,
        'exterior': 0,
        'interior': 0,
        'facility': 0,
        'other': 0
    }
    
    for _, category, _ in deduped_images:
        if category in counts:
            counts[category] += 1
    
    if logger:
        total = sum(counts.values())
        logger.info(f"Gallery photo analysis (post-dedupe): interior={counts['interior']}, exterior={counts['exterior']}, "
                   f"floorplan={counts['floorplan']}, facility={counts['facility']}, other={counts['other']} (total={total})")
    
    return deduped_images, counts

def classify_image_fallback(img_element, src_url, logger=None):
    """Fallback image classification using keywords (only for thumbnails)"""
    # Get alt text and other attributes
    alt_text = (img_element.get('alt') or '').lower()
    title_text = (img_element.get('title') or '').lower()
    
    # Look for caption text near thumbnails
    caption_text = ''
    try:
        # For photo-slider-photo elements, look for caption
        parent = img_element.find_parent('photo-slider-photo')
        if parent:
            caption = parent.find('figcaption') or parent.find('div', class_='caption')
            if caption:
                caption_text = caption.get_text(strip=True).lower()
    except:
        pass
    
    # Combine text sources
    all_text = f"{alt_text} {title_text} {caption_text}"
    
    # Floor plan keywords
    if any(kw in all_text for kw in ['間取り', '間取図', '平面図']):
        return 'floorplan'
    
    # Interior keywords (from captions/alt)
    interior_keywords = ['室内', 'リビング', 'ダイニング', 'キッチン', '浴室', '洗面', 'トイレ', '洋室', '和室', '玄関', '収納']
    if any(kw in all_text for kw in interior_keywords):
        return 'interior'
    
    # Exterior keywords
    exterior_keywords = ['外観', '周辺', 'エントランス']
    if any(kw in all_text for kw in exterior_keywords):
        return 'exterior'
    
    return 'unknown'

def select_images_for_download(classified_urls, max_total=10, max_floorplan=1, max_exterior=1, max_facility=1, max_other=1, logger=None):
    """Select images with strict caps per category"""
    # classified_urls: list of (url, category, alt) tuples AFTER DEDUPE; category already normalized
    
    # Separate by category
    floorplans = [(u, c, a) for u, c, a in classified_urls if c == 'floorplan']
    exteriors = [(u, c, a) for u, c, a in classified_urls if c == 'exterior']
    interiors = [(u, c, a) for u, c, a in classified_urls if c == 'interior']
    facilities = [(u, c, a) for u, c, a in classified_urls if c == 'facility']
    others = [(u, c, a) for u, c, a in classified_urls if c == 'other']
    
    selected = []
    
    # Apply strict caps
    selected.extend(floorplans[:max_floorplan])
    selected.extend(exteriors[:max_exterior])
    selected.extend(facilities[:max_facility])
    selected.extend(others[:max_other])
    
    # Fill remainder with interior only
    remaining = max_total - len(selected)
    if remaining > 0:
        selected.extend(interiors[:remaining])
    
    # Calculate breakdown
    breakdown = {
        'floorplan': sum(1 for u, c, a in selected if c == 'floorplan'),
        'exterior': sum(1 for u, c, a in selected if c == 'exterior'),
        'facility': sum(1 for u, c, a in selected if c == 'facility'),
        'other': sum(1 for u, c, a in selected if c == 'other'),
        'interior': sum(1 for u, c, a in selected if c == 'interior'),
    }
    
    if logger:
        logger.info(f"Selected {len(selected)}/{max_total} images: {breakdown}")
    
    # Return URLs for download
    selected_urls = [url for url, _, _ in selected]
    return selected_urls, breakdown

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
            
            # Wait for JavaScript to load images
            if logger:
                logger.debug(f"Waiting 2-3 seconds for JavaScript to load images...")
            time.sleep(random.uniform(2.0, 3.0))
            
            # Get the page again after the wait
            response = session.get(property_url, timeout=15)
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {
                "url": property_url,
                "extraction_timestamp": datetime.now().isoformat()
            }
            
            # Extract property ID from URL using the same logic as dynamodb_utils
            raw_property_id = extract_property_id_from_url(property_url)
            if raw_property_id:
                property_id = create_property_id_key(raw_property_id)
                data["id"] = raw_property_id
                data["property_id"] = property_id
            else:
                # Fallback to URL hash as simple ID if extraction fails
                property_id = hashlib.md5(property_url.encode('utf-8')).hexdigest()[:8]
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
            
            # Use new deterministic overview parser
            overview = parse_overview_section(soup)
            mapped = normalize_overview(overview)
            
            # Extract property details from tables with field mapping
            field_mappings = {
                '価格': 'price_text',
                '専有面積': 'size_sqm_text',
                '築年月': 'building_age_text',
                '所在階': 'floor_text',
                '階': 'floor_text', 
                '階数': 'floor_text',
                '所在階/階数': 'floor_text',
                '所在地': 'address',
                '管理費': 'management_fee_text',
                '修繕積立金': 'repair_reserve_fee_text',
                '交通': 'station_info',
                '向き': 'primary_light',
                '方角': 'primary_light',
                '主要採光面': 'primary_light',
                '間取り': 'layout_text',
                '建物名': 'building_name',
                'バルコニー': 'balcony_area_text',
                'バルコニー面積': 'balcony_area_text',
                '総戸数': 'total_units_text',
                '最寄駅': 'station_info',
                'アクセス': 'station_info',
            }
            
            # First, use the new deterministic parser results
            if mapped:
                for key, value in mapped.items():
                    if key.endswith('_text') or key in ['address', 'station_info', 'layout_text', 'building_name']:
                        data[key] = value
                    elif key in ['floor', 'building_floors', 'primary_light']:
                        data[key] = value
                
                if logger:
                    logger.debug(f"Overview parser extracted {len(mapped)} fields")
            
            # Add new field mappings to existing ones
            field_mappings.update(NEW_FIELD_MAP)
            
            # Fallback to table parsing for any missing fields
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 5:
                    for row in rows:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            key = cells[0].text.strip()
                            # Clean up the value - remove trailing links like "リフォーム情報を見る"
                            value = cells[1].text.strip()
                            if key == '築年月' and 'リフォーム情報を見る' in value:
                                value = re.sub(r'リフォーム情報を見る.*$', '', value).strip()
                            if key and value and len(key) < 30:
                                if key not in data:
                                    data[key] = value
                                if key in field_mappings and field_mappings[key] not in data:
                                    mapped_key = field_mappings[key]
                                    # For 現況, keep only the first token
                                    if mapped_key == 'current_occupancy':
                                        value = value.split()[0] if value else value
                                    data[mapped_key] = value
            
            # Parse extracted fields
            # Price processing with listing price as primary source
            price_numeric = 0
            
            # First, try to use the listing price if provided
            if listing_price and listing_price > 0:
                price_numeric = listing_price
                if logger:
                    logger.debug(f"Using price from listing page: {listing_price}")
            else:
                # Fall back to extracting from detail page
                price_sources = []
                if 'price' in data:
                    price_sources.append(('regex_price', data['price']))
                if 'price_text' in data:
                    price_sources.append(('table_price', data['price_text']))
                if '価格' in data:
                    price_sources.append(('japanese_price', data['価格']))
                
                for source_name, price_value in price_sources:
                    if price_value:
                        parsed_price = parse_price_from_text(price_value)
                        if parsed_price > 0:
                            price_numeric = parsed_price
                            if logger:
                                logger.debug(f"Price extracted from {source_name}: {price_value} -> {parsed_price}")
                            break
            
            # Store the numeric price
            data['price'] = price_numeric
            
            # Size in square meters
            if 'size_sqm_text' in data:
                size_sqm = parse_numeric_field(data['size_sqm_text'].replace('m²', '').replace('㎡', ''))
                if size_sqm:
                    data['size_sqm'] = size_sqm
                    # Calculate price per sqm if we have both (price is in 万円, convert to yen for calculation)
                    if data.get('price') and data['price'] > 0:
                        calculated_price_per_sqm = (data['price'] * 10000) / size_sqm
                        data['price_per_sqm'] = calculated_price_per_sqm
                        if logger:
                            logger.debug(f"Calculated price_per_sqm: {calculated_price_per_sqm:.0f} yen/sqm")
            
            # Building age
            if 'building_age_text' in data:
                age = parse_building_age(data['building_age_text'])
                if age is not None:
                    data['building_age_years'] = age
            
            # Floor information
            if 'floor' not in data and 'building_floors' not in data:
                if 'floor_text' in data:
                    floor, total_floors = parse_floor_info(data['floor_text'])
                    if floor is not None:
                        data['floor'] = floor
                    if total_floors is not None:
                        data['building_floors'] = total_floors
            
            # Ward and district
            if ward:
                data['ward'] = ward
            else:
                # Extract from address
                address_sources = []
                if 'address' in data:
                    address_sources.append(('address', data['address']))
                if 'building_name' in data:
                    address_sources.append(('building_name', data['building_name']))
                if 'title' in data:
                    address_sources.append(('title', data['title']))
                
                for source_name, address_text in address_sources:
                    if address_text:
                        ward_result, district_result = extract_ward_and_district(address_text, None, logger)
                        if ward_result:
                            data['ward'] = ward_result
                            if district_result:
                                data['district'] = district_result
                            break
            
            # Fee normalization block (integers in yen/month)
            # Try most reliable methods first: data attributes from loan-simulator and budget-estimate
            mgmt_fee = None
            repair_fee = None
            
            # PRIORITY 1: Try data attributes from loan-simulator and budget-estimate elements
            # Method 1: loan-simulator data-maintenance-fee
            loan_sim = soup.find('loan-simulator')
            if loan_sim and loan_sim.get('data-maintenance-fee'):
                try:
                    mgmt_fee = int(loan_sim.get('data-maintenance-fee'))
                except (ValueError, TypeError):
                    pass
            
            # Method 2: budget-estimate data-management-fees (if loan-simulator didn't work)
            if mgmt_fee is None:
                budget_est = soup.find('budget-estimate')
                if budget_est and budget_est.get('data-management-fees'):
                    try:
                        mgmt_fee = int(budget_est.get('data-management-fees'))
                    except (ValueError, TypeError):
                        pass
            
            # PRIORITY 2: Try explicit 管理費 cell (if data attributes failed)
            if mgmt_fee is None:
                if '管理費' in data:
                    mgmt_fee = yen_to_int(data['管理費'])
                elif 'management_fee_text' in data:
                    mgmt_fee = yen_to_int(data['management_fee_text'])
                    if mgmt_fee is None:
                        # Fallback to old parse method
                        fee = parse_numeric_field(data['management_fee_text'])
                        if fee is not None:
                            mgmt_fee = int(fee)
            
            # PRIORITY 1: Try data attributes for repair reserve fee first
            # Try both loan-simulator and budget-estimate data-repair-reserve-fund
            for element_name in ['loan-simulator', 'budget-estimate']:
                element = soup.find(element_name)
                if element and element.get('data-repair-reserve-fund'):
                    try:
                        repair_fee = int(element.get('data-repair-reserve-fund'))
                        break
                    except (ValueError, TypeError):
                        continue
            
            # PRIORITY 2: Try explicit 修繕積立金 cell (if data attributes failed)
            if repair_fee is None:
                if '修繕積立金' in data:
                    repair_fee = yen_to_int(data['修繕積立金'])
                elif 'repair_reserve_fee_text' in data:
                    repair_fee = yen_to_int(data['repair_reserve_fee_text'])
                    if repair_fee is None:
                        # Fallback to old parse method
                        fee = parse_numeric_field(data['repair_reserve_fee_text'])
                        if fee is not None:
                            repair_fee = int(fee)
            
            # Fallback: parse from 管理費等 if needed
            if (mgmt_fee is None or repair_fee is None) and '管理費等' in data:
                s = data['管理費等']
                # Extract 管理費
                if mgmt_fee is None:
                    m = re.search(r'管理費[^0-9]*([\d,]+)\s*円', s)
                    if m:
                        mgmt_fee = int(m.group(1).replace(',', ''))
                # Extract 修繕積立金
                if repair_fee is None:
                    m = re.search(r'修繕積立金[^0-9]*([\d,]+)\s*円', s)
                    if m:
                        repair_fee = int(m.group(1).replace(',', ''))
            
            # Additional fallback: parse directly from table cells if still missing
            if mgmt_fee is None or repair_fee is None:
                rows = soup.find_all('tr')
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    for i, cell in enumerate(cells):
                        cell_text = cell.get_text(strip=True)
                        
                        # Look for management fee
                        if mgmt_fee is None and '管理費' in cell_text and '修繕' not in cell_text:
                            if i + 1 < len(cells):
                                next_cell = cells[i + 1]
                                next_text = next_cell.get_text(strip=True)
                                
                                # Parse the fee amount
                                if next_text and next_text not in ['-', '－']:
                                    # Look for patterns like "1万4300円/月" or "7300円/月"
                                    match = re.search(r'(\d+)万(\d+)', next_text)
                                    if match:
                                        man = int(match.group(1)) * 10000
                                        sen = int(match.group(2)) if match.group(2) else 0
                                        mgmt_fee = man + sen
                                    else:
                                        match = re.search(r'([\d,]+)円', next_text.replace(',', ''))
                                        if match:
                                            mgmt_fee = int(match.group(1).replace(',', ''))
                        
                        # Look for repair reserve fee
                        elif repair_fee is None and '修繕積立金' in cell_text:
                            if i + 1 < len(cells):
                                next_cell = cells[i + 1]
                                next_text = next_cell.get_text(strip=True)
                                
                                # Parse the fee amount
                                if next_text and next_text not in ['-', '－']:
                                    # Look for patterns like "1万4300円/月"
                                    match = re.search(r'(\d+)万(\d+)', next_text)
                                    if match:
                                        man = int(match.group(1)) * 10000
                                        sen = int(match.group(2)) if match.group(2) else 0
                                        repair_fee = man + sen
                                    else:
                                        match = re.search(r'([\d,]+)円', next_text.replace(',', ''))
                                        if match:
                                            repair_fee = int(match.group(1).replace(',', ''))
            
            # Store numeric-only fields if parsed
            if mgmt_fee is not None:
                data['management_fee'] = mgmt_fee
            if repair_fee is not None:
                data['repair_reserve_fee'] = repair_fee
            
            # Parse その他費用 → sum + monthly flag
            if 'その他費用' in data and 'other_fees_total' not in data:
                s = data['その他費用']
                amounts = [int(x.replace(',', '')) for x in re.findall(r'([\d,]+)\s*円', s)]
                if amounts:
                    data['other_fees_total'] = sum(amounts)
                    data['other_fees_is_monthly'] = bool(re.search(r'[／/]\s*月|月', s))
            
            # Calculate total monthly costs
            monthly_costs = 0
            if data.get('management_fee'):
                monthly_costs += data['management_fee']
            if data.get('repair_reserve_fee'):
                monthly_costs += data['repair_reserve_fee']
            if monthly_costs > 0:
                data['monthly_costs'] = monthly_costs
                data['total_monthly_costs'] = monthly_costs
            
            # Station distance and closest station
            station_sources = []
            if 'station_info' in data:
                station_sources.append(('station_info', data['station_info']))
            if '交通' in data:
                station_sources.append(('direct_transport', data['交通']))
            
            for source_name, text in station_sources:
                if text:
                    distance = parse_station_distance(text)
                    if distance is not None:
                        data['station_distance_minutes'] = distance
                        break
            
            for source_name, text in station_sources:
                if text:
                    station = parse_closest_station(text)
                    if station:
                        data['closest_station'] = station
                        break
            
            # Layout type and bedrooms
            if 'layout_text' in data:
                layout, bedrooms = parse_layout_type(data['layout_text'])
                if layout:
                    data['layout_type'] = layout
                if bedrooms is not None:
                    data['num_bedrooms'] = bedrooms
            
            # Extract enrichment fields
            all_text = " ".join([str(v) for v in data.values() if isinstance(v, str)])
            all_text_lower = all_text.lower()
            
            # View obstruction detection
            view_obstruction_keywords = [
                '眺望悪い', '前建てあり', '抜け感なし', '眺望不良', '景観悪い',
                '眺望なし', '眺望無し', '眺望劣る', '見晴らし悪い', '景観劣る'
            ]
            data['view_obstructed'] = any(keyword in all_text_lower for keyword in view_obstruction_keywords)
            
            # Light detection
            light_good = False
            if data.get('primary_light'):
                good_directions = ['南', '南東', '南西', '東南', '西南']
                light_good = any(direction in data['primary_light'] for direction in good_directions)
            
            light_keywords = ['日当たり良好', '陽当たり良い', '日当たり良', '採光良好', '日照良好', '明るい']
            keyword_light_good = any(keyword in all_text_lower for keyword in light_keywords)
            
            data['good_lighting'] = light_good or keyword_light_good
            
            # Extract building year
            building_year = None
            if 'building_age_text' in data and data['building_age_text']:
                building_year = extract_building_year(data['building_age_text'])
            if not building_year and '築年月' in data and data['築年月']:
                building_year = extract_building_year(data['築年月'])
            if building_year:
                data['building_year'] = building_year
            
            # Extract balcony size
            if 'balcony_area_text' in data:
                balcony_size = parse_numeric_field(data['balcony_area_text'].replace('m²', '').replace('㎡', ''))
                if balcony_size:
                    data['balcony_size_sqm'] = balcony_size
            
            # Reform/Renovation parser
            try:
                # Look for reform block
                reform_block = None
                for text_elem in soup.find_all(string=re.compile('リフォーム')):
                    # Navigate up to find container
                    container = text_elem
                    for _ in range(5):
                        if container and hasattr(container, 'parent'):
                            container = container.parent
                            if container and container.name in ['div', 'section', 'table']:
                                reform_block = container
                                break
                    if reform_block:
                        break
                
                if reform_block:
                    reform_text = reform_block.get_text(" ", strip=True)
                    # Pattern: 水回り YYYY年MM月実施 items... 内装 YYYY年MM月実施 items...
                    water_match = re.search(r'水回り\s+(\d{4})年(\d{2})月実施\s+([^内装]+)', reform_text)
                    interior_match = re.search(r'内装\s+(\d{4})年(\d{2})月実施\s+(.+)', reform_text)
                    
                    if water_match:
                        data['reform_water_date'] = f"{water_match.group(1)}-{water_match.group(2)}"
                        data['reform_water_items'] = water_match.group(3).strip()
                    
                    if interior_match:
                        data['reform_interior_date'] = f"{interior_match.group(1)}-{interior_match.group(2)}"
                        # Clean up items - remove any trailing patterns
                        items = interior_match.group(3).strip()
                        items = re.sub(r'[。、]+$', '', items)
                        data['reform_interior_items'] = items
            except Exception as e:
                if logger:
                    logger.debug(f"Reform parsing error (non-critical): {e}")
            
            # Additional fields
            data['first_seen_date'] = datetime.now().isoformat()
            data['source'] = 'homes_scraper'
            data['processed_date'] = datetime.now().strftime('%Y-%m-%d')
            
            # Interior photo detection and image extraction using gallery sections
            try:
                if logger:
                    logger.info(f"Starting gallery photo analysis for {property_id}")
                
                # Collect images from gallery sections with deduplication
                classified_urls, counts = collect_gallery_images(soup, logger)
                
                # HARD SKIP RULE: Skip listing if no interior photos (after dedupe)
                if counts['interior'] == 0:
                    if logger:
                        logger.warning(f"Skipping listing {property_id}: no interior photos found")
                    # Return None to indicate this property should be skipped
                    return None
                
                # Store classification counts (post-dedupe)
                data['interior_photo_count'] = counts['interior']
                data['exterior_photo_count'] = counts['exterior']
                data['floorplan_photo_count'] = counts['floorplan']
                data['facility_photo_count'] = counts['facility']
                data['other_photo_count'] = counts['other']
                data['has_interior_photos'] = True  # Always true if we reach here
                
                # Select images for download with strict caps
                selected_urls, breakdown = select_images_for_download(
                    classified_urls, max_total=10, max_floorplan=1, max_exterior=1, 
                    max_facility=1, max_other=1, logger=logger
                )
                
                if selected_urls and output_bucket:
                    if session_pool and image_rate_limiter:
                        s3_keys = download_images_parallel(selected_urls, session_pool, output_bucket, property_id, logger, image_rate_limiter)
                    else:
                        s3_keys = download_images_parallel_fallback(selected_urls, session, output_bucket, property_id, logger)
                    
                    if s3_keys:
                        data["photo_filenames"] = "|".join(s3_keys)
                        data["image_count"] = len(s3_keys)
                        if logger:
                            logger.info(f"Downloaded {len(s3_keys)}/{len(selected_urls)} images")
                    else:
                        data["image_count"] = 0
                        if logger:
                            logger.warning("No images were successfully downloaded")
                else:
                    data["image_count"] = 0
                    data["photo_filenames"] = ""
                    if logger:
                        logger.info("No images selected for download or no output bucket configured")
                    
            except Exception as e:
                if logger:
                    logger.error(f"Image extraction failed: {str(e)}")
                # On error, skip the listing to be safe
                return None
            
            # Final price validation
            if not data.get('price') or data.get('price') == 0:
                if 'title' in data and '万円' in data['title']:
                    title_price = parse_price_from_text(data['title'])
                    if title_price > 0:
                        data['price'] = title_price
                        if logger:
                            logger.debug(f"Price extracted from title: {data['title']} -> {title_price}")
            
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


def scrape_suumo_property(session, property_url, retries=3, config=None, logger=None, session_pool=None, image_rate_limiter=None):
    """Extract Suumo property information with comprehensive field extraction"""
    last_error = None
    output_bucket = config.get('output_bucket', '') if config else ''
    
    for attempt in range(retries + 1):
        try:
            # Add delay
            time.sleep(random.uniform(1, 2))
            
            response = session.get(property_url, timeout=15)
            
            if response.status_code != 200:
                if attempt == retries:
                    raise Exception(f"HTTP {response.status_code}")
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {
                "url": property_url,
                "extraction_timestamp": datetime.now().isoformat(),
                "source": "suumo"
            }
            
            # Extract property ID from URL using the same logic as dynamodb_utils
            raw_property_id = extract_property_id_from_url(property_url)
            if raw_property_id:
                property_id = create_property_id_key(raw_property_id)
                data["id"] = raw_property_id
                data["property_id"] = property_id
            else:
                # Fallback to URL hash as simple ID if extraction fails
                property_id = hashlib.md5(property_url.encode('utf-8')).hexdigest()[:8]
                data["id"] = property_id
                data["property_id"] = f"PROP#{datetime.now().strftime('%Y%m%d')}_{property_id}"
            
            # Extract property name
            property_name = soup.find('h1', class_='mainIndexR')
            if property_name:
                name_text = property_name.get_text(strip=True)
                # Extract property name and price from title
                name_parts = name_text.split()
                if name_parts:
                    data["property_name"] = name_parts[0]
                    # Also extract price from title if present
                    for part in name_parts:
                        if '万円' in part:
                            price_match = re.search(r'(\d+)万円', part)
                            if price_match:
                                # Store price in 万円 format (same as Lifull) for frontend compatibility
                                data["price"] = int(price_match.group(1))
                                data["price_text"] = part
            
            # Extract title
            data["title"] = property_name.get_text(strip=True) if property_name else ""
            
            # Extract property type
            property_type = soup.find('li', class_='pct01')
            if property_type:
                data["property_type"] = property_type.get_text(strip=True)
            
            # Extract property description
            description_h3 = soup.find('h3', class_='fs16 b')
            if description_h3:
                data['property_description_title'] = description_h3.get_text(strip=True)
                desc_p = description_h3.find_next_sibling('p', class_='fs14')
                if desc_p:
                    data['property_description'] = desc_p.get_text(strip=True)
            
            # Extract detailed information from tables
            tables = soup.find_all('table', class_='bdGrayT')
            
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    # Get ALL th/td pairs in this row (not just the first)
                    all_ths = row.find_all('th')
                    all_tds = row.find_all('td')
                    
                    # Process each th/td pair
                    for th, td in zip(all_ths, all_tds):
                        if not th or not td:
                            continue
                            
                        key = th.get_text(strip=True)
                        val = td.get_text(strip=True)
                        
                        # Price and fees
                        if '価格' in key and not data.get('price'):
                            price_match = re.search(r'(\d+)万円', val)
                            if price_match:
                                # Store price in 万円 format (same as Lifull) for frontend compatibility
                                data["price"] = int(price_match.group(1))
                                data["price_text"] = val
                        
                        elif '管理費' in key:
                            data['management_fee_text'] = val
                            # Parse patterns like "1万4300円/月" or "7300円/月"
                            match = re.search(r'(\d+)万(\d+)', val)
                            if match:
                                man = int(match.group(1)) * 10000
                                sen = int(match.group(2)) if match.group(2) else 0
                                data['management_fee'] = man + sen
                            else:
                                match = re.search(r'([\d,]+)円', val.replace(',', ''))
                                if match:
                                    data['management_fee'] = int(match.group(1).replace(',', ''))
                        
                        elif '修繕積立金' in key:
                            data['repair_reserve_fee_text'] = val
                            # Parse patterns like "1万4300円/月"
                            match = re.search(r'(\d+)万(\d+)', val)
                            if match:
                                man = int(match.group(1)) * 10000
                                sen = int(match.group(2)) if match.group(2) else 0
                                data['repair_reserve_fee'] = man + sen
                            else:
                                match = re.search(r'([\d,]+)円', val.replace(',', ''))
                                if match:
                                    data['repair_reserve_fee'] = int(match.group(1).replace(',', ''))
                        
                        # Transaction fees
                        elif '諸費用' in key or '取引にかかる費用' in key:
                            data['transaction_fees'] = val
                            if '仲介手数料無料' in val:
                                data['no_brokerage_fee'] = True
                            elif '仲介手数料' in val:
                                brokerage_match = re.search(r'(\d+[\d,]*)円', val.replace(',', ''))
                                if brokerage_match:
                                    data['brokerage_fee'] = int(brokerage_match.group(1).replace(',', ''))
                        
                        # Property characteristics
                        elif '間取り' in key:
                            data['layout_text'] = val
                            # Parse layout type (1LDK, 2DK, etc.)
                            layout_match = re.search(r'(\d+[A-Z]+)', val)
                            if layout_match:
                                data['layout_type'] = layout_match.group(1)
                            # Extract number of bedrooms
                            bedroom_match = re.search(r'^(\d+)', val)
                            if bedroom_match:
                                data['num_bedrooms'] = int(bedroom_match.group(1))
                        
                        elif '専有面積' in key:
                            data['size_text'] = val
                            # Handle different size formats: "54.00m²", "54m<sup>2</sup>", "54.00平米"
                            size_match = re.search(r'([\d.]+)(?:m[²²]?|m<sup>2</sup>|平米|㎡)', val)
                            if size_match:
                                size_value = float(size_match.group(1))
                                data['size'] = size_value  # Legacy field
                                data['size_sqm'] = size_value  # Expected field for consistency with Suumo
                        
                        elif 'バルコニー面積' in key or ('その他面積' in key and 'バルコニー' in val):
                            # Handle different size formats: "6.48m²", "6.48m<sup>2</sup>", "6.48平米"  
                            balcony_match = re.search(r'([\d.]+)(?:m[²²]?|m<sup>2</sup>|平米|㎡)', val)
                            if balcony_match:
                                data['balcony_size_sqm'] = float(balcony_match.group(1))
                            data['balcony_text'] = val
                        
                        elif '所在階' in key:
                            # Handle combined format: "2階/SRC7階建"
                            combined_match = re.search(r'(\d+)階/([A-Z]+)(\d+)階建', val)
                            if combined_match:
                                data['floor'] = int(combined_match.group(1))
                                structure = combined_match.group(2)
                                if not structure.endswith('造'):
                                    structure += '造'
                                data['structure'] = structure
                                data['total_floors'] = int(combined_match.group(3))
                                data['building_floors'] = int(combined_match.group(3))  # For DynamoDB
                            else:
                                # Regular floor extraction
                                floor_match = re.search(r'(\d+)階', val)
                                if floor_match:
                                    data['floor'] = int(floor_match.group(1))
                            data['floor_info'] = val
                        
                        elif '向き' in key:
                            data['primary_light'] = val
                            good_directions = ['南', '南東', '南西', '東南', '西南']
                            data['good_lighting'] = any(direction in val for direction in good_directions)
                        
                        elif '総戸数' in key:
                            units_match = re.search(r'(\d+)戸', val)
                            if units_match:
                                data['total_units'] = int(units_match.group(1))
                        
                        # Building info
                        elif '構造' in key or '階建' in key:
                            data['building_structure'] = val
                            
                            # Handle structure and floors in one field: "SRC7階建"
                            struct_floors_match = re.search(r'([A-Z]+)造?(\d+)階建', val)
                            if struct_floors_match:
                                structure = struct_floors_match.group(1)
                                if not structure.endswith('造'):
                                    structure += '造'
                                data['structure'] = structure
                                data['total_floors'] = int(struct_floors_match.group(2))
                                data['building_floors'] = int(struct_floors_match.group(2))  # For DynamoDB
                            else:
                                # Extract total floors only
                                floors_match = re.search(r'(\d+)階建', val)
                                if floors_match:
                                    data['total_floors'] = int(floors_match.group(1))
                                    data['building_floors'] = int(floors_match.group(1))  # For DynamoDB
                                    
                                # Extract structure patterns
                                structure_patterns = ['SRC', 'RC', 'S造', 'W造', '鉄骨', '鉄筋', '木造']
                                for struct_type in structure_patterns:
                                    if struct_type in val:
                                        if struct_type == '鉄骨':
                                            data['structure'] = 'S造'
                                        elif struct_type == '鉄筋':
                                            data['structure'] = 'RC造'
                                        elif struct_type == '木造':
                                            data['structure'] = 'W造'
                                        elif not struct_type.endswith('造'):
                                            data['structure'] = struct_type + '造'
                                        else:
                                            data['structure'] = struct_type
                                        break
                        
                        elif '完成時期' in key or '築年月' in key:
                            data['built_text'] = val
                            year_match = re.search(r'(\d{4})年', val)
                            month_match = re.search(r'(\d{1,2})月', val)
                            if year_match:
                                data['building_year'] = int(year_match.group(1))
                                data['building_age_years'] = datetime.now().year - int(year_match.group(1))
                            if month_match:
                                data['building_month'] = int(month_match.group(1))
                        
                        # Energy and sustainability metrics
                        elif 'エネルギー消費性能' in key:
                            data['energy_performance'] = val
                            if 'ZEH' in val:
                                data['is_zeh'] = True
                        
                        elif '断熱性能' in key:
                            data['insulation_performance'] = val
                            # Extract grade if present
                            grade_match = re.search(r'等級(\d+)', val)
                            if grade_match:
                                data['insulation_grade'] = int(grade_match.group(1))
                        
                        elif '目安光熱費' in key:
                            data['estimated_utility_cost_text'] = val
                            utility_match = re.search(r'([\d,]+)円', val.replace(',', ''))
                            if utility_match:
                                data['estimated_utility_cost'] = int(utility_match.group(1))
                        
                        # Location
                        elif key == '住所' or key == '所在地':
                            data['address'] = val
                            # Extract prefecture
                            pref_match = re.search(r'(東京都|神奈川県|埼玉県|千葉県|茨城県|栃木県|群馬県|山梨県)', val)
                            if pref_match:
                                data['prefecture'] = pref_match.group(1)
                            # Extract city
                            city_match = re.search(r'([^都道府県]+市)', val)
                            if city_match:
                                data['city'] = city_match.group(1)
                            # Extract ward if present
                            ward_match = re.search(r'([^都道府県市]+区)', val)
                            if ward_match:
                                japanese_ward = ward_match.group(1)
                                # Convert Japanese ward to English
                                english_ward = JAPANESE_TO_ENGLISH_WARD.get(japanese_ward, japanese_ward)
                                data['ward'] = english_ward
                            # Extract district/town
                            district_match = re.search(r'区([^0-9０-９]+)', val)
                            if district_match:
                                data['district'] = district_match.group(1).strip()
                        
                        elif key == '交通':
                            data['station_info'] = val
                        
                        # Renovation info
                        elif 'リフォーム' in key:
                            data['renovation_status'] = val
                            data['has_renovation'] = True
                            # Parse renovation details
                            if '年' in val and '月' in val:
                                year_match = re.search(r'(\d{4})年', val)
                                month_match = re.search(r'(\d{1,2})月', val)
                                if year_match and month_match:
                                    data['renovation_year'] = int(year_match.group(1))
                                    data['renovation_month'] = int(month_match.group(1))
                            # Extract renovation items
                            if 'キッチン' in val:
                                data['renovation_kitchen'] = True
                            if '浴室' in val:
                                data['renovation_bathroom'] = True
                            if 'トイレ' in val:
                                data['renovation_toilet'] = True
                            if '内装' in val:
                                data['renovation_interior'] = True
                            if 'フローリング' in val:
                                data['renovation_flooring'] = True
                        
                        # Move-in availability
                        elif '引渡' in key or '入居' in key:
                            data['move_in_availability'] = val
                            if '即' in val:
                                data['immediate_move_in'] = True
                        
                        # Land rights
                        elif '敷地の権利形態' in key or '権利形態' in key:
                            data['land_rights'] = val
                            if '所有権' in val:
                                data['freehold'] = True
                            elif '借地' in val:
                                data['leasehold'] = True
                        
                        # Zoning
                        elif '用途地域' in key:
                            data['zoning'] = val
                        
                        # Company info
                        elif '取引態様' in key:
                            data['transaction_type'] = val
                            if '売主' in val:
                                data['is_direct_seller'] = True
                            elif '代理' in val:
                                data['is_agent'] = True
                            elif '仲介' in val:
                                data['is_broker'] = True
            
            # Extract company information
            company_link = soup.find('a', class_='jscToiawaseSakiWindow')
            if company_link:
                data['company_name'] = company_link.get_text(strip=True)
            
            # Extract phone number
            phone_spans = soup.find_all('span', class_='fs18 b')
            for span in phone_spans:
                text = span.get_text(strip=True)
                if 'TEL' in text or re.search(r'\d{2,4}-\d{2,4}-\d{4}', text):
                    phone_match = re.search(r'([\d-]+)', text)
                    if phone_match:
                        data['contact_phone'] = phone_match.group(1)
            
            # Extract event/viewing information
            event_section = soup.find(text=re.compile('現地見学会'))
            if event_section:
                parent = event_section.parent
                if parent:
                    data['viewing_info'] = parent.get_text(strip=True)
            
            # Extract transportation details (multiple stations)
            stations = []
            # Method 1: From table cells
            transport_cells = soup.find_all('td', class_='bdCell')
            for cell in transport_cells:
                text = cell.get_text()
                if '歩' in text and '分' in text:
                    station_matches = re.findall(r'([^「」]+線)?「([^」]+)」歩(\d+)分', text)
                    for match in station_matches:
                        station_data = {
                            'line': match[0].replace('線', '') if match[0] else '',
                            'station': match[1],
                            'walk_minutes': int(match[2])
                        }
                        # Avoid duplicates
                        if station_data not in stations:
                            stations.append(station_data)
            
            # Method 2: From any text containing station info
            transport_sections = soup.find_all(text=re.compile(r'「.+?」歩\d+分'))
            for section in transport_sections:
                matches = re.findall(r'([^「」]+線)?「([^」]+)」歩(\d+)分', str(section))
                for match in matches:
                    station_data = {
                        'line': match[0].replace('線', '') if match[0] else '',
                        'station': match[1],
                        'walk_minutes': int(match[2])
                    }
                    if station_data not in stations:
                        stations.append(station_data)
            
            if stations:
                data['stations'] = stations
                data['station_count'] = len(stations)
                # Set closest station
                closest = min(stations, key=lambda x: x['walk_minutes'])
                data['closest_station'] = closest['station']
                data['station_distance_minutes'] = closest['walk_minutes']
                # Calculate transportation convenience score
                data['transport_score'] = max(0, 100 - (closest['walk_minutes'] * 5))
            
            # Extract special features - improved parsing
            features = []
            
            # From feature list items at top
            feature_items = soup.find_all('li', class_='pct01')
            features.extend([f.get_text(strip=True) for f in feature_items if f.get_text(strip=True)])
            
            # From detailed feature section at bottom
            feature_section = soup.find('div', class_='mt10')
            if feature_section:
                # Look for feature lists separated by slashes
                feature_texts = feature_section.find_all(text=re.compile('/'))
                for text in feature_texts:
                    if isinstance(text, str):
                        items = [item.strip() for item in text.split('/') if item.strip()]
                        features.extend(items)
            
            # Remove duplicates while preserving order
            seen = set()
            unique_features = []
            for f in features:
                if f not in seen and len(f) < 50:  # Exclude very long text
                    seen.add(f)
                    unique_features.append(f)
            
            if unique_features:
                data['special_features'] = unique_features
                data['feature_count'] = len(unique_features)
                
                # Check for key features
                feature_text = ' '.join(unique_features)
                data['has_elevator'] = 'エレベーター' in feature_text
                data['is_corner_unit'] = '角住戸' in feature_text or '角部屋' in feature_text
                data['has_parking'] = '駐車場' in feature_text
                data['has_bike_parking'] = '駐輪場' in feature_text
                data['has_renovation'] = 'リノベーション' in feature_text or 'リフォーム' in feature_text
                data['south_facing'] = '南向き' in feature_text or '南面' in feature_text
                data['has_security'] = 'オートロック' in feature_text or 'セキュリティ' in feature_text
                data['has_floor_heating'] = '床暖房' in feature_text
                data['pet_allowed'] = 'ペット可' in feature_text or 'ペット相談' in feature_text
            
            # Enhanced neighborhood info extraction
            neighborhood = {}
            amenity_count = 0
            
            # Method 1: From structured list items
            neighborhood_items = soup.find_all('li', class_='dibz w235 vat')
            for item in neighborhood_items:
                text = item.get_text(strip=True)
                # Parse different facility types with distances
                facility_patterns = [
                    (r'(.+?)まで(\d+)m', 'meters'),
                    (r'(.+?)：徒歩(\d+)分', 'minutes'),
                    (r'(.+?)徒歩約?(\d+)分', 'minutes')
                ]
                
                for pattern, unit in facility_patterns:
                    match = re.search(pattern, text)
                    if match:
                        facility = match.group(1)
                        distance = int(match.group(2))
                        
                        # Convert minutes to meters if needed (80m per minute)
                        if unit == 'minutes':
                            distance = distance * 80
                        
                        amenity_count += 1
                        
                        # Categorize facilities
                        if 'スーパー' in facility or 'ストア' in facility:
                            if 'supermarket_distance' not in neighborhood or distance < neighborhood['supermarket_distance']:
                                neighborhood['supermarket_distance'] = distance
                                neighborhood['supermarket_name'] = facility
                        elif 'コンビニ' in facility or 'セブン' in facility or 'ファミリー' in facility or 'ローソン' in facility:
                            if 'convenience_store_distance' not in neighborhood or distance < neighborhood['convenience_store_distance']:
                                neighborhood['convenience_store_distance'] = distance
                                neighborhood['convenience_store_name'] = facility
                        elif '小学校' in facility:
                            neighborhood['elementary_school_distance'] = distance
                            neighborhood['elementary_school_name'] = facility
                        elif '中学校' in facility:
                            neighborhood['middle_school_distance'] = distance
                            neighborhood['middle_school_name'] = facility
                        elif '幼稚園' in facility or '保育園' in facility:
                            if 'kindergarten_distance' not in neighborhood or distance < neighborhood['kindergarten_distance']:
                                neighborhood['kindergarten_distance'] = distance
                                neighborhood['kindergarten_name'] = facility
                        elif '公園' in facility:
                            if 'park_distance' not in neighborhood or distance < neighborhood['park_distance']:
                                neighborhood['park_distance'] = distance
                                neighborhood['park_name'] = facility
                        elif '病院' in facility or 'クリニック' in facility:
                            if 'hospital_distance' not in neighborhood or distance < neighborhood['hospital_distance']:
                                neighborhood['hospital_distance'] = distance
                                neighborhood['hospital_name'] = facility
                        elif '薬' in facility or 'ドラッグ' in facility:
                            if 'drugstore_distance' not in neighborhood or distance < neighborhood['drugstore_distance']:
                                neighborhood['drugstore_distance'] = distance
                                neighborhood['drugstore_name'] = facility
                        elif '郵便局' in facility:
                            neighborhood['post_office_distance'] = distance
                            neighborhood['post_office_name'] = facility
                        elif '銀行' in facility or '信用金庫' in facility:
                            if 'bank_distance' not in neighborhood or distance < neighborhood['bank_distance']:
                                neighborhood['bank_distance'] = distance
                                neighborhood['bank_name'] = facility
            
            # Method 2: From facility table
            facility_divs = soup.find_all('div', class_='fl w320 mt5 lh15')
            for div in facility_divs:
                text = div.get_text(strip=True)
                # Parse facility info
                match = re.search(r'(.+?)：徒歩(\d+)分（(\d+)ｍ）', text)
                if not match:
                    match = re.search(r'(.+?)：徒歩(\d+)分', text)
                if match:
                    facility_name = match.group(1)
                    walk_minutes = int(match.group(2))
                    meters = int(match.group(3)) if match.lastindex >= 3 else walk_minutes * 80
                    
                    amenity_count += 1
                    
                    # Categorize and store
                    if 'スーパー' in text or 'ストア' in facility_name:
                        if 'supermarket_distance' not in neighborhood or meters < neighborhood['supermarket_distance']:
                            neighborhood['supermarket_distance'] = meters
                            neighborhood['supermarket_name'] = facility_name
            
            if neighborhood:
                data['neighborhood_facilities'] = neighborhood
                data['amenity_count'] = amenity_count
                
                # Calculate neighborhood quality score
                score = 100
                if neighborhood.get('supermarket_distance', 1000) > 500:
                    score -= 10
                if neighborhood.get('convenience_store_distance', 1000) > 300:
                    score -= 10
                if neighborhood.get('park_distance', 1000) > 1000:
                    score -= 5
                data['neighborhood_score'] = max(0, score)
            
            # Fallback fee parsing if not found in main table
            if not data.get('management_fee') or not data.get('repair_reserve_fee'):
                rows = soup.find_all('tr')
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    for i, cell in enumerate(cells):
                        cell_text = cell.get_text(strip=True)
                        
                        # Look for management fee
                        if not data.get('management_fee') and '管理費' in cell_text and '修繕' not in cell_text:
                            if i + 1 < len(cells):
                                next_cell = cells[i + 1]
                                next_text = next_cell.get_text(strip=True)
                                
                                # Parse the fee amount
                                if next_text and next_text not in ['-', '－']:
                                    data['management_fee_text'] = next_text
                                    # Look for patterns like "1万4300円/月" or "7300円/月"
                                    match = re.search(r'(\d+)万(\d+)', next_text)
                                    if match:
                                        man = int(match.group(1)) * 10000
                                        sen = int(match.group(2)) if match.group(2) else 0
                                        data['management_fee'] = man + sen
                                    else:
                                        match = re.search(r'([\d,]+)円', next_text.replace(',', ''))
                                        if match:
                                            data['management_fee'] = int(match.group(1).replace(',', ''))
                        
                        # Look for repair reserve fee
                        elif not data.get('repair_reserve_fee') and '修繕積立金' in cell_text:
                            if i + 1 < len(cells):
                                next_cell = cells[i + 1]
                                next_text = next_cell.get_text(strip=True)
                                
                                # Parse the fee amount
                                if next_text and next_text not in ['-', '－']:
                                    data['repair_reserve_fee_text'] = next_text
                                    # Look for patterns like "1万4300円/月"
                                    match = re.search(r'(\d+)万(\d+)', next_text)
                                    if match:
                                        man = int(match.group(1)) * 10000
                                        sen = int(match.group(2)) if match.group(2) else 0
                                        data['repair_reserve_fee'] = man + sen
                                    else:
                                        match = re.search(r'([\d,]+)円', next_text.replace(',', ''))
                                        if match:
                                            data['repair_reserve_fee'] = int(match.group(1).replace(',', ''))
            
            # Calculate total monthly costs
            monthly_costs = 0
            if data.get('management_fee'):
                monthly_costs += data['management_fee']
            if data.get('repair_reserve_fee'):
                monthly_costs += data['repair_reserve_fee']
            if monthly_costs > 0:
                data['monthly_costs'] = monthly_costs
                data['total_monthly_costs'] = monthly_costs
            
            # Note: price_per_sqm calculation is handled later with proper unit conversion
            
            # Extract images - comprehensive approach
            image_urls = []
            seen_images = set()
            
            # Multiple image selectors
            image_selectors = [
                '.carousel_item-object img',  # Carousel images
                '.w220.h165 img',  # Thumbnail images
                '.w296.h222 img',  # Large thumbnails
                'img[alt][src*="gazo/bukken"]',  # Property images
                'a.jscNyroModal img',  # Modal images
            ]
            
            for selector in image_selectors:
                imgs = soup.select(selector)
                for img in imgs:
                    src = img.get('src') or img.get('data-src') or img.get('rel')
                    if src and 'spacer' not in src and 'spinner' not in src:
                        # Clean up image URL
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = 'https://suumo.jp' + src
                        
                        # Check if it's a real image URL
                        if ('resizeImage' in src or 'gazo/bukken' in src) and src not in seen_images:
                            image_urls.append(src)
                            seen_images.add(src)
            
            if image_urls:
                data['has_interior_photos'] = True
                data['image_count'] = len(image_urls)
                data['image_urls'] = image_urls[:20]  # Store first 20 URLs
                
                # Analyze image types
                interior_count = sum(1 for url in image_urls if 'interior' in url.lower() or '内装' in url)
                exterior_count = sum(1 for url in image_urls if 'exterior' in url.lower() or '外観' in url)
                data['interior_photo_count'] = interior_count
                data['exterior_photo_count'] = exterior_count
                
                # Download images if configured
                if output_bucket and image_urls[:10]:
                    # Image download logic would go here if needed
                    pass
            
            # Listing metadata and market context
            info_date = soup.find(text=re.compile('情報提供日'))
            if info_date:
                date_match = re.search(r'(\d{4})年(\d+)月(\d+)日', info_date.parent.get_text())
                if not date_match:
                    date_match = re.search(r'(\d{2})/(\d+)/(\d+)', info_date.parent.get_text())
                    if date_match:
                        year = 2000 + int(date_match.group(1)) if int(date_match.group(1)) < 50 else 1900 + int(date_match.group(1))
                        data['listing_date'] = f"{year}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
                else:
                    data['listing_date'] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
                
                # Calculate days on market
                if data.get('listing_date'):
                    try:
                        listing_date = datetime.strptime(data['listing_date'], '%Y-%m-%d')
                        days_on_market = (datetime.now() - listing_date).days
                        data['days_on_market'] = days_on_market
                        
                        # Market freshness indicator
                        if days_on_market <= 7:
                            data['market_freshness'] = 'new'
                        elif days_on_market <= 30:
                            data['market_freshness'] = 'fresh'
                        elif days_on_market <= 90:
                            data['market_freshness'] = 'standard'
                        else:
                            data['market_freshness'] = 'stale'
                    except:
                        pass
            
            # Update date
            update_date = soup.find(text=re.compile('次回更新日'))
            if update_date:
                data['next_update'] = update_date.parent.get_text(strip=True).replace('次回更新日', '').replace('：', '').strip()
            
            # Price history (if available)
            price_update = soup.find(text=re.compile('価格更新'))
            if price_update:
                data['has_price_update'] = True
                update_text = price_update.parent.get_text(strip=True)
                data['price_update_info'] = update_text
            
            # Process size_sqm_text field (same logic as Homes.co.jp scraper)
            if 'size_sqm_text' in data:
                size_sqm = parse_numeric_field(data['size_sqm_text'].replace('m²', '').replace('㎡', '').replace('m<sup>2</sup>', ''))
                if size_sqm:
                    data['size_sqm'] = size_sqm
                    # Calculate price per sqm if we have both (price is in 万円, convert to yen for calculation)
                    if data.get('price') and data['price'] > 0:
                        calculated_price_per_sqm = (data['price'] * 10000) / size_sqm
                        data['price_per_sqm'] = calculated_price_per_sqm
                        if logger:
                            logger.debug(f"Calculated price_per_sqm: {calculated_price_per_sqm:.0f} yen/sqm")
            
            # Overall quality scores
            if data.get('building_age_years'):
                age_score = max(0, 100 - (data['building_age_years'] * 2))
                if data.get('has_renovation'):
                    age_score = min(100, age_score + 20)
                data['building_condition_score'] = age_score
            
            # Calculate overall property score
            scores = []
            if data.get('transport_score'):
                scores.append(data['transport_score'])
            if data.get('neighborhood_score'):
                scores.append(data['neighborhood_score'])
            if data.get('building_condition_score'):
                scores.append(data['building_condition_score'])
            
            if scores:
                data['overall_score'] = int(sum(scores) / len(scores))
            
            data['first_seen_date'] = datetime.now().isoformat()
            data['processed_date'] = datetime.now().strftime('%Y-%m-%d')
            
            return data
            
        except Exception as e:
            last_error = e
            if logger:
                logger.debug(f"Suumo scrape attempt {attempt + 1} failed: {str(e)}")
            
            if attempt == retries:
                break
                
            time.sleep((2 ** attempt) + random.uniform(0, 1))
    
    if last_error:
        raise last_error
    else:
        raise Exception("Max retries exceeded for Suumo property")