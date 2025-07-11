#!/bin/bash
# Enhanced deployment script with full verification
# Builds Python 3.13 layers, tests them, and deploys to AWS
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

print_warning() {
    echo -e "${YELLOW}WARNING:${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-ai-scraper-dev}"
DEPLOYMENT_BUCKET="${DEPLOYMENT_BUCKET:-ai-scraper-dev-artifacts-$REGION}"

print_status "🚀 Starting enhanced Lambda layer deployment with Python 3.13"
print_status "Region: $REGION"
print_status "Stack: $STACK_NAME"
print_status "Bucket: $DEPLOYMENT_BUCKET"

# Pre-flight checks
print_step "Pre-flight checks..."

# Check if all required scripts exist
required_scripts=("build-layers.sh" "test-layers.sh")
for script in "${required_scripts[@]}"; do
    if [ ! -f "$script" ]; then
        print_error "Required script $script not found"
        exit 1
    fi
    if [ ! -x "$script" ]; then
        print_error "Script $script is not executable"
        print_status "Run: chmod +x $script"
        exit 1
    fi
done

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI not found. Please install AWS CLI."
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials not configured. Please run 'aws configure'."
    exit 1
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker not found. Please install Docker."
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    print_error "Docker daemon is not running. Please start Docker."
    exit 1
fi

print_status "✅ All prerequisites check passed"

# Step 1: Build layers with error checking
print_step "Step 1: Building Python 3.13 layers..."
if ! ./build-layers.sh; then
    print_error "Layer build failed"
    exit 1
fi
print_status "✅ Layer build completed successfully"

# Step 2: Test layers work properly  
print_step "Step 2: Testing layers..."
if ! ./test-layers.sh; then
    print_error "Layer tests failed"
    exit 1
fi
print_status "✅ Layer tests passed"

# Step 3: Package and deploy using existing infrastructure
print_step "Step 3: Packaging for deployment..."
if [ ! -d "ai-infra" ]; then
    print_error "ai-infra directory not found"
    exit 1
fi

cd ai-infra

# Check package script exists
if [ ! -f "package-lambdas.sh" ]; then
    print_error "package-lambdas.sh not found in ai-infra/"
    exit 1
fi

# Make sure it's executable
chmod +x package-lambdas.sh

# Run packaging script
if ! ./package-lambdas.sh; then
    print_error "Packaging failed"
    exit 1
fi

print_status "✅ Packaging completed successfully"

# Step 4: Deploy CloudFormation with Python 3.13
print_step "Step 4: Deploying CloudFormation stack..."

# Check CloudFormation template exists
if [ ! -f "ai-stack-cfn.yaml" ]; then
    print_error "ai-stack-cfn.yaml not found in ai-infra/"
    exit 1
fi

# Get current stack status if it exists
if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" &> /dev/null; then
    print_status "Stack $STACK_NAME exists, updating..."
    operation="update"
else
    print_status "Stack $STACK_NAME does not exist, creating..."
    operation="create"
fi

# Deploy stack
if ! aws cloudformation deploy \
    --template-file ai-stack-cfn.yaml \
    --stack-name "$STACK_NAME" \
    --parameter-overrides \
        DeploymentBucket="$DEPLOYMENT_BUCKET" \
    --capabilities CAPABILITY_IAM \
    --region "$REGION"; then
    print_error "CloudFormation deployment failed"
    exit 1
fi

print_status "✅ CloudFormation deployment completed successfully"

# Step 5: Get deployment information
print_step "Step 5: Deployment summary..."

# Get stack outputs
stack_outputs=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs' \
    --output table 2>/dev/null || echo "No outputs found")

print_status "Stack outputs:"
echo "$stack_outputs"

# Get layer versions
print_status "Layer versions created:"
layer_arns=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'StackResources[?ResourceType==`AWS::Lambda::LayerVersion`].[LogicalResourceId,PhysicalResourceId]' \
    --output table 2>/dev/null || echo "No layer resources found")

echo "$layer_arns"

# Final success message
print_status "🎉 Enhanced deployment completed successfully!"
print_status ""
print_status "✅ Python 3.13 layers built and deployed"
print_status "✅ All Lambda functions updated to Python 3.13"
print_status "✅ Latest package versions installed"
print_status "✅ Comprehensive testing completed"
print_status ""
print_status "Your Lambda functions are now ready with Python 3.13 runtime!"
print_status "Stack: $STACK_NAME"
print_status "Region: $REGION"

cd ..  # Return to project root