#!/usr/bin/env python3
"""
Test script to compare different HTTP clients for scraping realtor.com
"""
import time
import random

TEST_URL = "https://www.realtor.com/realestateandhomes-search/Paonia_CO"

def test_requests():
    """Test with plain requests library"""
    print("\n" + "="*60)
    print("Testing: requests library")
    print("="*60)

    import requests

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        session = requests.Session()
        session.headers.update(headers)

        response = session.get(TEST_URL, timeout=30)

        print(f"Status Code: {response.status_code}")
        print(f"Response Length: {len(response.text)} chars")

        # Check for listings
        if 'realestateandhomes-detail' in response.text:
            import re
            listings = re.findall(r'href="(/realestateandhomes-detail/[^"]+)"', response.text)
            unique_listings = list(set(listings))
            print(f"SUCCESS: Found {len(unique_listings)} unique listing URLs")
            if unique_listings:
                print(f"Sample: {unique_listings[0][:80]}...")
            return True
        elif response.status_code == 403:
            print("BLOCKED: 403 Forbidden")
        elif response.status_code == 429:
            print("BLOCKED: 429 Too Many Requests")
        elif 'captcha' in response.text.lower() or 'challenge' in response.text.lower():
            print("BLOCKED: Captcha/Challenge detected")
        else:
            print(f"FAILED: No listings found in response")
            print(f"HTML snippet: {response.text[:500]}...")
        return False

    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_curl_cffi():
    """Test with curl_cffi library (browser impersonation)"""
    print("\n" + "="*60)
    print("Testing: curl_cffi with Chrome impersonation")
    print("="*60)

    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        print("ERROR: curl_cffi not installed. Run: pip install curl_cffi")
        return False

    try:
        # Create session with browser impersonation
        session = curl_requests.Session(impersonate="chrome120")

        response = session.get(TEST_URL, timeout=30)

        print(f"Status Code: {response.status_code}")
        print(f"Response Length: {len(response.text)} chars")

        # Check for listings
        if 'realestateandhomes-detail' in response.text:
            import re
            listings = re.findall(r'href="(/realestateandhomes-detail/[^"]+)"', response.text)
            unique_listings = list(set(listings))
            print(f"SUCCESS: Found {len(unique_listings)} unique listing URLs")
            if unique_listings:
                print(f"Sample: {unique_listings[0][:80]}...")
            return True
        elif response.status_code == 403:
            print("BLOCKED: 403 Forbidden")
        elif response.status_code == 429:
            print("BLOCKED: 429 Too Many Requests")
        elif 'captcha' in response.text.lower() or 'challenge' in response.text.lower():
            print("BLOCKED: Captcha/Challenge detected")
        else:
            print(f"FAILED: No listings found in response")
            print(f"HTML snippet: {response.text[:500]}...")
        return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_curl_cffi_multiple_pages():
    """Test fetching multiple pages with curl_cffi"""
    print("\n" + "="*60)
    print("Testing: curl_cffi - Multiple pages")
    print("="*60)

    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        print("ERROR: curl_cffi not installed")
        return False

    try:
        session = curl_requests.Session(impersonate="chrome120")

        all_listings = []
        for page in range(1, 4):  # Test 3 pages
            if page == 1:
                url = TEST_URL
            else:
                url = f"{TEST_URL}/pg-{page}"

            print(f"\nFetching page {page}: {url}")

            # Random delay between requests
            if page > 1:
                delay = random.uniform(2, 5)
                print(f"Waiting {delay:.1f}s...")
                time.sleep(delay)

            response = session.get(url, timeout=30)
            print(f"Status: {response.status_code}, Length: {len(response.text)}")

            if response.status_code != 200:
                print(f"BLOCKED on page {page}")
                break

            import re
            listings = re.findall(r'href="(/realestateandhomes-detail/[^"]+)"', response.text)
            unique_listings = list(set(listings))
            all_listings.extend(unique_listings)
            print(f"Found {len(unique_listings)} listings on this page")

        all_unique = list(set(all_listings))
        print(f"\nTotal unique listings across all pages: {len(all_unique)}")
        return len(all_unique) > 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_playwright():
    """Test with Playwright (real browser)"""
    print("\n" + "="*60)
    print("Testing: Playwright with Chromium")
    print("="*60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    try:
        with sync_playwright() as p:
            # Launch browser (headless)
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            print(f"Navigating to {TEST_URL}...")
            response = page.goto(TEST_URL, wait_until='networkidle', timeout=60000)

            status = response.status if response else 'unknown'
            print(f"Status Code: {status}")

            html = page.content()
            print(f"Response Length: {len(html)} chars")

            # Check for listings
            if 'realestateandhomes-detail' in html:
                import re
                listings = re.findall(r'href="(/realestateandhomes-detail/[^"]+)"', html)
                unique_listings = list(set(listings))
                print(f"SUCCESS: Found {len(unique_listings)} unique listing URLs")
                if unique_listings:
                    print(f"Sample: {unique_listings[0][:80]}...")
                browser.close()
                return True
            elif status == 403:
                print("BLOCKED: 403 Forbidden")
            elif status == 429:
                print("BLOCKED: 429 Too Many Requests")
            elif 'captcha' in html.lower() or 'challenge' in html.lower():
                print("BLOCKED: Captcha/Challenge detected")
                # Save HTML for debugging
                with open('/tmp/playwright_response.html', 'w') as f:
                    f.write(html)
                print("Saved response to /tmp/playwright_response.html")
            else:
                print(f"FAILED: No listings found in response")
                print(f"HTML snippet: {html[:500]}...")

            browser.close()
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_playwright_multiple_pages():
    """Test fetching multiple pages with Playwright"""
    print("\n" + "="*60)
    print("Testing: Playwright - Multiple pages")
    print("="*60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed")
        return False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            all_listings = []
            for pg in range(1, 4):  # Test 3 pages
                if pg == 1:
                    url = TEST_URL
                else:
                    url = f"{TEST_URL}/pg-{pg}"

                print(f"\nFetching page {pg}: {url}")

                # Random delay between requests
                if pg > 1:
                    delay = random.uniform(3, 6)
                    print(f"Waiting {delay:.1f}s...")
                    time.sleep(delay)

                response = page.goto(url, wait_until='networkidle', timeout=60000)
                status = response.status if response else 'unknown'
                html = page.content()
                print(f"Status: {status}, Length: {len(html)}")

                if status != 200:
                    print(f"BLOCKED on page {pg}")
                    break

                import re
                listings = re.findall(r'href="(/realestateandhomes-detail/[^"]+)"', html)
                unique_listings = list(set(listings))
                all_listings.extend(unique_listings)
                print(f"Found {len(unique_listings)} listings on this page")

            browser.close()

            all_unique = list(set(all_listings))
            print(f"\nTotal unique listings across all pages: {len(all_unique)}")
            return len(all_unique) > 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("Realtor.com Scraper Test")
    print("Target:", TEST_URL)

    # Test 1: Plain requests
    requests_ok = test_requests()

    # Small delay between tests
    time.sleep(2)

    # Test 2: curl_cffi single page
    curl_ok = test_curl_cffi()

    # Test 3: Playwright single page
    time.sleep(2)
    playwright_ok = test_playwright()

    # Test 4: Playwright multiple pages (only if single page worked)
    if playwright_ok:
        time.sleep(2)
        test_playwright_multiple_pages()

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"requests:   {'PASS' if requests_ok else 'FAIL'}")
    print(f"curl_cffi:  {'PASS' if curl_ok else 'FAIL'}")
    print(f"playwright: {'PASS' if playwright_ok else 'FAIL'}")
