#!/usr/bin/env python3
"""
HTTP-based scraper for homes.co.jp with session management and complete data extraction
Replaces Chrome/Selenium with fast, reliable HTTP requests + session flow
"""
import time
import pandas as pd
import os
import requests
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import boto3
from datetime import datetime
import json
import threading
from queue import Queue, Empty
from enum import Enum
from typing import Optional, Dict, Any, List
import urllib.parse
import io
import argparse
import logging
from PIL import Image
from decimal import Decimal

# Enhanced browser profiles for stealth mode
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
    },
    {
        "name": "Safari_Mac",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
            "Accept-Language": "ja-jp",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
    },
    {
        "name": "Firefox_Windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
    }
]

# Entry points for behavioral mimicry
ENTRY_POINTS = {
    "default": "/mansion/chuko/tokyo/chofu-city/list/",
    "list_page_1": "/mansion/chuko/tokyo/chofu-city/list/",
    "list_page_2": "/mansion/chuko/tokyo/chofu-city/list/?page=2",
    "list_page_3": "/mansion/chuko/tokyo/chofu-city/list/?page=3",
    "list_page_4": "/mansion/chuko/tokyo/chofu-city/list/?page=4",
    "search_query": "/search/?q=マンション+調布&area=tokyo",
    "price_sort": "/mansion/chuko/tokyo/chofu-city/list/?sort=price_asc",
    "area_search": "/mansion/chuko/tokyo/chofu-city/list/?area_detail=1"
}

# Search queries for behavioral simulation
SEARCH_QUERIES = [
    "マンション 調布",
    "中古マンション 調布市",
    "調布 マンション 価格",
    "調布駅 マンション",
    "調布市 住宅"
]

# Legacy user agents for compatibility
USER_AGENTS = [profile["headers"]["User-Agent"] for profile in BROWSER_PROFILES]


class CircuitBreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ErrorCategory(Enum):
    NETWORK = "NETWORK"
    HTTP_ERROR = "HTTP_ERROR"
    ANTI_BOT = "ANTI_BOT"
    PARSING = "PARSING"
    VALIDATION = "VALIDATION"
    UNKNOWN = "UNKNOWN"


class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60, success_threshold=3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
        self.lock = threading.Lock()
        
    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        # Check state and decide whether to proceed
        with self.lock:
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0  # Reset success count for half-open state
                    if 'logger' in globals() and logger:
                        log_structured_message(logger, "INFO", "Circuit breaker transitioning to HALF_OPEN")
                    # Allow this thread to proceed in HALF_OPEN state
                    should_proceed = True
                else:
                    raise Exception("Circuit breaker is OPEN - refusing request")
            elif self.state == CircuitBreakerState.HALF_OPEN:
                # In HALF_OPEN state, only allow limited concurrent requests
                # For safety, we'll be conservative and allow sequential testing
                should_proceed = True
            else:
                # CLOSED state - allow request
                should_proceed = True
        
        # Execute the function outside the lock but track result atomically
        if should_proceed:
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except Exception as e:
                self._on_failure()
                raise e
    
    def _should_attempt_reset(self):
        """Check if circuit breaker should attempt reset (must be called within lock)"""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.recovery_timeout
    
    def _on_success(self):
        """Handle successful request"""
        with self.lock:
            self.failure_count = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = CircuitBreakerState.CLOSED
                    self.success_count = 0
                    if 'logger' in globals() and logger:
                        log_structured_message(logger, "INFO", "Circuit breaker reset to CLOSED")
            elif self.state == CircuitBreakerState.CLOSED:
                # Reset success count for closed state
                self.success_count = 0
    
    def _on_failure(self):
        """Handle failed request"""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                if 'logger' in globals() and logger:
                    log_structured_message(logger, "WARNING", "Circuit breaker opened from HALF_OPEN state")
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                if 'logger' in globals() and logger:
                    log_structured_message(logger, "WARNING", "Circuit breaker opened", 
                                         failure_count=self.failure_count,
                                         threshold=self.failure_threshold)
    
    def get_state(self):
        """Get current circuit breaker state"""
        return self.state


