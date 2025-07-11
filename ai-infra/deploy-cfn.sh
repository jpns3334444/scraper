#!/bin/bash

# CloudFormation deployment script for AI infrastructure
# Replaces the SAM-based deployment

set -e

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-ai-scraper-dev}"
DEPLOYMENT_BUCKET="${DEPLOYMENT_BUCKET:-ai-scraper-dev-artifacts-$REGION}"

# Email configuration
EMAIL_FROM="${EMAIL_FROM:-noreply@example.com}"
EMAIL_TO="${EMAIL_TO:-admin@example.com}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

print_info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] INFO:${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
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
    
    # Display AWS account info
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    print_info "AWS Account ID: $ACCOUNT_ID"
    print_info "Region: $REGION"
    print_info "Stack Name: $STACK_NAME"
}

# Check or create OpenAI API key secret
check_openai_secret() {
    print_status "Checking OpenAI API key secret..."
    
    if ! aws secretsmanager describe-secret \
        --secret-id "ai-scraper/openai-api-key" \
        --region "$REGION" &> /dev/null; then
        
        print_warning "OpenAI API key secret not found."
        print_info "Please create it manually:"
        echo ""
        echo "aws secretsmanager create-secret \\"
        echo "    --name ai-scraper/openai-api-key \\"
        echo "    --secret-string 'YOUR_OPENAI_API_KEY' \\"
        echo "    --region $REGION"
        echo ""
        exit 1
    else
        print_status "OpenAI API key secret exists"
    fi
}

# Package and upload Lambda code
package_lambdas() {
    print_status "Packaging Lambda functions and layers..."
    
    # Run the packaging script
    ./package-lambdas.sh
    
    if [ $? -ne 0 ]; then
        print_error "Lambda packaging failed"
        exit 1
    fi
}

# Deploy CloudFormation stack
deploy_stack() {
    print_status "Deploying CloudFormation stack..."
    
    # Get OpenAI API key (dummy value for parameter)
    OPENAI_KEY="stored-in-secrets-manager"
    
    # Deploy the stack
    aws cloudformation deploy \
        --template-file ai-stack-cfn.yaml \
        --stack-name "$STACK_NAME" \
        --parameter-overrides \
            DeploymentBucket="$DEPLOYMENT_BUCKET" \
            OpenAIAPIKey="$OPENAI_KEY" \
            EmailFrom="$EMAIL_FROM" \
            EmailTo="$EMAIL_TO" \
        --capabilities CAPABILITY_IAM \
        --region "$REGION" \
        --no-fail-on-empty-changeset
    
    if [ $? -eq 0 ]; then
        print_status "Stack deployment successful!"
    else
        print_error "Stack deployment failed"
        exit 1
    fi
}

# Display stack outputs
display_outputs() {
    print_status "Stack outputs:"
    
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
}

# Test the deployment
test_deployment() {
    print_status "Testing deployment..."
    
    # Get State Machine ARN
    STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
        --output text)
    
    if [ -n "$STATE_MACHINE_ARN" ]; then
        print_info "State Machine ARN: $STATE_MACHINE_ARN"
        print_info "You can manually trigger the workflow with:"
        echo ""
        echo "aws stepfunctions start-execution \\"
        echo "    --state-machine-arn $STATE_MACHINE_ARN \\"
        echo "    --input '{\"date\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}' \\"
        echo "    --region $REGION"
    fi
}

# Main execution
main() {
    print_status "Starting AI infrastructure deployment (CloudFormation)..."
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --stack-name)
                STACK_NAME="$2"
                shift 2
                ;;
            --region)
                REGION="$2"
                AWS_REGION="$2"
                shift 2
                ;;
            --email-from)
                EMAIL_FROM="$2"
                shift 2
                ;;
            --email-to)
                EMAIL_TO="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --stack-name NAME    CloudFormation stack name (default: ai-scraper-dev)"
                echo "  --region REGION      AWS region (default: ap-northeast-1)"
                echo "  --email-from EMAIL   From email for SES (default: noreply@example.com)"
                echo "  --email-to EMAIL     To email for reports (default: admin@example.com)"
                echo "  --help               Show this help message"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Execute deployment steps
    check_prerequisites
    check_openai_secret
    package_lambdas
    deploy_stack
    display_outputs
    test_deployment
    
    print_status "Deployment complete! ✅"
    print_info "The AI analysis will run daily at 03:00 JST (18:00 UTC)"
}

# Run main function
main "$@"