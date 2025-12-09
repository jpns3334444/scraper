#!/usr/bin/env python3
"""
Core scraping functionality for Redfin (US market)
Extracts property details from individual listing pages
Uses curl_cffi for browser impersonation to bypass bot detection
"""
import time
import random
import re
import json
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
import os

# Try to use curl_cffi for browser impersonation
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    import requests as curl_requests
    CURL_CFFI_AVAILABLE = False


def create_session(logger=None):
    """Create HTTP session with browser impersonation"""
    if CURL_CFFI_AVAILABLE:
        session = curl_requests.Session(impersonate="chrome120")
        if logger:
            logger.debug("Session created with curl_cffi Chrome 120 impersonation")
    else:
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        if logger:
            logger.warning("curl_cffi not available, using standard requests (may be blocked)")

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
    """Extract property ID from Redfin URL"""
    # Redfin URL format: /home/77583431 or /unit-4/home/193987083
    match = re.search(r'/home/(\d+)', url)
    if match:
        return match.group(1)

    # Fallback: use URL slug
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    if path_parts:
        return '_'.join(path_parts[-3:])[:100]

    return None


def create_property_id_key(raw_property_id, date_str=None):
    """Create property_id key for DynamoDB"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    return f"PROP#{date_str}_{raw_property_id}"


def extract_redfin_property_details(url, session=None, logger=None):
    """
    Extract property details from a Redfin property detail page

    Returns dict with US property fields or None on error
    """
    if session is None:
        session = create_session(logger)

    try:
        headers = {'Referer': 'https://www.redfin.com/'}
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
            property_data['redfin_id'] = raw_id

        # Extract from meta tags (most reliable for Redfin)
        meta_data = extract_redfin_meta_data(soup, logger)
        property_data.update(meta_data)

        # Extract from JSON-LD
        json_data = extract_json_ld_data(soup, logger)
        for key, value in json_data.items():
            if key not in property_data or not property_data.get(key):
                property_data[key] = value

        # Fall back to HTML parsing for missing fields
        html_data = extract_html_data(soup, logger)
        for key, value in html_data.items():
            if key not in property_data or not property_data.get(key):
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

    except Exception as e:
        if logger:
            logger.error(f"Error extracting {url}: {str(e)}")
        return {'error': str(e), 'url': url}


def extract_redfin_meta_data(soup, logger=None):
    """Extract property data from Redfin meta tags"""
    data = {}

    meta_mapping = {
        'twitter:text:price': 'price',
        'twitter:text:beds': 'beds',
        'twitter:text:baths': 'baths',
        'twitter:text:sqft': 'size_sqft',
        'twitter:text:street_address': 'address',
        'twitter:text:city': 'city',
        'twitter:text:state_code': 'state',
        'twitter:text:zip': 'zip_code',
        'twitter:text:description_simple': 'description',
        'twitter:text:listing_source': 'listing_source',
    }

    try:
        for meta_name, field in meta_mapping.items():
            meta = soup.find('meta', {'name': meta_name})
            if meta and meta.get('content'):
                content = meta['content']

                if field == 'price':
                    price_match = re.search(r'\$?([\d,]+)', content)
                    if price_match:
                        data[field] = int(price_match.group(1).replace(',', ''))
                elif field in ['beds']:
                    try:
                        data[field] = int(content)
                    except ValueError:
                        pass
                elif field in ['baths']:
                    try:
                        data[field] = float(content) if '.' in content else int(content)
                    except ValueError:
                        pass
                elif field == 'size_sqft':
                    sqft_match = re.search(r'([\d,]+)', content)
                    if sqft_match:
                        data[field] = int(sqft_match.group(1).replace(',', ''))
                elif field == 'description':
                    import html
                    data[field] = html.unescape(content)[:1000]
                else:
                    data[field] = content

        # Extract geo coordinates
        geo_meta = soup.find('meta', {'name': 'ICBM'})
        if geo_meta and geo_meta.get('content'):
            coords = geo_meta['content'].split(',')
            if len(coords) == 2:
                try:
                    data['latitude'] = float(coords[0].strip())
                    data['longitude'] = float(coords[1].strip())
                except ValueError:
                    pass

    except Exception as e:
        if logger:
            logger.debug(f"Meta extraction error: {str(e)}")

    return data


def extract_json_ld_data(soup, logger=None):
    """Extract property data from JSON-LD structured data"""
    data = {}

    try:
        script_tags = soup.find_all('script', type='application/ld+json')
        for script in script_tags:
            try:
                json_data = json.loads(script.string)

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
    if isinstance(item_type, list):
        item_types = item_type
    else:
        item_types = [item_type]

    if any(t in ['Product', 'RealEstateListing', 'Residence', 'SingleFamilyResidence', 'House'] for t in item_types):
        # Price from offers
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
            import html
            data['description'] = html.unescape(item['description'])[:1000]

        # Name/Title
        if item.get('name'):
            data['title'] = item['name']

        # Date posted and last reviewed
        if item.get('datePosted'):
            data['date_listed'] = item['datePosted']
        if item.get('lastReviewed'):
            data['date_updated'] = item['lastReviewed']

        # Parse mainEntity for more detailed property info
        main_entity = item.get('mainEntity', {})
        if isinstance(main_entity, dict):
            # Year built
            if main_entity.get('yearBuilt'):
                data['year_built'] = int(main_entity['yearBuilt'])

            # Accommodation category (property type)
            if main_entity.get('accommodationCategory'):
                data['property_type'] = main_entity['accommodationCategory']

            # Geo coordinates
            geo = main_entity.get('geo', {})
            if isinstance(geo, dict):
                if geo.get('latitude'):
                    data['latitude'] = float(geo['latitude'])
                if geo.get('longitude'):
                    data['longitude'] = float(geo['longitude'])

            # Amenities (parking, laundry, etc.)
            amenities = main_entity.get('amenityFeature', [])
            if isinstance(amenities, list):
                amenity_list = []
                for amenity in amenities:
                    if isinstance(amenity, dict) and amenity.get('name'):
                        amenity_list.append(amenity['name'])
                        # Extract parking info
                        name_lower = amenity['name'].lower()
                        if 'parking' in name_lower or 'garage' in name_lower:
                            data['parking'] = amenity['name']
                if amenity_list:
                    data['amenities'] = amenity_list

            # Extract images from mainEntity (higher quality)
            images = main_entity.get('image', [])
            if isinstance(images, list) and images:
                image_urls = []
                for img in images:
                    if isinstance(img, dict) and img.get('url'):
                        image_urls.append(img['url'])
                    elif isinstance(img, str):
                        image_urls.append(img)
                if image_urls:
                    data['image_urls'] = image_urls[:40]
                    data['image_count'] = len(image_urls)

    return data


def extract_html_data(soup, logger=None):
    """Extract property data from HTML elements"""
    data = {}

    try:
        page_text = soup.get_text(' ', strip=True).lower()

        # Year built
        year_match = re.search(r'(?:built|year built)[\s:]*(\d{4})', page_text, re.IGNORECASE)
        if year_match:
            year = int(year_match.group(1))
            if 1800 <= year <= datetime.now().year:
                data['year_built'] = year

        # Lot size in acres
        lot_match = re.search(r'([\d,\.]+)\s*(?:acre|ac)\b', page_text, re.IGNORECASE)
        if lot_match:
            try:
                acres = float(lot_match.group(1).replace(',', ''))
                if 0 < acres < 10000:  # Sanity check
                    data['lot_size_acres'] = acres
                    data['lot_size_sqft'] = int(acres * 43560)
            except ValueError:
                pass

        # Lot size in sqft (if not already set)
        if 'lot_size_sqft' not in data:
            lot_sqft_match = re.search(r'lot[\s:]*size[\s:]*[^\d]*([\d,]+)\s*(?:sq\s*ft|sqft)', page_text, re.IGNORECASE)
            if lot_sqft_match:
                try:
                    data['lot_size_sqft'] = int(lot_sqft_match.group(1).replace(',', ''))
                except ValueError:
                    pass

        # Property type
        type_patterns = [
            (r'\b(single family|single-family)\b', 'Single Family'),
            (r'\b(condo|condominium)\b', 'Condo'),
            (r'\b(townhouse|townhome)\b', 'Townhouse'),
            (r'\b(multi-?family|duplex|triplex)\b', 'Multi-Family'),
            (r'\b(land|lot|vacant)\b', 'Land'),
            (r'\b(mobile|manufactured)\b', 'Mobile'),
        ]
        for pattern, prop_type in type_patterns:
            if re.search(pattern, page_text, re.IGNORECASE):
                data['property_type'] = prop_type
                break

        # HOA fee
        hoa_match = re.search(r'hoa[\s:]*\$?([\d,]+)', page_text, re.IGNORECASE)
        if hoa_match:
            try:
                data['hoa_fee'] = int(hoa_match.group(1).replace(',', ''))
            except ValueError:
                pass

        # MLS number (look in original HTML, not lowercased)
        original_text = soup.get_text(' ', strip=True)
        mls_match = re.search(r'MLS#?\s*[:\s]?(\d+)', original_text)
        if mls_match:
            data['mls_number'] = mls_match.group(1)

        # Days on market
        dom_match = re.search(r'(\d+)\s*days?\s*on\s*redfin', page_text, re.IGNORECASE)
        if dom_match:
            try:
                data['days_on_market'] = int(dom_match.group(1))
            except ValueError:
                pass

    except Exception as e:
        if logger:
            logger.debug(f"HTML extraction error: {str(e)}")

    return data


def extract_property_images(soup, logger=None):
    """Extract property image URLs from Redfin page"""
    images = []
    seen = set()

    try:
        # Check meta tags first (most reliable)
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property')
            if name and 'image' in name.lower() and meta.get('content'):
                img_url = meta['content']
                if 'cdn-redfin.com/photo' in img_url and img_url not in seen:
                    seen.add(img_url)
                    images.append(img_url)

        # Also look for preload images
        for link in soup.find_all('link', {'rel': 'preload', 'as': 'image'}):
            href = link.get('href')
            if href and 'cdn-redfin.com/photo' in href and href not in seen:
                seen.add(href)
                images.append(href)

        # Look in image elements
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src and 'cdn-redfin.com/photo' in src and src not in seen:
                # Skip small thumbnails
                if 'bigphoto' in src or 'mbpaddedwide' in src or 'genMid' in src:
                    seen.add(src)
                    images.append(src)

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


# Backwards compatibility alias
extract_realtor_property_details = extract_redfin_property_details
