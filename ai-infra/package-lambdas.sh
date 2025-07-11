#!/bin/bash

# Lambda packaging script for CloudFormation deployment
# This script packages Lambda functions and layers, uploads them to S3

set -e

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-ai-scraper-dev}"
DEPLOYMENT_BUCKET="${DEPLOYMENT_BUCKET:-ai-scraper-dev-artifacts-$REGION}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# Check if deployment bucket exists, create if not
check_deployment_bucket() {
    print_status "Checking deployment bucket: $DEPLOYMENT_BUCKET"
    
    if ! aws s3 ls "s3://$DEPLOYMENT_BUCKET" --region "$REGION" 2>/dev/null; then
        print_status "Creating deployment bucket: $DEPLOYMENT_BUCKET"
        aws s3 mb "s3://$DEPLOYMENT_BUCKET" --region "$REGION"
        
        # Enable versioning
        aws s3api put-bucket-versioning \
            --bucket "$DEPLOYMENT_BUCKET" \
            --versioning-configuration Status=Enabled \
            --region "$REGION"
    else
        print_status "Deployment bucket exists: $DEPLOYMENT_BUCKET"
    fi
}

# Package Lambda layers
package_layers() {
    print_status "Packaging Lambda layers..."
    
    # Create temp directory for packaging
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    # Package Python dependencies layer
    print_status "Packaging Python dependencies layer..."
    cd ../lambda-layers/python-deps
    zip -r "$TEMP_DIR/python-deps.zip" python/
    aws s3 cp "$TEMP_DIR/python-deps.zip" "s3://$DEPLOYMENT_BUCKET/layers/python-deps.zip" --region "$REGION"
    print_status "Python dependencies layer uploaded"
    
    # Package OpenAI dependencies layer
    print_status "Packaging OpenAI dependencies layer..."
    cd ../openai-deps
    zip -r "$TEMP_DIR/openai-deps.zip" python/
    aws s3 cp "$TEMP_DIR/openai-deps.zip" "s3://$DEPLOYMENT_BUCKET/layers/openai-deps.zip" --region "$REGION"
    print_status "OpenAI dependencies layer uploaded"
    
    cd ../../ai-infra
}

# Package Lambda functions
package_functions() {
    print_status "Packaging Lambda functions..."
    
    FUNCTIONS=("etl" "prompt_builder" "llm_batch" "report_sender")
    
    for func in "${FUNCTIONS[@]}"; do
        print_status "Packaging $func function..."
        
        # Create temp directory for this function
        FUNC_TEMP_DIR=$(mktemp -d)
        
        # Copy function code
        cp -r "../lambda/$func/"*.py "$FUNC_TEMP_DIR/"
        
        # Check if function has additional requirements (skip if only comments)
        if [ -f "../lambda/$func/requirements.txt" ] && grep -q '^[^#]' "../lambda/$func/requirements.txt"; then
            print_status "Installing additional dependencies for $func..."
            pip install -r "../lambda/$func/requirements.txt" -t "$FUNC_TEMP_DIR/" --no-deps --quiet
        else
            print_status "Skipping dependencies for $func (using lambda layers)"
        fi
        
        # Create zip file
        cd "$FUNC_TEMP_DIR"
        zip -r "$TEMP_DIR/$func.zip" .
        cd - > /dev/null
        
        # Upload to S3
        aws s3 cp "$TEMP_DIR/$func.zip" "s3://$DEPLOYMENT_BUCKET/functions/$func.zip" --region "$REGION"
        print_status "$func function uploaded"
        
        # Clean up function temp dir
        rm -rf "$FUNC_TEMP_DIR"
    done
}

# Deploy CloudFormation stack
deploy_stack() {
    print_status "Deploying CloudFormation stack..."
    
    # Get OpenAI API key from existing secret (if it exists)
    OPENAI_KEY=$(aws secretsmanager get-secret-value \
        --secret-id "ai-scraper/openai-api-key" \
        --region "$REGION" \
        --query SecretString \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$OPENAI_KEY" ]; then
        print_error "OpenAI API key not found in Secrets Manager"
        print_status "Please create the secret first:"
        echo "aws secretsmanager create-secret --name ai-scraper/openai-api-key --secret-string 'YOUR_API_KEY' --region $REGION"
        exit 1
    fi
    
    # Deploy stack
    aws cloudformation deploy \
        --template-file ai-stack-cfn.yaml \
        --stack-name "$STACK_NAME" \
        --parameter-overrides \
            DeploymentBucket="$DEPLOYMENT_BUCKET" \
            OpenAIAPIKey="$OPENAI_KEY" \
            EmailFrom="${EMAIL_FROM:-noreply@example.com}" \
            EmailTo="${EMAIL_TO:-admin@example.com}" \
        --capabilities CAPABILITY_IAM \
        --region "$REGION"
    
    print_status "Stack deployment complete!"
}

# Main execution
main() {
    print_status "Starting Lambda packaging and deployment..."
    
    # Check prerequisites
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI not found. Please install AWS CLI."
        exit 1
    fi
    
    if ! command -v zip &> /dev/null; then
        print_error "zip command not found. Please install zip."
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Please run 'aws configure'."
        exit 1
    fi
    
    # Execute steps
    check_deployment_bucket
    package_layers
    package_functions
    
    print_status "All Lambda packages uploaded successfully!"
    print_status "Deployment bucket: $DEPLOYMENT_BUCKET"
    print_status ""
    print_status "To deploy the CloudFormation stack, run:"
    echo "aws cloudformation deploy \\"
    echo "    --template-file ai-stack-cfn.yaml \\"
    echo "    --stack-name $STACK_NAME \\"
    echo "    --parameter-overrides DeploymentBucket=$DEPLOYMENT_BUCKET \\"
    echo "    --capabilities CAPABILITY_IAM \\"
    echo "    --region $REGION"
}

# Run main function
main "$@"