#!/usr/bin/env python3
"""
Core scraping functionality for realtor.com (US market)
Extracts property details from individual listing pages
"""
import time
import requests
import random
import re
import json
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
import hashlib
import os

# Browser profiles for anti-bot evasion
BROWSER_PROFILES = [
    {
        "name": "Chrome_Windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-platform": '"Windows"',
            "Accept-Language": "en-US,en;q=0.9"
        }
    },
    {
        "name": "Chrome_Mac",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-platform": '"macOS"',
            "Accept-Language": "en-US,en;q=0.9"
        }
    },
    {
        "name": "Firefox_Windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Accept-Language": "en-US,en;q=0.5"
        }
    }
]


def create_session(logger=None):
    """Create HTTP session with anti-bot headers"""
    session = requests.Session()

    profile = random.choice(BROWSER_PROFILES)
    base_headers = profile["headers"].copy()

    base_headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
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


def parse_us_price(price_text):
    """Parse US price text like '$450,000' to integer USD"""
    if not price_text:
        return None

    price_str = str(price_text)

    skip_phrases = ['contact', 'call', 'price upon request', 'auction', 'n/a']
    if any(phrase in price_str.lower() for phrase in skip_phrases):
        return None

    try:
        cleaned = re.sub(r'[^\d.]', '', price_str)
        if not cleaned:
            return None

        if '.' in cleaned:
            price = int(float(cleaned))
        else:
            price = int(cleaned)

        if price < 10000:
            return None

        return price

    except (ValueError, AttributeError):
        return None


def extract_property_id_from_url(url):
    """Extract property ID from realtor.com URL"""
    patterns = [
        r'_M(\d+-\d+)$',
        r'_M(\d+)$',
        r'/realestateandhomes-detail/[^/]+_([A-Z0-9-]+)$',
        r'/([A-Z0-9]+-[0-9]+)/?$',
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)

    if '/realestateandhomes-detail/' in url:
        slug_match = re.search(r'/realestateandhomes-detail/([^?]+)', url)
        if slug_match:
            return slug_match.group(1).replace('/', '_')[:100]

    return None


