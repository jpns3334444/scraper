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
* Backend: AWS Lambda (Python), DynamoDB, S3, CloudFormation (us-east-1)
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
├── stack.yaml                        # Unified CloudFormation template (API + Workers + Infra)
├── deploy.sh                         # Single deployment script
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
│   ├── trigger-lambda.sh             # Lambda function trigger/testing utility
│   ├── update-lambda.sh              # Individual Lambda code update script
│   ├── api/                          # API Lambdas (serve frontend)
│   │   ├── dashboard/                # GET /properties - property listing
│   │   │   └── app.py
│   │   └── favorites/                # Favorites & hidden CRUD operations
│   │       └── app.py
│   └── workers/                      # Background processing Lambdas
│       ├── url_collector/            # Scrapes listing URLs from Realtor.com
│       │   ├── app.py
│       │   ├── core_scraper.py
│       │   └── dynamodb_utils.py
│       ├── property_processor/       # Scrapes property details
│       │   ├── app.py
│       │   ├── core_scraper.py
│       │   └── dynamodb_utils.py
│       ├── property_analyzer/        # Computes 12-factor investment scores
│       │   ├── app.py
│       │   └── decimal_utils.py
│       └── favorite_analyzer/        # GPT analysis for favorited properties
│           └── app.py
├── cloudformation/                   # Additional CloudFormation templates (if needed)
└── clear-dydb.py                     # DynamoDB table clearing utility
```

## Lambda Organization

### API Lambdas (`lambda/api/`)
These serve the frontend via API Gateway:
- **dashboard**: Returns paginated property listings with filters
- **favorites**: CRUD for user favorites and hidden properties, triggers GPT analysis

### Worker Lambdas (`lambda/workers/`)
These run in the background via Step Functions pipeline:
- **url_collector**: Discovers new property URLs from Realtor.com search pages
- **property_processor**: Scrapes detailed property data from individual listings
- **property_analyzer**: Computes investment scores using 12-factor algorithm
- **favorite_analyzer**: Generates GPT-powered investment analysis for favorites

## Deployment

Single command deploys everything:
```bash
./deploy.sh
```

This will:
1. Build the OpenAI Lambda layer (if needed)
2. Package all Lambda functions
3. Deploy the unified CloudFormation stack
4. Output the API Gateway URL for Vercel

## Testing

```bash
# Test the scraper pipeline (from lambda/ directory)
cd lambda
./trigger-lambda.sh url-collector --sync
./trigger-lambda.sh property-processor --max-properties 5 --sync
./trigger-lambda.sh property-analyzer --sync

# Update a single Lambda function
./update-lambda.sh dashboard

# Test API endpoints
curl https://YOUR_API_GATEWAY_URL/prod/properties
```
