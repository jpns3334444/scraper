# Deployment Bug Analysis Report

This report analyzes critical bugs that would prevent the system from running successfully on first deployment.

## Priority 1 - Deployment Blockers (Will prevent even starting)

### 2. Missing Jinja2 Template Files 
**Location**: `ai-infra/lambda/report_sender/app.py:13`  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES - if email templates are required  
**Issue**: Code imports Jinja2 and likely needs HTML email templates, but no template files are present.  
**Fix**: Create basic email template files or remove Jinja2 dependency if not used.

### 3. Lambda Layer Dependencies
**Location**: CloudFormation template references layer at line 58  
**Will this prevent deployment?** YES  
**Will this crash on first run?** N/A - won't deploy  
**Issue**: CloudFormation references `layers/openai-layer.zip` in S3 bucket, but this layer must be pre-built and uploaded.  
**Fix**: Build and upload the OpenAI layer to S3 before deployment, or use inline dependencies.

## Priority 2 - First-Run Failures (Will crash on first execution)

### 4. Missing `snapshots.snapshot_manager` Module Call
**Location**: `ai-infra/lambda/snapshot_generator/app.py:20`  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES  
**Issue**: Code calls `generate_daily_snapshots(event)` but this function doesn't exist in `/mnt/c/Users/azure/Desktop/scraper/snapshots/snapshot_manager.py`.  
**Fix**: Implement the `generate_daily_snapshots()` function or use a different function name.

### 5. Missing `notifications.notifier` Module Call
**Location**: `ai-infra/lambda/daily_digest/app.py:16`  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES  
**Issue**: Code calls `send_daily_digest(event)` but need to verify this function exists.  
**Fix**: Ensure `send_daily_digest()` function is implemented in the notifier module.

### 6. Model Mismatch - O3 vs GPT-4o
**Location**: Multiple Lambda functions  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES - OpenAI API errors  
**Issue**: 
- CloudFormation sets `OPENAI_MODEL: gpt-4o` (line 300)
- LLM Lambda uses `model="o3"` hardcoded (line 304 in prompt_builder)
- O3 models have different parameters than GPT-4o models
**Fix**: Make model names consistent. Use either `gpt-4o` throughout or `o3` throughout.

### 7. Async Client Import Issue
**Location**: `ai-infra/lambda/llm_batch/app.py:312`  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES  
**Issue**: Code creates `AsyncOpenAI(api_key=client.api_key)` but `client` is a sync OpenAI client, so `client.api_key` may not be accessible.  
**Fix**: Store API key in a variable: `api_key = client.api_key; async_client = AsyncOpenAI(api_key=api_key)`

## Priority 3 - Integration Breaks (Will fail when components connect)

### 8. Data Flow Mismatch - ETL to Prompt Builder
**Location**: Step Functions state machine + Lambda functions  
**Will this prevent deployment?** NO  
**Will this crash on first run?** POTENTIALLY  
**Issue**: ETL Lambda returns `processed_data` field (line 202 in etl/app.py), but Prompt Builder expects `candidates` data and looks for `clean/{date}/listings.jsonl` (line 159 in prompt_builder/app.py).  
**Fix**: Either ETL should also save candidates to S3, or Prompt Builder should use the processed_data from the event.

### 9. DynamoDB Writer Data Format Mismatch
**Location**: `ai-infra/lambda/dynamodb_writer/app.py:40-42`  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES  
**Issue**: DynamoDB Writer expects `batch_result.individual_results[]` with `analysis` field, but LLM Batch Lambda returns `batch_result[]` with `evaluation_data` field.  
**Fix**: Align data structure between LLM Batch output and DynamoDB Writer input expectations.

### 10. Missing Lambda Packaging Dependencies
**Location**: All Lambda functions  
**Will this prevent deployment?** YES  
**Will this crash on first run?** N/A - won't deploy properly  
**Issue**: Lambda functions import modules like `analysis.*`, `schemas.*`, `notifications.*`, `snapshots.*` but these need to be packaged with each Lambda deployment.  
**Fix**: Ensure all custom modules are included in Lambda deployment packages, or use Lambda layers.

## Priority 4 - Common LLM Generation Mistakes

### 11. Hardcoded Email Addresses
**Location**: CloudFormation template line 12-15  
**Will this prevent deployment?** NO  
**Will this crash on first run?** NO  
**Issue**: Email addresses are hardcoded as `jpns3334444@gmail.com` in template defaults.  
**Fix**: Use parameterized values or environment-specific configuration.

### 12. Region Hardcoding
**Location**: CloudFormation Layer ARNs line 240, 267, etc.  
**Will this prevent deployment?** YES - if deploying outside ap-northeast-1  
**Will this crash on first run?** N/A  
**Issue**: AWS Lambda layer ARNs are hardcoded to `ap-northeast-1` region.  
**Fix**: Use region parameters in layer ARNs: `!Sub 'arn:aws:lambda:${AWS::Region}:336392948345:layer:AWSSDKPandas-Python312:15'`

### 13. Missing Error Handling for Required Files
**Location**: Multiple Lambda functions  
**Will this prevent deployment?** NO  
**Will this crash on first run?** YES  
**Issue**: Functions don't handle missing S3 files gracefully (CSV files, snapshots, etc.)  
**Fix**: Add proper error handling and fallback mechanisms for missing files.

## Summary of Critical Fixes Needed

**Before Deployment:**
1. Build and upload OpenAI layer to S3
2. Package all custom Python modules with Lambda functions
3. Create email templates or remove Jinja2 dependency

**Code Fixes for First Run:**
1. Implement missing functions: `generate_daily_snapshots()`, `send_daily_digest()`  
2. Fix model name consistency (use either `gpt-4o` or `o3` consistently)
3. Fix async client initialization in LLM batch Lambda
4. Align data structures between ETL → Prompt Builder → LLM Batch → DynamoDB Writer
5. Add error handling for missing S3 files

**Configuration Fixes:**
1. Remove hardcoded email addresses
2. Make layer ARNs region-agnostic
3. Ensure all environment variables are properly set

Most critical: **Lambda packaging dependencies** and **missing function implementations** will cause immediate deployment/runtime failures.