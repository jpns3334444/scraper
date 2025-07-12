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
        with self.lock:
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitBreakerState.HALF_OPEN
                    log_structured_message("INFO", "Circuit breaker transitioning to HALF_OPEN")
                else:
                    raise Exception("Circuit breaker is OPEN - refusing request")
            
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self):
        """Check if circuit breaker should attempt reset"""
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
                    log_structured_message("INFO", "Circuit breaker reset to CLOSED")
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
                log_structured_message("WARNING", "Circuit breaker opened from HALF_OPEN state")
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                log_structured_message("WARNING", "Circuit breaker opened", 
                                     failure_count=self.failure_count,
                                     threshold=self.failure_threshold)
    
    def get_state(self):
        """Get current circuit breaker state"""
        return self.state


class SessionPool:
    def __init__(self, pool_size=3, max_age_seconds=300):
        self.pool = Queue(maxsize=pool_size)
        self.pool_size = pool_size
        self.max_age_seconds = max_age_seconds
        self.lock = threading.Lock()
        self.session_metadata = {}
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the session pool with fresh sessions"""
        for _ in range(self.pool_size):
            session = self._create_fresh_session()
            self.pool.put(session)
    
    def _create_fresh_session(self):
        """Create a new session with metadata tracking"""
        stealth_mode = os.environ.get("STEALTH_MODE", "false").lower() == "true"
        session = create_stealth_session(stealth_mode=stealth_mode)
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
            log_structured_message("WARNING", "Session pool exhausted, creating new session")
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


def create_stealth_session(stealth_mode=False):
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
        
        # Log session creation (function defined later in file)
        try:
            log_structured_message("INFO", "Stealth session created", 
                                 profile=profile["name"], 
                                 user_agent=base_headers["User-Agent"][:50] + "...")
        except NameError:
            # Function not yet defined during import, skip logging
            pass
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
    """Simulate realistic human reading time for property details"""
    base_reading = random.uniform(15, 45)  # 15-45 seconds base
    detail_reading = random.uniform(30, 120)  # 30-120 seconds for details
    decision_time = random.uniform(2, 8)  # 2-8 seconds decision making
    return base_reading + detail_reading + decision_time

def simulate_navigation_delay():
    """Simulate realistic navigation delays between pages"""
    click_delay = random.uniform(0.5, 2.0)  # Time to click
    page_load_wait = random.uniform(1.0, 3.0)  # Wait for page load
    return click_delay + page_load_wait

def simulate_search_behavior(session, base_url):
    """Simulate realistic search behavior before scraping"""
    stealth_mode = os.environ.get("STEALTH_MODE", "false").lower() == "true"
    if not stealth_mode:
        return  # Skip simulation in normal mode
    
    log_structured_message("INFO", "Simulating search behavior for stealth")
    
    try:
        # Simulate search query
        search_query = random.choice(SEARCH_QUERIES)
        search_url = f"{base_url.replace('/list/', '/search/')}?q={search_query}"
        
        # Add delay before search
        time.sleep(random.uniform(2, 5))
        
        response = session.get(search_url, timeout=15)
        if response.status_code == 200:
            log_structured_message("INFO", "Search simulation successful", query=search_query)
            
            # Simulate reading search results
            time.sleep(simulate_navigation_delay())
            
            # Sometimes navigate back to main listing
            if random.random() < 0.7:  # 70% chance to go back to listings
                session.get(base_url, timeout=15)
                log_structured_message("INFO", "Navigated back to main listings")
                time.sleep(simulate_navigation_delay())
        
    except Exception as e:
        log_structured_message("WARNING", "Search simulation failed", error=str(e))

def simulate_browsing_patterns(session, all_urls, entry_point="default"):
    """Simulate realistic browsing patterns based on entry point"""
    stealth_mode = os.environ.get("STEALTH_MODE", "false").lower() == "true"
    if not stealth_mode:
        return all_urls  # Return unchanged in normal mode
    
    base_url = "https://www.homes.co.jp"
    entry_path = ENTRY_POINTS.get(entry_point, ENTRY_POINTS["default"])
    entry_url = f"{base_url}{entry_path}"
    
    log_structured_message("INFO", "Simulating browsing patterns", 
                         entry_point=entry_point, entry_url=entry_url)
    
    try:
        # Start from the specified entry point
        session.headers['Sec-Fetch-Site'] = 'none'  # Direct navigation
        response = session.get(entry_url, timeout=15)
        
        if response.status_code == 200:
            # Simulate reading the entry page
            time.sleep(simulate_navigation_delay())
            
            # Update referer for subsequent requests
            session.headers['Referer'] = entry_url
            session.headers['Sec-Fetch-Site'] = 'same-origin'
            
            # Sometimes browse additional pages before starting real scraping
            if random.random() < 0.4:  # 40% chance to browse more
                additional_pages = random.randint(1, 2)
                for i in range(additional_pages):
                    page_num = random.randint(2, 5)
                    browse_url = f"{base_url}/mansion/chuko/tokyo/chofu-city/list/?page={page_num}"
                    
                    time.sleep(simulate_navigation_delay())
                    browse_response = session.get(browse_url, timeout=15)
                    
                    if browse_response.status_code == 200:
                        log_structured_message("INFO", "Browsed additional page", page=page_num)
                        time.sleep(simulate_navigation_delay())
                        session.headers['Referer'] = browse_url
            
            # Randomize the order of URLs for more natural behavior
            randomized_urls = all_urls.copy()
            random.shuffle(randomized_urls)
            
            return randomized_urls
            
    except Exception as e:
        log_structured_message("WARNING", "Browsing simulation failed", error=str(e))
    
    return all_urls  # Return original list if simulation fails

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
        
        log_structured_message("INFO", "Detection metrics sent", 
                             risk_level=risk_level, 
                             indicators_count=len(indicators),
                             session_id=session_id)
        
    except Exception as e:
        log_structured_message("ERROR", "Failed to send detection metrics", error=str(e))

def discover_tokyo_areas():
    """Discover all Tokyo area URLs from the city listing page"""
    stealth_mode = os.environ.get("STEALTH_MODE", "false").lower() == "true"
    session = create_stealth_session(stealth_mode=stealth_mode)
    
    city_listing_url = "https://www.homes.co.jp/mansion/chuko/tokyo/city/"
    
    try:
        log_structured_message("INFO", "Discovering Tokyo areas", url=city_listing_url)
        
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
            log_structured_message("INFO", "Using fallback area list, validating URLs")
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
        
        log_structured_message("INFO", "Tokyo areas discovered", 
                             total_areas=len(unique_areas), 
                             areas=unique_areas[:10])  # Log first 10 for brevity
        
        return unique_areas
        
    except Exception as e:
        log_structured_message("ERROR", "Failed to discover Tokyo areas", error=str(e))
        
        # Return fallback list if discovery fails
        fallback_areas = [
            'chofu-city', 'shibuya-ku', 'shinjuku-ku', 'setagaya-ku', 
            'minato-ku', 'chiyoda-ku', 'nerima-ku', 'suginami-ku'
        ]
        log_structured_message("WARNING", "Using fallback area list", areas=fallback_areas)
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
    
    log_structured_message("INFO", "Daily area distribution calculated", 
                         session_id=session_id, 
                         date_key=date_key,
                         assigned_areas=assigned_areas,
                         total_sessions=len(session_order),
                         total_areas=len(all_areas))
    
    return assigned_areas

def get_stealth_session_config():
    """Get stealth mode configuration from environment variables"""
    return {
        'session_id': os.environ.get('SESSION_ID', f'session-{int(time.time())}'),
        'max_properties': int(os.environ.get('MAX_PROPERTIES', '50')),
        'entry_point': os.environ.get('ENTRY_POINT', 'default'),
        'stealth_mode': os.environ.get('STEALTH_MODE', 'false').lower() == 'true'
    }

# Global circuit breaker and session pool instances
circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
session_pool = SessionPool(pool_size=3)


def extract_listing_urls_from_html(html_content):
    """Extract unique listing URLs from HTML content"""
    relative_urls = re.findall(r'/mansion/b-\d+/', html_content)
    unique_listings = set()
    
    for url in relative_urls:
        absolute_url = f"https://www.homes.co.jp{url.rstrip('/')}"
        unique_listings.add(absolute_url)
    
    return list(unique_listings)

def collect_area_listing_urls(area_name, max_pages=None, session=None, stealth_config=None):
    """Collect listing URLs from a specific Tokyo area"""
    base_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{area_name}/list"
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    
    # Use provided session or create new one
    if session is None:
        session = create_stealth_session(stealth_mode=stealth_mode)
        should_close_session = True
    else:
        should_close_session = False
    
    all_links = set()
    
    log_structured_message("INFO", "Starting area URL collection", 
                         area=area_name, base_url=base_url, stealth_mode=stealth_mode)
    
    try:
        # Step 1: Get page 1 to establish session
        print(f"=== Collecting from {area_name} (page 1) ===")
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
            log_structured_message("INFO", "Page limit applied", 
                                 area=area_name, total_pages=total_pages, max_pages=max_pages)
        
        log_structured_message("INFO", "Area pagination info parsed", 
                             area=area_name, total_listings=total_count, 
                             total_pages=total_pages, max_page=max_page)
        
        # Extract listings from page 1
        page1_listings = extract_listing_urls_from_html(response.text)
        all_links.update(page1_listings)
        print(f"{area_name} page 1: Found {len(page1_listings)} listings")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages with stealth timing
        for page_num in range(2, max_page + 1):
            print(f"=== Collecting from {area_name} (page {page_num}) ===")
            
            # Use human-like delays in stealth mode
            if stealth_mode:
                delay = simulate_navigation_delay() + random.uniform(2, 5)
            else:
                delay = random.uniform(1, 3)
            
            time.sleep(delay)
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    log_structured_message("WARNING", "Failed to access area page", 
                                         area=area_name, page=page_num, status_code=response.status_code)
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    log_structured_message("ERROR", "Anti-bot protection triggered", 
                                         area=area_name, page=page_num)
                    break
                
                page_listings = extract_listing_urls_from_html(response.text)
                all_links.update(page_listings)
                print(f"{area_name} page {page_num}: Found {len(page_listings)} listings")
                
                session.headers['Referer'] = page_url
                log_structured_message("INFO", "Area page scraped successfully", 
                                     area=area_name, page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                log_structured_message("ERROR", "Error fetching area page", 
                                     area=area_name, page=page_num, error=str(e))
                continue
        
        area_links_list = list(all_links)
        log_structured_message("INFO", "Area URL collection completed", 
                             area=area_name, total_unique_links=len(area_links_list))
        
        return area_links_list
        
    except Exception as e:
        log_structured_message("ERROR", "Error in area URL collection", area=area_name, error=str(e))
        return []
    
    finally:
        if should_close_session:
            session.close()

def collect_multiple_areas_urls(areas, stealth_config=None):
    """Collect listing URLs from multiple Tokyo areas in one session"""
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    session = create_stealth_session(stealth_mode=stealth_mode)
    all_urls = []
    
    log_structured_message("INFO", "Starting multi-area URL collection", 
                         areas=areas, total_areas=len(areas), stealth_mode=stealth_mode)
    
    try:
        # Simulate search behavior once at the beginning in stealth mode
        if stealth_mode and areas:
            first_area_url = f"https://www.homes.co.jp/mansion/chuko/tokyo/{areas[0]}/list"
            simulate_search_behavior(session, first_area_url)
        
        for i, area in enumerate(areas):
            print(f"\n=== Processing area {i+1}/{len(areas)}: {area} ===")
            
            # Add delay between areas in stealth mode
            if stealth_mode and i > 0:
                area_transition_delay = simulate_navigation_delay() + random.uniform(5, 15)
                print(f"Stealth mode: Area transition delay {area_transition_delay:.1f}s")
                time.sleep(area_transition_delay)
            
            # Collect ALL pages from this area (no limit)
            area_urls = collect_area_listing_urls(area, max_pages=None, session=session, stealth_config=stealth_config)
            all_urls.extend(area_urls)
            
            print(f"Area {area}: Collected {len(area_urls)} URLs (Total: {len(all_urls)})")
        
        # Apply browsing patterns in stealth mode
        if stealth_mode and stealth_config:
            entry_point = stealth_config.get('entry_point', 'default')
            all_urls = simulate_browsing_patterns(session, all_urls, entry_point)
        
        log_structured_message("INFO", "Multi-area URL collection completed", 
                             total_areas=len(areas), total_urls=len(all_urls), stealth_mode=stealth_mode)
        
        return all_urls, session
        
    except Exception as e:
        log_structured_message("ERROR", "Error in multi-area URL collection", error=str(e))
        session.close()
        raise

def collect_all_listing_urls(base_url, max_pages=10, stealth_config=None):
    """Legacy function - collect listing URLs from single area (for backward compatibility)"""
    stealth_mode = stealth_config and stealth_config.get('stealth_mode', False)
    session = create_stealth_session(stealth_mode=stealth_mode)
    all_links = set()
    
    # Simulate search behavior in stealth mode
    if stealth_mode:
        simulate_search_behavior(session, base_url)
    
    log_structured_message("INFO", "Starting listing URL collection", 
                         base_url=base_url, stealth_mode=stealth_mode)
    
    try:
        # Step 1: Get page 1 to establish session
        print(f"=== Collecting listing URLs from page 1 ===")
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
        
        log_structured_message("INFO", "Pagination info parsed", 
                             total_listings=total_count, max_page=max_page)
        
        # Extract listings from page 1
        page1_listings = extract_listing_urls_from_html(response.text)
        all_links.update(page1_listings)
        print(f"Page 1: Found {len(page1_listings)} listings")
        
        # Set referer for subsequent requests
        session.headers['Referer'] = base_url
        
        # Step 2: Get remaining pages with stealth timing
        for page_num in range(2, max_page + 1):
            print(f"=== Collecting listings from page {page_num} ===")
            
            # Use human-like delays in stealth mode
            if stealth_mode:
                delay = simulate_navigation_delay() + random.uniform(3, 8)
            else:
                delay = random.uniform(2, 4)
            
            time.sleep(delay)
            page_url = f"{base_url}/?page={page_num}"
            
            try:
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    log_structured_message("WARNING", "Failed to access page", 
                                         page=page_num, status_code=response.status_code)
                    continue
                
                if "pardon our interruption" in response.text.lower():
                    log_structured_message("ERROR", "Anti-bot protection triggered", page=page_num)
                    break
                
                page_listings = extract_listing_urls_from_html(response.text)
                all_links.update(page_listings)
                print(f"Page {page_num}: Found {len(page_listings)} listings")
                
                session.headers['Referer'] = page_url
                log_structured_message("INFO", "Page scraped successfully", 
                                     page=page_num, listings_found=len(page_listings))
                
            except Exception as e:
                log_structured_message("ERROR", "Error fetching page", 
                                     page=page_num, error=str(e))
                continue
        
        all_links_list = list(all_links)
        
        # Apply browsing patterns in stealth mode
        if stealth_mode and stealth_config:
            entry_point = stealth_config.get('entry_point', 'default')
            all_links_list = simulate_browsing_patterns(session, all_links_list, entry_point)
        
        log_structured_message("INFO", "URL collection completed", 
                             total_unique_links=len(all_links_list),
                             stealth_mode=stealth_mode)
        
        return all_links_list, session
        
    except Exception as e:
        log_structured_message("ERROR", "Error in URL collection", error=str(e))
        session.close()
        raise

def extract_property_details_with_circuit_breaker(property_url, referer_url, retries=3):
    """Extract detailed property information using circuit breaker pattern"""
    session = None
    try:
        # Get session from pool
        session = session_pool.get_session()
        
        # Use circuit breaker to protect the scraping operation
        result = circuit_breaker.call(
            _extract_property_details_core,
            session, property_url, referer_url, retries
        )
        
        return result
        
    except Exception as e:
        error_category = categorize_error(e)
        log_structured_message("ERROR", "Circuit breaker protected extraction failed", 
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


def extract_property_images(soup, session, base_url, bucket=None, property_id=None):
    """Extract property images and upload to S3, return S3 keys"""
    s3_keys = []
    image_urls = set()
    stealth_mode = os.environ.get("STEALTH_MODE", "false").lower() == "true"
    
    try:
        # Look for common image selectors on homes.co.jp
        selectors = [
            'img[src*="photo"]',
            '.photo img',
            '.gallery img',
            '.image-gallery img',
            'img[alt*="写真"]',
            'img[alt*="画像"]',
            '.property-image img',
            'img[src*="mansion"]'
        ]
        
        for selector in selectors:
            for img in soup.select(selector):
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    # Convert relative URLs to absolute
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = base_url + src
                    elif not src.startswith('http'):
                        src = base_url + '/' + src.lstrip('/')
                    
                    # Filter out small images and icons
                    if any(exclude in src.lower() for exclude in ['icon', 'logo', 'btn', 'arrow', 'small']):
                        continue
                    
                    image_urls.add(src)
        
        # Download images and upload to S3 (or just collect URLs if no bucket)
        for i, img_url in enumerate(list(image_urls)[:5]):  # Limit to first 5 images
            try:
                img_response = session.get(img_url, timeout=10)
                if img_response.status_code == 200 and 'image' in img_response.headers.get('content-type', ''):
                    content_type = img_response.headers.get('content-type', 'image/jpeg')
                    
                    # Upload to S3 if bucket provided, otherwise skip
                    if bucket and property_id:
                        s3_key = upload_image_to_s3(
                            img_response.content, 
                            bucket, 
                            property_id, 
                            i, 
                            content_type
                        )
                        if s3_key:
                            s3_keys.append(s3_key)
                    else:
                        # Local mode - just store the original URL for reference
                        s3_keys.append(f"local_image_{i}_{img_url.split('/')[-1]}")
                    
                    # Small delay between image downloads
                    delay = random.uniform(0.5, 1.5)
                    if stealth_mode:
                        delay += random.uniform(1, 3)  # Extra delay in stealth mode for S3 uploads
                    time.sleep(delay)
                    
            except Exception as e:
                log_structured_message("WARNING", "Failed to download/upload image", 
                                     image_url=img_url, property_id=property_id, 
                                     image_index=i, error=str(e))
                continue
        
        return s3_keys
        
    except Exception as e:
        log_structured_message("ERROR", "Image extraction failed", 
                             property_id=property_id, error=str(e))
        return []

def _extract_property_details_core(session, property_url, referer_url, retries=3):
    """Core property extraction logic with enhanced error handling, stealth timing, and image capture"""
    last_error = None
    stealth_mode = os.environ.get("STEALTH_MODE", "false").lower() == "true"
    output_bucket = os.environ.get("OUTPUT_BUCKET")  # Check if S3 bucket is configured
    
    for attempt in range(retries + 1):
        try:
            # Set proper referer and add realistic delay
            session.headers['Referer'] = referer_url
            
            # Use human-like timing in stealth mode
            if stealth_mode:
                delay = simulate_human_reading_time()
                # Cap the delay to prevent extremely long waits
                delay = min(delay, 180)  # Max 3 minutes
                print(f"Stealth mode: Simulating {delay:.1f}s human reading time")
                time.sleep(delay)
            else:
                time.sleep(random.uniform(2, 5))
            
            print(f"Scraping: {property_url}")
            response = session.get(property_url, timeout=15)
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                if attempt == retries:
                    raise requests.exceptions.HTTPError(error_msg)
                # Exponential backoff with jitter
                backoff_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(backoff_time)
                continue
            
            if "pardon our interruption" in response.text.lower():
                raise Exception("Anti-bot protection detected")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            data = {"url": property_url}
            
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
                            if key and value and len(key) < 30:  # Reasonable key length
                                data[key] = value
                    break
            
            # Extract property ID from URL for S3 organization
            property_id = "unknown"
            id_match = re.search(r'/b-(\d+)/', property_url)
            if id_match:
                property_id = id_match.group(1)
                data["id"] = property_id
            
            # Extract property images and upload to S3 (if bucket configured)
            try:
                s3_keys = extract_property_images(
                    soup, session, "https://www.homes.co.jp", 
                    bucket=output_bucket, property_id=property_id
                )
                if s3_keys:
                    # Store S3 keys in photo_filenames field (pipe-separated)
                    data["photo_filenames"] = "|".join(s3_keys)
                    data["image_count"] = len(s3_keys)
                    log_structured_message("INFO", "Images processed", 
                                         url=property_url, property_id=property_id,
                                         image_count=len(s3_keys), 
                                         has_s3_bucket=bool(output_bucket))
            except Exception as e:
                log_structured_message("WARNING", "Image processing failed", 
                                     url=property_url, property_id=property_id, error=str(e))
            
            # Log successful extraction
            log_structured_message("INFO", "Property details extracted successfully", 
                                 url=property_url, fields_extracted=len(data))
            
            return data
            
        except Exception as e:
            last_error = e
            error_category = categorize_error(e, response if 'response' in locals() else None)
            
            log_structured_message("WARNING", f"Extraction attempt {attempt + 1} failed", 
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

def upload_image_to_s3(image_content, bucket, property_id, image_index, content_type="image/jpeg"):
    """Upload image content to S3 and return S3 key"""
    try:
        # Determine file extension based on content type
        if 'png' in content_type.lower():
            file_extension = '.png'
        elif 'gif' in content_type.lower():
            file_extension = '.gif'
        elif 'webp' in content_type.lower():
            file_extension = '.webp'
        else:
            file_extension = '.jpg'  # Default to JPEG
        
        # Generate current date for S3 path
        date_str = datetime.now().strftime('%Y-%m-%d')
        s3_key = f"raw/{date_str}/images/{property_id}_{image_index}{file_extension}"
        
        # Upload to S3
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=image_content,
            ContentType=content_type
        )
        
        log_structured_message("INFO", "Image uploaded to S3", 
                             s3_key=s3_key, property_id=property_id, 
                             image_index=image_index, content_type=content_type)
        return s3_key
        
    except Exception as e:
        log_structured_message("ERROR", "S3 image upload failed", 
                             property_id=property_id, image_index=image_index, 
                             error=str(e))
        return None

def upload_to_s3(file_path, bucket, s3_key):
    """Upload file to S3"""
    try:
        s3 = boto3.client("s3")
        s3.upload_file(file_path, bucket, s3_key)
        print(f"📤 Uploaded to s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        print(f"❌ S3 upload failed: {e}")
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
        
        log_structured_message("INFO", "CloudWatch metrics sent", 
                             success_count=success_count, 
                             error_count=error_count,
                             duration_seconds=duration_seconds)
        return True
        
    except Exception as e:
        log_structured_message("ERROR", "Failed to send CloudWatch metrics", error=str(e))
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

def log_structured_message(level, message, **kwargs):
    """Log structured message in JSON format"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        **kwargs
    }
    print(json.dumps(log_entry))

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

