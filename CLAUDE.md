# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Tokyo Real Estate AI Analysis system that scrapes property listings, analyzes them with AI, and provides investment recommendations via a dashboard and email reports. The system uses AWS Lambda functions orchestrated by Step Functions, with data stored in DynamoDB and S3.

## Common Development Commands

### Deployment Commands
```bash
# Deploy the entire AI stack
./deploy-ai.sh

# Deploy dashboard
cd dashboard && ./deploy-dashboard.sh

# Update a specific Lambda function quickly
./update-lambda.sh property_processor
./update-lambda.sh property_analyzer
./update-lambda.sh url_collector
```

### Testing Lambda Functions
```bash
# Test property processor
./trigger-lambda.sh --function property-processor --max-properties 5 --sync

# Test property analyzer
./trigger-lambda.sh --function property-analyzer --sync

# Test URL collector
./trigger-lambda.sh --function url-collector --areas "chofu-city" --sync

# Debug mode with detailed logging
./trigger-lambda.sh --function property-processor --debug --sync
```

## High-Level Architecture

### Data Flow
1. **URL Collection**: `url_collector` Lambda scrapes property listing URLs from real estate sites
2. **Property Processing**: `property_processor` Lambda extracts detailed data from each listing
3. **Property Analysis**: `property_analyzer` Lambda evaluates properties using LLM for investment potential
4. **Data Storage**: Properties stored in DynamoDB with verdicts (BUY/WATCH/REJECT)
5. **Dashboard**: Web interface queries DynamoDB via `dashboard_api` Lambda
6. **Reports**: Daily digest emails sent with top property recommendations

### Key Lambda Functions
- **url_collector**: Scrapes listing URLs from configured areas
- **property_processor**: Extracts property details (price, size, location, images)
- **property_analyzer**: Uses OpenAI to analyze investment potential
- **dashboard_api**: Provides filtered/sorted property data to web dashboard
- **daily_digest**: Sends email summaries of best properties

### Data Storage
- **DynamoDB**: Primary storage for property data and analysis results
- **S3 Bucket** (`tokyo-real-estate-ai-data`): Stores scraped images and batch processing data

### Infrastructure as Code
- **CloudFormation**: `ai-stack.yaml` defines all AWS resources
- **Lambda Layers**: OpenAI SDK packaged as layer for shared use
- **Deployment**: `deploy-ai.sh` handles packaging and deployment

## Development Patterns

### Lambda Function Structure
Each Lambda follows this pattern:
```python
# lambda/<function_name>/app.py
def lambda_handler(event, context):
    # Main entry point
    pass
```

### Shared Code
- `lambda/util/`: Common utilities (config, metrics)
- `analysis/`: Property analysis logic
- `schemas/`: Data models and validation

### Error Handling
- All Lambdas use structured logging with session IDs
- Errors are logged to CloudWatch with full context
- Functions return standardized error responses

### Testing Approach
- Unit tests in `tests/` using pytest
- Moto for AWS service mocking
- Integration tests via Lambda invocation

## Key Configuration

### Environment Variables
- `OUTPUT_BUCKET`: S3 bucket for data storage
- `DYNAMODB_TABLE`: Property data table name
- `OPENAI_API_KEY`: Stored in AWS Secrets Manager

### Deployment Parameters
- Stack name: `tokyo-real-estate-ai`
- Region: `ap-northeast-1` (Tokyo)
- Python runtime: 3.12

## Security Considerations
- OpenAI API key stored in AWS Secrets Manager
- Lambda functions use IAM roles with least privilege
- No hardcoded credentials in code