#!/usr/bin/env python3
"""
Core scraping functionality for Redfin (US market)
Uses curl_cffi for browser impersonation to bypass bot detection
"""
import time
import random
import re
import json
from bs4 import BeautifulSoup
from datetime import datetime

# Use curl_cffi for browser impersonation
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    import requests as curl_requests
    CURL_CFFI_AVAILABLE = False


def create_session(logger=None):
    """Create HTTP session with browser impersonation"""
    if CURL_CFFI_AVAILABLE:
        # Use curl_cffi with Chrome browser impersonation
        session = curl_requests.Session(impersonate="chrome120")
        if logger:
            logger.debug("Session created with curl_cffi (Chrome 120 impersonation)")
    else:
        # Fallback to regular requests (likely to be blocked)
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
        })
        if logger:
            logger.warning("curl_cffi not available, using requests (may be blocked)")

    return session


def parse_us_price(price_text):
    """
    Parse US price text like '$450,000' or '450000' to numeric value in USD
    Returns integer price in dollars
    """
    if not price_text:
        return None

    price_str = str(price_text)

    # Skip non-price text
    skip_phrases = ['contact', 'call', 'price upon request', 'auction', 'n/a']
    if any(phrase in price_str.lower() for phrase in skip_phrases):
        return None

    try:
        # Remove $ and commas, extract digits
        cleaned = re.sub(r'[^\d.]', '', price_str)

        if not cleaned:
            return None

        # Handle decimal prices
        if '.' in cleaned:
            price = int(float(cleaned))
        else:
            price = int(cleaned)

        # Sanity check - US real estate typically > $10,000
        if price < 10000:
            return None

        return price

    except (ValueError, AttributeError):
        return None


def extract_listing_urls_from_redfin_html(html_content, city, state, logger=None):
    """
    Extract property listing URLs and basic info from Redfin search results HTML
    Returns list of dicts: [{'url': str, 'price': int, 'city': str, 'state': str, 'address': str}, ...]
    """
    soup = BeautifulSoup(html_content, 'lxml')
    results = []
    seen_urls = set()

    # Redfin URL pattern: /CO/Denver/address/home/123456
    # Match links to property detail pages
    property_links = soup.select(f'a[href*="/{state}/"][href*="/home/"]')

    for link in property_links:
        href = link.get('href', '')

        # Skip if already seen or not a valid property link
        if href in seen_urls:
            continue

        # Must contain /home/ followed by digits (property ID)
        if not re.search(r'/home/\d+', href):
            continue

        # Build full URL
        if href.startswith('/'):
            full_url = f"https://www.redfin.com{href}"
        elif href.startswith('http'):
            full_url = href
        else:
            continue

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract property ID from URL
        property_id_match = re.search(r'/home/(\d+)', href)
        property_id = property_id_match.group(1) if property_id_match else None

        # Extract address from URL
        # Format: /CO/Denver/1234-Main-St-80202/home/123456
        address_match = re.search(r'/([^/]+)/home/\d+', href)
        address = address_match.group(1).replace('-', ' ') if address_match else None

        # Try to find price near this link
        price = None

        # Look for price in parent card element
        card = link.find_parent(['div', 'article'], class_=re.compile(r'home|card|listing', re.I))
        if card:
            # Look for price element (Redfin uses class like 'homecardV2Price')
            price_elem = card.find(class_=re.compile(r'price', re.I))
            if price_elem:
                price = parse_us_price(price_elem.get_text())

            # Alternative: look for $ followed by digits
            if not price:
                price_text = card.find(string=re.compile(r'\$[\d,]+'))
                if price_text:
                    price = parse_us_price(price_text)

        results.append({
            'url': full_url,
            'price': price or 0,
            'city': city,
            'state': state,
            'address': address,
            'property_id': property_id,
            'source': 'redfin'
        })

    if logger:
        logger.debug(f"Extracted {len(results)} property URLs from Redfin HTML")

    return results