class SessionPool:
    def __init__(self, pool_size=3, max_age_seconds=300, stealth_mode=False, logger=None):
        self.pool = Queue(maxsize=pool_size)
        self.pool_size = pool_size
        self.max_age_seconds = max_age_seconds
        self.lock = threading.Lock()
        self.session_metadata = {}
        self.stealth_mode = stealth_mode
        self.logger = logger
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the session pool with fresh sessions"""
        for _ in range(self.pool_size):
            session = self._create_fresh_session(self.stealth_mode, self.logger)
            self.pool.put(session)
    
    def _create_fresh_session(self, stealth_mode=False, logger=None):
        """Create a new session with metadata tracking"""
        session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
        session_id = id(session)
        self.session_metadata[session_id] = {
            'created_at': time.time(),
            'request_count': 0,
            'last_used': time.time(),
            'stealth_mode': stealth_mode
        }
        return session
    
    def get_session(self, timeout=5):
        """Get a session from the pool"""
        try:
            session = self.pool.get(timeout=timeout)
            session_id = id(session)
            
            # Check if session is too old
            if session_id in self.session_metadata:
                age = time.time() - self.session_metadata[session_id]['created_at']
                if age > self.max_age_seconds:
                    session.close()
                    session = self._create_fresh_session()
                    session_id = id(session)
                
                self.session_metadata[session_id]['last_used'] = time.time()
                self.session_metadata[session_id]['request_count'] += 1
            
            return session
        except Empty:
            if self.logger:
                log_structured_message(self.logger, "WARNING", "Session pool exhausted, creating new session")
            return self._create_fresh_session()
    
    def return_session(self, session):
        """Return a session to the pool"""
        try:
            self.pool.put(session, timeout=1)
        except:
            # Pool is full, close the session
            session.close()
            session_id = id(session)
            if session_id in self.session_metadata:
                del self.session_metadata[session_id]
    
    def close_all(self):
        """Close all sessions in the pool"""
        while not self.pool.empty():
            try:
                session = self.pool.get_nowait()
                session.close()
            except Empty:
                break
        
        for session_id in list(self.session_metadata.keys()):
            del self.session_metadata[session_id]


def categorize_error(error, response=None):
    """Categorize error for better handling and reporting"""
    error_str = str(error).lower()
    
    if isinstance(error, requests.exceptions.ConnectionError):
        return ErrorCategory.NETWORK
    elif isinstance(error, requests.exceptions.Timeout):
        return ErrorCategory.NETWORK
    elif isinstance(error, requests.exceptions.HTTPError):
        return ErrorCategory.HTTP_ERROR
    elif "pardon our interruption" in error_str:
        return ErrorCategory.ANTI_BOT
    elif "anti-bot" in error_str or "protection" in error_str:
        return ErrorCategory.ANTI_BOT
    elif "parsing" in error_str or "beautifulsoup" in error_str:
        return ErrorCategory.PARSING
    elif "validation" in error_str:
        return ErrorCategory.VALIDATION
    else:
        return ErrorCategory.UNKNOWN


def create_stealth_session(stealth_mode=False, logger=None):
    """Create HTTP session with stealth capabilities and browser fingerprint variation"""
    session = requests.Session()
    
    if stealth_mode:
        # Use varied browser profile for stealth mode
        profile = random.choice(BROWSER_PROFILES)
        base_headers = profile["headers"].copy()
        
        # Add common headers
        base_headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
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
        
        # Add Chrome-specific headers if it's a Chrome profile
        if "Chrome" in profile["name"]:
            base_headers.update({
                'sec-ch-ua-mobile': '?0',
                'sec-ch-viewport-width': str(random.choice([1920, 1366, 1536, 1440, 1280])),
                'sec-ch-prefers-color-scheme': random.choice(['light', 'dark'])
            })
        
        # Vary some headers for uniqueness
        if random.random() < 0.3:  # 30% chance to add optional headers
            base_headers['X-Requested-With'] = 'XMLHttpRequest' if random.random() < 0.1 else None
            
        session.headers.update(base_headers)
        
        # Log session creation
        if logger:
            logger.info(json.dumps({
                "message": "Stealth session created",
                "profile": profile["name"],
                "user_agent": base_headers["User-Agent"][:50] + "..."
            }))
    else:
        # Legacy mode for compatibility
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        }
        session.headers.update(headers)
    
    return session

# Legacy function for backward compatibility
def create_enhanced_session():
    """Legacy function - use create_stealth_session instead"""
    return create_stealth_session(stealth_mode=False)


# Behavioral mimicry functions for stealth mode
def simulate_human_reading_time():
    """Simple respectful delay for property details"""
    return random.uniform(0.5, 2.0)

def simulate_navigation_delay():
    """Simple respectful navigation delay"""
    return random.uniform(0.5, 1.5)



def check_detection_indicators(response_times, error_count, total_requests):
    """Check for potential detection indicators"""
    indicators = []
    risk_level = "LOW"
    
    if not response_times:
        return "UNKNOWN", ["No response time data available"]
    
    avg_response_time = sum(response_times) / len(response_times)
    error_rate = error_count / max(total_requests, 1)
    
    # Check for unusually fast responses (possible caching/detection)
    if avg_response_time < 0.5:
        indicators.append(f"Unusually fast responses: {avg_response_time:.2f}s average")
        risk_level = "MEDIUM"
    
    # Check for high error rates
    if error_rate > 0.3:
        indicators.append(f"High error rate: {error_rate:.1%}")
        risk_level = "HIGH"
    elif error_rate > 0.15:
        indicators.append(f"Elevated error rate: {error_rate:.1%}")
        if risk_level == "LOW":
            risk_level = "MEDIUM"
    
    # Check for response time patterns that might indicate throttling
    if len(response_times) > 5:
        recent_times = response_times[-5:]
        early_times = response_times[:5]
        
        if len(early_times) > 0 and len(recent_times) > 0:
            early_avg = sum(early_times) / len(early_times)
            recent_avg = sum(recent_times) / len(recent_times)
            
            # If recent responses are significantly slower, might indicate throttling
            if recent_avg > early_avg * 2:
                indicators.append(f"Response time degradation: {early_avg:.2f}s → {recent_avg:.2f}s")
                if risk_level == "LOW":
                    risk_level = "MEDIUM"
    
    if not indicators:
        indicators.append("No detection indicators found")
    
    return risk_level, indicators

def send_detection_metrics(risk_level, indicators, stealth_config=None):
    """Send detection risk metrics to CloudWatch"""
    try:
        cloudwatch = boto3.client('cloudwatch')
        
        # Convert risk level to numeric value
        risk_values = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "UNKNOWN": 0}
        risk_value = risk_values.get(risk_level, 0)
        
        session_id = stealth_config.get('session_id', 'unknown') if stealth_config else 'standard'
        
        metric_data = [
            {
                'MetricName': 'DetectionRiskLevel',
                'Value': risk_value,
                'Unit': 'Count',
                'Dimensions': [
                    {
                        'Name': 'SessionId',
                        'Value': session_id
                    },
                    {
                        'Name': 'RiskLevel',
                        'Value': risk_level
                    }
                ]
            },
            {
                'MetricName': 'DetectionIndicatorCount',
                'Value': len(indicators),
                'Unit': 'Count',
                'Dimensions': [
                    {
                        'Name': 'SessionId',
                        'Value': session_id
                    }
                ]
            }
        ]
        
        cloudwatch.put_metric_data(
            Namespace='StealthDetectionMetrics',
            MetricData=metric_data
        )
        
        if 'logger' in globals() and logger:
            log_structured_message(logger, "INFO", "Detection metrics sent", 
                                 risk_level=risk_level, 
                                 indicators_count=len(indicators),
                                 session_id=session_id)
        
    except Exception as e:
        if 'logger' in globals() and logger:
            log_structured_message(logger, "ERROR", "Failed to send detection metrics", error=str(e))

def discover_tokyo_areas(stealth_mode=False, logger=None):
    """Discover all Tokyo area URLs from the city listing page"""
    session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
    
    city_listing_url = "https://www.homes.co.jp/mansion/chuko/tokyo/city/"
    
    try:
        if logger:
            log_structured_message(logger, "INFO", "Discovering Tokyo areas", url=city_listing_url)
        
        response = session.get(city_listing_url, timeout=15)
        if response.status_code != 200:
            raise Exception(f"Failed to access city listing: HTTP {response.status_code}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all area links - looking for links that match the pattern
        area_links = []
        
        # Look for links that contain "/mansion/chuko/tokyo/" and end with "/list"
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/mansion/chuko/tokyo/' in href and href.endswith('/list/'):
                # Extract the area part from the URL
                area_part = href.split('/mansion/chuko/tokyo/')[-1].replace('/list/', '')
                if area_part and area_part != 'city':
                    area_links.append(area_part)
        
        # Also look for city/ward names in text and construct URLs
        # This is a fallback in case direct links aren't found
        if not area_links:
            # Look for common Tokyo ward/city patterns
            text_content = soup.get_text()
            
            # Common Tokyo areas (fallback list)
            known_areas = [
                'shibuya-ku', 'shinjuku-ku', 'minato-ku', 'chiyoda-ku', 'chuo-ku',
                'setagaya-ku', 'nerima-ku', 'suginami-ku', 'nakano-ku', 'itabashi-ku',
                'koto-ku', 'sumida-ku', 'taito-ku', 'arakawa-ku', 'adachi-ku',
                'katsushika-ku', 'edogawa-ku', 'ota-ku', 'shinagawa-ku', 'meguro-ku',
                'shibuya-ku', 'bunkyo-ku', 'toshima-ku',
                'chofu-city', 'mitaka-city', 'musashino-city', 'tachikawa-city',
                'hachioji-city', 'fuchu-city', 'machida-city', 'koganei-city',
                'kodaira-city', 'hino-city', 'higashimurayama-city', 'kunitachi-city'
            ]
            
            # Validate which areas actually exist by testing URLs
            if logger:
                log_structured_message(logger, "INFO", "Using fallback area list, validating URLs")
            for area in known_areas:
                test_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{area}/list/"
                try:
                    test_response = session.head(test_url, timeout=10)
                    if test_response.status_code == 200:
                        area_links.append(area)
                        time.sleep(1)  # Small delay between validation requests
                except:
                    continue
        
        # Remove duplicates and sort
        unique_areas = sorted(list(set(area_links)))
        
        # Filter out invalid area names
        valid_areas = []
        for area in unique_areas:
            # Skip invalid patterns
            if (area and
                not area.endswith('/') and
                not area.startswith('list') and
                len(area) > 2 and
                not any(char in area for char in ['?', '&', '=', '#'])):
                valid_areas.append(area)
        
        if logger:
            log_structured_message(logger, "INFO", "Tokyo areas discovered", 
                                 total_areas=len(valid_areas), 
                                 filtered_out=len(unique_areas) - len(valid_areas),
                                 areas=valid_areas[:10])  # Log first 10 for brevity
        
        return valid_areas
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Failed to discover Tokyo areas", error=str(e))
        
        # Return fallback list if discovery fails
        fallback_areas = [
            'chofu-city', 'shibuya-ku', 'shinjuku-ku', 'setagaya-ku', 
            'minato-ku', 'chiyoda-ku', 'nerima-ku', 'suginami-ku'
        ]
        if logger:
            log_structured_message(logger, "WARNING", "Using fallback area list", areas=fallback_areas)
        return fallback_areas
    
    finally:
        session.close()

def get_daily_area_distribution(all_areas, session_id, date_key):
    """Distribute areas across sessions with daily randomization"""
    import hashlib
    
    # Create deterministic seed from date to ensure same distribution per day
    seed_string = f"{date_key}-tokyo-areas"
    seed = int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)
    
    # Set random seed for consistent daily distribution
    random.seed(seed)
    shuffled_areas = all_areas.copy()
    random.shuffle(shuffled_areas)
    
    # Define session order
    session_order = [
        'morning-1', 'morning-2', 'afternoon-1', 'afternoon-2',
        'evening-1', 'evening-2', 'night-1', 'night-2'
    ]
    
    # Distribute areas across sessions
    areas_per_session = len(shuffled_areas) // len(session_order)
    remainder = len(shuffled_areas) % len(session_order)
    
    session_areas = {}
    area_index = 0
    
    for i, session in enumerate(session_order):
        # Some sessions get one extra area if there's a remainder
        session_area_count = areas_per_session + (1 if i < remainder else 0)
        session_areas[session] = shuffled_areas[area_index:area_index + session_area_count]
        area_index += session_area_count
    
    # Get areas for the requested session
    assigned_areas = session_areas.get(session_id, [])
    
    if 'logger' in globals() and logger:
        log_structured_message(logger, "INFO", "Daily area distribution calculated", 
                             session_id=session_id, 
                             date_key=date_key,
                             assigned_areas=assigned_areas,
                             total_sessions=len(session_order),
                             total_areas=len(all_areas))
    
    return assigned_areas

def get_scraper_config(args):
    """Get scraper configuration from command line arguments"""
    areas = [area.strip() for area in args.areas.split(',') if area.strip()] if args.areas else []
    
    # Determine stealth mode - either explicit stealth mode or if mode is 'stealth'
    stealth_mode = args.mode == 'stealth'
    
    # Full-load mode overrides some settings
    full_load_mode = args.full_load or args.mode == 'full-load'
    
    # In full-load mode, always enable deduplication unless explicitly disabled
    enable_deduplication = args.check_duplicates if hasattr(args, 'check_duplicates') else True
    if full_load_mode and not hasattr(args, 'check_duplicates'):
        enable_deduplication = True
    
    return {
        'session_id': os.environ.get('SESSION_ID', f'session-{int(time.time())}'),
        'max_properties': args.max_properties,
        'entry_point': os.environ.get('ENTRY_POINT', 'default'),
        'stealth_mode': stealth_mode,
        'mode': args.mode,
        'areas': areas,
        'max_threads': args.max_threads,
        'output_bucket': args.output_bucket,
        # Full-load specific settings
        'full_load_mode': full_load_mode,
        'enable_deduplication': enable_deduplication,
        'track_price_changes': args.track_price_changes if hasattr(args, 'track_price_changes') else True,
        'batch_size': min(args.batch_size, 25) if hasattr(args, 'batch_size') else 25,  # DynamoDB limit
        'dynamodb_table': args.dynamodb_table if hasattr(args, 'dynamodb_table') else 'tokyo-real-estate-ai-RealEstateAnalysis'
    }

# Backward compatibility alias
def get_stealth_session_config(args):
    """Backward compatibility alias for get_scraper_config"""
    return get_scraper_config(args)

# Global circuit breaker instance
circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
# Session pool will be initialized in main()


def extract_listing_urls_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    relative_urls = re.findall(r'/mansion/b-\d+/?', html_content)
    unique_listings = set()
    
    for url in relative_urls:
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        unique_listings.add(absolute_url)
    
    return list(unique_listings)

def extract_listings_with_metadata_from_html(html_content):
    """Extract listing URLs with metadata (including prices) from HTML content
    
    Note: This function attempts to extract prices from listing pages.
    If prices are not available on listing pages, it returns URLs with empty metadata.
    """
    from bs4 import BeautifulSoup
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        listings = []
        
        # Find all listing links
        relative_urls = re.findall(r'/mansion/b-\d+/?', html_content)
        
        for url in relative_urls:
            absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
            
            # Try to extract price from the listing context
            # This is a best-effort approach - prices might not be available on listing pages
            listing_metadata = {
                'url': absolute_url,
                'price': None,
                'price_display': None,
                'title': None
            }
            
            # Look for price patterns near the URL in the HTML
            # Pattern 1: Look for price in万円 format around the URL
            url_context_pattern = f"{re.escape(url)}.*?(\\d{{1,4}}(?:,\\d{{3}})*万円)"
            price_match = re.search(url_context_pattern, html_content, re.DOTALL)
            if not price_match:
                # Pattern 2: Look backwards from the URL
                reverse_pattern = f"(\\d{{1,4}}(?:,\\d{{3}})*万円).*?{re.escape(url)}"
                price_match = re.search(reverse_pattern, html_content, re.DOTALL)
            
            if price_match:
                price_text = price_match.group(1)
                try:
                    price_num = int(price_text.replace('万円', '').replace(',', '')) * 10000
                    listing_metadata['price'] = price_num
                    listing_metadata['price_display'] = price_text
                except ValueError:
                    pass
            
            listings.append(listing_metadata)
        
        # Remove duplicates based on URL
        seen_urls = set()
        unique_listings = []
        for listing in listings:
            if listing['url'] not in seen_urls:
                seen_urls.add(listing['url'])
                unique_listings.append(listing)
        
        return unique_listings
        
    except Exception as e:
        # Fallback to URL-only extraction if metadata extraction fails
        return [{'url': url, 'price': None, 'price_display': None, 'title': None} 
                for url in extract_listing_urls_from_html(html_content)]

def collect_area_listing_urls_efficient(area_name, existing_properties=None, max_pages=None, session=None, stealth_config=None, logger=None):
    """Efficiently collect listing URLs from a specific Tokyo area with price checking during collection"""
    base_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{area_name}/list"
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    
    # Use provided session or create new one
    if session is None:
        session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
        should_close_session = True
    else:
        should_close_session = False
    
    # Initialize result containers
    new_urls = []
    price_changed_urls = []
    price_unchanged_urls = []
    existing_properties = existing_properties or {}
    
    # Create metadata lookup for new URLs
    metadata_lookup = {}
    
    if logger:
        log_structured_message(logger, "INFO", "Starting efficient area URL collection", 
                             area=area_name, base_url=base_url, stealth_mode=stealth_mode,
                             existing_properties_count=len(existing_properties))
    
    try:
        # Step 1: Get page 1 to establish session
        if logger:
            logger.info(f"=== Efficiently collecting from {area_name} (page 1) ===")
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
        
        # Set reasonable upper limit to prevent infinite loops, but allow all pages
        max_page = min(total_pages, max_pages) if max_pages else total_pages
        
        # Log if we're limiting pages
        if max_pages and total_pages > max_pages:
            if logger:
                log_structured_message(logger, "INFO", "Page limit applied", 
                                     area=area_name, total_pages=total_pages, max_pages=max_pages)
        
        if logger:
            log_structured_message(logger, "INFO", "Area pagination info parsed", 
                                 area=area_name, total_listings=total_count, 
                                 total_pages=total_pages, max_page=max_page)
        
        # Extract listings with metadata from page 1
        page1_listings = extract_listings_with_metadata_from_html(response.text)
        
        # Store metadata for all listings from page 1
        for listing in page1_listings:
            metadata_lookup[listing['url']] = listing
        
        # Process page 1 listings
        page1_new, page1_changed, page1_unchanged = process_listings_with_existing_check(
            page1_listings, existing_properties, logger)
        
        new_urls.extend(page1_new)
        price_changed_urls.extend(page1_changed)
        price_unchanged_urls.extend(page1_unchanged)
        
        if logger:
            logger.info(f"{area_name} page 1: Found {len(page1_listings)} listings "
                       f"(new: {len(page1_new)}, changed: {len(page1_changed)}, unchanged: {len(page1_unchanged)})")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages with stealth timing
        for page_num in range(2, max_page + 1):
            if logger:
                logger.info(f"=== Efficiently collecting from {area_name} (page {page_num}) ===")
            
            # Simple respectful delay
            time.sleep(random.uniform(0.1, 0.3))
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    if logger:
                        log_structured_message(logger, "WARNING", "Failed to access area page", 
                                             area=area_name, page=page_num, status_code=response.status_code)
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    if logger:
                        log_structured_message(logger, "ERROR", "Anti-bot protection triggered", 
                                             area=area_name, page=page_num)
                    break
                
                # Extract listings with metadata from this page
                page_listings = extract_listings_with_metadata_from_html(response.text)
                
                # Store metadata for all listings from this page
                for listing in page_listings:
                    metadata_lookup[listing['url']] = listing
                
                # Process listings
                page_new, page_changed, page_unchanged = process_listings_with_existing_check(
                    page_listings, existing_properties, logger)
                
                new_urls.extend(page_new)
                price_changed_urls.extend(page_changed)
                price_unchanged_urls.extend(page_unchanged)
                
                if logger:
                    logger.info(f"{area_name} page {page_num}: Found {len(page_listings)} listings "
                               f"(new: {len(page_new)}, changed: {len(page_changed)}, unchanged: {len(page_unchanged)})")
                
                session.headers['Referer'] = page_url
                if logger:
                    log_structured_message(logger, "INFO", "Area page scraped successfully", 
                                         area=area_name, page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                if logger:
                    log_structured_message(logger, "ERROR", "Error fetching area page", 
                                         area=area_name, page=page_num, error=str(e))
                continue
        
        total_listings = len(new_urls) + len(price_changed_urls) + len(price_unchanged_urls)
        if logger:
            log_structured_message(logger, "INFO", "Efficient area URL collection completed", 
                                 area=area_name, total_listings=total_listings,
                                 new_urls=len(new_urls), price_changed=len(price_changed_urls),
                                 price_unchanged=len(price_unchanged_urls))
        
        return {
            'new_urls': new_urls,
            'price_changed_urls': price_changed_urls,
            'price_unchanged_urls': price_unchanged_urls,
            'metadata_lookup': metadata_lookup,
            'session': session if not should_close_session else None
        }
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Failed to collect area URLs efficiently", 
                                 area=area_name, error=str(e))
        raise
    finally:
        if should_close_session and session:
            session.close()

def process_listings_with_existing_check(listings_with_metadata, existing_properties, logger=None):
    """Process listings to categorize them as new, price changed, or unchanged"""
    new_urls = []
    price_changed_urls = []
    price_unchanged_urls = []
    
    for listing in listings_with_metadata:
        url = listing['url']
        current_price = listing.get('price')
        
        # Extract property ID from URL
        raw_property_id = extract_property_id_from_url(url)
        if not raw_property_id:
            # If we can't extract property ID, treat as new
            new_urls.append(url)
            continue
        
        # Check if property exists
        if raw_property_id in existing_properties:
            existing_record = existing_properties[raw_property_id]
            existing_price = existing_record.get('price', 0)
            
            # Compare prices if both are available
            if current_price is not None and existing_price > 0:
                if current_price != existing_price:
                    # Price changed
                    price_changed_urls.append({
                        'url': url,
                        'existing_record': existing_record,
                        'current_metadata': listing,
                        'price_change': {
                            'old_price': existing_price,
                            'new_price': current_price,
                            'change_amount': current_price - existing_price,
                            'change_percent': ((current_price - existing_price) / existing_price) * 100 if existing_price > 0 else 0
                        }
                    })
                else:
                    # Price unchanged
                    price_unchanged_urls.append(url)
            else:
                # Can't compare prices, but property exists - treat as unchanged unless we need to re-scrape
                price_unchanged_urls.append(url)
        else:
            # New property
            new_urls.append(url)
    
    return new_urls, price_changed_urls, price_unchanged_urls

def collect_area_listing_urls(area_name, max_pages=None, session=None, stealth_config=None, logger=None):
    """Collect listing URLs from a specific Tokyo area"""
    base_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{area_name}/list"
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    
    # Use provided session or create new one
    if session is None:
        session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
        should_close_session = True
    else:
        should_close_session = False
    
    all_links = set()
    
    if logger:
        log_structured_message(logger, "INFO", "Starting area URL collection", 
                             area=area_name, base_url=base_url, stealth_mode=stealth_mode)
    
    try:
        # Step 1: Get page 1 to establish session
        if logger:
            logger.info(f"=== Collecting from {area_name} (page 1) ===")
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
        
        # Set reasonable upper limit to prevent infinite loops, but allow all pages
        max_page = min(total_pages, max_pages) if max_pages else total_pages
        
        # Log if we're limiting pages
        if max_pages and total_pages > max_pages:
            if logger:
                log_structured_message(logger, "INFO", "Page limit applied", 
                                     area=area_name, total_pages=total_pages, max_pages=max_pages)
        
        if logger:
            log_structured_message(logger, "INFO", "Area pagination info parsed", 
                                 area=area_name, total_listings=total_count, 
                                 total_pages=total_pages, max_page=max_page)
        
        # Extract listings from page 1
        page1_listings = extract_listing_urls_from_html(response.text)
        all_links.update(page1_listings)
        if logger:
            logger.info(f"{area_name} page 1: Found {len(page1_listings)} listings")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages with stealth timing
        for page_num in range(2, max_page + 1):
            if logger:
                logger.info(f"=== Collecting from {area_name} (page {page_num}) ===")
            
            # Simple respectful delay
            time.sleep(random.uniform(0.1, 0.3))
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    if logger:
                        log_structured_message(logger, "WARNING", "Failed to access area page", 
                                             area=area_name, page=page_num, status_code=response.status_code)
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    if logger:
                        log_structured_message(logger, "ERROR", "Anti-bot protection triggered", 
                                             area=area_name, page=page_num)
                    break
                
                page_listings = extract_listing_urls_from_html(response.text)
                all_links.update(page_listings)
                if logger:
                    logger.info(f"{area_name} page {page_num}: Found {len(page_listings)} listings")
                
                session.headers['Referer'] = page_url
                if logger:
                    log_structured_message(logger, "INFO", "Area page scraped successfully", 
                                         area=area_name, page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                if logger:
                    log_structured_message(logger, "ERROR", "Error fetching area page", 
                                         area=area_name, page=page_num, error=str(e))
                continue
        
        area_links_list = list(all_links)
        if logger:
            log_structured_message(logger, "INFO", "Area URL collection completed", 
                                 area=area_name, total_unique_links=len(area_links_list))
        
        return area_links_list
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Error in area URL collection", area=area_name, error=str(e))
        return []
    
    finally:
        if should_close_session:
            session.close()

def collect_multiple_areas_urls(areas, stealth_config=None, logger=None, max_urls=None):
    """Collect listing URLs from multiple Tokyo areas in one session"""
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
    all_urls = []
    
    if logger:
        log_structured_message(logger, "INFO", "Starting multi-area URL collection", 
                             areas=areas, total_areas=len(areas), stealth_mode=stealth_mode, max_urls=max_urls)
    
    try:
        # Simulate search behavior once at the beginning in stealth mode
        
        for i, area in enumerate(areas):
            progress_pct = ((i + 1) / len(areas)) * 100
            if logger:
                logger.info(f"\n=== [{progress_pct:.1f}%] Processing area {i+1}/{len(areas)}: {area} ===")
            
            # Simple area transition delay
            if i > 0:
                time.sleep(random.uniform(0.1, 0.3))
            
            # Collect ALL pages from this area (no limit)
            area_start_time = time.time()
            area_urls = collect_area_listing_urls(area, max_pages=None, session=session, stealth_config=stealth_config, logger=logger)
            area_duration = time.time() - area_start_time
            all_urls.extend(area_urls)
            
            if logger:
                logger.info(f"✅ Area {area}: {len(area_urls)} URLs in {area_duration:.1f}s (Total: {len(all_urls)})")
                
                # Check if we've reached the max_urls limit
                if max_urls and len(all_urls) >= max_urls:
                    logger.info(f"🚀 Reached max URLs limit ({max_urls}), stopping collection early")
                    all_urls = all_urls[:max_urls]  # Trim to exact limit
                    break
                
                # Show ETA for remaining areas
                if i < len(areas) - 1:
                    avg_time_per_area = area_duration
                    remaining_areas = len(areas) - (i + 1)
                    eta_seconds = remaining_areas * avg_time_per_area
                    eta_minutes = eta_seconds / 60
                    logger.info(f"📊 Progress: {len(all_urls)} URLs collected, ~{eta_minutes:.1f} minutes remaining")
        
        # Apply browsing patterns in stealth mode
        
        if logger:
            log_structured_message(logger, "INFO", "Multi-area URL collection completed", 
                                 total_areas=len(areas), total_urls=len(all_urls), stealth_mode=stealth_mode)
        
        return all_urls, session
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Error in multi-area URL collection", error=str(e))
        session.close()
        raise

def collect_urls_with_deduplication(areas, stealth_config=None, enable_dedup=True, logger=None):
    """Efficient URL collection with deduplication and metadata extraction"""
    if not enable_dedup:
        # Fall back to standard collection if deduplication is disabled
        if len(areas) > 1:
            return collect_multiple_areas_urls(areas, stealth_config, logger)
        else:
            base_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{areas[0]}/list"
            return collect_all_listing_urls(base_url, None, stealth_config, logger)
    
    # Enhanced collection with deduplication using new efficient flow
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    
    if logger:
        logger.info(f"🚀 Starting efficient URL collection with deduplication for {len(areas)} areas")
    
    try:
        # Setup DynamoDB connection
        dynamodb, table = setup_dynamodb_client(logger)
        
        # Step 1: Load all existing properties from DynamoDB into memory for O(1) lookups
        existing_properties = load_all_existing_properties(table, logger)
        
        # Step 2: Collect URLs and perform price checking during collection
        session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
        
        all_new_urls = []
        all_price_changed_urls = []
        all_price_unchanged_urls = []
        all_metadata_lookup = {}
        
        # Simulate search behavior once at the beginning in stealth mode
        
        for i, area in enumerate(areas):
            progress_pct = ((i + 1) / len(areas)) * 100
            if logger:
                logger.info(f"\n=== [{progress_pct:.1f}%] Efficiently processing area {i+1}/{len(areas)}: {area} ===")
            
            # Simple area transition delay
            if i > 0:
                time.sleep(random.uniform(0.1, 0.3))
            
            # Efficiently collect URLs with price checking for this area
            area_start_time = time.time()
            area_result = collect_area_listing_urls_efficient(
                area, existing_properties, max_pages=None, session=session, 
                stealth_config=stealth_config, logger=logger)
            area_duration = time.time() - area_start_time
            
            # Aggregate results
            all_new_urls.extend(area_result['new_urls'])
            all_price_changed_urls.extend(area_result['price_changed_urls'])
            all_price_unchanged_urls.extend(area_result['price_unchanged_urls'])
            
            # Merge metadata lookup
            all_metadata_lookup.update(area_result['metadata_lookup'])
            
            total_area_listings = len(area_result['new_urls']) + len(area_result['price_changed_urls']) + len(area_result['price_unchanged_urls'])
            if logger:
                logger.info(f"✅ Area {area}: {total_area_listings} URLs in {area_duration:.1f}s "
                           f"(new: {len(area_result['new_urls'])}, changed: {len(area_result['price_changed_urls'])}, unchanged: {len(area_result['price_unchanged_urls'])})")
                
                # Show ETA for remaining areas
                if i < len(areas) - 1:
                    avg_time_per_area = area_duration
                    remaining_areas = len(areas) - (i + 1)
                    eta_seconds = remaining_areas * avg_time_per_area
                    eta_minutes = eta_seconds / 60
                    total_processed = len(all_new_urls) + len(all_price_changed_urls) + len(all_price_unchanged_urls)
                    logger.info(f"📊 Progress: {total_processed} URLs processed, ~{eta_minutes:.1f} minutes remaining")
        
        # Apply browsing patterns in stealth mode for new URLs only
        
        # Step 3: Process price changes in DynamoDB if any were found
        if all_price_changed_urls:
            if logger:
                logger.info(f"💰 Updating {len(all_price_changed_urls)} listings with price changes...")
            
            for item in all_price_changed_urls:
                update_listing_with_price_change(
                    item['existing_record'], 
                    item['current_metadata'], 
                    table, 
                    logger
                )
        
        # Step 4: Create discovery records for truly new listings
        if all_new_urls:
            if logger:
                logger.info(f"✨ Creating discovery records for {len(all_new_urls)} new listings...")
            
            # Create discovery records using metadata already extracted from listing pages
            discovery_start = time.time()
            processed_property_ids = set()  # Prevent duplicate property IDs
            with table.batch_writer() as batch:
                batch_count = 0
                for idx, url in enumerate(all_new_urls):
                    progress_pct = ((idx + 1) / len(all_new_urls)) * 100
                    
                    # Log progress every 25 items or at key milestones
                    if (idx + 1) % 25 == 0 or idx == 0 or idx == len(all_new_urls) - 1:
                        elapsed = time.time() - discovery_start
                        rate = (idx + 1) / elapsed if elapsed > 0 else 0
                        eta = (len(all_new_urls) - (idx + 1)) / rate if rate > 0 else 0
                        if logger:
                            logger.info(f"✨ [{progress_pct:.1f}%] Discovery progress: {idx+1}/{len(all_new_urls)} (~{eta/60:.1f}min remaining)")
                    
                    # Use metadata from lookup if available
                    listing_metadata = all_metadata_lookup.get(url, {})
                    
                    # Extract property ID from URL
                    raw_property_id = extract_property_id_from_url(url)
                    if raw_property_id:
                        property_id = create_property_id_key(raw_property_id)
                        # Create record with data we already have from listing page
                        record = {
                            'property_id': property_id,
                            'sort_key': 'META',
                            'listing_url': url,
                            'listing_status': 'discovered',
                            'analysis_date': datetime.now().isoformat(),
                            'price': listing_metadata.get('price', 0),
                            'price_display': listing_metadata.get('price_display', ''),
                            'title': listing_metadata.get('title', ''),
                            'data_source': 'scraper_discovery_fast'
                        }
                        
                        # Validate record and required keys before writing to DynamoDB
                        if record.get('property_id') and record.get('sort_key'):
                            # Skip if property_id already processed to prevent duplicates
                            if property_id in processed_property_ids:
                                continue
                            processed_property_ids.add(property_id)
                            
                            batch.put_item(Item=record)
                            batch_count += 1
                        else:
                            if logger:
                                logger.warning(f"Skipping record with missing keys: property_id={property_id}, url={url}")
                        
                        # Batch limit management
                        if batch_count % 25 == 0:
                            if logger:
                                logger.info(f"💾 Saved {batch_count} discovery records to DynamoDB")
                    else:
                        if logger:
                            logger.warning(f"Could not extract property ID from URL: {url}")
        
        # Step 5: Log summary
        total_processed = len(all_new_urls) + len(all_price_changed_urls) + len(all_price_unchanged_urls)
        summary = {
            'total_urls_found': total_processed,
            'existing_listings': len(all_price_changed_urls) + len(all_price_unchanged_urls),
            'new_listings': len(all_new_urls),
            'price_changed': len(all_price_changed_urls),
            'price_unchanged': len(all_price_unchanged_urls),
            'processed_for_full_scraping': len(all_new_urls)  # Only new URLs need full scraping
        }
        
        if logger:
            log_structured_message(logger, "INFO", "Efficient deduplication summary", **summary)
            logger.info(f"🚀 Efficient Summary: {summary['total_urls_found']} total, {summary['new_listings']} new, "
                       f"{summary['price_changed']} price changes, {summary['existing_listings']} existing")
        
        # Return only new URLs for full scraping
        return all_new_urls, session, summary
        
    except Exception as e:
        if logger:
            logger.error(f"❌ Error in enhanced URL collection: {str(e)}")
        raise

def collect_all_listing_urls(base_url, max_pages=10, stealth_config=None, logger=None):
    """Legacy function - collect listing URLs from single area (for backward compatibility)"""
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    session = create_stealth_session(stealth_mode=stealth_mode, logger=logger)
    all_links = set()
    
    
    if logger:
        log_structured_message(logger, "INFO", "Starting listing URL collection", 
                             base_url=base_url, stealth_mode=stealth_mode)
    
    try:
        # Step 1: Get page 1 to establish session
        if logger:
            logger.info(f"=== Collecting listing URLs from page 1 ===")
        response = session.get(base_url, timeout=15)
        
        if response.status_code != 200:
            raise Exception(f"Failed to access page 1: HTTP {response.status_code}")
        
        if "pardon our interruption" in response.text.lower():
            raise Exception("Anti-bot protection detected on page 1")
        
        # Parse pagination info
        soup = BeautifulSoup(response.content, 'html.parser')
        total_element = soup.select_one('.totalNum')
        total_count = int(total_element.text) if total_element else 0
        
        page_links = soup.select('a[data-page]')
        max_page = max([int(link.get('data-page', 1)) for link in page_links]) if page_links else 1
        if max_pages is not None:
            max_page = min(max_page, max_pages)
        
        if logger:
            log_structured_message(logger, "INFO", "Pagination info parsed", 
                                 total_listings=total_count, max_page=max_page)
        
        # Extract listings from page 1
        page1_listings = extract_listing_urls_from_html(response.text)
        all_links.update(page1_listings)
        if logger:
            logger.info(f"Page 1: Found {len(page1_listings)} listings")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages with stealth timing
        for page_num in range(2, max_page + 1):
            if logger:
                logger.info(f"=== Collecting listings from page {page_num} ===")
            
            # Simple respectful delay
            delay = random.uniform(1, 3)
            
            time.sleep(delay)
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    if logger:
                        log_structured_message(logger, "WARNING", "Failed to access page", 
                                             page=page_num, status_code=response.status_code)
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    if logger:
                        log_structured_message(logger, "ERROR", "Anti-bot protection triggered", page=page_num)
                    break
                
                page_listings = extract_listing_urls_from_html(response.text)
                all_links.update(page_listings)
                if logger:
                    logger.info(f"Page {page_num}: Found {len(page_listings)} listings")
                
                session.headers['Referer'] = page_url
                if logger:
                    log_structured_message(logger, "INFO", "Page scraped successfully", 
                                         page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                if logger:
                    log_structured_message(logger, "ERROR", "Error fetching page", 
                                         page=page_num, error=str(e))
                continue
        
        all_links_list = list(all_links)
        
        # Apply browsing patterns in stealth mode
        
        if logger:
            log_structured_message(logger, "INFO", "URL collection completed", 
                                 total_unique_links=len(all_links_list),
                                 stealth_mode=stealth_mode)
        
        return all_links_list, session
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Error in URL collection", error=str(e))
        session.close()
        raise

def extract_property_details_with_circuit_breaker(property_url, referer_url, retries=3, config=None, logger=None):
    """Extract detailed property information using circuit breaker pattern"""
    session = None
    try:
        # Create a session pool if it doesn't exist
        if 'session_pool' not in globals():
            global session_pool
            stealth_mode = config.get('stealth_mode', False) if config else False
            session_pool = SessionPool(pool_size=3, stealth_mode=stealth_mode, logger=logger)
        
        # Get session from pool
        session = session_pool.get_session()
        
        # Use circuit breaker to protect the scraping operation
        result = circuit_breaker.call(
            _extract_property_details_core,
            session, property_url, referer_url, retries, config, logger
        )
        
        return result
        
    except Exception as e:
        error_category = categorize_error(e)
        if logger:
            log_structured_message(logger, "ERROR", "Circuit breaker protected extraction failed", 
                                 url=property_url, error=str(e), category=error_category.value)
        
        # Return structured error response
        return {
            "url": property_url, 
            "error": str(e),
            "error_category": error_category.value,
            "circuit_breaker_state": circuit_breaker.get_state().value
        }
        
    finally:
        if session:
            session_pool.return_session(session)


def extract_property_images(soup, session, base_url, bucket=None, property_id=None, config=None, date_key=None, logger=None):
    """Extract property images and upload to S3, return S3 keys"""
    s3_keys = []
    image_urls = set()
    stealth_mode = config.get('stealth_mode', False) if config else False
    mode = config.get('mode', 'normal') if config else 'normal'
    
    try:
        # Updated selectors specifically for homes.co.jp structure
        selectors = [
            # Main property gallery images
            '.mainPhoto img',
            '.detailPhoto img', 
            '.gallery-item img',
            '.photo-gallery img',
            # Common image containers
            '.property-photos img',
            '.mansion-photos img',
            # Generic image selectors with filters
            'img[src*="/photo/"]',
            'img[src*="/image/"]',
            'img[src*="mansion"]',
            'img[src*="property"]',
            # Lazy loading images
            'img[data-src*="photo"]',
            'img[data-original*="photo"]',
            # Any img in photo containers
            '[class*="photo"] img',
            '[id*="photo"] img'
        ]
        
        for selector in selectors:
            for img in soup.select(selector):
                # Check multiple possible src attributes
                src = (img.get('src') or 
                      img.get('data-src') or 
                      img.get('data-original') or 
                      img.get('data-lazy-src') or
                      img.get('data-lazy'))
                
                if src:
                    # Convert relative URLs to absolute
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = base_url + src
                    elif not src.startswith('http'):
                        src = base_url + '/' + src.lstrip('/')
                    
                    # Filter out unwanted images (be more specific)
                    exclude_patterns = [
                        'icon', 'logo', 'btn', 'button', 'arrow', 'banner',
                        'thumb', 'favicon', 'sprite', 'bg_', 'background',
                        'nav_', 'header_', 'footer_', 'menu_'
                    ]
                    
                    # Check if any exclude pattern is in the URL
                    if any(pattern in src.lower() for pattern in exclude_patterns):
                        continue
                        
                    # Only include images that are likely property photos
                    if any(pattern in src.lower() for pattern in ['photo', 'image', 'pic', 'img']):
                        image_urls.add(src)
        
        # Also look for images in script tags (sometimes URLs are in JavaScript)
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Look for image URLs in JavaScript
                js_images = re.findall(r'["\']([^"\']*(?:photo|image|pic)[^"\']*\.(?:jpg|jpeg|png|gif|webp))["\']', 
                                     script.string, re.IGNORECASE)
                for img_url in js_images:
                    if img_url.startswith('//'):
                        img_url = 'https:' + img_url
                    elif img_url.startswith('/'):
                        img_url = base_url + img_url
                    elif not img_url.startswith('http'):
                        img_url = base_url + '/' + img_url.lstrip('/')
                    image_urls.add(img_url)
        
        if logger:
            logger.info(f"Found {len(image_urls)} potential images for property {property_id}")
        
        # Apply per-property image cap in testing mode
        urls = list(image_urls)
        if mode == 'testing':
            urls = urls[:5]  # Only process first 5 images in testing mode
            if logger:
                logger.info(f"Testing mode: limiting to 5 images per property")
        
        # Limit to max 10 images per property for performance
        if len(urls) > 10:
            original_count = len(urls)
            urls = urls[:10]
            if logger:
                logger.info(f"Limited to first 10 images for performance (found {original_count} total)")
        
        # Download and process images
        for i, img_url in enumerate(urls):
            try:
                img_response = session.get(img_url, timeout=10)
                if img_response.status_code == 200:
                    content_type = img_response.headers.get('content-type', 'image/jpeg')
                    
                    # Only process actual images
                    if 'image' in content_type:
                        # Check image size to filter out tiny images
                        content_length = len(img_response.content)
                        if content_length < 1000:  # Skip very small images (< 1KB)
                            if logger:
                                logger.info(f"Skipping small image {i}: {img_url} ({content_length} bytes)")
                            continue
                        
                        try:
                            # Convert image to JPEG and resize
                            img = Image.open(io.BytesIO(img_response.content))
                            
                            # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
                            if img.mode not in ('RGB', 'L'):
                                img = img.convert('RGB')
                            
                            # Resize if larger than 1024x1024, preserving aspect ratio
                            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            
                            # Save to bytes buffer as JPEG
                            output_buffer = io.BytesIO()
                            img.save(output_buffer, format='JPEG', quality=85, optimize=True)
                            output_buffer.seek(0)
                            processed_image_bytes = output_buffer.getvalue()
                            
                            # Upload to S3 if bucket provided
                            if bucket and property_id:
                                s3_key = upload_image_to_s3(
                                    processed_image_bytes, 
                                    bucket, 
                                    property_id, 
                                    i, 
                                    'image/jpeg',  # Always JPEG now
                                    date_key=date_key,
                                    logger=logger
                                )
                                if s3_key:
                                    s3_keys.append(s3_key)
                            else:
                                # Local mode - store reference with .jpg extension
                                filename = f"{property_id}_image_{i}.jpg"
                                s3_keys.append(filename)
                                
                        except Exception as e:
                            if logger:
                                logger.error(f"Failed to process image {i}: {str(e)}")
                            continue
                        
                        # Minimal delay between downloads for performance
                        delay = 0.1
                        if stealth_mode:
                            delay = random.uniform(0.2, 0.5)
                        time.sleep(delay)        
            except Exception as e:
                if logger:
                    logger.warning(f"Failed to download image {i} from {img_url}: {str(e)}")
                continue

        if logger:
            logger.info(f"Successfully processed {len(s3_keys)} images for property {property_id}")
        return s3_keys
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Image extraction failed", 
                                 property_id=property_id, error=str(e))
        return []


def _extract_property_details_core(session, property_url, referer_url, retries=3, config=None, logger=None):
    """Core property extraction logic with enhanced error handling, stealth timing, and improved image capture"""
    last_error = None
    stealth_mode = config.get('stealth_mode', False) if config else False
    output_bucket = config.get('output_bucket', '') if config else ''
    
    for attempt in range(retries + 1):
        try:
            # Set proper referer and add realistic delay
            session.headers['Referer'] = referer_url
            
            # Simple respectful delay
            time.sleep(random.uniform(0.1, 0.2))
            
            if logger:
                logger.info(f"Scraping: {property_url}")
            response = session.get(property_url, timeout=15)
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                if attempt == retries:
                    raise requests.exceptions.HTTPError(error_msg)
                backoff_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(backoff_time)
                continue
            
            if "pardon our interruption" in response.text.lower():
                raise Exception("Anti-bot protection detected")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {"url": property_url}
            
            # FIXED: Better property ID extraction from URL
            property_id = "unknown"
            
            # Try multiple patterns for property ID extraction
            patterns = [
                r'/mansion/b-(\d+)/?',          # /mansion/b-1234567890/ or /mansion/b-1234567890
                r'/b-(\d+)/?',                  # /b-1234567890/ or /b-1234567890
                r'property[_-]?id[=:](\d+)',    # property_id=123 or property:123
                r'mansion[_-]?(\d{8,})',        # mansion_12345678 or mansion-12345678
                r'/(\d{10,})/'                  # Any 10+ digit number in URL path
            ]
            
            for pattern in patterns:
                match = re.search(pattern, property_url)
                if match:
                    property_id = match.group(1)
                    if logger:
                        logger.debug(f"Extracted property ID: {property_id} using pattern: {pattern}")
                    break
            
            # If still unknown, try to extract from page content
            if property_id == "unknown":
                # Look for property ID in meta tags
                meta_tags = soup.find_all('meta')
                for meta in meta_tags:
                    content = meta.get('content', '')
                    if re.search(r'\d{8,}', content):
                        id_match = re.search(r'(\d{8,})', content)
                        if id_match:
                            property_id = id_match.group(1)
                            if logger:
                                logger.debug(f"Found property ID in meta content: {property_id}")
                            break
                
                # Look for ID in script tags or data attributes
                if property_id == "unknown":
                    scripts = soup.find_all('script')
                    for script in scripts:
                        if script.string:
                            id_matches = re.findall(r'(?:property|mansion|id)["\']?\s*[:=]\s*["\']?(\d{8,})', script.string)
                            if id_matches:
                                property_id = id_matches[0]
                                if logger:
                                    logger.debug(f"Found property ID in script: {property_id}")
                                break
            
            # Store the extracted ID
            data["id"] = property_id
            
            # Extract title from h1 elements
            h1_elements = soup.select('h1')
            for h1 in h1_elements:
                if h1.text.strip() and ('マンション' in h1.text or '万円' in h1.text):
                    data["title"] = h1.text.strip()
                    break
            
            # Extract price using regex from content
            price_pattern = re.search(r'(\d{1,4}(?:,\d{3})*万円)', response.text)
            if price_pattern:
                data["price"] = price_pattern.group(1)
            
            # Extract detailed property information from tables
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 10:  # Main property details table
                    for row in rows:
                        cells = row.find_all(['th', 'td'])
                        if len(cells) >= 2:
                            key = cells[0].text.strip()
                            value = cells[1].text.strip()
                            if key and value and len(key) < 30:
                                data[key] = value
                    break
            
            # IMPROVED: Extract property images with better naming
            try:
                if logger:
                    logger.info(f"Starting image extraction for property {property_id}...")
                s3_keys = extract_property_images(
                    soup, session, "https://www.homes.co.jp", 
                    bucket=output_bucket, property_id=property_id,
                    config=config, date_key=config.get('date_key'), logger=logger
                )
                if s3_keys:
                    data["photo_filenames"] = "|".join(s3_keys)
                    data["image_count"] = len(s3_keys)
                    if logger:
                        log_structured_message(logger, "INFO", "Images processed", 
                                             url=property_url, property_id=property_id,
                                             image_count=len(s3_keys), 
                                             has_s3_bucket=bool(output_bucket))
                else:
                    if logger:
                        logger.warning(f"No images found for property {property_id}")
                    
            except Exception as e:
                if logger:
                    log_structured_message(logger, "WARNING", "Image processing failed", 
                                         url=property_url, property_id=property_id, error=str(e))
            
            # Log successful extraction
            if logger:
                log_structured_message(logger, "INFO", "Property details extracted successfully", 
                                     url=property_url, fields_extracted=len(data))
            
            return data
            
        except Exception as e:
            last_error = e
            error_category = categorize_error(e, response if 'response' in locals() else None)
            
            if logger:
                log_structured_message(logger, "WARNING", f"Extraction attempt {attempt + 1} failed", 
                                     url=property_url, error=str(e), 
                                     category=error_category.value, attempt=attempt + 1)
            
            if attempt == retries:
                break
                
            # Exponential backoff with jitter for exceptions
            backoff_time = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(backoff_time)
    
    # All retries failed
    if last_error:
        raise last_error
    else:
        raise Exception("Max retries exceeded")

def upload_image_to_s3(image_content, bucket, property_id, image_index, content_type="image/jpeg", date_key=None, logger=None):
    """Upload image content to S3 and return S3 key"""
    try:
        # Always use .jpg extension now since we standardize to JPEG
        file_extension = '.jpg'
        
        # Use provided date_key or fallback to current date
        if date_key:
            date_str = date_key
        else:
            date_str = datetime.now().strftime('%Y-%m-%d')
            if logger:
                logger.warning("No date_key provided to upload_image_to_s3, using current date")
        
        s3_key = f"raw/{date_str}/images/{property_id}_{image_index}{file_extension}"
        
        # Upload to S3
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=image_content,
            ContentType='image/jpeg'  # Always JPEG
        )
        
        if logger:
            log_structured_message(logger, "INFO", "Image uploaded to S3", 
                                 s3_key=s3_key, property_id=property_id, 
                                 image_index=image_index, content_type='image/jpeg')
        return s3_key
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "S3 image upload failed", 
                                 property_id=property_id, image_index=image_index, 
                                 error=str(e))
        return None

def upload_to_s3(file_path, bucket, s3_key, logger=None):
    """Upload file to S3"""
    try:
        s3 = boto3.client("s3")
        s3.upload_file(file_path, bucket, s3_key)
        if logger:
            logger.info(f"📤 Uploaded to s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"❌ S3 upload failed: {e}")
        return False

def send_cloudwatch_metrics(success_count, error_count, duration_seconds, total_properties, stealth_config=None):
    """Send custom metrics to CloudWatch with stealth mode indicators"""
    try:
        cloudwatch = boto3.client('cloudwatch')
        
        # Determine dimensions based on mode
        if stealth_config and stealth_config.get('stealth_mode'):
            instance_name = f"StealthScraper-{stealth_config.get('session_id', 'unknown')}"
            namespace = 'StealthScraperMetrics'
        else:
            instance_name = 'MarketScraper'
            namespace = 'ScraperMetrics'
        
        # Prepare base metric data
        metric_data = [
            {
                'MetricName': 'PropertiesScraped',
                'Value': success_count,
                'Unit': 'Count',
                'Dimensions': [
                    {
                        'Name': 'ScraperInstance',
                        'Value': instance_name
                    }
                ]
            },
            {
                'MetricName': 'ScrapingErrors',
                'Value': error_count,
                'Unit': 'Count',
                'Dimensions': [
                    {
                        'Name': 'ScraperInstance',
                        'Value': instance_name
                    }
                ]
            },
            {
                'MetricName': 'JobDuration',
                'Value': duration_seconds,
                'Unit': 'Seconds',
                'Dimensions': [
                    {
                        'Name': 'ScraperInstance',
                        'Value': instance_name
                    }
                ]
            },
            {
                'MetricName': 'SuccessRate',
                'Value': (success_count / total_properties * 100) if total_properties > 0 else 0,
                'Unit': 'Percent',
                'Dimensions': [
                    {
                        'Name': 'ScraperInstance',
                        'Value': instance_name
                    }
                ]
            }
        ]
        
        # Add stealth-specific metrics
        if stealth_config and stealth_config.get('stealth_mode'):
            avg_delay = duration_seconds / max(success_count, 1)  # Average time per property
            metric_data.extend([
                {
                    'MetricName': 'StealthModeActive',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {
                            'Name': 'SessionId',
                            'Value': stealth_config.get('session_id', 'unknown')
                        },
                        {
                            'Name': 'EntryPoint',
                            'Value': stealth_config.get('entry_point', 'default')
                        }
                    ]
                },
                {
                    'MetricName': 'AverageDelayPerProperty',
                    'Value': avg_delay,
                    'Unit': 'Seconds',
                    'Dimensions': [
                        {
                            'Name': 'SessionId',
                            'Value': stealth_config.get('session_id', 'unknown')
                        }
                    ]
                }
            ])
        
        # Send metrics to CloudWatch
        cloudwatch.put_metric_data(
            Namespace=namespace,
            MetricData=metric_data
        )
        
        if 'logger' in globals() and logger:
            log_structured_message(logger, "INFO", "CloudWatch metrics sent", 
                                 success_count=success_count, 
                                 error_count=error_count,
                                 duration_seconds=duration_seconds)
        return True
        
    except Exception as e:
        if 'logger' in globals() and logger:
            log_structured_message(logger, "ERROR", "Failed to send CloudWatch metrics", error=str(e))
        return False

def write_job_summary(summary_data):
    """Write job summary to JSON file"""
    try:
        summary_path = "/var/log/scraper/summary.json"
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
        print(f"📋 Job summary written to {summary_path}")
    except Exception as e:
        # Fallback to current directory if /var/log/scraper not accessible
        try:
            with open("summary.json", "w") as f:
                json.dump(summary_data, f, indent=2)
            print(f"📋 Job summary written to summary.json")
        except:
            print(f"❌ Failed to write job summary: {e}")

def setup_logging():
    """Configure logging with simple text formatting"""
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler()  # Output to stdout
        ]
    )
    
    return logging.getLogger(__name__)

def log_structured_message(logger, level, message, **kwargs):
    """Log message with simple text formatting"""
    if not logger:
        return
    
    # Format additional fields as simple key=value pairs
    if kwargs:
        extra_info = " ".join([f"{k}={v}" for k, v in kwargs.items()])
        full_message = f"{message} - {extra_info}"
    else:
        full_message = message
    
    if level == "INFO":
        logger.info(full_message)
    elif level == "WARNING":
        logger.warning(full_message)
    elif level == "ERROR":
        logger.error(full_message)
    elif level == "DEBUG":
        logger.debug(full_message)

# =============================================================================
# DynamoDB Helper Functions for Full Load and Duplicate Detection
# =============================================================================

def setup_dynamodb_client(logger=None):
    """Setup DynamoDB client and table reference with error handling"""
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        
        # Use the same table as the AI pipeline
        table_name = os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-RealEstateAnalysis')
        table = dynamodb.Table(table_name)
        
        # Test connection by getting table description
        table.load()
        
        if logger:
            log_structured_message(logger, "INFO", "DynamoDB connection established", 
                                 table_name=table_name, 
                                 region='ap-northeast-1')
        
        return dynamodb, table
        
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Failed to setup DynamoDB connection", 
                                 table_name=table_name, 
                                 error=str(e))
        raise Exception(f"DynamoDB setup failed: {str(e)}")

def extract_property_id_from_url(url):
    """Extract property ID from listing URL"""
    patterns = [
        r'/mansion/b-(\d+)/?$',         # /mansion/b-1234567890 or /mansion/b-1234567890/
        r'/b-(\d+)/?$',                 # /b-1234567890 or /b-1234567890/
        r'property[_-]?id[=:](\d+)',    # property_id=123 or property:123
        r'mansion[_-]?(\d{8,})',        # mansion_12345678 or mansion-12345678
        r'/(\d{10,})/?$'                # Any 10+ digit number at end of URL path
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None

def create_property_id_key(raw_property_id, date_str=None):
    """Create property_id key for DynamoDB in same format as AI pipeline"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    return f"PROP#{date_str}_{raw_property_id}"

