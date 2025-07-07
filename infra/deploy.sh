#!/bin/bash

# =====================================================================
# AI Real Estate Analysis - Deployment Script
# Deploys the AI analysis stack using AWS SAM
# =====================================================================

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default values
STACK_NAME="ai-scraper"
ENVIRONMENT="dev"
AWS_REGION="us-east-1"
TEMPLATE_FILE="ai-stack.yaml"
BUILD_DIR=".aws-sam"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Deploy the AI Real Estate Analysis stack to AWS.

OPTIONS:
    -e, --environment ENV     Environment name (dev, staging, prod) [default: dev]
    -s, --stack-name NAME     CloudFormation stack name [default: ai-scraper]
    -r, --region REGION       AWS region [default: us-east-1]
    -b, --bucket BUCKET       S3 bucket for SAM deployment artifacts (required)
    --openai-key KEY          OpenAI API key (required)
    --slack-webhook URL       Slack webhook URL (required)
    --email-from EMAIL        From email address for notifications (required)
    --email-to EMAIL          To email address for notifications (required)
    --validate-only           Only validate template, don't deploy
    --build-only              Only build, don't deploy
    -h, --help               Show this help message

EXAMPLES:
    # Deploy to development
    ./deploy.sh -e dev -b my-sam-bucket --openai-key sk-... --slack-webhook https://hooks.slack.com/... --email-from from@example.com --email-to to@example.com

    # Deploy to production
    ./deploy.sh -e prod -s ai-scraper-prod -b my-sam-bucket --openai-key sk-... --slack-webhook https://hooks.slack.com/... --email-from from@example.com --email-to to@example.com

    # Validate only
    ./deploy.sh --validate-only

REQUIRED TOOLS:
    - AWS CLI (configured with appropriate permissions)
    - AWS SAM CLI
    - Docker (for building Lambda containers)

EOF
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    
    # Check AWS SAM CLI
    if ! command -v sam &> /dev/null; then
        print_error "AWS SAM CLI is not installed. Please install it first."
        exit 1
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install it first."
        exit 1
    fi
    
    # Check if Docker is running
    if ! docker info &> /dev/null; then
        print_error "Docker is not running. Please start Docker first."
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Please run 'aws configure' first."
        exit 1
    fi
    
    print_success "All prerequisites satisfied"
}

# Function to validate CloudFormation template
validate_template() {
    print_status "Validating CloudFormation template..."
    
    cd "$SCRIPT_DIR"
    
    if aws cloudformation validate-template --template-body file://"$TEMPLATE_FILE" &> /dev/null; then
        print_success "CloudFormation template is valid"
    else
        print_error "CloudFormation template validation failed"
        aws cloudformation validate-template --template-body file://"$TEMPLATE_FILE"
        exit 1
    fi
}

