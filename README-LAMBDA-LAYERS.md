# Lambda Layer Python 3.13 Rebuild Guide

## Overview
This guide provides a complete solution for rebuilding your Lambda layers from Python 3.8 to Python 3.13 using the official AWS Lambda Docker image.

## Problem Solved
- **Issue**: Lambda functions updated to Python 3.13 runtime but layers contain Python 3.8 compiled packages
- **Error**: Import errors due to version mismatch (e.g., `.cpython-38-x86_64-linux-gnu.so` files)
- **Solution**: Rebuild layers with Python 3.13 compatible packages using official AWS image

## Quick Start

### Prerequisites
- Docker installed and running
- AWS CLI configured
- Basic bash shell access

### Three-Step Process

1. **Build layers with latest Python 3.13 packages:**
   ```bash
   ./build-layers.sh
   ```

2. **Test layers work properly:**
   ```bash
   ./test-layers.sh
   ```

3. **Deploy everything to AWS:**
   ```bash
   ./deploy-enhanced.sh
   ```

## What's Included

### 1. Enhanced Build Script (`build-layers.sh`)
- Uses official AWS Lambda Python 3.13 image: `public.ecr.aws/lambda/python:3.13`
- Installs latest versions of all packages
- Comprehensive error checking and validation
- Clean rebuild process that removes old Python 3.8 files

### 2. Layer Verification Script (`test-layers.sh`)
- Tests all package imports work correctly
- Verifies version compatibility
- Tests combined layer usage (simulates Lambda environment)
- Ensures no conflicts between layers

### 3. Enhanced Deployment Script (`deploy-enhanced.sh`)
- Full end-to-end deployment with verification
- Uses existing CloudFormation infrastructure
- Comprehensive error handling
- Detailed progress reporting

### 4. Updated CloudFormation Template
- All Lambda functions updated to Python 3.13 runtime
- Layer compatibility set to Python 3.13
- No breaking changes to existing infrastructure

### 5. Updated Requirements
- Latest stable versions of all packages
- Python 3.13 compatible version ranges
- Removed strict version pinning for better compatibility

## Package Versions

### Python Dependencies Layer
- **pandas**: Latest 2.2.x series (was 2.1.4)
- **numpy**: Latest 1.26.x series (was 1.24.4)
- **boto3**: Latest version (was 1.34.162)
- **pytz**: Latest version (was 2023.3)

### OpenAI Dependencies Layer
- **openai**: Latest stable >=1.50.0 (was 1.42.0)
- **requests**: Latest stable >=2.32.0 (was 2.32.4)
- **python-json-logger**: Latest >=2.0.0 (was 2.0.7)

## Manual Docker Commands

If you prefer to run Docker commands manually:

```bash
# Clean old layers
rm -rf lambda-layers/python-deps/python
rm -rf lambda-layers/openai-deps/python

# Build python-deps layer
docker run --rm -v $(pwd)/lambda-layers/python-deps:/output \
  public.ecr.aws/lambda/python:3.13 \
  pip install pandas numpy boto3 pytz -t /output/python/

# Build openai-deps layer
docker run --rm -v $(pwd)/lambda-layers/openai-deps:/output \
  public.ecr.aws/lambda/python:3.13 \
  pip install openai requests python-json-logger -t /output/python/
```

## Deployment Process

The deployment uses your existing infrastructure:

1. **Layer Building**: Creates Python 3.13 compatible packages
2. **Testing**: Verifies all imports work in Lambda environment
3. **Packaging**: Uses existing `ai-infra/package-lambdas.sh` script
4. **CloudFormation**: Updates layer versions automatically
5. **Verification**: Confirms deployment success

## Benefits of This Approach

### Technical Benefits
- **Latest Python**: Python 3.13 performance and security improvements
- **Latest Packages**: All security patches and bug fixes
- **Official Image**: Guaranteed compatibility with AWS Lambda
- **No Custom Dockerfile**: Uses AWS official image directly

### Operational Benefits
- **Minimal Changes**: Works with existing deployment infrastructure
- **Comprehensive Testing**: Catches issues before deployment
- **Error Handling**: Fails fast with clear error messages
- **Progress Tracking**: Clear status updates throughout process

## Troubleshooting

### Common Issues

1. **Docker not found**: Install Docker Desktop and enable WSL 2 integration
2. **Permission errors**: Ensure scripts are executable with `chmod +x`
3. **AWS credentials**: Run `aws configure` to set up credentials
4. **Layer import errors**: Run `./test-layers.sh` to verify layers work

### Verification Steps

After deployment, verify your Lambda functions work:

1. Check CloudFormation stack status
2. Test Lambda function imports
3. Verify no Python 3.8 files remain
4. Check layer sizes are reasonable

## Files Created

- ✅ `build-layers.sh` - Layer building script
- ✅ `test-layers.sh` - Layer verification script  
- ✅ `deploy-enhanced.sh` - Complete deployment script
- ✅ `ai-infra/ai-stack-cfn.yaml` - Updated CloudFormation template
- ✅ `lambda-layers/requirements.txt` - Updated requirements
- ✅ `README-LAMBDA-LAYERS.md` - This documentation

## Next Steps

1. Run `./deploy-enhanced.sh` to deploy everything
2. Test your Lambda functions work correctly
3. Monitor CloudWatch logs for any import errors
4. Consider setting up automated layer rebuilds for future updates

Your Lambda functions are now ready with Python 3.13 and the latest packages!