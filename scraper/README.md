
# Real Estate Scraper

This is a sophisticated HTTP-based scraper designed to collect property data from `homes.co.jp`. It includes advanced features like stealth browsing, session management, a circuit breaker for reliability, and integration with AWS for data storage and monitoring.

## Features

*   **Multiple Scraping Modes:**
    *   `normal`: Standard, high-speed scraping.
    *   `testing`: A lightweight mode for quick tests, limited to a small number of properties.
    *   `stealth`: A slower, more human-like browsing mode to avoid detection.
*   **Session Management:** Uses a pool of rotating sessions with varied browser profiles to mimic real user behavior.
*   **Circuit Breaker:** Automatically halts requests when a high error rate is detected, preventing IP bans and gracefully handling site interruptions.
*   **AWS Integration:** Can upload scraped data and images to S3 and send performance metrics to CloudWatch.
*   **Dynamic Area Discovery:** Can automatically discover and distribute scraping tasks across all areas in Tokyo.

## Dependencies

The following Python libraries are required to run the scraper:

*   `pandas`
*   `requests`
*   `beautifulsoup4`
*   `boto3`
*   `Pillow`

You can install them using pip:
```bash
pip install pandas requests beautifulsoup4 boto3 Pillow
```

## How to Run

The scraper is run from the command line and can be configured using arguments and environment variables.

### Basic Usage

```bash
python3 scrape.py
```

### Scraping Modes

You can specify the scraping mode using the `--mode` flag.

*   **Normal Mode:**
    ```bash
    python3 scrape.py --mode normal --max-properties 100 --areas "shibuya-ku,shinjuku-ku"
    ```

*   **Testing Mode:** (Runs with a hard limit of 5 properties for quick validation)
    ```bash
    python3 scrape.py --mode testing
    ```

*   **Stealth Mode:** (Uses human-like delays and browsing patterns)
    ```bash
    python3 scrape.py --mode stealth --max-properties 50
    ```

### Command-Line Arguments

*   `--mode`: The scraping mode (`normal`, `testing`, `stealth`). Default: `normal`.
*   `--max-properties`: The maximum number of properties to scrape.
*   `--output-bucket`: The S3 bucket to upload the results to.
*   `--max-threads`: The number of concurrent threads to use for scraping.
*   `--areas`: A comma-separated list of Tokyo areas to scrape (e.g., `"chofu-city,shibuya-ku"`).

### Environment Variables

The scraper can also be configured using the following environment variables:

*   `MODE`
*   `MAX_PROPERTIES`
*   `OUTPUT_BUCKET`
*   `MAX_THREADS`
*   `AREAS`
*   `SESSION_ID` (Used in stealth mode to identify the scraping session)
*   `ENTRY_POINT` (Used in stealth mode to simulate different user entry points)