def collect_redfin_listings(city, state, max_pages=10, city_id=None, session=None, logger=None, rate_limiter=None):
    """
    Collect property listings from Redfin for a given city

    Args:
        city: City name (e.g., 'Denver')
        state: State abbreviation (e.g., 'CO')
        max_pages: Maximum number of pages to scrape
        city_id: Redfin city ID (optional, will try to auto-detect)
        session: curl_cffi Session object
        logger: Logger instance
        rate_limiter: RateLimiter instance

    Returns:
        List of dicts: [{'url': str, 'price': int, 'city': str, ...}, ...]
    """
    if session is None:
        session = create_session(logger)

    # Format city name for URL
    city_formatted = city.replace(' ', '-')

    # Use city_id if provided, otherwise use city_id in URL path
    if city_id and city_id > 0:
        base_url = f"https://www.redfin.com/city/{city_id}/{state}/{city_formatted}"
    else:
        # Alternative URL format without city_id
        base_url = f"https://www.redfin.com/city/{city_id or 0}/{state}/{city_formatted}"

    if logger:
        logger.info(f"Starting Redfin collection for {city}, {state}")

    all_listings = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        if rate_limiter:
            rate_limiter.wait()

        # Construct page URL
        if page == 1:
            url = base_url
        else:
            url = f"{base_url}/page-{page}"

        if logger:
            logger.debug(f"Fetching page {page}: {url}")

        try:
            response = session.get(url, timeout=30)

            # Check for blocking/rate limiting
            if response.status_code == 403:
                if logger:
                    logger.warning(f"403 Forbidden on page {page} - blocked")
                if rate_limiter:
                    rate_limiter.record_error(is_rate_limit=True)
                break

            if response.status_code == 429:
                if logger:
                    logger.warning(f"429 Too Many Requests on page {page}")
                if rate_limiter:
                    rate_limiter.record_error(is_rate_limit=True)
                # Wait longer and retry once
                time.sleep(10)
                response = session.get(url, timeout=30)
                if response.status_code != 200:
                    break

            if response.status_code == 404:
                if logger:
                    logger.info(f"Page {page} not found - reached end of listings")
                break

            response.raise_for_status()

            if rate_limiter:
                rate_limiter.record_success()

            # Parse listings from this page
            page_listings = extract_listing_urls_from_redfin_html(
                response.text, city, state, logger
            )

            if not page_listings:
                if logger:
                    logger.info(f"No listings found on page {page} - reached end")
                break

            # Add new listings (deduplicate)
            new_count = 0
            for listing in page_listings:
                if listing['url'] not in seen_urls:
                    seen_urls.add(listing['url'])
                    all_listings.append(listing)
                    new_count += 1

            if logger:
                logger.info(f"Page {page}: {new_count} new listings (total: {len(all_listings)})")

            # If no new listings were found, we've likely seen all properties
            if new_count == 0:
                if logger:
                    logger.info(f"No new listings on page {page} - stopping")
                break

            # Delay between pages to be respectful
            if page < max_pages:
                delay = random.uniform(2.0, 4.0)
                time.sleep(delay)

        except Exception as e:
            if logger:
                logger.error(f"Error fetching page {page}: {str(e)}")
            if rate_limiter:
                rate_limiter.record_error()
            if 'timeout' in str(e).lower():
                continue
            break

    if logger:
        logger.info(f"Collection complete for {city}, {state}: {len(all_listings)} total listings")

    return all_listings


# Alias for backwards compatibility
def collect_realtor_listings(*args, **kwargs):
    """Backwards compatibility alias - now uses Redfin"""
    return collect_redfin_listings(*args, **kwargs)


def get_target_cities(config, logger=None):
    """
    Get list of target cities to scrape based on configuration

    Args:
        config: Configuration dict with 'redfin' section
        logger: Logger instance

    Returns:
        List of dicts: [{'city': str, 'state': str, 'city_id': int}, ...]
    """
    # Check for redfin config first, fall back to realtor config for compatibility
    redfin_config = config.get('redfin', config.get('realtor', {}))

    target_city = redfin_config.get('TARGET_CITY', 'Denver')
    target_state = redfin_config.get('TARGET_STATE', 'CO')
    city_id = redfin_config.get('CITY_ID', 0)  # 0 means auto-detect

    cities = [{
        'city': target_city,
        'state': target_state,
        'city_id': city_id
    }]

    if logger:
        logger.info(f"Target cities: {cities}")

    return cities
