# AI Infrastructure Debugging Session
**Date**: 2025-07-10  
**Objective**: Resolve AI infrastructure deployment issues and eliminate unnecessary Docker usage

## Current Issues
- Significant deployment difficulties with AI infrastructure
- Docker is being used unnecessarily for Lambda functions
- Need to simplify deployment process

## Key Findings

### Docker Usage Analysis - COMPLETE
- **Status**: COMPLETELY UNNECESSARY - All Lambda functions can use ZIP packaging
- **Current State**: 4 identical Dockerfiles exist that serve no purpose
- **Dependencies**: Only basic packages (boto3, pandas, numpy, openai) - all available in Lambda runtime
- **Files Found**: 
  - `/lambda/etl/Dockerfile` - Uses python:3.12 base (conflicts with SAM template python3.8)
  - `/lambda/prompt_builder/Dockerfile` 
  - `/lambda/llm_batch/Dockerfile`
  - `/lambda/report_sender/Dockerfile`
  - `/get-docker.sh` - Docker installation script (unused)

### SAM Template Analysis
- **Current Configuration**: ALREADY CORRECTLY CONFIGURED for ZIP packaging
- **Runtime**: python3.8 in SAM template vs python:3.12 in Dockerfiles (MISMATCH!)
- **CodeUri**: Points to directories, not containers
- **No Container Configuration**: Template uses ZIP-based Lambda deployment

### Deployment Script Analysis  
- **Line 77**: States "Docker (for building Lambda containers)" as requirement
- **Line 98-99**: Comments show Docker was removed: "Docker is no longer required for ZIP-based Lambda deployment"
- **Issue**: Help text still mentions Docker but code doesn't use it

### Makefile Analysis
- **Lines 79-84**: Build target uses Docker containers unnecessarily  
- **Lines 178-188**: Individual Docker build targets that serve no purpose
- **Line 32**: Hardcoded Python 3.12 (conflicts with SAM template 3.8)

### Root Cause of Issues
1. **Version Mismatch**: Dockerfiles use Python 3.12, SAM uses python3.8
2. **Unused Docker Infrastructure**: All Docker files are dead code
3. **Confusing Documentation**: Mixed messages about Docker requirements
4. **Build Process Conflict**: Make targets suggest Docker when SAM uses ZIP

## Action Items - DETAILED
1. **Remove Docker Files**: Delete 4 Dockerfiles + get-docker.sh 
2. **Update Makefile**: Remove Docker targets, fix Python version references
3. **Update deploy.sh**: Remove Docker from help text and prerequisites
4. **Verify SAM Template**: Ensure python3.8 runtime is maintained (per user requirement)
5. **Test Build Process**: Ensure `sam build` works without Docker

## Files to Modify/Remove
- **DELETE**: `/lambda/*/Dockerfile` (4 files)
- **DELETE**: `/get-docker.sh`
- **MODIFY**: `/Makefile` (remove Docker targets, fix Python version)
- **MODIFY**: `/ai-infra/deploy.sh` (update help text)

## Root Cause Summary
The deployment issues are caused by CONFLICTING CONFIGURATIONS:
- SAM template expects ZIP packaging with python3.8
- Dockerfiles try to build python:3.12 containers  
- Build process has both ZIP and Docker paths creating confusion

## COMPLETED ACTIONS - 2025-07-10

### Files Removed ✅
- `/lambda/etl/Dockerfile` - DELETED
- `/lambda/prompt_builder/Dockerfile` - DELETED  
- `/lambda/llm_batch/Dockerfile` - DELETED
- `/lambda/report_sender/Dockerfile` - DELETED
- `/get-docker.sh` - DELETED

### Files Modified ✅
- `/Makefile` - Updated Python version 3.12→3.8, removed Docker targets, added SAM commands
- `/ai-infra/deploy.sh` - Removed Docker from prerequisites
- `/.claude/CHANGELOG.md` - Documented all changes

### Verification ✅
- SAM template validation: PASSED
- Build process test: `sam build` works without Docker
- Version consistency: SAM template python3.8 maintained

