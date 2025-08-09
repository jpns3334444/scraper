# CLAUDE.md

## READ THIS FIRST

- **All constants and settings are in `./config.json` at the repo root.**
- This file is the **only source of truth** for stack names, table names, bucket names, Lambda names, regions, and other settings. Any new names, regions, etc must be added to the config.json, NO hardcoding variables/names.
- Always **load `config.json` before writing or editing any code**.
- **Do not hardcode** values that exist in `config.json`.
- If you can’t find a value, ask — do not invent defaults.

## Project Summary

Tokyo Real Estate Investment Analysis System:

* Scrapes property data from Homes.co.jp
* Analyzes with a 12-factor investment scoring algorithm
* After users favorite a property, it is sent to GPT5 api for analysis and returned to the user
* Backend: AWS Lambda (Python), DynamoDB, S3, CloudFormation
* Frontend: Vanilla JS SPA with modular components

## Key Rule

Whenever editing code, scripts, or templates:

1. Load `config.json`
2. Use values from it
3. Never inline constants


## Complete Repository Structure

```
/
├── config.json                       # Single source of truth for all configuration
├── scripts/
│   ├── cfg.sh                        # Bash configuration loader
│   ├── cfn-params.sh                 # CloudFormation parameter generator
│   ├── example-usage.sh              # Configuration usage examples
│   └── load-config.py                # Python configuration loader
├── front-end/                        # Frontend SPA with modular architecture
│   ├── config/
│   │   └── constants.js              # Frontend configuration constants
│   ├── core/                         # Core application modules
│   │   ├── api.js                    # API client for backend communication
│   │   ├── router.js                 # Client-side routing and tab management
│   │   └── state.js                  # Global application state management
│   ├── features/                     # Feature-based modules
│   │   ├── auth/                     # Authentication system
│   │   │   ├── AuthManager.js        # Authentication logic and state
│   │   │   ├── AuthModal.js          # Login/register modal component
│   │   │   └── auth.css              # Authentication styling
│   │   ├── favorites/                # Favorites management system
│   │   │   ├── AnalysisView.js       # Investment analysis display
│   │   │   ├── FavoritesManager.js   # Favorites business logic
│   │   │   ├── FavoritesView.js      # Favorites display component
│   │   │   ├── analysis.css          # Analysis view styling
│   │   │   └── favorites.css         # Favorites styling
│   │   ├── hidden/                   # Hidden properties system
│   │   │   ├── HiddenManager.js      # Hidden properties business logic
│   │   │   ├── HiddenView.js         # Hidden properties display
│   │   │   └── hidden.css            # Hidden properties styling
│   │   └── properties/               # Main properties display
│   │       ├── PropertiesManager.js  # Properties business logic
│   │       ├── PropertiesView.js     # Properties table and filtering
│   │       └── properties.css        # Properties styling
│   ├── shared/                       # Shared components and utilities
│   │   ├── components/               # Reusable UI components
│   │   │   ├── FilterDropdown.js     # Dynamic filter dropdown component
│   │   │   ├── Pagination.js         # Pagination component
│   │   │   └── Table.js              # Data table component
│   │   ├── styles/                   # Global styling
│   │   │   ├── base.css              # Base styles and CSS variables
│   │   │   ├── components.css        # Component styles
│   │   │   └── layout.css            # Layout and responsive design
│   │   └── utils/                    # Utility functions
│   │       ├── dom.js                # DOM manipulation utilities
│   │       ├── formatters.js         # Data formatting functions
│   │       └── storage.js            # Local storage utilities
│   ├── deploy-frontend.sh            # Frontend deployment script
│   ├── front-end-stack.yaml          # Frontend CloudFormation template
│   ├── index.html                    # Main HTML entry point
│   ├── main.js                       # Application initialization
│   ├── test_payload.json             # Test data for development
│   └── test_remove.json              # Test data for removal operations
├── lambda/                           # AWS Lambda functions
│   ├── common/                       # Shared Lambda utilities
│   │   └── __init__.py
│   ├── dashboard_api/                # Main API for frontend
│   │   ├── app.py                    # Dashboard API handler
│   │   ├── dashboard_api.zip         # Deployment package
│   │   └── requirements.txt          # Python dependencies
│   ├── favorite_analyzer/            # Investment analysis for favorites
│   │   └── app.py                    # Favorite analysis handler
│   ├── favorites_api/                # User favorites management API
│   │   ├── app.py                    # Favorites API handler
│   │   ├── favorites_api.zip         # Deployment package
│   │   └── requirements.txt          # Python dependencies
│   ├── legacy/                       # Legacy functions (deprecated)
│   │   ├── daily_digest/             # Email digest functionality
│   │   ├── dynamodb_writer/          # Direct DB writing
│   │   ├── etl/                      # ETL processing
│   │   ├── llm_batch/                # Batch LLM processing
│   │   ├── prompt_builder/           # LLM prompt construction
│   │   ├── report_sender/            # Email reporting
│   │   ├── snapshot_generator/       # Data snapshots
│   │   └── util/                     # Legacy utilities
│   ├── login_user/                   # User authentication
│   │   ├── app.py                    # Login handler
│   │   └── requirements.txt          # Python dependencies
│   ├── property_analyzer/            # Property investment scoring
│   │   ├── app.py                    # Analysis handler
│   │   ├── decimal_utils.py          # Decimal handling utilities
│   │   ├── README.md                 # Analysis algorithm documentation
│   │   └── requirements.txt          # Python dependencies
│   ├── property_processor/           # Property data scraping
│   │   ├── app.py                    # Processing handler
│   │   ├── core_scraper.py           # Core scraping logic
│   │   ├── dynamodb_utils.py         # DynamoDB utilities
│   │   └── requirements.txt          # Python dependencies
│   ├── register_user/                # User registration
│   │   ├── app.py                    # Registration handler
│   │   └── requirements.txt          # Python dependencies
│   └── url_collector/                # URL discovery and collection
│       ├── app.py                    # URL collection handler
│       ├── core_scraper.py           # Core scraping logic
│       ├── dynamodb_utils.py         # DynamoDB utilities
│       ├── listings_debug.csv        # Debug data
│       ├── requirements.txt          # Python dependencies
│       ├── test_regression.py        # Regression tests
│       └── test_url_regex.py         # URL pattern tests
├── html/                             # Sample HTML files for reference
│   ├── individual-homes-listing.html # Individual property page sample
│   └── listingspage.html             # Listings page sample
├── tests/                            # Test files
│   └── test_overview_parser.py       # Parser testing
├── ai-stack.yaml                     # Main CloudFormation template
├── clear-dydb.py                     # DynamoDB table clearing utility
├── CONFIG_README.md                  # Configuration system documentation
├── deploy-ai.sh                      # Main deployment script
├── trigger-lambda.sh                 # Lambda function testing utility
├── update-lambda.sh                  # Individual Lambda update script
├── test_favorites_fixed.py           # Favorites testing
├── test_favorites.py                 # Favorites testing
├── test_fixed_endpoint.py            # API endpoint testing
├── test_lambda_direct.json           # Lambda test payload
├── test_payload.json                 # Test data
├── test_simple.json                  # Simple test data
└── test-response.json                # Test response data
```

