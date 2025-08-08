# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a comprehensive Tokyo Real Estate Investment Analysis System that scrapes property data from Homes.co.jp, analyzes investment potential using a 12-factor scoring algorithm, and provides a web dashboard for property discovery and user favorites management.

The backend is a serverless application using AWS Lambda functions written in Python, with DynamoDB for data storage and S3 for file storage. The infrastructure is defined in the `ai-stack.yaml` CloudFormation template.

The frontend is a single-page application (SPA) built with vanilla JavaScript that allows users to view, filter, and manage property listings.

## Folder Structure

```
/
├── .claude/
│   └── settings.local.json
├── .github/
│   └── workflows/
│       └── ai-ci.yml
├── front-end/
│   ├── .claude/
│   │   └── settings.local.json
│   ├── config/
│   │   └── constants.js
│   ├── core/
│   │   ├── api.js
│   │   ├── router.js
│   │   └── state.js
│   ├── features/
│   │   ├── auth/
│   │   │   ├── auth.css
│   │   │   ├── AuthManager.js
│   │   │   └── AuthModal.js
│   │   ├── favorites/
│   │   │   ├── favorites.css
│   │   │   ├── FavoritesManager.js
│   │   │   └── FavoritesView.js
│   │   ├── hidden/
│   │   │   ├── hidden.css
│   │   │   ├── HiddenManager.js
│   │   │   └── HiddenView.js
│   │   └── properties/
│   │       ├── properties.css
│   │       ├── PropertiesManager.js
│   │       └── PropertiesView.js
│   ├── shared/
│   │   ├── components/
│   │   │   ├── FilterDropdown.js
│   │   │   ├── Pagination.js
│   │   │   └── Table.js
│   │   ├── styles/
│   │   │   ├── base.css
│   │   │   ├── components.css
│   │   │   └── layout.css
│   │   └── utils/
│   │       ├── dom.js
│   │       ├── formatters.js
│   │       └── storage.js
│   ├── .frontend-bcrypt-layer-version
│   ├── backup-monolithic-scripts.html
│   ├── backup-monolithic-styles.html
│   ├── deploy-frontend.sh
│   ├── front-end-stack.yaml
│   ├── index.html
│   ├── main.js
│   ├── test_payload.json
│   └── test_remove.json
├── html/
│   ├── individual-homes-listing.html
│   └── listingspage.html
├── lambda/
│   ├── common/
│   │   ├── __init__.py
│   │   └── __pycache__/
│   ├── dashboard_api/
│   │   ├── app.py
│   │   ├── dashboard_api.zip
│   │   └── requirements.txt
│   ├── favorite_analyzer/
│   │   └── app.py
│   ├── favorites_api/
│   │   ├── app.py
│   │   ├── favorites_api.zip
│   │   └── requirements.txt
│   ├── legacy/
│   │   ├── daily_digest/
│   │   │   └── app.py
│   │   ├── dynamodb_writer/
│   │   │   └── app.py
│   │   ├── etl/
│   │   │   ├── app.py
│   │   │   └── __pycache__/
│   │   ├── llm_batch/
│   │   │   ├── app.py
│   │   │   └── requirements.txt
│   │   ├── prompt_builder/
│   │   │   ├── app.py
│   │   │   └── system_prompt.txt
│   │   ├── report_sender/
│   │   │   ├── app.py
│   │   │   ├── email_template.html
│   │   │   └── requirements.txt
│   │   ├── snapshot_generator/
│   │   │   └── app.py
│   │   └── util/
│   │       ├── __init__.py
│   │       ├── config.py
│   │       ├── metrics.py
│   │       └── __pycache__/
│   ├── login_user/
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── property_analyzer/
│   │   ├── app.py
│   │   ├── decimal_utils.py
│   │   ├── README.md
│   │   └── requirements.txt
│   ├── property_processor/
│   │   ├── app.py
│   │   ├── core_scraper.py
│   │   ├── dynamodb_utils.py
│   │   ├── requirements.txt
│   │   └── __pycache__/
│   ├── register_user/
│   │   ├── app.py
│   │   └── requirements.txt
│   └── url_collector/
│       ├── app.py
│       ├── core_scraper.py
│       ├── dynamodb_utils.py
│       ├── listings_debug.csv
│       ├── requirements.txt
│       ├── test_regression.py
│       ├── test_url_regex.py
│       └── __pycache__/
├── tests/
│   └── test_overview_parser.py
├── .bcrypt-layer-version
├── .gitignore
├── .layer-version
├── ai-stack.yaml
├── CLAUDE.md
├── clear-dydb.py
├── debug_api_gateway.py
├── deploy-ai.sh
├── GEMINI.md
├── test_favorites_fixed.py
├── test_favorites.py
├── test_fixed_endpoint.py
├── test_lambda_direct.json
├── test_payload.json
├── test_simple.json
├── test-response.json
├── trigger-lambda.sh
└── update-lambda.sh
```

## Key Commands

### Deployment Commands
- `./deploy-ai.sh` - Deploy the complete AI stack with Lambda functions, DynamoDB tables, and S3 resources
- `front-end/deploy-frontend.sh` - Deploy the web dashboard stack with S3 hosting and API Gateway
- `./update-lambda.sh <lambda_folder>` - Update individual Lambda functions without full redeployment