# Function to build Lambda functions
build_functions() {
    print_status "Building Lambda functions..."
    
    cd "$SCRIPT_DIR"
    
    # Clean previous build
    if [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
    
    # Build with SAM
    if sam build --template "$TEMPLATE_FILE" --base-dir "$PROJECT_ROOT"; then
        print_success "Lambda functions built successfully"
    else
        print_error "Failed to build Lambda functions"
        exit 1
    fi
}

# Function to deploy stack
deploy_stack() {
    print_status "Deploying stack: $FULL_STACK_NAME"
    
    cd "$SCRIPT_DIR"
    
    # Prepare parameter overrides
    local param_overrides=""
    
    if [ -n "$OPENAI_API_KEY" ]; then
        param_overrides="$param_overrides OpenAIAPIKey=$OPENAI_API_KEY"
    fi
    
    if [ -n "$SLACK_WEBHOOK_URL" ]; then
        param_overrides="$param_overrides SlackHookURL=$SLACK_WEBHOOK_URL"
    fi
    
    if [ -n "$EMAIL_FROM" ]; then
        param_overrides="$param_overrides EmailFrom=$EMAIL_FROM"
    fi
    
    if [ -n "$EMAIL_TO" ]; then
        param_overrides="$param_overrides EmailTo=$EMAIL_TO"
    fi
    
    # Deploy with SAM
    if sam deploy \
        --template-file "$BUILD_DIR/template.yaml" \
        --stack-name "$FULL_STACK_NAME" \
        --s3-bucket "$DEPLOYMENT_BUCKET" \
        --s3-prefix "$FULL_STACK_NAME" \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides $param_overrides \
        --no-fail-on-empty-changeset \
        --region "$AWS_REGION" \
        --tags Environment="$ENVIRONMENT" Project="ai-real-estate"; then
        
        print_success "Stack deployed successfully"
        
        # Get stack outputs
        print_status "Stack outputs:"
        aws cloudformation describe-stacks \
            --stack-name "$FULL_STACK_NAME" \
            --region "$AWS_REGION" \
            --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
            --output table
    else
        print_error "Failed to deploy stack"
        exit 1
    fi
}

# Function to run smoke tests
run_smoke_tests() {
    print_status "Running smoke tests..."
    
    # Get Step Functions ARN from stack outputs
    local state_machine_arn
    state_machine_arn=$(aws cloudformation describe-stacks \
        --stack-name "$FULL_STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
        --output text)
    
    if [ -z "$state_machine_arn" ]; then
        print_warning "Could not retrieve State Machine ARN, skipping smoke tests"
        return
    fi
    
    print_status "State Machine ARN: $state_machine_arn"
    
    # Test with a recent date (yesterday)
    local test_date
    test_date=$(date -d "yesterday" +%Y-%m-%d)
    
    print_status "Starting test execution with date: $test_date"
    
    local execution_arn
    execution_arn=$(aws stepfunctions start-execution \
        --state-machine-arn "$state_machine_arn" \
        --name "smoke-test-$(date +%Y%m%d-%H%M%S)" \
        --input "{\"date\":\"$test_date\"}" \
        --region "$AWS_REGION" \
        --query 'executionArn' \
        --output text)
    
    print_status "Test execution started: $execution_arn"
    
    # Wait for a short time to see if it starts properly
    sleep 30
    
    local status
    status=$(aws stepfunctions describe-execution \
        --execution-arn "$execution_arn" \
        --region "$AWS_REGION" \
        --query 'status' \
        --output text)
    
    if [ "$status" = "RUNNING" ] || [ "$status" = "SUCCEEDED" ]; then
        print_success "Smoke test: Step Functions execution started successfully"
    else
        print_warning "Smoke test: Step Functions execution status: $status"
        
        # Get error details if failed
        if [ "$status" = "FAILED" ]; then
            aws stepfunctions describe-execution \
                --execution-arn "$execution_arn" \
                --region "$AWS_REGION" \
                --query 'error'
        fi
    fi
}

# Function to show deployment summary
show_summary() {
    cat << EOF

${GREEN}========================================${NC}
${GREEN}  Deployment Summary${NC}
${GREEN}========================================${NC}

Stack Name: $FULL_STACK_NAME
Environment: $ENVIRONMENT
Region: $AWS_REGION
Template: $TEMPLATE_FILE

${BLUE}Next Steps:${NC}
1. Monitor the first execution in Step Functions console
2. Check CloudWatch logs for any issues
3. Verify Slack and email notifications are working
4. Set up CloudWatch alarms for monitoring

${BLUE}Useful Commands:${NC}
# View stack resources
aws cloudformation describe-stack-resources --stack-name $FULL_STACK_NAME

# View recent executions
aws stepfunctions list-executions --state-machine-arn \$(aws cloudformation describe-stacks --stack-name $FULL_STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==\`StateMachineArn\`].OutputValue' --output text)

# Manual execution
aws stepfunctions start-execution --state-machine-arn \$(aws cloudformation describe-stacks --stack-name $FULL_STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==\`StateMachineArn\`].OutputValue' --output text) --name manual-\$(date +%Y%m%d-%H%M%S) --input '{"date":"$(date +%Y-%m-%d)"}'

${GREEN}========================================${NC}

EOF
}

# Parse command line arguments
VALIDATE_ONLY=false
BUILD_ONLY=false
DEPLOYMENT_BUCKET=""
OPENAI_API_KEY=""
SLACK_WEBHOOK_URL=""
EMAIL_FROM=""
EMAIL_TO=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -s|--stack-name)
            STACK_NAME="$2"
            shift 2
            ;;
        -r|--region)
            AWS_REGION="$2"
            shift 2
            ;;
        -b|--bucket)
            DEPLOYMENT_BUCKET="$2"
            shift 2
            ;;
        --openai-key)
            OPENAI_API_KEY="$2"
            shift 2
            ;;
        --slack-webhook)
            SLACK_WEBHOOK_URL="$2"
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
        --validate-only)
            VALIDATE_ONLY=true
            shift
            ;;
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Set full stack name
FULL_STACK_NAME="${STACK_NAME}-${ENVIRONMENT}"

# Main execution
main() {
    print_status "Starting deployment of AI Real Estate Analysis stack"
    print_status "Environment: $ENVIRONMENT"
    print_status "Stack Name: $FULL_STACK_NAME"
    print_status "Region: $AWS_REGION"
    
    check_prerequisites
    validate_template
    
    if [ "$VALIDATE_ONLY" = true ]; then
        print_success "Template validation completed"
        exit 0
    fi
    
    build_functions
    
    if [ "$BUILD_ONLY" = true ]; then
        print_success "Build completed"
        exit 0
    fi
    
    # Check required parameters for deployment
    if [ -z "$DEPLOYMENT_BUCKET" ]; then
        print_error "Deployment bucket is required for deployment. Use -b or --bucket option."
        exit 1
    fi
    
    if [ -z "$OPENAI_API_KEY" ]; then
        print_error "OpenAI API key is required. Use --openai-key option."
        exit 1
    fi
    
    if [ -z "$SLACK_WEBHOOK_URL" ]; then
        print_error "Slack webhook URL is required. Use --slack-webhook option."
        exit 1
    fi
    
    if [ -z "$EMAIL_FROM" ]; then
        print_error "From email address is required. Use --email-from option."
        exit 1
    fi
    
    if [ -z "$EMAIL_TO" ]; then
        print_error "To email address is required. Use --email-to option."
        exit 1
    fi
    
    deploy_stack
    run_smoke_tests
    show_summary
}

# Run main function
main "$@"