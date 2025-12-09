#!/bin/bash
# Local testing script for scraper components
# Tests the core scraping logic without Lambda/DynamoDB

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

echo "🧪 Local Scraper Test"
echo "===================="

# Activate venv if it exists
if [ -d "$REPO_ROOT/.venv" ]; then
    echo "Using virtual environment..."
    source "$REPO_ROOT/.venv/bin/activate"
fi

# Check dependencies
echo "Checking dependencies..."
python3 -c "import requests, bs4" 2>/dev/null || {
    echo "❌ Missing dependencies. Install with:"
    echo "   pip install requests beautifulsoup4 lxml"
    exit 1
}

echo ""
echo "Testing Redfin scraper..."
echo ""

python3 << 'EOF'
import sys
import json
import os

sys.path.insert(0, 'workers/url_collector')

from core_scraper import create_session, collect_redfin_listings, get_target_cities

# Load config from repo root
config_path = os.path.join(os.getcwd(), '..', 'config.json')
with open(config_path) as f:
    config = json.load(f)

# Create a simple logger
class SimpleLogger:
    def info(self, msg): print(f"INFO: {msg}")
    def debug(self, msg): print(f"DEBUG: {msg}")
    def warning(self, msg): print(f"WARN: {msg}")
    def error(self, msg): print(f"ERROR: {msg}")

logger = SimpleLogger()

print("Creating session (curl_cffi with Chrome impersonation)...")
session = create_session(logger)

print("\nGetting target cities from config...")
cities = get_target_cities(config, logger)
print(f"Target cities: {cities}")

if cities:
    city_info = cities[0]
    city_name = city_info['city']
    state_code = city_info['state']
    city_id = city_info.get('city_id', 0)

    print(f"\nTesting Redfin URL collection for: {city_name}, {state_code}")
    print(f"Search URL: https://www.redfin.com/city/{city_id}/{state_code}/{city_name}")

    print("\nFetching first 2 pages of listings...")
    listings = collect_redfin_listings(
        city=city_name,
        state=state_code,
        max_pages=2,  # Test 2 pages
        city_id=city_id,
        session=session,
        logger=logger
    )

    print(f"\n✅ Found {len(listings)} listings")

    if listings:
        print("\nSample listings:")
        for i, listing in enumerate(listings[:5]):
            price = listing.get('price', 0)
            if isinstance(price, int) and price > 0:
                price = f"${price:,}"
            else:
                price = "N/A"
            print(f"  {i+1}. {listing.get('url', 'N/A')[:70]}...")
            print(f"      Price: {price}, Address: {listing.get('address', 'N/A')}")
else:
    print("No target cities configured!")

print("\n✨ Local test complete!")
EOF