def create_property_id_key(raw_property_id, date_str=None):
    """Create property_id key for DynamoDB"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    return f"PROP#{date_str}_{raw_property_id}"


def extract_realtor_property_details(url, session=None, logger=None):
    """
    Extract property details from a realtor.com property detail page

    Returns dict with US property fields or None on error
    """
    if session is None:
        session = create_session(logger)

    try:
        headers = {'Referer': 'https://www.realtor.com/'}
        response = session.get(url, headers=headers, timeout=30)

        if response.status_code == 403:
            if logger:
                logger.warning(f"403 Forbidden for {url}")
            return {'error': '403 Forbidden', 'url': url}

        if response.status_code == 404:
            if logger:
                logger.warning(f"404 Not Found for {url}")
            return {'error': '404 Not Found', 'url': url}

        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'lxml')

        # Initialize property data
        property_data = {
            'listing_url': url,
            'extraction_timestamp': datetime.now().isoformat(),
        }

        # Extract property ID from URL
        raw_id = extract_property_id_from_url(url)
        if raw_id:
            property_data['property_id'] = create_property_id_key(raw_id)
            property_data['mls_id'] = raw_id

        # Try to extract data from JSON-LD first (most reliable)
        json_data = extract_json_ld_data(soup, logger)
        if json_data:
            property_data.update(json_data)

        # Fall back to HTML parsing
        html_data = extract_html_data(soup, logger)
        # Only update fields not already set
        for key, value in html_data.items():
            if key not in property_data or not property_data[key]:
                property_data[key] = value

        # Calculate derived fields
        if property_data.get('price') and property_data.get('size_sqft'):
            try:
                price = float(property_data['price'])
                sqft = float(property_data['size_sqft'])
                if sqft > 0:
                    property_data['price_per_sqft'] = round(price / sqft, 2)
            except (ValueError, TypeError):
                pass

        # Extract images
        images = extract_property_images(soup, logger)
        if images:
            property_data['image_urls'] = images[:20]  # Limit to 20 images
            property_data['image_count'] = len(images)

        return property_data

    except requests.RequestException as e:
        if logger:
            logger.error(f"Request error for {url}: {str(e)}")
        return {'error': str(e), 'url': url}
    except Exception as e:
        if logger:
            logger.error(f"Parsing error for {url}: {str(e)}")
        return {'error': str(e), 'url': url}


def extract_json_ld_data(soup, logger=None):
    """Extract property data from JSON-LD structured data"""
    data = {}

    try:
        script_tags = soup.find_all('script', type='application/ld+json')
        for script in script_tags:
            try:
                json_data = json.loads(script.string)

                # Handle array of items
                if isinstance(json_data, list):
                    for item in json_data:
                        extracted = parse_json_ld_item(item)
                        data.update(extracted)
                else:
                    extracted = parse_json_ld_item(json_data)
                    data.update(extracted)

            except (json.JSONDecodeError, AttributeError):
                continue

    except Exception as e:
        if logger:
            logger.debug(f"JSON-LD extraction error: {str(e)}")

    return data


def parse_json_ld_item(item):
    """Parse a single JSON-LD item for property data"""
    data = {}

    if not isinstance(item, dict):
        return data

    item_type = item.get('@type', '')

    # Handle Product type (common for real estate listings)
    if item_type in ['Product', 'RealEstateListing', 'Residence', 'SingleFamilyResidence', 'House']:
        # Price
        offers = item.get('offers', {})
        if isinstance(offers, dict):
            price = parse_us_price(offers.get('price'))
            if price:
                data['price'] = price

        # Address
        address = item.get('address', {})
        if isinstance(address, dict):
            data['address'] = address.get('streetAddress', '')
            data['city'] = address.get('addressLocality', '')
            data['state'] = address.get('addressRegion', '')
            data['zip_code'] = address.get('postalCode', '')

        # Description
        if item.get('description'):
            data['description'] = item['description'][:500]  # Limit length

        # Name/Title
        if item.get('name'):
            data['title'] = item['name']

    return data


def extract_html_data(soup, logger=None):
    """Extract property data from HTML elements"""
    data = {}

    try:
        # Price - look for common price patterns
        price_selectors = [
            '[data-testid="list-price"]',
            '.price',
            '.list-price',
            '[class*="price"]',
        ]
        for selector in price_selectors:
            elem = soup.select_one(selector)
            if elem:
                price = parse_us_price(elem.get_text())
                if price:
                    data['price'] = price
                    break

        # Beds/Baths/Sqft - often in a summary row
        summary_patterns = [
            (r'(\d+)\s*(?:bed|bd)', 'beds'),
            (r'(\d+\.?\d*)\s*(?:bath|ba)', 'baths'),
            (r'([\d,]+)\s*(?:sq\s*ft|sqft|square\s*feet)', 'size_sqft'),
            (r'([\d,\.]+)\s*(?:acre|ac)', 'lot_size_acres'),
        ]

        # Get all text content for pattern matching
        page_text = soup.get_text(' ', strip=True).lower()

        for pattern, field in summary_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                value = match.group(1).replace(',', '')
                try:
                    if field == 'baths':
                        data[field] = float(value)
                    elif field == 'lot_size_acres':
                        data[field] = float(value)
                        data['lot_size_sqft'] = int(float(value) * 43560)
                    else:
                        data[field] = int(float(value))
                except ValueError:
                    pass

        # Address
        address_selectors = [
            '[data-testid="address"]',
            '.address',
            '.property-address',
            'h1',  # Often the title contains the address
        ]
        for selector in address_selectors:
            elem = soup.select_one(selector)
            if elem:
                addr_text = elem.get_text(strip=True)
                if addr_text and len(addr_text) < 200:
                    data['address'] = addr_text
                    # Try to parse city/state/zip from address
                    parsed = parse_address(addr_text)
                    data.update(parsed)
                    break

        # Property type
        type_patterns = [
            (r'\b(single family|single-family)\b', 'Single Family'),
            (r'\b(condo|condominium)\b', 'Condo'),
            (r'\b(townhouse|townhome)\b', 'Townhouse'),
            (r'\b(multi-?family|duplex|triplex)\b', 'Multi-Family'),
            (r'\b(land|lot)\b', 'Land'),
            (r'\b(mobile|manufactured)\b', 'Mobile'),
        ]
        for pattern, prop_type in type_patterns:
            if re.search(pattern, page_text, re.IGNORECASE):
                data['property_type'] = prop_type
                break

        # Year built
        year_match = re.search(r'(?:built|year built|constructed)[\s:]*(\d{4})', page_text, re.IGNORECASE)
        if year_match:
            year = int(year_match.group(1))
            if 1800 <= year <= datetime.now().year:
                data['year_built'] = year

        # HOA
        hoa_match = re.search(r'hoa[\s:]*\$?([\d,]+)', page_text, re.IGNORECASE)
        if hoa_match:
            try:
                data['hoa_fee'] = int(hoa_match.group(1).replace(',', ''))
            except ValueError:
                pass

    except Exception as e:
        if logger:
            logger.debug(f"HTML extraction error: {str(e)}")

    return data


def parse_address(address_text):
    """Parse city, state, zip from address text"""
    data = {}

    # Pattern: "City, ST 12345" or "City, State 12345"
    match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})?', address_text)
    if match:
        data['city'] = match.group(1).strip()
        data['state'] = match.group(2)
        if match.group(3):
            data['zip_code'] = match.group(3)

    return data


def extract_property_images(soup, logger=None):
    """Extract property image URLs from the page"""
    images = []
    seen = set()

    try:
        # Look for image elements
        img_selectors = [
            'img[src*="rdcpix"]',  # realtor.com image CDN
            'img[data-src*="rdcpix"]',
            '[class*="gallery"] img',
            '[class*="photo"] img',
            '[class*="image"] img',
        ]

        for selector in img_selectors:
            for img in soup.select(selector):
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src and src not in seen and not src.startswith('data:'):
                    # Filter out small thumbnails and icons
                    if any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'agent']):
                        continue
                    seen.add(src)
                    images.append(src)

        # Also check for background images in style attributes
        for elem in soup.select('[style*="background-image"]'):
            style = elem.get('style', '')
            match = re.search(r'url\(["\']?([^)"\']+)["\']?\)', style)
            if match:
                url = match.group(1)
                if url not in seen and 'rdcpix' in url:
                    seen.add(url)
                    images.append(url)

    except Exception as e:
        if logger:
            logger.debug(f"Image extraction error: {str(e)}")

    return images


def download_image(url, session, timeout=15, logger=None):
    """Download a single image and return bytes"""
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except Exception as e:
        if logger:
            logger.debug(f"Image download failed: {url} - {str(e)}")
        return None
