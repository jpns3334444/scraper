# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

This is a Tokyo Real Estate Analysis System that scrapes, analyzes, and reports on property listings. The system consists of:

### Core Components

1. **AI Infrastructure (`ai_infra/`)** - AWS Lambda-based serverless pipeline
   - Lambda functions for ETL, prompt building, LLM batch processing, reporting
   - Step Functions orchestration for the full AI workflow
   - DynamoDB for data storage and dashboard API

2. **Analysis Engine** - Python modules for property evaluation
   - `analysis/lean_scoring.py` - Deterministic scoring algorithm (Lean v1.3)
   - `analysis/comparables.py` - Market comparison analysis
   - `analysis/analyzer.py` - Main analysis coordinator

3. **Data Models (`schemas/`)** - Type definitions and validation
   - `models.py` - Property, analysis, and snapshot data classes
   - JSON schema validation for LLM outputs

4. **Dashboard (`dashboard/`)** - Web interface for viewing analyzed properties
   - Single-page HTML app with AWS Lambda API backend
   - Real-time filtering and sorting of property data

### Data Flow Architecture

```
Raw Scraping → ETL Processing → Lean Scoring → LLM Analysis → Daily Digest
     ↓              ↓              ↓             ↓             ↓
S3 Storage → DynamoDB Storage → Candidate Filtering → Email Reports → Dashboard
```

The system implements "Lean v1.3" - an efficiency-focused approach that uses deterministic scoring to filter candidates before expensive LLM analysis, achieving ~99% token reduction.

## Development Commands

### Deployment Commands
```bash
# Deploy AI infrastructure (main pipeline)
cd ai_infra && ./deploy-ai.sh

# Deploy dashboard (after AI infrastructure is deployed)
cd ai_infra && ./deploy-dashboard.sh

# Update scraper Lambda function only
cd ai_infra && ./update-scraper-lambda.sh
```

### Testing Commands
```bash
# Run Python tests
pytest tests/ -v

# Test individual Lambda functions locally
cd ai_infra && ./test-local.sh etl test-events/etl-event.json
cd ai_infra && ./test-local.sh prompt_builder test-events/prompt-builder-event.json
cd ai_infra && ./test-local.sh llm_batch test-events/llm-batch-event.json

# Test full AI workflow
cd ai_infra && ./trigger_ai_workflow.sh [YYYY-MM-DD] [region]
```

### Operational Commands
```bash
# Trigger scraper manually
cd ai_infra && ./trigger_lambda_scraper.sh --max-properties 10 --sync

# Monitor AI workflow execution
cd ai_infra && ./trigger_ai_workflow.sh 2025-01-25 ap-northeast-1 --all
```

## Key Implementation Details

### Lean v1.3 Pipeline
- **Deterministic Scoring**: Properties scored using market data, location factors, and building characteristics
- **Candidate Gating**: Only high-scoring properties (typically 2-5% of total) proceed to LLM analysis
- **Token Efficiency**: ~1200 tokens per property vs ~2000+ in legacy mode
- **Schema Validation**: LLM outputs validated against strict JSON schemas

### Testing Strategy
- Uses `pytest` with moto for AWS service mocking
- Test fixtures in `tests/conftest.py` provide sample data
- Local Lambda testing via `ai_infra/test_runner.py`
- Integration tests validate end-to-end pipeline behavior

### Configuration
- Environment variables managed via `.env.json` (not in repo)
- AWS resources managed via CloudFormation templates
- OpenAI API key stored in AWS Secrets Manager
- Email configuration in deployment scripts

### AWS Resources
- **Lambda Functions**: ETL, prompt builder, LLM batch, report sender, scraper, dashboard API
- **Step Functions**: Orchestrates the full AI analysis workflow
- **DynamoDB**: Stores processed property data for dashboard queries
- **S3**: Raw data, processed outputs, and static dashboard hosting
- **SES**: Email delivery for daily digest reports

## Data Models

Key data structures are defined in `schemas/models.py`:
- `PropertyListing` - Raw property data
- `PropertyAnalysis` - Scored and analyzed property results
- `GlobalSnapshot`/`WardSnapshot` - Market statistics
- `DailyDigestData` - Email report structure

## Important Patterns

### Error Handling
- Lambda functions return structured error responses
- CloudWatch logs capture detailed execution information
- Step Functions handle retry logic for transient failures

### Data Validation
- JSON schema validation for all external data inputs
- Type hints throughout Python codebase using dataclasses
- Schema compliance checking for LLM outputs

### Performance Optimization
- Batch processing for DynamoDB operations
- S3 object versioning for deployment artifacts
- Cached OpenAI layer to reduce deployment times

## Logging and Monitoring Considerations

- **Log Filtering**: We must filter lambda logs for the scraper on sessionID, otherwise we will see logs for multiple runs. We ONLY WANT TO SEE LOGS FOR THE CURRENT EXECUTION.

## Important Coding Guidelines

- **Programming Language Note**: IT IS ALWAYS PYTHON3, NEVER PYTHON