def extract_listing_metadata_from_listing_page(url, session, logger=None):
    """Extract basic metadata (price, property ID) from listing page without full scraping"""
    try:
        if logger:
            logger.debug(f"Extracting metadata from listing page: {url}")
        
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            return None
        
        if "pardon our interruption" in response.text.lower():
            if logger:
                logger.warning(f"Anti-bot protection detected for metadata extraction: {url}")
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        metadata = {
            'url': url,
            'scraped_at': datetime.now().isoformat()
        }
        
        # Extract property ID
        raw_property_id = extract_property_id_from_url(url)
        if raw_property_id:
            metadata['raw_property_id'] = raw_property_id
            metadata['property_id'] = create_property_id_key(raw_property_id)
        
        # Extract price using regex from content
        price_pattern = re.search(r'(\d{1,4}(?:,\d{3})*万円)', response.text)
        if price_pattern:
            price_text = price_pattern.group(1)
            # Convert to integer (remove 万円 and commas, multiply by 10000)
            price_num = int(price_text.replace('万円', '').replace(',', '')) * 10000
            metadata['price'] = price_num
            metadata['price_display'] = price_text
        
        # Extract title from h1 elements
        h1_elements = soup.select('h1')
        for h1 in h1_elements:
            if h1.text.strip() and ('マンション' in h1.text or '万円' in h1.text):
                metadata['title'] = h1.text.strip()
                break
        
        return metadata
        
    except Exception as e:
        if logger:
            logger.warning(f"Failed to extract metadata from {url}: {str(e)}")
        return None

