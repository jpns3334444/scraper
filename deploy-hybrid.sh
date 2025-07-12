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

# Step 2: Check if OpenAI layer already exists in S3
print_status "Checking for existing OpenAI layer in S3..."
if aws s3 ls s3://$DEPLOYMENT_BUCKET/layers/openai-deps.zip --region $REGION > /dev/null 2>&1; then
    print_status "✅ OpenAI layer already exists in S3, skipping build"
else
    print_status "Building minimal OpenAI layer using Docker (one-time setup)..."
    rm -rf openai-layer/
    
    # Create Dockerfile for OpenAI layer
    cat > Dockerfile.openai-layer << 'EOF'
FROM public.ecr.aws/lambda/python:3.12
COPY requirements-openai.txt .
RUN pip install -r requirements-openai.txt -t /opt/python/
EOF
    
    # Create requirements file for OpenAI only
    echo "openai" > requirements-openai.txt
    
    # Build layer using Docker
    print_status "Building OpenAI layer with Docker..."
    docker build -f Dockerfile.openai-layer -t openai-layer .
    
    # Extract layer from Docker container
    print_status "Extracting layer from Docker container..."
    docker run --rm --entrypoint="" -v $(pwd):/output openai-layer sh -c "cp -r /opt/* /output/openai-layer-temp/"
    
    # Create proper layer structure
    mkdir -p openai-layer
    mv openai-layer-temp openai-layer/python
    
    # Create layer zip
    zip -r openai-layer.zip openai-layer/ -x "*.pyc" "*/__pycache__/*"
    
    LAYER_SIZE=$(du -sh openai-layer.zip | cut -f1)
    print_status "✅ OpenAI layer built with Docker: $LAYER_SIZE"
    
    # Upload the layer immediately after building
    print_status "Uploading OpenAI layer to S3..."
    aws s3 cp openai-layer.zip s3://$DEPLOYMENT_BUCKET/layers/openai-deps.zip --region $REGION
    
    # Clean up local files
    rm -f openai-layer.zip Dockerfile.openai-layer requirements-openai.txt
    rm -rf openai-layer/
fi

# Step 3: Package Lambda functions (fast!)
print_status "Packaging Lambda functions..."
zip -r etl-function.zip lambda/etl/ -x "*.pyc" "*/__pycache__/*"
zip -r prompt-builder-function.zip lambda/prompt_builder/ -x "*.pyc" "*/__pycache__/*"
zip -r llm-batch-function.zip lambda/llm_batch/ -x "*.pyc" "*/__pycache__/*"
zip -r report-sender-function.zip lambda/report_sender/ -x "*.pyc" "*/__pycache__/*"

print_status "✅ All functions packaged"

# Step 4: Upload Lambda functions to S3
print_status "Uploading Lambda functions to S3..."
aws s3 cp etl-function.zip s3://$DEPLOYMENT_BUCKET/functions/etl.zip --region $REGION
aws s3 cp prompt-builder-function.zip s3://$DEPLOYMENT_BUCKET/functions/prompt_builder.zip --region $REGION
aws s3 cp llm-batch-function.zip s3://$DEPLOYMENT_BUCKET/functions/llm_batch.zip --region $REGION
aws s3 cp report-sender-function.zip s3://$DEPLOYMENT_BUCKET/functions/report_sender.zip --region $REGION

print_status "✅ Lambda functions uploaded"

# Step 5: Deploy CloudFormation
print_status "Deploying CloudFormation stack..."
print_status "Stack: $STACK_NAME"
print_status "Template: ai-infra/ai-stack-cfn.yaml"
print_status "Output Bucket: tokyo-real-estate-ai-data"

# Get OpenAI API key from AWS Secrets Manager
print_status "Retrieving OpenAI API key from AWS Secrets Manager..."
OPENAI_API_KEY=$(aws secretsmanager get-secret-value --secret-id "ai-scraper/openai-api-key" --query 'SecretString' --output text --region $REGION 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$OPENAI_API_KEY" ]; then
    print_error "Failed to retrieve OpenAI API key from AWS Secrets Manager"
    print_error "Please ensure the secret 'ai-scraper/openai-api-key' exists"
    exit 1
fi

print_status "Starting CloudFormation deployment..."
aws cloudformation deploy \
  --template-file ai-infra/ai-stack-cfn.yaml \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_IAM \
  --region $REGION \
  --parameter-overrides \
    DeploymentBucket=$DEPLOYMENT_BUCKET \
    OutputBucket=tokyo-real-estate-ai-data \
    OpenAIAPIKey="$OPENAI_API_KEY" \
    EmailFrom=noreply@example.com \
    EmailTo=test@example.com \
    OpenAIDepsLayerKey=layers/openai-deps.zip

DEPLOY_RESULT=$?

if [ $DEPLOY_RESULT -eq 0 ]; then
    print_status "🎉 Deployment successful!"
    print_status "Stack uses AWS prebuilt layers (no build time) + minimal OpenAI layer"
    print_status "Output bucket: tokyo-real-estate-ai-data"
    
    # Show stack outputs
    print_status "Stack outputs:"
    aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query 'Stacks[0].Outputs' --output table
else
    print_error "CloudFormation deployment failed with exit code: $DEPLOY_RESULT"
    print_error "Checking for stack events and failure details..."
    
    # Get detailed failure information
    aws cloudformation describe-stack-events --stack-name $STACK_NAME --region $REGION \
      --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`ROLLBACK_IN_PROGRESS` || ResourceStatus==`DELETE_IN_PROGRESS`].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]' \
      --output table
    
    print_error "Deployment failed. Check the error details above."
    exit 1
fi

# Cleanup
print_status "Cleaning up local files..."
rm -f *.zip
rm -rf openai-layer/

print_status "✅ Deployment complete. Next: Test the functions!"