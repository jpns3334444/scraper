# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a Tokyo Real Estate Analysis system combining web scraping and AI-powered investment analysis. The system consists of two complementary subsystems:

1. **Data Collection System** (`/scraper/`): EC2-based web scraper that collects daily property data
2. **AI Analysis System** (`/ai-infra/`, `/lambda/`): Serverless pipeline that processes data and generates investment reports using OpenAI GPT-4.1

The complete architecture document is in `docs/architecture.md`.

## Common Development Commands

### Testing
```bash
# Run all tests with coverage
make test

# Run tests with verbose output  
make test-verbose

# Test individual Lambda functions locally
make test-etl-local
make test-prompt-builder-local
make test-llm-batch-local
make test-report-sender-local
```

### Code Quality
```bash
# Run linting checks
make lint

# Format code automatically
make format

# Check formatting without changes
make format-check

# Run type checking
make type-check

# Complete development setup (install + format + lint + type-check + test)
make dev-setup

# Pre-commit checks
make pre-commit
```

### Building and Deployment
```bash
# Build minimal OpenAI layer (replaces heavy custom layers)
mkdir -p openai-layer/python
pip install openai --target openai-layer/python/ --no-cache-dir
zip -r openai-layer.zip openai-layer/ -x "*.pyc" "*/__pycache__/*"

# Package Lambda functions for CloudFormation  
zip -r etl-function.zip lambda/etl/ -x "*.pyc" "*/__pycache__/*"
zip -r prompt-builder-function.zip lambda/prompt_builder/ -x "*.pyc" "*/__pycache__/*"
zip -r llm-batch-function.zip lambda/llm_batch/ -x "*.pyc" "*/__pycache__/*"
zip -r report-sender-function.zip lambda/report_sender/ -x "*.pyc" "*/__pycache__/*"

# Validate CloudFormation template
make validate

# Deploy to development environment
make deploy-dev

# Deploy to production environment  
make deploy-prod
```

### Layer Management (Hybrid Approach)
The system now uses a hybrid layer approach for optimal performance and reliability:

**AWS Prebuilt Layers (90% of dependencies):**
- pandas, numpy, boto3, pytz, scipy, s3transfer, urllib3
- Uses: `arn:aws:lambda:ap-northeast-1:336392948345:layer:AWSSDKPandas-Python312:15`
- Benefits: AWS-managed, tested, optimized, no build time

**Minimal Custom Layer (OpenAI only):**
- Only contains: openai package and its dependencies  
- Size: ~4MB (vs 500MB+ for previous custom layers)
- Build time: <1 minute (vs 10+ minutes for Docker builds)
- Benefits: Fast builds, small deployment packages, easy maintenance

```bash
# Test layer imports (quick validation)
python3 -c "import sys; sys.path.insert(0, 'openai-layer/python'); import openai; print('OpenAI layer works!')"
```

### Local Testing
```bash
# Create sample data and test locally (creates mock data)
make local-run DATE=2025-07-07

# Manual execution of specific date through AWS
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:STACK-ai-analysis \
  --input '{"date":"2025-07-07"}'
```

## System Architecture

### Data Flow
1. **Web Scraper** (`scraper/scrape.py`) → Daily CSV + Images to S3 (`raw/YYYY-MM-DD/`)
2. **EventBridge** triggers Step Functions daily at 18:00 UTC (03:00 JST)
3. **ETL Lambda** (`lambda/etl/`) → Processes CSV to JSONL with computed features
4. **Prompt Builder Lambda** (`lambda/prompt_builder/`) → Selects top 100 listings, creates GPT-4.1 vision prompts
5. **LLM Batch Lambda** (`lambda/llm_batch/`) → Submits to OpenAI Batch API, polls for completion
6. **Report Sender Lambda** (`lambda/report_sender/`) → Generates Markdown reports, sends to Slack + Email

### Key Technologies
- **Runtime**: Python 3.12 (using AWS prebuilt layers)
- **Orchestration**: AWS Step Functions with retry logic and error handling
- **Storage**: S3 for all data (raw CSV, processed JSONL, prompts, AI responses, reports)
- **AI**: OpenAI GPT-4.1 Vision API via Batch API for cost efficiency
- **Notifications**: Slack webhooks + Amazon SES for email
- **Infrastructure**: CloudFormation templates in `ai-infra/`

### Lambda Functions Structure
Each Lambda function in `lambda/*/` follows this pattern:
- `app.py` - Main handler function
- `requirements.txt` - Dependencies (typically empty, using layers)
- Functions use shared layers for dependencies to reduce package size

### Configuration Management
- **Secrets**: OpenAI API key stored in SSM Parameter Store (`/ai-scraper/*/openai-api-key`)
- **Environment Variables**: Set in CloudFormation template (`ai-infra/ai-stack.yaml`)
- **Email Configuration**: SES sender/recipient in Lambda environment variables

## Development Workflow

### Making Changes to Lambda Functions
1. Edit code in `lambda/*/app.py`
2. Run `make format lint type-check test` to validate changes
3. Run `make build` to package functions
4. Deploy with `make deploy-dev` or `./deploy-enhanced.sh`

### Updating Dependencies
1. Modify `requirements.txt` files in lambda layer directories
2. Run `./build-layers.sh` to rebuild with Python 3.12 compatibility
3. Run `./test-layers.sh` to verify imports work
4. Deploy updated layers with deployment scripts

### Testing Strategy
- **Unit Tests**: In `tests/` using pytest, moto for AWS mocking
- **Integration Tests**: Use `make local-run` with sample data
- **Layer Tests**: Automated import verification with test scripts
- **End-to-End**: Manual Step Functions execution with real AWS services

### Working with the AI Analysis Pipeline
- **Prompt Engineering**: Modify system prompts in `lambda/prompt_builder/app.py`
- **Ranking Logic**: Adjust property selection criteria in prompt builder
- **Cost Control**: Limit listing count (default 100) and photos per listing (default 20)
- **Monitoring**: Check CloudWatch logs for errors, OpenAI API usage

### Debugging Production Issues
1. Check Step Functions execution history in AWS Console
2. Review CloudWatch logs for specific Lambda function errors
3. Use operations runbook in `docs/runbook.md` for common issues
4. Test individual components with `aws lambda invoke` commands

## Important Notes

- **Python Version**: System uses Python 3.12 runtime with compatible layers
- **OpenAI Costs**: Monitor usage as GPT-4.1 Vision API can be expensive
- **Secrets Management**: Never commit API keys; use SSM Parameter Store
- **S3 Structure**: Maintain consistent folder structure (`raw/`, `clean/`, `prompts/`, `batch_output/`, `reports/`)
- **Two Subsystems**: AI analysis system is independent of the scraper system in `/scraper/`

## Security Practices

- **IMPORTANT**: We are using AWS secrets to store all API keys/ anything of that nature

## Cleanup and Maintenance Guidelines

- **Cleanup Procedures**:
  - Whenever we stop using a file/process... delete it! Delete any unused, unnecessary files you come across as well.