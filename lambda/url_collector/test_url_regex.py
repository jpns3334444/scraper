#!/usr/bin/env python3
# test_url_regex.py
import csv, sys, argparse, pathlib, collections
from core_scraper import (
    extract_listing_urls_from_html,
    extract_listings_with_prices_from_html
)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--html",
        default="listingspage.html",
        help="Path to sample HTML page"
    )
    parser.add_argument(
        "--out",
        default="listings_debug.csv",
        help="CSV file to write full listing dump"
    )
    args = parser.parse_args()

    html_path = pathlib.Path(args.html)
    if not html_path.exists():
        print(f"❌  File not found: {html_path}")
        sys.exit(1)

    html_text = html_path.read_text(encoding="utf-8")

    urls = extract_listing_urls_from_html(html_text)
    if not urls:
        print("❌  extract_listing_urls_from_html() returned 0 rows")
        sys.exit(1)

    listings = extract_listings_with_prices_from_html(html_text)
    if not listings:
        print("❌  extract_listings_with_prices_from_html() returned 0 rows")
        sys.exit(1)

    # duplicate detection
    counter = collections.Counter(l["url"] for l in listings)
    dupes = {u for u, c in counter.items() if c > 1}
    if dupes:
        print(f"⚠️  Duplicate URLs detected: {len(dupes)}")

    # write CSV
    out_path = pathlib.Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "price", "price_text", "duplicate"])
        for row in listings:
            w.writerow([
                row["url"],
                row["price"],
                row["price_text"],
                "yes" if row["url"] in dupes else "no"
            ])

    zeros = sum(1 for l in listings if l["price"] == 0)

    print(f"URLs found (basic): {len(urls)}")
    print(f"Listings found (with prices): {len(listings)}   zero-price rows: {zeros}")

    # sanity expectation (adjust if needed)
    if not (40 <= len(listings) <= 120):
        print("⚠️  Unexpected listing count; double-check HTML sample.")
    
    # Show a sample of the rows still missing a price
    if zeros:
        print("\nSample zero-price URLs (first 10):")
        zero_price_listings = [l for l in listings if l["price"] == 0]
        for row in zero_price_listings[:10]:
            print("  •", row["url"])
    
    print(f"\nFull dump written to {out_path}")
    sys.exit(0)

if __name__ == "__main__":
    main()