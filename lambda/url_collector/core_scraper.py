#!/usr/bin/env python3
"""
Core scraping functionality for realtor.com (US market)
"""
import time
import requests
import random
import re
import json
from bs4 import BeautifulSoup
from datetime import datetime

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

    # Random browser profile
    profile = random.choice(BROWSER_PROFILES)
    base_headers = profile["headers"].copy()

    # Common headers
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

        # Handle decimal prices (unlikely for real estate but just in case)
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


def extract_listing_urls_from_realtor_html(html_content, logger=None):
    """
    Extract property listing URLs and prices from realtor.com search results HTML
    Returns list of dicts: [{'url': str, 'price': int, 'city': str}, ...]
    """
    soup = BeautifulSoup(html_content, 'lxml')
    results = []
    seen_urls = set()

    # realtor.com uses various card structures
    # Look for property cards with data attributes or specific classes

    # Method 1: Look for property card links
    property_links = soup.select('a[href*="/realestateandhomes-detail/"]')

    for link in property_links:
        href = link.get('href', '')

        # Skip if already seen
        if href in seen_urls:
            continue

        # Build full URL
        if href.startswith('/'):
            full_url = f"https://www.realtor.com{href}"
        elif href.startswith('http'):
            full_url = href
        else:
            continue

        # Extract property ID from URL for deduplication
        # URL format: /realestateandhomes-detail/{address}_{property_id}
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Try to find price near this link
        price = None

        # Look for price in parent card element
        card = link.find_parent(['div', 'li', 'article'], class_=re.compile(r'card|listing|property', re.I))
        if card:
            # Look for price element
            price_elem = card.find(string=re.compile(r'\$[\d,]+'))
            if price_elem:
                price = parse_us_price(price_elem)

            # Alternative: look for data-price attribute
            if not price:
                price_attr = card.get('data-price') or card.get('data-list-price')
                if price_attr:
                    price = parse_us_price(price_attr)

        results.append({
            'url': full_url,
            'price': price or 0,
            'city': 'Paonia'  # Default to target city, will be extracted from URL if needed
        })

    # Method 2: Try to parse JSON-LD structured data if available
    script_tags = soup.find_all('script', type='application/ld+json')
    for script in script_tags:
        try:
            data = json.loads(script.string)
            # Handle different JSON-LD formats
            if isinstance(data, list):
                for item in data:
                    if item.get('@type') in ['Product', 'RealEstateListing', 'Residence']:
                        url = item.get('url')
                        price_obj = item.get('offers', {})
                        price = parse_us_price(price_obj.get('price') if isinstance(price_obj, dict) else None)

                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            results.append({
                                'url': url,
                                'price': price or 0,
                                'city': 'Paonia'
                            })
        except (json.JSONDecodeError, AttributeError):
            continue

    if logger:
        logger.debug(f"Extracted {len(results)} property URLs from HTML")

    return results


def extract_next_page_url(html_content, current_page, base_url):
    """
    Extract next page URL from realtor.com pagination
    Returns next page URL or None if no more pages
    """
    soup = BeautifulSoup(html_content, 'lxml')

    # Look for next page link
    next_link = soup.find('a', {'aria-label': re.compile(r'next|page.*' + str(current_page + 1), re.I)})
    if next_link and next_link.get('href'):
        href = next_link['href']
        if href.startswith('/'):
            return f"https://www.realtor.com{href}"
        return href

    # Alternative: construct page URL directly
    # realtor.com format: /realestateandhomes-search/City_ST/pg-{page}
    next_page_url = f"{base_url}/pg-{current_page + 1}"

    # Check if there are more results by looking for pagination info
    pagination = soup.find(class_=re.compile(r'pagination|page-nav', re.I))
    if pagination:
        # Check if current page has results
        results_count = soup.find(string=re.compile(r'\d+\s*(results?|homes?|properties)', re.I))
        if results_count:
            return next_page_url

    return None


def collect_realtor_listings(city, state, max_pages=50, session=None, logger=None, rate_limiter=None):
    """
    Collect property listings from realtor.com for a given city

    Args:
        city: City name (e.g., 'Paonia')
        state: State abbreviation (e.g., 'CO')
        max_pages: Maximum number of pages to scrape
        session: requests.Session object
        logger: Logger instance
        rate_limiter: RateLimiter instance

    Returns:
        List of dicts: [{'url': str, 'price': int, 'city': str}, ...]
    """
    if session is None:
        session = create_session(logger)

    # Format city name for URL (replace spaces with underscores, remove special chars)
    city_formatted = city.replace(' ', '_').replace('-', '_')
    base_url = f"https://www.realtor.com/realestateandhomes-search/{city_formatted}_{state}"

    if logger:
        logger.info(f"Starting collection for {city}, {state} from {base_url}")

    all_listings = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        if rate_limiter:
            rate_limiter.wait()

        # Construct page URL
        if page == 1:
            url = base_url
        else:
            url = f"{base_url}/pg-{page}"

        if logger:
            logger.debug(f"Fetching page {page}: {url}")

        try:
            # Add referer header for more natural browsing
            headers = {'Referer': base_url if page > 1 else 'https://www.realtor.com/'}

            response = session.get(url, headers=headers, timeout=30)

            # Check for blocking/rate limiting
            if response.status_code == 403:
                if logger:
                    logger.warning(f"403 Forbidden on page {page} - possible rate limiting")
                if rate_limiter:
                    rate_limiter.record_error(is_rate_limit=True)
                break

            if response.status_code == 404:
                if logger:
                    logger.info(f"Page {page} not found - reached end of listings")
                break

            response.raise_for_status()

            if rate_limiter:
                rate_limiter.record_success()

            # Parse listings from this page
            page_listings = extract_listing_urls_from_realtor_html(response.text, logger)

            if not page_listings:
                if logger:
                    logger.info(f"No listings found on page {page} - reached end")
                break

            # Add new listings (deduplicate)
            new_count = 0
            for listing in page_listings:
                if listing['url'] not in seen_urls:
                    seen_urls.add(listing['url'])
                    listing['city'] = city  # Ensure city is set
                    all_listings.append(listing)
                    new_count += 1

            if logger:
                logger.info(f"Page {page}: {new_count} new listings (total: {len(all_listings)})")

            # If no new listings were found, we've likely seen all properties
            if new_count == 0:
                if logger:
                    logger.info(f"No new listings on page {page} - stopping")
                break

            # Small delay between pages
            time.sleep(random.uniform(1.0, 2.0))

        except requests.RequestException as e:
            if logger:
                logger.error(f"Error fetching page {page}: {str(e)}")
            if rate_limiter:
                rate_limiter.record_error()
            # Continue to next page or break depending on error
            if 'timeout' in str(e).lower():
                continue
            break

    if logger:
        logger.info(f"Collection complete for {city}, {state}: {len(all_listings)} total listings")

    return all_listings


def get_target_cities(config, logger=None):
    """
    Get list of target cities to scrape based on configuration

    Args:
        config: Configuration dict with 'realtor' section
        logger: Logger instance

    Returns:
        List of dicts: [{'city': str, 'state': str}, ...]
    """
    # For now, return the single configured city
    # Can be expanded later to support multiple cities
    realtor_config = config.get('realtor', {})

    target_city = realtor_config.get('TARGET_CITY', 'Paonia')
    target_state = realtor_config.get('TARGET_STATE', 'CO')

    cities = [{'city': target_city, 'state': target_state}]

    if logger:
        logger.info(f"Target cities: {cities}")

    return cities
