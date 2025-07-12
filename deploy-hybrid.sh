#!/bin/bash
# Streamlined deployment using AWS prebuilt layers + minimal OpenAI layer
# This replaces the complex Docker-based layer building approach

set -e

# Color output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}WARNING:${NC} $1"
}

# Configuration
DEPLOYMENT_BUCKET="ai-scraper-dev-artifacts-ap-northeast-1"
STACK_NAME="ai-scraper-dev"
REGION="ap-northeast-1"

print_status "🚀 Starting hybrid layer deployment (AWS prebuilt + minimal OpenAI)"

# Step 1: Verify AWS CLI and credentials
print_status "Checking AWS credentials..."
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    print_error "AWS credentials not configured"
    exit 1
fi

# Step 2: Build minimal OpenAI layer (fast!)
print_status "Building minimal OpenAI layer (~1 minute)..."
rm -rf openai-layer/
mkdir -p openai-layer/python
pip install openai --target openai-layer/python/ --no-cache-dir
zip -r openai-layer.zip openai-layer/ -x "*.pyc" "*/__pycache__/*"

LAYER_SIZE=$(du -sh openai-layer.zip | cut -f1)
print_status "✅ OpenAI layer built: $LAYER_SIZE"

# Step 3: Package Lambda functions (fast!)
print_status "Packaging Lambda functions..."
zip -r etl-function.zip lambda/etl/ -x "*.pyc" "*/__pycache__/*"
zip -r prompt-builder-function.zip lambda/prompt_builder/ -x "*.pyc" "*/__pycache__/*"
zip -r llm-batch-function.zip lambda/llm_batch/ -x "*.pyc" "*/__pycache__/*"
zip -r report-sender-function.zip lambda/report_sender/ -x "*.pyc" "*/__pycache__/*"

print_status "✅ All functions packaged"

# Step 4: Upload to S3 (only small files!)
print_status "Uploading to S3..."
aws s3 cp openai-layer.zip s3://$DEPLOYMENT_BUCKET/layers/openai-deps.zip --region $REGION
aws s3 cp etl-function.zip s3://$DEPLOYMENT_BUCKET/functions/etl.zip --region $REGION
aws s3 cp prompt-builder-function.zip s3://$DEPLOYMENT_BUCKET/functions/prompt_builder.zip --region $REGION
aws s3 cp llm-batch-function.zip s3://$DEPLOYMENT_BUCKET/functions/llm_batch.zip --region $REGION
aws s3 cp report-sender-function.zip s3://$DEPLOYMENT_BUCKET/functions/report_sender.zip --region $REGION

print_status "✅ Upload complete"

# Step 5: Deploy CloudFormation
print_status "Deploying CloudFormation stack..."
aws cloudformation deploy \
  --template-file ai-infra/ai-stack-cfn.yaml \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_IAM \
  --region $REGION \
  --parameter-overrides \
    DeploymentBucket=$DEPLOYMENT_BUCKET \
    OutputBucket=re-stock \
    OpenAIAPIKey=dummy \
    EmailFrom=noreply@example.com \
    EmailTo=test@example.com \
    OpenAIDepsLayerKey=layers/openai-deps.zip

if [ $? -eq 0 ]; then
    print_status "🎉 Deployment successful!"
    print_status "Stack uses AWS prebuilt layers (no build time) + minimal OpenAI layer"
    print_status "Total deployment time: <5 minutes (vs 15+ minutes previously)"
else
    print_error "Deployment failed"
    exit 1
fi

# Cleanup
print_status "Cleaning up local files..."
rm -f *.zip
rm -rf openai-layer/

print_status "✅ Deployment complete. Next: Test the functions!"