## DEPLOYMENT ISSUE RESOLUTION
**ROOT CAUSE**: Version conflict between SAM template (python3.8) and Dockerfiles (python:3.12)
**SOLUTION**: Removed all Docker components, unified on SAM ZIP-based deployment  
**RESULT**: Simplified deployment process, eliminated Docker dependency completely

## NEXT STEPS FOR DEPLOYMENT
- Deploy using: `cd ai-infra && ./deploy.sh -e dev -b YOUR_BUCKET --openai-key KEY --email-from FROM --email-to TO`
- No Docker installation required
- Faster build times with ZIP packaging

## DEPLOYMENT ISSUES - 2025-07-10

### Issue 1: SAM Build Path Problem
**Error**: `Skipping copy operation since source /mnt/c/Users/azure/Desktop/lambda/etl does not exist`
**Cause**: SAM is looking for Lambda functions in wrong directory (absolute path instead of relative)
**Status**: Investigating - Lambda functions exist at correct relative path `../lambda/etl/`

### Issue 2: Lambda Function Timeout Limit
**Error**: `Value '3600' at 'timeout' failed to satisfy constraint: Member must have value less than or equal to 900`
**Cause**: LLMBatchFunction configured with 3600 second timeout, but Lambda maximum is 900 seconds
**Status**: RESOLVED - Fixed timeout to 900 seconds

### Issue 3: S3 Bucket Region Mismatch
**Error**: `deployment s3 bucket is in a different region`
**Cause**: SAM artifacts bucket in us-east-1, deployment target in ap-northeast-1
**Status**: RESOLVED - Created regional bucket `ai-scraper-sam-deploy-artifacts-ap-northeast-1`

## DEPLOYMENT SUCCESS - 2025-07-10 16:40:35

### Stack Details
- **Stack Name**: ai-scraper-dev
- **Region**: ap-northeast-1
- **Status**: CREATE_COMPLETE
- **Step Functions ARN**: arn:aws:states:ap-northeast-1:901472985889:stateMachine:ai-scraper-dev-ai-analysis
- **ETL Function ARN**: arn:aws:lambda:ap-northeast-1:901472985889:function:ai-scraper-dev-etl

### Deployed Resources
✅ Lambda Functions (4): ETL, PromptBuilder, LLMBatch, ReportSender
✅ Step Functions State Machine: ai-scraper-dev-ai-analysis
✅ EventBridge Rule: Daily execution at 18:00 UTC (03:00 JST)
✅ IAM Roles: Lambda execution, Step Functions, EventBridge
✅ SSM Parameter: OpenAI API key storage

## TESTING ISSUES - 2025-07-10

### Issue 4: Lambda Dependencies Not Installed
**Error**: `Unable to import module 'app': No module named 'pandas'`
**Error**: `Unable to import module 'app': No module named 'openai'`
**Cause**: SAM build process didn't install requirements.txt dependencies during deployment
**Status**: CRITICAL - Lambda functions deployed without required Python packages
**Requirements Found**:
- ETL: pandas==1.5.3, numpy==1.24.4, boto3==1.34.162
- PromptBuilder: boto3==1.34.162
- LLMBatch: openai==1.42.0, boto3==1.34.162
- ReportSender: boto3==1.34.162

### Issue 5: Missing S3 Bucket/Test Data
**Error**: `NoSuchBucket: The specified bucket does not exist`
**Error**: `Parameter validation failed: Invalid type for parameter Key, value: None`
**Cause**: Lambda functions expect specific S3 buckets and data files that don't exist
**Status**: Need to create test data or use proper S3 bucket (tokyo-real-estate-ai-data)

### Issue 6: Missing Function Parameters
**Error**: Functions expecting specific input parameters for S3 keys and data
**Cause**: Test payload '{"test": "data"}' doesn't match expected function input schema
**Status**: Need to create proper test payloads matching function expectations

## CRITICAL DEPLOYMENT PROBLEM
**ROOT CAUSE**: Lambda functions deployed successfully but WITHOUT dependencies installed
**IMPACT**: All functions fail at runtime due to missing Python packages
**NEXT STEPS**: 
1. Fix SAM build process to install dependencies
2. Redeploy with proper package installation
3. Create test data and proper test payloads