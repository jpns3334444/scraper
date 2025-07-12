#!/bin/bash
# Deploy-only script - assumes layers are already built and tested
set -e

# Color output for better UX
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="ai-scraper-dev"
BUCKET_NAME="ai-scraper-dev-artifacts-${REGION}"

print_status "🚀 Starting Lambda deployment (layers already built)"
print_status "Region: $REGION"
print_status "Stack: $STACK_NAME"
print_status "Bucket: $BUCKET_NAME"

# Quick layer verification
print_step "Verifying layers exist..."
for layer in python-deps openai-deps; do
    if [ ! -d "lambda-layers/$layer/python" ]; then
        print_error "Layer lambda-layers/$layer/python not found"
        print_status "Run build scripts first to create the layers"
        exit 1
    fi
done
print_status "✅ All layers found"

# Package layers
print_step "Packaging layers..."
cd lambda-layers

print_status "Packaging python-deps layer..."
if [ -f "python-deps-layer.zip" ]; then
    rm python-deps-layer.zip
fi
cd python-deps && zip -r ../python-deps-layer.zip . && cd ..

print_status "Packaging openai-deps layer..."
if [ -f "openai-deps-layer.zip" ]; then
    rm openai-deps-layer.zip
fi
cd openai-deps && zip -r ../openai-deps-layer.zip . && cd ..

cd ..

# Package Lambda functions
print_step "Packaging Lambda functions..."

print_status "Packaging ETL function..."
cd lambda/etl
if [ -f "etl-function.zip" ]; then
    rm etl-function.zip
fi
zip etl-function.zip app.py
mv etl-function.zip ../../
cd ../..

print_status "Packaging Prompt Builder function..."
cd lambda/prompt_builder
if [ -f "prompt-builder-function.zip" ]; then
    rm prompt-builder-function.zip
fi
zip prompt-builder-function.zip app.py
mv prompt-builder-function.zip ../../
cd ../..

print_status "Packaging LLM Batch function..."
cd lambda/llm_batch
if [ -f "llm-batch-function.zip" ]; then
    rm llm-batch-function.zip
fi
zip llm-batch-function.zip app.py
mv llm-batch-function.zip ../../
cd ../..

print_status "Packaging Report Sender function..."
cd lambda/report_sender
if [ -f "report-sender-function.zip" ]; then
    rm report-sender-function.zip
fi
zip report-sender-function.zip app.py
mv report-sender-function.zip ../../
cd ../..

# Deploy with CloudFormation
print_step "Deploying with CloudFormation..."

print_status "Uploading artifacts to S3..."
aws s3 cp lambda-layers/python-deps-layer.zip s3://$BUCKET_NAME/layers/python-deps.zip
aws s3 cp lambda-layers/openai-deps-layer.zip s3://$BUCKET_NAME/layers/openai-deps.zip
aws s3 cp etl-function.zip s3://$BUCKET_NAME/functions/etl.zip
aws s3 cp prompt-builder-function.zip s3://$BUCKET_NAME/functions/prompt_builder.zip
aws s3 cp llm-batch-function.zip s3://$BUCKET_NAME/functions/llm_batch.zip
aws s3 cp report-sender-function.zip s3://$BUCKET_NAME/functions/report_sender.zip

print_status "Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file ai-infra/ai-stack-cfn.yaml \
    --stack-name $STACK_NAME \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --parameter-overrides \
        DeploymentBucket=$BUCKET_NAME \
        OutputBucket=re-stock \
        OpenAIAPIKey=dummy \
        EmailFrom=noreply@example.com \
        EmailTo=test@example.com

print_status "🎉 Deployment completed successfully!"
print_status "Stack: $STACK_NAME in region $REGION"

# Clean up local zip files
rm -f lambda-layers/python-deps-layer.zip lambda-layers/openai-deps-layer.zip
rm -f etl-function.zip prompt-builder-function.zip llm-batch-function.zip report-sender-function.zip

print_status "✅ Cleanup completed"