def load_all_existing_properties(table, logger=None):
    """Load all existing properties from DynamoDB into a dictionary for O(1) lookups"""
    if logger:
        logger.info("📊 Loading all existing properties from DynamoDB...")
    
    existing_properties = {}
    date_str = datetime.now().strftime('%Y%m%d')
    
    try:
        # Scan the table to get all META items
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        }
        
        items_processed = 0
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                raw_property_id = item.get('property_id', '').replace(f'_{date_str}', '')
                if raw_property_id:
                    # Store with raw property ID as key for easy lookup
                    existing_properties[raw_property_id] = {
                        'property_id': item.get('property_id'),
                        'price': int(item.get('price', 0)),
                        'analysis_date': item.get('analysis_date', ''),
                        'listing_url': item.get('listing_url', ''),
                        'recommendation': item.get('recommendation', ''),
                        'investment_score': int(item.get('investment_score', 0))
                    }
                    items_processed += 1
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        if logger:
            logger.info(f"📋 Loaded {items_processed} existing properties from DynamoDB")
        
        return existing_properties
        
    except Exception as e:
        if logger:
            logger.error(f"❌ Failed to load existing properties: {str(e)}")
        return {}

def check_existing_listings_batch(urls, table, logger=None):
    """Check multiple URLs against DynamoDB in batch to find existing listings with retry logic"""
    date_str = datetime.now().strftime('%Y%m%d')
    existing_listings = {}
    not_found = []
    
    if logger:
        log_structured_message(logger, "INFO", "Starting batch duplicate check", 
                             total_urls=len(urls), 
                             batch_size=25)
    
    try:
        # Process URLs in batches of 25 (DynamoDB batch limit)
        batch_size = 25
        for i in range(0, len(urls), batch_size):
            batch_urls = urls[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(urls) + batch_size - 1) // batch_size
            
            if logger and batch_num % 10 == 1:  # Log every 10th batch
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_urls)} URLs)")
            
            # Prepare batch request
            keys_to_get = []
            keys_to_urls = {}
            valid_urls = []
            
            for url in batch_urls:
                raw_property_id = extract_property_id_from_url(url)
                if raw_property_id:
                    property_id = create_property_id_key(raw_property_id, date_str)
                    key = {
                        'property_id': property_id, 
                        'sort_key': 'META'
                    }
                    keys_to_urls[f"{property_id}#META"] = url
                    valid_urls.append(url)
                    keys_to_get.append(key)
                else:
                    # URLs without valid property IDs are treated as new
                    not_found.append(url)
            
            if not keys_to_get:
                not_found.extend(valid_urls)
                continue
            
            # Execute batch get with retry logic using resource API
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Use the high-level resource API for batch operations
                    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
                    response = dynamodb.batch_get_item(
                        RequestItems={
                            table.table_name: {
                                'Keys': keys_to_get
                            }
                        }
                    )
                    
                    # Process results
                    if table.table_name in response.get('Responses', {}):
                        for item in response['Responses'][table.table_name]:
                            property_id = item.get('property_id')
                            sort_key = item.get('sort_key')
                            key = f"{property_id}#{sort_key}"
                            
                            if key in keys_to_urls:
                                url = keys_to_urls[key]
                                existing_listings[url] = {
                                    'property_id': property_id,
                                    'price': int(item.get('price', 0)),
                                    'analysis_date': item.get('analysis_date', ''),
                                    'listing_url': item.get('listing_url', ''),
                                    'recommendation': item.get('recommendation', ''),
                                    'investment_score': int(item.get('investment_score', 0))
                                }
                    
                    # Handle unprocessed items (if any)
                    if response.get('UnprocessedKeys'):
                        if logger:
                            log_structured_message(logger, "WARNING", "Some items were unprocessed", 
                                                 unprocessed_count=len(response['UnprocessedKeys']))
                    
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    if attempt == max_retries - 1:
                        # Final attempt failed
                        if logger:
                            log_structured_message(logger, "ERROR", "Batch get failed after retries", 
                                                 batch_num=batch_num, 
                                                 attempt=attempt + 1, 
                                                 error=str(e))
                        # Treat all URLs in this batch as new
                        not_found.extend(valid_urls)
                        break
                    else:
                        # Retry with exponential backoff
                        retry_delay = (2 ** attempt) * 0.5
                        if logger:
                            log_structured_message(logger, "WARNING", "Batch get failed, retrying", 
                                                 batch_num=batch_num, 
                                                 attempt=attempt + 1, 
                                                 retry_delay=retry_delay,
                                                 error=str(e))
                        time.sleep(retry_delay)
            
            # Track URLs not found in this batch
            found_urls_this_batch = set(url for url in valid_urls if url in existing_listings)
            not_found.extend([url for url in valid_urls if url not in found_urls_this_batch])
            
            # Small delay between batches to avoid throttling
            if i + batch_size < len(urls):
                time.sleep(0.1)
    
    except Exception as e:
        if logger:
            log_structured_message(logger, "ERROR", "Critical error in batch duplicate check", error=str(e))
        # In case of critical error, treat all as not found
        not_found = urls
        existing_listings = {}
    
    if logger:
        log_structured_message(logger, "INFO", "Batch duplicate check completed", 
                             existing_listings=len(existing_listings), 
                             new_listings=len(not_found),
                             total_processed=len(urls))
    
    return existing_listings, not_found

