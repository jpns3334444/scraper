# CLAUDE.md

## READ THIS FIRST

- **All constants and settings are in `./config.json` at the repo root.**
- This file is the **only source of truth** for stack names, table names, bucket names, Lambda names, regions, and other settings. Any new names, regions, etc must be added to the config.json, NO hardcoding variables/names.
- Always **load `config.json` before writing or editing any code**.
- **Do not hardcode** values that exist in `config.json`.
- If you can't find a value, ask — do not invent defaults.

## Project Summary

US Real Estate Investment Analysis System:

* Scrapes property data from Realtor.com (currently targeting Paonia, CO)
* Analyzes with a 12-factor investment scoring algorithm
* After users favorite a property, it is sent to GPT API for analysis and returned to the user
* Backend: AWS Lambda (Python), DynamoDB, S3, CloudFormation (us-west-2)
* Frontend: Next.js with TypeScript and Tailwind CSS (deployed on Vercel)

## Key Rule

Whenever editing code, scripts, or templates:

1. Load `config.json`
2. Use values from it
3. Never inline constants


## Repository Structure

```
/
├── config.json                       # Single source of truth for all configuration
├── scripts/
│   ├── cfg.sh                        # Bash configuration loader
│   ├── cfn-params.sh                 # CloudFormation parameter generator
│   ├── example-usage.sh              # Configuration usage examples
│   └── load-config.py                # Python configuration loader
├── frontend-nextjs/                  # Next.js frontend (TypeScript + Tailwind)
│   ├── app/                          # Next.js App Router pages
│   │   ├── page.tsx                  # Main properties page
│   │   ├── layout.tsx                # Root layout
│   │   ├── globals.css               # Global styles
│   │   ├── favorites/page.tsx        # Favorites page
│   │   └── hidden/page.tsx           # Hidden properties page
│   ├── components/                   # React components
│   │   ├── AnalysisView.tsx          # Investment analysis display
│   │   ├── AuthModal.tsx             # Login/register modal
│   │   ├── AuthProvider.tsx          # Authentication context
│   │   ├── FilterBar.tsx             # Property filtering
│   │   ├── Navigation.tsx            # Navigation component
│   │   ├── PropertyCard.tsx          # Property card display
│   │   └── PropertyGrid.tsx          # Properties grid layout
│   ├── hooks/                        # Custom React hooks
│   │   ├── useAuth.ts                # Authentication hook
│   │   ├── useFavorites.ts           # Favorites management hook
│   │   └── useProperties.ts          # Properties data hook
│   ├── lib/                          # Utilities and types
│   │   ├── api.ts                    # API client
│   │   └── types.ts                  # TypeScript type definitions
│   ├── next.config.js                # Next.js configuration
│   ├── tailwind.config.js            # Tailwind CSS configuration
│   ├── tsconfig.json                 # TypeScript configuration
│   ├── package.json                  # Dependencies
│   └── vercel.json                   # Vercel deployment config
├── lambda/                           # AWS Lambda functions
│   ├── dashboard_api/                # Main API for frontend
│   │   └── app.py                    # Dashboard API handler
│   ├── favorite_analyzer/            # Investment analysis for favorites
│   │   └── app.py                    # Favorite analysis handler
│   ├── favorites_api/                # User favorites management API
│   │   └── app.py                    # Favorites API handler
│   ├── login_user/                   # User authentication
│   │   └── app.py                    # Login handler
│   ├── property_analyzer/            # Property investment scoring
│   │   ├── app.py                    # Analysis handler
│   │   └── decimal_utils.py          # Decimal handling utilities
│   ├── property_processor/           # Property data scraping
│   │   ├── app.py                    # Processing handler
│   │   ├── core_scraper.py           # Core scraping logic
│   │   └── dynamodb_utils.py         # DynamoDB utilities
│   ├── register_user/                # User registration
│   │   └── app.py                    # Registration handler
│   └── url_collector/                # URL discovery and collection
│       ├── app.py                    # URL collection handler
│       ├── core_scraper.py           # Core scraping logic
│       └── dynamodb_utils.py         # DynamoDB utilities
├── cloudformation/                   # Additional CloudFormation templates
│   └── transit-cache-table.yaml      # Transit cache table template
├── ai-stack.yaml                     # Main CloudFormation template
├── clear-dydb.py                     # DynamoDB table clearing utility
├── deploy-ai.sh                      # Main deployment script
├── trigger-lambda.sh                 # Lambda function testing utility
└── update-lambda.sh                  # Individual Lambda update script
```
