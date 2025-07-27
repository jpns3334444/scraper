# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tokyo Real Estate Lean Analysis System - An automated AWS-based pipeline for analyzing Tokyo real estate investments using deterministic scoring (Lean v1.3).

## Core Architecture

### Processing Pipeline (Lean v1.3)
1. **EC2 Scraper** → Scrapes homes.co.jp listings and images → Stores in S3
2. **ETL Lambda** → Normalizes data and applies deterministic scoring
3. **Candidate Gating** → Filters top ~20% properties by score/discount
4. **LLM Analysis** → Generates qualitative insights for candidates only
5. **Daily Digest** → Single email summarizing all candidates

### Key Design Principles
- **99% LLM token reduction**: Only top candidates analyzed by LLM
- **Deterministic scoring**: All filtering/scoring logic in Python (not LLM)
- **Schema validation**: LLM outputs validated against `schemas/evaluation_min.json`
- **No traditional package management**: Dependencies installed directly in scripts

## Development Commands

### Testing
```bash
# Install dependencies
pip install boto3 pandas requests responses moto==4.2.14 openai jsonschema

# Run all tests
pytest -q

# Run specific test file
pytest tests/test_lean_scoring.py

# Run with coverage
pytest --cov=scraper --cov-report=html
```

### Local Testing of Lambda Functions
```bash
cd scraper/ai_infra
./test-local.sh <function_name> <event_file>
# Example: ./test-local.sh etl test-events/etl-event.json
```

### Deployment
```bash
# Deploy full stack
cd scraper/scraper
./deploy-all.sh

# Deploy AI infrastructure only
cd scraper/ai_infra
./deploy-ai.sh

# Deploy compute (EC2) only
cd scraper/scraper
./deploy-compute.sh

# Recreate compute (EC2) instance from scratch
cd scraper/scraper
./deploy-compute.sh --recreate
```

### Manual Triggers
```bash
# Trigger scraper on EC2
./trigger_scraper_script.sh <instance-id>

# Trigger AI workflow
cd scraper/ai_infra
./trigger_ai_workflow.sh <date>
# Example: ./trigger_ai_workflow.sh 2025-07-07
```

## Key Environment Variables
```bash
LEAN_MODE=1                    # Enable Lean pipeline
LEAN_SCORING=1                 # Use deterministic scoring
LEAN_PROMPT=1                  # Use lean prompt structure
LEAN_SCHEMA_ENFORCE=1          # Enforce JSON schema on LLM output
MAX_CANDIDATES_PER_DAY=120     # Safety limit on daily candidates
OUTPUT_BUCKET=<s3-bucket>      # Destination for processed data
AWS_REGION=ap-northeast-1      # Tokyo region only
```

## Code Organization

### Core Modules
- `analysis/lean_scoring.py` - Deterministic property scoring algorithm
- `analysis/comparables.py` - Similar property matching
- `notifications/daily_digest.py` - Email digest generation
- `schemas/models.py` - Data models (Property, Candidate, etc.)

### Lambda Functions
- `ai_infra/lambda/etl/` - Data normalization and scoring
- `ai_infra/lambda/prompt_builder/` - Candidate prompt preparation
- `ai_infra/lambda/llm_batch/` - LLM API interaction
- `ai_infra/lambda/report_sender/` - Email digest generation
- `ai_infra/lambda/dynamodb_writer/` - Result persistence

### Infrastructure
- `scraper/scraper/infra-stack.yaml` - Core AWS resources
- `scraper/ai_infra/ai-stack.yaml` - Lambda and Step Functions
- `scraper/scraper/compute-stack.yaml` - EC2 instances

## Important Notes

- **No linting tools configured** - Maintain consistent Python style manually
- **No CI/CD** - Manual deployment via shell scripts
- **Lambda deployment** - Uses zip packages, not containers
- **Testing focus** - Always add tests when modifying pipeline components
- **Tokyo-specific** - System designed for Tokyo real estate market only

## Scraping Guidelines
- Do not run the scraper script locally as we do not want our IP to be attached to the scraping

## Critical Infrastructure Warnings

### EC2 Logging Configuration
- NEVER, EVER FUCKING CHANGE THE EC2 LOG CONFIGURATION WITHOUT CONSULTING ME. IT GOES EC2 > OUTPUT FILE > AND THEN AGENT SENDS THEM TO CLOUDWATCH. DO NOT FUCK WITH IT, DO U FUCKING UNDERSTAND?