def compare_listing_price(url, current_metadata, existing_record, logger=None):
    """Compare current listing price with existing record"""
    if not current_metadata or not existing_record:
        return False, 0
    
    current_price = current_metadata.get('price', 0)
    existing_price = existing_record.get('price', 0)
    
    if current_price != existing_price:
        price_change = current_price - existing_price
        price_change_pct = (price_change / existing_price * 100) if existing_price > 0 else 0
        
        if logger:
            logger.info(f"Price change detected for {url}: {existing_price:,} -> {current_price:,} ({price_change_pct:+.1f}%)")
        
        return True, price_change
    
    return False, 0

def create_listing_meta_record(metadata, date_str=None):
    """Create a minimal META record for a new listing"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    
    now = datetime.now()
    property_id = metadata.get('property_id')
    
    if not property_id:
        raw_id = metadata.get('raw_property_id')
        if raw_id:
            property_id = create_property_id_key(raw_id, date_str)
    
    # Ensure we have a valid property_id
    if not property_id:
        return None
    
    record = {
        'property_id': property_id,
        'sort_key': 'META',
        'listing_url': metadata.get('url', ''),
        'scraped_date': metadata.get('scraped_at', now.isoformat()),
        'analysis_date': now.isoformat(),
        'price': metadata.get('price', 0),
        'listing_status': 'discovered',  # Mark as discovered but not fully analyzed
        'property_id_simple': metadata.get('raw_property_id', ''),
        'data_source': 'scraper_discovery',
        'analysis_yymm': now.strftime('%Y-%m'),
        'invest_partition': 'DISCOVERED',  # Separate from analyzed properties
    }
    
    # Add title if available
    if metadata.get('title'):
        record['title'] = metadata['title']
    
    return record

def update_listing_with_price_change(existing_record, new_metadata, table, logger=None):
    """Update existing listing record with new price and create price history"""
    try:
        property_id = existing_record['property_id']
        old_price = existing_record.get('price', 0)
        new_price = new_metadata.get('price', 0)
        now = datetime.now()
        
        # Update the META record
        update_expression = "SET price = :new_price, analysis_date = :now, listing_status = :status"
        expression_values = {
            ':new_price': new_price,
            ':now': now.isoformat(),
            ':status': 'price_updated'
        }
        
        table.update_item(
            Key={'property_id': property_id, 'sort_key': 'META'},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
        
        # Create price history record
        price_change = new_price - old_price
        price_change_pct = Decimal(str(round((price_change / old_price * 100), 2))) if old_price > 0 else Decimal('0')
        
        hist_record = {
            'property_id': property_id,
            'sort_key': f"HIST#{now.strftime('%Y-%m-%d_%H:%M:%S')}",
            'price': new_price,
            'previous_price': old_price,
            'price_change_amount': price_change,
            'price_drop_pct': price_change_pct,
            'listing_status': 'price_updated',
            'analysis_date': now.isoformat(),
            'change_detected_by': 'scraper_full_load',
            'ttl_epoch': int(time.time()) + 60*60*24*365  # 1 year TTL
        }
        
        table.put_item(Item=hist_record)
        
        if logger:
            logger.info(f"Updated price record for {property_id}: {old_price:,} -> {new_price:,}")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to update listing price: {str(e)}")
        return False

def validate_full_load_environment(config, logger=None):
    """Validate environment and configuration for full-load mode"""
    validation_errors = []
    
    # Check if DynamoDB table is configured
    if not config.get('dynamodb_table'):
        validation_errors.append("DynamoDB table name not configured")
    
    # Check AWS credentials
    try:
        boto3.client('dynamodb', region_name='ap-northeast-1')
    except Exception as e:
        validation_errors.append(f"AWS credentials not configured: {str(e)}")
    
    # Check if table exists and is accessible
    if config.get('dynamodb_table'):
        try:
            dynamodb, table = setup_dynamodb_client(logger)
            # Try a simple operation to verify access
            table.get_item(Key={'property_id': 'test', 'sort_key': 'test'})
        except Exception as e:
            if "Requested resource not found" not in str(e):
                validation_errors.append(f"DynamoDB table access error: {str(e)}")
    
    # Log validation results
    if validation_errors:
        if logger:
            log_structured_message(logger, "ERROR", "Full-load environment validation failed", 
                                 errors=validation_errors)
        return False, validation_errors
    else:
        if logger:
            log_structured_message(logger, "INFO", "Full-load environment validation passed")
        return True, []

def validate_property_data(property_data):
    """Validate and clean property data"""
    if not isinstance(property_data, dict):
        return False, "Property data must be a dictionary"
    
    # Check required fields
    required_fields = ["url"]
    for field in required_fields:
        if field not in property_data:
            return False, f"Missing required field: {field}"
    
    # Validate URL format
    if not property_data["url"].startswith("https://"):
        return False, "Invalid URL format"
    
    # Validate price format if present
    if "price" in property_data and property_data["price"]:
        price_pattern = re.compile(r'^\d{1,4}(?:,\d{3})*万円$')
        if not price_pattern.match(property_data["price"]):
            return False, f"Invalid price format: {property_data['price']}"
    
    # Clean and validate title
    if "title" in property_data and property_data["title"]:
        title = property_data["title"].strip()
        if len(title) > 200:
            property_data["title"] = title[:200] + "..."
        elif len(title) < 5:
            return False, "Title too short"
    
    # Remove empty or invalid fields
    cleaned_data = {}
    for key, value in property_data.items():
        if value and str(value).strip():
            cleaned_value = str(value).strip()
            if len(cleaned_value) <= 500:  # Reasonable field length limit
                cleaned_data[key] = cleaned_value
    
    property_data.clear()
    property_data.update(cleaned_data)
    
    return True, "Data validation passed"

def parse_arguments():
    """Parse command line arguments with environment variable fallbacks"""
    parser = argparse.ArgumentParser(
        description="HTTP-based scraper for homes.co.jp with session management and full-load support"
    )
    
    parser.add_argument(
        '--mode',
        choices=['normal', 'testing', 'stealth', 'full-load'],
        default=os.environ.get('MODE', 'normal'),
        help='Scraping mode (default: normal)'
    )
    
    parser.add_argument(
        '--max-properties',
        type=int,
        default=int(os.environ.get('MAX_PROPERTIES', '5')),
        help='Maximum number of properties to scrape (default: 5, ignored in full-load mode)'
    )
    
    parser.add_argument(
        '--output-bucket',
        type=str,
        default=os.environ.get('OUTPUT_BUCKET', ''),
        help='S3 bucket for output (optional)'
    )
    
    parser.add_argument(
        '--max-threads',
        type=int,
        default=int(os.environ.get('MAX_THREADS', '2')),
        help='Maximum number of threads for concurrent scraping (default: 2)'
    )
    
    parser.add_argument(
        '--areas',
        type=str,
        default=os.environ.get('AREAS', ''),
        help='Comma-separated list of Tokyo areas to scrape'
    )
    
    # Full-load specific arguments
    parser.add_argument(
        '--full-load',
        action='store_true',
        default=os.environ.get('FULL_LOAD', '').lower() in ('true', '1', 'yes'),
        help='Enable full load mode for all Tokyo areas with deduplication'
    )
    
    parser.add_argument(
        '--check-duplicates',
        action='store_true',
        default=os.environ.get('CHECK_DUPLICATES', 'true').lower() in ('true', '1', 'yes'),
        help='Enable duplicate checking against DynamoDB (default: true)'
    )
    
    parser.add_argument(
        '--track-price-changes',
        action='store_true', 
        default=os.environ.get('TRACK_PRICE_CHANGES', 'true').lower() in ('true', '1', 'yes'),
        help='Enable price change tracking (default: true)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=int(os.environ.get('BATCH_SIZE', '25')),
        help='Batch size for DynamoDB operations (default: 25, max: 25)'
    )
    
    parser.add_argument(
        '--dynamodb-table',
        type=str,
        default=os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-RealEstateAnalysis'),
        help='DynamoDB table name for deduplication and price tracking'
    )
    
    return parser.parse_args()

def main():
    """Main scraper function using HTTP with session flow, stealth capabilities, and full-load support"""
    # Parse command line arguments
    args = parse_arguments()
    
    # Setup logging
    logger = setup_logging()
    
    job_start_time = datetime.now()
    
    # Get configuration from args (updated function)
    config = get_scraper_config(args)
    is_local_testing = not config['output_bucket']
    
    # Determine mode and limits based on configuration
    mode = config['mode']
    full_load_mode = config.get('full_load_mode', False)
    
    # Enforce hard 5-property limit in testing mode
    if mode == 'testing':
        max_properties_limit = 5  # Hard limit for testing
        mode_name = "TESTING MODE"
        stealth_enabled = False
        log_structured_message(logger, "INFO", "TESTING MODE: Limited scope for testing", 
                             session_id=config['session_id'],
                             max_properties=max_properties_limit,
                             areas=config['areas'],
                             start_time=job_start_time.isoformat())
        logger.info(f"🧪 TESTING MODE - Session: {config['session_id']}, Max Properties: {max_properties_limit}, Areas: {config['areas']}")
    elif full_load_mode or mode == 'full-load':
        max_properties_limit = config['max_properties'] if config['max_properties'] > 0 else 0 # No limit in full-load mode
        mode_name = "FULL LOAD MODE"
        stealth_enabled = False  # Full load uses own optimization
        log_structured_message(logger, "INFO", "FULL LOAD MODE: Complete Tokyo market with deduplication", 
                             session_id=config['session_id'],
                             enable_deduplication=config['enable_deduplication'],
                             track_price_changes=config['track_price_changes'],
                             dynamodb_table=config['dynamodb_table'],
                             start_time=job_start_time.isoformat())
        logger.info(f"🌍 FULL LOAD MODE - Dedup: {config['enable_deduplication']}, Price Tracking: {config['track_price_changes']}")
    elif mode == 'stealth' or config['stealth_mode']:
        max_properties_limit = config['max_properties']
        mode_name = "STEALTH MODE"
        stealth_enabled = True
        log_structured_message(logger, "INFO", "STEALTH MODE: Session-based distributed scraping", 
                             session_id=config['session_id'],
                             max_properties=max_properties_limit,
                             entry_point=config['entry_point'],
                             start_time=job_start_time.isoformat())
        logger.info(f"🥷 STEALTH MODE - Session: {config['session_id']}, Max Properties: {max_properties_limit}")
    elif mode == 'normal':
        max_properties_limit = config['max_properties'] or 500
        mode_name = "NORMAL MODE"
        stealth_enabled = False
        log_structured_message(logger, "INFO", "NORMAL MODE: Standard scraping", 
                             session_id=config['session_id'],
                             max_properties=max_properties_limit,
                             areas=config['areas'],
                             start_time=job_start_time.isoformat())
        logger.info(f"📊 NORMAL MODE - Session: {config['session_id']}, Max Properties: {max_properties_limit}, Areas: {config['areas']}")
    elif is_local_testing:
        max_properties_limit = 5
        mode_name = "LOCAL TESTING"
        stealth_enabled = False
        log_structured_message(logger, "INFO", "LOCAL TESTING MODE: Limited to 5 listings", start_time=job_start_time.isoformat())
        logger.info("🧪 LOCAL TESTING MODE - Processing only 5 listings for quick testing")
    else:
        max_properties_limit = 500  # Default limit
        mode_name = "PRODUCTION"
        stealth_enabled = False
        log_structured_message(logger, "INFO", "Starting HTTP scraper job", start_time=job_start_time.isoformat())
    
    error_count = 0
    success_count = 0
    session = None
    
    try:
        # Configuration
        date_key = datetime.now().strftime('%Y-%m-%d')
        config['date_key'] = date_key  # Add date_key to config for passing to functions
        
        # Step 0: Determine areas based on mode
        if mode == 'testing':
            # Use specific areas from configuration or default to chofu-city
            session_areas = config['areas'] if config['areas'] else ["chofu-city"]
            logger.info(f"🧪 TESTING MODE - Using areas: {session_areas}")
        elif full_load_mode or mode == 'full-load':
            # Full-load mode: Check if this is a testing scenario
            if config['max_properties'] and config['max_properties'] <= 50:
                # Testing scenario - use limited areas for efficiency
                if config['areas']:
                    session_areas = config['areas']
                    logger.info(f"🧪 FULL LOAD TESTING - Using specified areas: {session_areas}")
                else:
                    session_areas = ["chofu-city"]  # Default to single area for testing
                    logger.info(f"🧪 FULL LOAD TESTING - Using default single area: {session_areas}")
            else:
                # True full-load mode: validate environment and discover all Tokyo areas
                logger.info(f"\n🌍 FULL LOAD MODE - Validating environment...")
                
                # Validate environment for full-load mode
                is_valid, validation_errors = validate_full_load_environment(config, logger)
                if not is_valid:
                    error_msg = f"Full-load environment validation failed: {', '.join(validation_errors)}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                
                logger.info(f"✅ Environment validation passed - Discovering all Tokyo areas...")
                session_areas = discover_tokyo_areas(stealth_mode=False, logger=logger)
                
                if not session_areas:
                    raise Exception("No Tokyo areas discovered for full load")
                
                logger.info(f"🏙️ Full load will process {len(session_areas)} Tokyo areas: {session_areas[:5]}{'...' if len(session_areas) > 5 else ''}")
                log_structured_message(logger, "INFO", "Full load area discovery", 
                                    total_areas=len(session_areas),
                                    sample_areas=session_areas[:10])
        elif mode == 'normal':
            # Use specific areas from configuration or default to chofu-city
            session_areas = config['areas'] if config['areas'] else ["chofu-city"]
            logger.info(f"📊 NORMAL MODE - Using areas: {session_areas}")
        elif stealth_enabled:
            logger.info(f"\n🗖️ Discovering Tokyo areas and calculating session assignment...")
            all_tokyo_areas = discover_tokyo_areas(stealth_mode=stealth_enabled, logger=logger)
            session_areas = get_daily_area_distribution(all_tokyo_areas, config['session_id'], date_key)
            
            if not session_areas:
                raise Exception(f"No areas assigned to session {config['session_id']}")
            
            logger.info(f"🏆 Session {config['session_id']} assigned areas: {session_areas}")
            log_structured_message(logger, "INFO", "Session area assignment", 
                                session_id=config['session_id'],
                                assigned_areas=session_areas,
                                total_tokyo_areas=len(all_tokyo_areas))
        else:
            # Fallback to single area for other modes
            session_areas = ["chofu-city"]
        
        # Step 1: Collect all listing URLs with enhanced deduplication
        logger.info(f"\n🔗 Collecting listing URLs from {len(session_areas)} areas ({mode_name})...")
        
        # Use enhanced collection with deduplication for full-load mode
        if full_load_mode or mode == 'full-load':
            logger.info(f"🔍 Starting full load process with {len(session_areas)} Tokyo areas...")
            logger.info(f"📊 Process overview: Area scanning → Duplicate check → Price comparison → New property scraping")
            all_urls, session, dedup_summary = collect_urls_with_deduplication(
                session_areas, 
                config, 
                enable_dedup=config['enable_deduplication'], 
                logger=logger
            )
            BASE_URL = "https://www.homes.co.jp"  # Base URL for multi-area
            
            # Log deduplication results
            if dedup_summary:
                logger.info(f"📊 Deduplication Results: {dedup_summary['new_listings']} new URLs to process "
                           f"(from {dedup_summary['total_urls_found']} total found)")
                if dedup_summary['price_changed'] > 0:
                    logger.info(f"💰 {dedup_summary['price_changed']} price changes detected and updated")
        else:
            # Standard collection for other modes
            if len(session_areas) > 1:
                # Pass max_urls limit for full load mode with max_properties set
                max_urls_limit = None
                if full_load_mode and config.get('max_properties') and config['max_properties'] > 0:
                    max_urls_limit = config['max_properties']
                    if logger:
                        logger.info(f"🚀 Full load mode with max_properties limit: will collect only {max_urls_limit} URLs")
                
                all_urls, session = collect_multiple_areas_urls(session_areas, config, logger, max_urls=max_urls_limit)
                BASE_URL = "https://www.homes.co.jp"  # Base URL for multi-area
            else:
                # Single area fallback - collect all pages
                BASE_URL = f"https://www.homes.co.jp/mansion/chuko/tokyo/{session_areas[0]}/list"
                max_pages = 1 if is_local_testing else None  # No limit in production
                all_urls, session = collect_all_listing_urls(BASE_URL, max_pages, config, logger)
            
            dedup_summary = None
        
        if not all_urls:
            if full_load_mode:
                logger.info("✅ Full load complete: All listings are up-to-date, no new properties to process")
                # Create a summary for full load with no new properties
                summary_data = {
                    "start_time": job_start_time.isoformat(),
                    "end_time": datetime.now().isoformat(),
                    "duration_seconds": (datetime.now() - job_start_time).total_seconds(),
                    "scraper_type": "HTTP_FULL_LOAD",
                    "mode": mode_name,
                    "full_load_mode": True,
                    "total_urls_found": dedup_summary.get('total_urls_found', 0) if dedup_summary else 0,
                    "new_listings": 0,
                    "price_changes": dedup_summary.get('price_changed', 0) if dedup_summary else 0,
                    "existing_listings": dedup_summary.get('existing_listings', 0) if dedup_summary else 0,
                    "status": "SUCCESS_NO_NEW_PROPERTIES"
                }
                write_job_summary(summary_data)
                log_structured_message(logger, "INFO", "Full load completed with no new properties", **summary_data)
                return
            else:
                raise Exception("No listing URLs found")
        
        # Apply limits based on mode and user settings
        if mode == 'testing':
            max_props = 5  # Hard limit for testing mode
            all_urls = all_urls[:max_props]
            logger.info(f"🧪 TESTING MODE: LIMITED TO {len(all_urls)} PROPERTIES")
        elif config['max_properties'] and config['max_properties'] > 0:
            # Apply user-specified limit in all modes (including full-load)
            original_count = len(all_urls)
            all_urls = all_urls[:config['max_properties']]
            mode_label = "FULL-LOAD" if full_load_mode else "STANDARD"
            logger.info(f"🌐 {mode_label} MODE: LIMITED TO {len(all_urls)} PROPERTIES (user specified max_properties={config['max_properties']}, found {original_count} total)")
        else:
            # No limit - process all found properties
            logger.info(f"🚀 PROCESSING ALL {len(all_urls)} PROPERTIES FOUND")
            if stealth_enabled:
                logger.info(f"🥷 STEALTH MODE: Using human-like delays for {len(all_urls)} properties")
        
        log_structured_message(logger, "INFO", "URL collection completed", 
                             total_urls=len(all_urls), 
                             full_load_mode=full_load_mode,
                             deduplication_enabled=config.get('enable_deduplication', False))
        
        # Step 2: Extract detailed information from each property with circuit breaker protection
        logger.info(f"\n📋 Extracting details from {len(all_urls)} properties...")
        listings_data = []
        circuit_breaker_triggered = False
        response_times = []
        request_start_times = []
        scraping_start_time = time.time()
        
        # Use configured thread pool size
        max_threads = config.get('max_threads', 8)
        if stealth_enabled and max_threads > 1:
            max_threads = 1  # Force single-threaded for stealth mode
            logger.info("🥷 Using single-threaded extraction for stealth")
        else:
            logger.info(f"🔧 Using {max_threads} threads for extraction")
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            # Submit all tasks using circuit breaker enhanced function
            futures = {
                executor.submit(extract_property_details_with_circuit_breaker, url, BASE_URL, config=config, logger=logger): url 
                for url in all_urls
            }
            
            completed_count = 0
            # Collect results with graceful degradation and detection monitoring
            for future in as_completed(futures):
                url = futures[future]
                request_start = time.time()
                completed_count += 1
                
                # Show progress every 10 completions or at milestones
                if completed_count % 10 == 0 or completed_count == 1 or completed_count == len(all_urls):
                    progress_pct = (completed_count / len(all_urls)) * 100
                    elapsed = time.time() - scraping_start_time
                    rate = completed_count / elapsed if elapsed > 0 else 0
                    eta = (len(all_urls) - completed_count) / rate if rate > 0 else 0
                    logger.info(f"🏠 [{progress_pct:.1f}%] Scraping progress: {completed_count}/{len(all_urls)} "
                               f"({success_count} ok, {error_count} errors) ~{eta/60:.1f}min remaining")
                
                try:
                    result = future.result()
                    request_end = time.time()
                    response_time = request_end - request_start
                    response_times.append(response_time)
                    
                    # Check if circuit breaker was triggered
                    if "circuit_breaker_state" in result and result["circuit_breaker_state"] == "OPEN":
                        circuit_breaker_triggered = True
                        log_structured_message(logger, "WARNING", "Circuit breaker triggered - degrading gracefully", 
                                             url=url, circuit_breaker_state=result["circuit_breaker_state"])
                    
                    # Validate and clean property data
                    if "error" not in result:
                        is_valid, validation_message = validate_property_data(result)
                        if not is_valid:
                            log_structured_message(logger, "WARNING", "Data validation failed", url=url, reason=validation_message)
                            result["validation_error"] = validation_message
                            error_count += 1
                        else:
                            success_count += 1
                    else:
                        error_count += 1
                    
                    listings_data.append(result)
                        
                except Exception as e:
                    error_category = categorize_error(e)
                    log_structured_message(logger, "ERROR", "Error processing property", 
                                         url=url, error=str(e), category=error_category.value)
                    error_count += 1
                    listings_data.append({
                        "url": url, 
                        "error": str(e),
                        "error_category": error_category.value
                    })
                    
                    # Implement graceful degradation if too many errors
                    if error_count > len(all_urls) * 0.5:  # More than 50% errors
                        log_structured_message(logger, "WARNING", "High error rate detected - considering early termination",
                                             error_rate=error_count / len(listings_data) if listings_data else 1.0,
                                             total_processed=len(listings_data),
                                             total_errors=error_count)
                        
                        # If circuit breaker is open and we have high errors, stop processing
                        if circuit_breaker_triggered and error_count > 10:
                            log_structured_message(logger, "ERROR", "Circuit breaker open with high error rate - stopping processing",
                                                 error_count=error_count, processed_count=len(listings_data))
                            break
                
                # Track response times for detection monitoring
                if len(response_times) % 10 == 0 and len(response_times) > 0:
                    # Check detection indicators every 10 requests
                    risk_level, indicators = check_detection_indicators(response_times, error_count, len(listings_data))
                    if risk_level != "LOW":
                        log_structured_message(logger, "WARNING", "Detection risk elevated", 
                                             risk_level=risk_level, 
                                             indicators=indicators,
                                             processed_count=len(listings_data))
                        
                        # Send detection metrics in stealth mode
                        if stealth_enabled:
                            send_detection_metrics(risk_level, indicators, config)
        
        # Step 3: Save data
        df = pd.DataFrame(listings_data)
        
        # Generate filename based on areas scraped
        date_str = datetime.now().strftime('%Y-%m-%d')
        if len(session_areas) == 1:
            area_name = session_areas[0]
            filename = f"{area_name}-listings-{date_str}.csv"
        else:
            filename = f"tokyo-multi-area-listings-{date_str}.csv"
        
        # Save locally (try desktop first, fallback to current directory)
        try:
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", filename)
            df.to_csv(desktop_path, index=False)
            local_path = desktop_path
        except:
            local_path = filename
            df.to_csv(local_path, index=False)
        
        log_structured_message(logger, "INFO", "Data saved locally", file_path=local_path)
        
        # Step 4: Upload to S3
        s3_upload_success = False
        output_bucket = config.get('output_bucket', '')
        s3_key = None
        
        if output_bucket and not is_local_testing:
            s3_key = f"scraper-output/{filename}"
            s3_upload_success = upload_to_s3(local_path, output_bucket, s3_key, logger)
        elif is_local_testing:
            logger.info("🧪 LOCAL TESTING: Skipping S3 upload")
            log_structured_message(logger, "INFO", "LOCAL TESTING: S3 upload skipped")
        else:
            log_structured_message(logger, "WARNING", "OUTPUT_BUCKET environment variable not set")
        
        # Step 5.5: Trigger AI Analysis Workflow (if configured)
        ai_workflow_arn = os.environ.get('AI_WORKFLOW_ARN')
        if ai_workflow_arn and s3_upload_success and not is_local_testing:
            try:
                stepfunctions = boto3.client('stepfunctions', region_name='ap-northeast-1')
                
                # Extract date from the data
                analysis_date = date_str  # Already have this from filename generation
                
                execution_name = f"scraper-triggered-{analysis_date}-{int(time.time())}"
                
                response = stepfunctions.start_execution(
                    stateMachineArn=ai_workflow_arn,
                    name=execution_name,
                    input=json.dumps({"date": analysis_date})
                )
                
                execution_arn = response['executionArn']
                logger.info(f"✨ AI Analysis workflow triggered successfully!")
                logger.info(f"📊 Execution: {execution_name}")
                logger.info(f"🔗 ARN: {execution_arn}")
                
                log_structured_message(logger, "INFO", "AI workflow triggered", 
                                     execution_name=execution_name,
                                     execution_arn=execution_arn,
                                     analysis_date=analysis_date)
                
            except Exception as e:
                # Don't fail the scraper if AI trigger fails
                logger.warning(f"⚠️ Failed to trigger AI workflow: {str(e)}")
                log_structured_message(logger, "WARNING", "AI workflow trigger failed", 
                                     error=str(e), ai_workflow_arn=ai_workflow_arn)
        elif is_local_testing:
            logger.info("🧪 LOCAL TESTING: Skipping AI workflow trigger")
        else:
            if not ai_workflow_arn:
                logger.info("ℹ️ AI_WORKFLOW_ARN not configured - skipping AI analysis")
        
        # Step 6: Generate job summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        # Initialize summary_data for AI workflow tracking
        ai_workflow_triggered = False
        ai_execution_name = None
        ai_execution_arn = None
        ai_workflow_error = None
        
        # Check if AI workflow was triggered
        if ai_workflow_arn and s3_upload_success and not is_local_testing:
            ai_workflow_triggered = 'execution_arn' in locals() and execution_arn
            if ai_workflow_triggered:
                ai_execution_name = execution_name
                ai_execution_arn = execution_arn
            else:
                ai_workflow_error = locals().get('e', 'Unknown error')
        
        # Base summary data
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP_FULL_LOAD" if full_load_mode else "HTTP_SESSION_FLOW",
            "mode": mode_name,
            "stealth_mode": stealth_enabled,
            "full_load_mode": full_load_mode,
            "session_id": config.get('session_id'),
            "entry_point": config.get('entry_point'),
            "max_properties_limit": max_properties_limit,
            "total_urls_found": len(all_urls),
            "successful_scrapes": success_count,
            "failed_scrapes": error_count,
            "total_records": len(listings_data),
            "output_file": filename,
            "s3_upload_success": s3_upload_success,
            "s3_key": s3_key,
            "ai_workflow_triggered": ai_workflow_triggered,
            "ai_execution_name": ai_execution_name,
            "ai_execution_arn": ai_execution_arn,
            "ai_workflow_error": str(ai_workflow_error) if ai_workflow_error else None,
            "status": "SUCCESS" if success_count > 0 else "FAILED"
        }
        
        # Add full-load specific information
        if full_load_mode and dedup_summary:
            summary_data.update({
                "deduplication_enabled": config.get('enable_deduplication', False),
                "price_tracking_enabled": config.get('track_price_changes', False),
                "total_urls_discovered": dedup_summary.get('total_urls_found', 0),
                "existing_listings_found": dedup_summary.get('existing_listings', 0),
                "new_listings_found": dedup_summary.get('new_listings', 0),
                "price_changes_detected": dedup_summary.get('price_changed', 0),
                "price_unchanged_listings": dedup_summary.get('price_unchanged', 0),
                "dynamodb_table": config.get('dynamodb_table', ''),
                "tokyo_areas_processed": len(session_areas)
            })
        
        write_job_summary(summary_data)
        
        # Step 6: Send CloudWatch metrics and final detection check
        if not is_local_testing:
            send_cloudwatch_metrics(success_count, error_count, duration, len(all_urls), config)
            
            # Final detection risk assessment
            if response_times:
                final_risk_level, final_indicators = check_detection_indicators(response_times, error_count, len(listings_data))
                log_structured_message(logger, "INFO", "Final detection risk assessment", 
                                     risk_level=final_risk_level, 
                                     indicators=final_indicators)
                
                if stealth_enabled:
                    send_detection_metrics(final_risk_level, final_indicators, config)
        else:
            log_structured_message(logger, "INFO", f"{mode_name}: Skipping CloudWatch metrics")
        
        log_structured_message(logger, "INFO", "HTTP scraper job completed successfully", **summary_data)
        
        logger.info(f"\n✅ {mode_name} scraping completed successfully!")
        if stealth_enabled:
            logger.info(f"🥷 Session: {config['session_id']}")
        elif full_load_mode and dedup_summary:
            logger.info(f"🌍 Full Load Complete!")
            logger.info(f"   📈 Total URLs discovered: {dedup_summary['total_urls_found']:,}")
            logger.info(f"   ✨ New properties processed: {dedup_summary['new_listings']:,}")
            logger.info(f"   💰 Price changes detected: {dedup_summary['price_changed']:,}")
            logger.info(f"   📋 Properties scraped: {success_count:,}")
            efficiency = ((dedup_summary['total_urls_found'] - dedup_summary['new_listings']) / dedup_summary['total_urls_found'] * 100) if dedup_summary['total_urls_found'] > 0 else 0
            logger.info(f"   ⚡ Efficiency gain: {efficiency:.1f}% (skipped {dedup_summary['total_urls_found'] - dedup_summary['new_listings']:,} duplicates)")
        logger.info(f"📊 Results: {success_count} successful, {error_count} failed")
        logger.info(f"⏱️ Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
        logger.info(f"💾 Output: {local_path}")
        if s3_upload_success:
            logger.info(f"☁️ S3: s3://{output_bucket}/{s3_key}")
        
    except Exception as e:
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP_SESSION_FLOW",
            "mode": locals().get('mode_name', 'UNKNOWN'),
            "stealth_mode": locals().get('stealth_enabled', False),
            "session_id": locals().get('config', {}).get('session_id'),
            "status": "ERROR",
            "error": str(e)
        }
        
        write_job_summary(summary_data)
        log_structured_message(logger, "ERROR", "HTTP scraper job failed", **summary_data)
        logger.error(f"\n❌ Scraping failed: {e}")
        raise
    
    finally:
        # Close the original session if it exists
        if session:
            session.close()

if __name__ == "__main__":
    main()