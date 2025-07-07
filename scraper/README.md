# Scraper System (Data Collection)

This directory contains the web scraper that collects Tokyo real estate data daily.

## Purpose

The scraper runs on EC2 infrastructure and:
- Scrapes property listings from real estate websites
- Processes and cleans the data
- Uploads results to S3 as CSV files and images
- Provides the **data source** for the AI analysis system

## Files

- `scrape.py` - Main scraper script with HTTP-based extraction
- `test-multi-area.py` - Multi-area testing script
- `test_scraper.py` - Unit tests for scraper
- `deploy-*.sh` - Deployment scripts for EC2 infrastructure
- `lifull-key.pem` - SSH key for EC2 access (if present)

## Deployment

Deploy the scraper infrastructure using the CloudFormation templates:

```bash
# Deploy infrastructure stack first
cd ../cf-templates
aws cloudformation create-stack \
  --stack-name scraper-infra \
  --template-body file://infra-stack.yaml \
  --capabilities CAPABILITY_IAM

# Deploy compute stack
./deploy-compute.sh
```

## Output Format

The scraper creates files in S3 with this structure:
```
s3://re-stock/
├── raw/
│   └── YYYY-MM-DD/
│       ├── listings.csv          # Main data file
│       └── images/
│           ├── photo1.jpg        # Property photos
│           └── photo2.jpg
```

## CSV Schema

```csv
id,headline,price_yen,area_m2,year_built,walk_mins_station,ward,photo_filenames
listing1,"Apartment in Shibuya",25000000,65.5,2010,8,Shibuya,"living.jpg|bedroom.jpg"
```

## Relationship to AI System

This scraper **feeds data** to the AI analysis system located in:
- `/lambda/` - AI processing functions  
- `/infra/ai-stack.yaml` - AI infrastructure

**Data Flow**: `Scraper → S3 → AI Analysis → Reports`