### Development Commands
- `./trigger-lambda.sh --function <function_name>` - Test individual Lambda functions with various parameters
- `python lambda/<function>/test_*.py` - Run specific test suites (e.g., URL regex tests)
- `./clear-dydb.py` - Clear DynamoDB tables for testing (use with caution)

### Configuration Management
- Environment variables: `AWS_REGION`, `STACK_NAME`, `LEAN_MODE`
- Stack names: `tokyo-real-estate-ai` (main), `tokyo-real-estate-dashboard` (frontend)
- Region: `ap-northeast-1` (Tokyo region for optimal performance)

## Architecture Overview

### Data Pipeline Flow
1. **URL Collection** (`url_collector`) - Discovers property listing URLs across Tokyo areas with parallel processing and rate limiting
2. **Property Processing** (`property_processor`) - Scrapes detailed property data including images and metadata
3. **Investment Analysis** (`property_analyzer`) - Calculates 12-factor investment scores and assigns verdicts (BUY_CANDIDATE/WATCH/REJECT)
4. **API Serving** (`dashboard_api`) - Provides filtered, paginated property data to the dashboard
5. **User Management** (`favorites_api`, `register_user`, `login_user`) - Handles user authentication and favorites

### Key Data Stores
- **Properties Table** (`tokyo-real-estate-ai-analysis-db`) - Main property data with composite keys (property_id, sort_key)
- **URL Tracking Table** (`tokyo-real-estate-ai-urls`) - Tracks discovered URLs and processing status
- **User Tables** - Authentication (`users`) and favorites (`user-favorites`) management
- **S3 Bucket** (`tokyo-real-estate-ai-data`) - Property images and CSV exports

### Scoring Algorithm
The property analyzer uses 12 scoring components:
- Ward Discount (0-25 pts) - Price vs ward median comparison
- Building Discount (0-10 pts) - Price vs same building median
- Comps Consistency (0-10 pts) - Price consistency within ward
- Condition (0-7 pts) - Building age assessment
- Size Efficiency (0-4 pts) - Optimal size range scoring
- Plus 7 additional factors including location, renovation potential, and data quality penalties

## Development Patterns

### Lambda Function Structure
All Lambda functions follow consistent patterns:
- `app.py` - Main handler with comprehensive error handling
- `requirements.txt` - Python dependencies (auto-installed during deployment)
- Shared modules: `util/`, `analysis/`, `schemas/` for code reuse
- Rate limiting and session management for web scraping functions

### Error Handling
- Detailed error categorization (rate limiting, parsing, network issues)
- Automatic retries with exponential backoff
- Dead letter queues for failed function executions
- CloudWatch logging with structured error reporting

### Performance Optimizations
- ThreadPoolExecutor for concurrent operations (configurable MAX_WORKERS)
- Session pooling with header rotation to avoid anti-bot detection
- Batch DynamoDB operations to reduce API calls
- Runtime limits and memory configuration per function type

## Common Development Tasks

### Adding New Analysis Factors
1. Modify scoring logic in `lambda/property_analyzer/app.py`
2. Update the README documentation with new factor details
3. Test with limited dataset using `--days-back` parameter

### Updating Web Scraping Logic
1. Core scraping utilities in `lambda/property_processor/core_scraper.py`
2. URL pattern matching in `lambda/url_collector/core_scraper.py`
3. Test regex patterns with `lambda/url_collector/test_url_regex.py`

### Dashboard Modifications
1. Frontend code in `front-end/`
2. Backend API in `lambda/dashboard_api/app.py`
3. Deploy dashboard with updated API endpoint using `front-end/deploy-frontend.sh`

### Infrastructure Changes
1. Main stack: `ai-stack.yaml` - Core Lambda functions and databases
2. Dashboard stack: `front-end/front-end-stack.yaml` - Web hosting and API Gateway
3. Both stacks support parameter overrides for different environments

## Testing and Debugging

### Function Testing
Use `./trigger-lambda.sh` with appropriate parameters:
- URL Collector: `--function url-collector --areas "chofu-city"`
- Property Processor: `--function property-processor --max-properties 5`
- Property Analyzer: `--function property-analyzer --days-back 7 --sync`

### Data Validation
- Properties require `sort_key='META'` for analysis processing
- URLs are validated against Homes.co.jp patterns before processing
- Image URLs are verified and stored with fallback handling

### Performance Monitoring
- CloudWatch metrics for Lambda duration, memory usage, and error rates
- DynamoDB capacity monitoring for read/write operations
- S3 storage costs for property images and data exports

## Security Considerations

### API Authentication
- JWT-based user authentication for favorites and user-specific features
- bcrypt password hashing with dedicated Lambda layer
- CORS configuration for browser-based dashboard access

### Data Protection
- No sensitive user data is logged or exposed in error messages
- Property images are served through presigned S3 URLs with expiration
- Rate limiting prevents abuse of scraping endpoints

### AWS Permissions
- Least-privilege IAM roles for each Lambda function
- Separate execution roles for scraping vs API functions
- SecretsManager integration for OpenAI API keys (used in future analysis features)
