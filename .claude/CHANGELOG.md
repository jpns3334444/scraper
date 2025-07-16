# Changelog

All notable changes to this project will be documented in this file. After every change,addition, deployment, modification, ANYTHING, you MUST document it in this changelog file.

IMPORTANT: For changelog entries, run: date +"%Y-%m-%d"
Format: ## 2024-07-10. If there is no section for the current day, create a new section.

CRITICAL RULES - FOLLOW EXACTLY:

1. Before ANY task: Run these commands and READ the output
   - cat CHANGELOG.md
   - grep -r "python" *.yml *.yaml Dockerfile* requirements.txt
   - head -5 Makefile

2. After ANY change (NO EXCEPTIONS):
   Update CHANGELOG.md with EVERY modification including:
   - Config changes (Python versions, dependencies)
   - File deletions
   - Version downgrades
   - Environment changes
   - Even "minor" adjustments

3. NEVER suggest version upgrades without asking first
4. NEVER assume the current state - always verify

## [7-10-2025]

### Added
- SAM deployment bucket `ai-scraper-sam-deploy-artifacts` for AI infrastructure deployment artifacts
- Regional SAM deployment bucket `ai-scraper-sam-deploy-artifacts-ap-northeast-1` for ap-northeast-1 region
- Modified AI analysis to process only top 5 listings for cost-effective testing (was 100)
- CHANGELOG.md file for tracking project changes
- AI_INFRASTRUCTURE_DEBUG.md file for tracking deployment issues and solutions

### Deployed
- **AI Infrastructure Stack**: ai-scraper-dev (ap-northeast-1)
- **Lambda Functions**: ETL, PromptBuilder, LLMBatch, ReportSender (all deployed successfully)
- **Step Functions**: ai-scraper-dev-ai-analysis state machine
- **EventBridge**: Daily execution rule at 18:00 UTC (03:00 JST)
- **IAM Roles**: Lambda execution, Step Functions, EventBridge roles
- **SSM Parameter**: OpenAI API key storage

### Removed
- Slack integration and notifications (email-only reporting now)
- Docker integration completely removed from AI infrastructure
- Deleted `/lambda/etl/Dockerfile` (Python 3.12 base image)
- Deleted `/lambda/prompt_builder/Dockerfile` (Python 3.12 base image)
- Deleted `/lambda/llm_batch/Dockerfile` (Python 3.12 base image)
- Deleted `/lambda/report_sender/Dockerfile` (Python 3.12 base image)
- Deleted `/get-docker.sh` (Docker installation script)
- Removed Docker build targets from Makefile
- Removed Docker prerequisite from deployment script help text

### Changed
- Prompt builder now selects top 5 listings instead of 100 for testing purposes
- AI infrastructure deployment process now uses dedicated SAM artifacts bucket
- Makefile Python version changed from 3.12 to 3.8 (matches SAM template runtime)
- Makefile build command now uses `sam build` instead of Docker containers
- Deployment process simplified to pure SAM ZIP-based packaging
- Build process no longer requires Docker installation
- **LLMBatchFunction timeout reduced from 3600 to 900 seconds** (Lambda maximum limit)
- **SAM template fixed**: Now uses correct timeout values for all Lambda functions

### Infrastructure
- Created S3 bucket `ai-scraper-sam-deploy-artifacts` for AWS SAM deployment artifacts
- Bucket is separate from data storage buckets (`lifull-scrape-tokyo`, `tokyo-real-estate-ai-data`)
- Resolved version conflict: SAM template uses python3.8, removed conflicting python:3.12 Dockerfiles
- AI infrastructure now uses consistent ZIP-based Lambda deployment without containers
- Eliminated Docker dependency eliminating major deployment complexity

## [Previous]

### Existing Features
- Complete real estate scraping pipeline with EC2-based data collection
- AI-powered analysis using GPT-4o vision for property evaluation
- Serverless AI analysis infrastructure with Lambda functions and Step Functions
- Email notification system for investment reports
- Cost-optimized batch processing using OpenAI Batch API
- Comprehensive testing suite with unit tests and mock data