def main():
    """Main scraper function using HTTP with session flow and stealth capabilities"""
    job_start_time = datetime.now()
    
    # Get stealth configuration
    stealth_config = get_stealth_session_config()
    is_local_testing = not os.environ.get("OUTPUT_BUCKET")
    
    # Determine mode and limits
    if stealth_config['stealth_mode']:
        max_properties_limit = stealth_config['max_properties']
        mode_name = "STEALTH MODE"
        log_structured_message("INFO", "STEALTH MODE: Session-based distributed scraping", 
                             session_id=stealth_config['session_id'],
                             max_properties=max_properties_limit,
                             entry_point=stealth_config['entry_point'],
                             start_time=job_start_time.isoformat())
        print(f"🥷 STEALTH MODE - Session: {stealth_config['session_id']}, Max Properties: {max_properties_limit}")
    elif is_local_testing:
        max_properties_limit = 5
        mode_name = "LOCAL TESTING"
        log_structured_message("INFO", "LOCAL TESTING MODE: Limited to 5 listings", start_time=job_start_time.isoformat())
        print("🧪 LOCAL TESTING MODE - Processing only 5 listings for quick testing")
    else:
        max_properties_limit = 500  # Default limit for normal mode
        mode_name = "PRODUCTION"
        log_structured_message("INFO", "Starting HTTP scraper job", start_time=job_start_time.isoformat())
    
    error_count = 0
    success_count = 0
    session = None
    
    try:
        # Configuration
        date_key = datetime.now().strftime('%Y-%m-%d')
        
        # Step 0: Discover all Tokyo areas and get session assignment
        if stealth_config['stealth_mode']:
            print(f"\n🗖️ Discovering Tokyo areas and calculating session assignment...")
            all_tokyo_areas = discover_tokyo_areas()
            session_areas = get_daily_area_distribution(all_tokyo_areas, stealth_config['session_id'], date_key)
            
            if not session_areas:
                raise Exception(f"No areas assigned to session {stealth_config['session_id']}")
            
            print(f"🏆 Session {stealth_config['session_id']} assigned areas: {session_areas}")
            log_structured_message("INFO", "Session area assignment", 
                                 session_id=stealth_config['session_id'],
                                 assigned_areas=session_areas,
                                 total_tokyo_areas=len(all_tokyo_areas))
        else:
            # Fallback to single area for non-stealth mode
            session_areas = ["chofu-city"]
        
        # Step 1: Collect all listing URLs with stealth capabilities
        print(f"\n🔗 Collecting listing URLs from {len(session_areas)} areas ({mode_name})...")
        
        if len(session_areas) > 1:
            all_urls, session = collect_multiple_areas_urls(session_areas, stealth_config)
        else:
            # Single area fallback - collect all pages
            BASE_URL = f"https://www.homes.co.jp/mansion/chuko/tokyo/{session_areas[0]}/list"
            max_pages = 1 if is_local_testing else None  # No limit in production
            all_urls, session = collect_all_listing_urls(BASE_URL, max_pages, stealth_config)
        
        if not all_urls:
            raise Exception("No listing URLs found")
        
        # Only limit URLs in local testing mode
        if is_local_testing:
            all_urls = all_urls[:5]  # Only process first 5 listings for testing
            print(f"🧪 LIMITED TO {len(all_urls)} LISTINGS FOR LOCAL TESTING")
        else:
            # In production/stealth mode: scrape ALL properties found
            print(f"🚀 PROCESSING ALL {len(all_urls)} PROPERTIES FOUND")
            if stealth_config['stealth_mode']:
                print(f"🥷 STEALTH MODE: Using human-like delays for {len(all_urls)} properties")
        
        log_structured_message("INFO", "URL collection completed", total_urls=len(all_urls))
        
        # Step 2: Extract detailed information from each property with circuit breaker protection
        print(f"\n📋 Extracting details from {len(all_urls)} properties...")
        listings_data = []
        circuit_breaker_triggered = False
        response_times = []
        request_start_times = []
        
        # Use conservative threading - single thread in stealth mode
        if stealth_config['stealth_mode']:
            max_threads = 1  # Single-threaded for maximum stealth
            print("🥷 Using single-threaded extraction for stealth")
        else:
            max_threads = 2  # Conservative threading for normal mode
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            # Submit all tasks using circuit breaker enhanced function
            futures = {
                executor.submit(extract_property_details_with_circuit_breaker, url, BASE_URL): url 
                for url in all_urls
            }
            
            # Collect results with graceful degradation and detection monitoring
            for future in as_completed(futures):
                url = futures[future]
                request_start = time.time()
                try:
                    result = future.result()
                    request_end = time.time()
                    response_time = request_end - request_start
                    response_times.append(response_time)
                    
                    # Check if circuit breaker was triggered
                    if "circuit_breaker_state" in result and result["circuit_breaker_state"] == "OPEN":
                        circuit_breaker_triggered = True
                        log_structured_message("WARNING", "Circuit breaker triggered - degrading gracefully", 
                                             url=url, circuit_breaker_state=result["circuit_breaker_state"])
                    
                    # Validate and clean property data
                    if "error" not in result:
                        is_valid, validation_message = validate_property_data(result)
                        if not is_valid:
                            log_structured_message("WARNING", "Data validation failed", url=url, reason=validation_message)
                            result["validation_error"] = validation_message
                            error_count += 1
                        else:
                            success_count += 1
                    else:
                        error_count += 1
                    
                    listings_data.append(result)
                        
                except Exception as e:
                    error_category = categorize_error(e)
                    log_structured_message("ERROR", "Error processing property", 
                                         url=url, error=str(e), category=error_category.value)
                    error_count += 1
                    listings_data.append({
                        "url": url, 
                        "error": str(e),
                        "error_category": error_category.value
                    })
                    
                    # Implement graceful degradation if too many errors
                    if error_count > len(all_urls) * 0.5:  # More than 50% errors
                        log_structured_message("WARNING", "High error rate detected - considering early termination",
                                             error_rate=error_count / len(listings_data) if listings_data else 1.0,
                                             total_processed=len(listings_data),
                                             total_errors=error_count)
                        
                        # If circuit breaker is open and we have high errors, stop processing
                        if circuit_breaker_triggered and error_count > 10:
                            log_structured_message("ERROR", "Circuit breaker open with high error rate - stopping processing",
                                                 error_count=error_count, processed_count=len(listings_data))
                            break
                
                # Track response times for detection monitoring
                if len(response_times) % 10 == 0 and len(response_times) > 0:
                    # Check detection indicators every 10 requests
                    risk_level, indicators = check_detection_indicators(response_times, error_count, len(listings_data))
                    if risk_level != "LOW":
                        log_structured_message("WARNING", "Detection risk elevated", 
                                             risk_level=risk_level, 
                                             indicators=indicators,
                                             processed_count=len(listings_data))
                        
                        # Send detection metrics in stealth mode
                        if stealth_config.get('stealth_mode'):
                            send_detection_metrics(risk_level, indicators, stealth_config)
        
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
        
        log_structured_message("INFO", "Data saved locally", file_path=local_path)
        
        # Step 4: Upload to S3
        s3_upload_success = False
        output_bucket = os.environ.get("OUTPUT_BUCKET")
        s3_key = None
        
        if output_bucket and not is_local_testing:
            s3_key = f"scraper-output/{filename}"
            s3_upload_success = upload_to_s3(local_path, output_bucket, s3_key)
        elif is_local_testing:
            print("🧪 LOCAL TESTING: Skipping S3 upload")
            log_structured_message("INFO", "LOCAL TESTING: S3 upload skipped")
        else:
            log_structured_message("WARNING", "OUTPUT_BUCKET environment variable not set")
        
        # Step 5: Generate job summary
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP_SESSION_FLOW",
            "mode": mode_name,
            "stealth_mode": stealth_config['stealth_mode'],
            "session_id": stealth_config.get('session_id'),
            "entry_point": stealth_config.get('entry_point'),
            "max_properties_limit": max_properties_limit,
            "total_urls_found": len(all_urls),
            "successful_scrapes": success_count,
            "failed_scrapes": error_count,
            "total_records": len(listings_data),
            "output_file": filename,
            "s3_upload_success": s3_upload_success,
            "s3_key": s3_key,
            "status": "SUCCESS" if success_count > 0 else "FAILED"
        }
        
        write_job_summary(summary_data)
        
        # Step 6: Send CloudWatch metrics and final detection check
        if not is_local_testing:
            send_cloudwatch_metrics(success_count, error_count, duration, len(all_urls), stealth_config)
            
            # Final detection risk assessment
            if response_times:
                final_risk_level, final_indicators = check_detection_indicators(response_times, error_count, len(listings_data))
                log_structured_message("INFO", "Final detection risk assessment", 
                                     risk_level=final_risk_level, 
                                     indicators=final_indicators)
                
                if stealth_config.get('stealth_mode'):
                    send_detection_metrics(final_risk_level, final_indicators, stealth_config)
        else:
            log_structured_message("INFO", f"{mode_name}: Skipping CloudWatch metrics")
        
        log_structured_message("INFO", "HTTP scraper job completed successfully", **summary_data)
        
        print(f"\n✅ {mode_name} scraping completed successfully!")
        if stealth_config['stealth_mode']:
            print(f"🥷 Session: {stealth_config['session_id']}")
        print(f"📊 Results: {success_count} successful, {error_count} failed")
        print(f"⏱️ Duration: {duration:.1f} seconds")
        print(f"💾 Output: {local_path}")
        if s3_upload_success:
            print(f"☁️ S3: s3://{output_bucket}/{s3_key}")
        
    except Exception as e:
        job_end_time = datetime.now()
        duration = (job_end_time - job_start_time).total_seconds()
        
        summary_data = {
            "start_time": job_start_time.isoformat(),
            "end_time": job_end_time.isoformat(),
            "duration_seconds": duration,
            "scraper_type": "HTTP_SESSION_FLOW",
            "mode": locals().get('mode_name', 'UNKNOWN'),
            "stealth_mode": stealth_config.get('stealth_mode', False),
            "session_id": stealth_config.get('session_id'),
            "status": "ERROR",
            "error": str(e)
        }
        
        write_job_summary(summary_data)
        log_structured_message("ERROR", "HTTP scraper job failed", **summary_data)
        print(f"\n❌ Scraping failed: {e}")
        raise
    
    finally:
        # Clean up session pool
        session_pool.close_all()
        
        # Close the original session if it exists
        if session:
            session.close()

if __name__ == "__main__":
    main()