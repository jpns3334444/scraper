#!/bin/bash

# Deploy Stealth Mode Infrastructure
# This script deploys the complete stealth scraper architecture

set -e

echo "🥷 Deploying Stealth Mode Scraper Infrastructure"
echo "================================================"

# Configuration
REGION="ap-northeast-1"
INFRA_STACK="scraper-infra-stack"
STEALTH_STACK="scraper-stealth-stack"
AUTOMATION_STACK="scraper-stealth-automation-stack"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Check prerequisites
print_status "Checking prerequisites..."

if ! command -v aws &> /dev/null; then
    print_error "AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials not configured. Please run 'aws configure' first."
    exit 1
fi

# Check if infrastructure stack exists
if ! aws cloudformation describe-stacks --stack-name "$INFRA_STACK" --region "$REGION" &> /dev/null; then
    print_error "Infrastructure stack '$INFRA_STACK' not found."
    print_warning "Please deploy the infrastructure stack first:"
    echo "  aws cloudformation deploy --stack-name $INFRA_STACK --template-file 'cf templates/infra-stack.yaml' --capabilities CAPABILITY_IAM --parameter-overrides MyIPv4=<your-ip>/32 MyIPv6=<your-ipv6>/128"
    exit 1
fi

print_success "Prerequisites check passed"

# Step 1: Deploy Stealth Infrastructure (DynamoDB, Step Functions)
print_status "Step 1: Deploying stealth infrastructure..."
aws cloudformation deploy \
    --stack-name "$STEALTH_STACK" \
    --template-file "cf templates/stealth-stack.yaml" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        InfraStackName="$INFRA_STACK" \
    --region "$REGION"

if [ $? -eq 0 ]; then
    print_success "Stealth infrastructure deployed successfully"
else
    print_error "Failed to deploy stealth infrastructure"
    exit 1
fi

# Step 2: Deploy Stealth Automation (EventBridge, Enhanced Lambda)
print_status "Step 2: Deploying stealth automation..."
aws cloudformation deploy \
    --stack-name "$AUTOMATION_STACK" \
    --template-file "cf templates/stealth-automation-stack.yaml" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        InfraStackName="$INFRA_STACK" \
        StealthStackName="$STEALTH_STACK" \
        NotificationEnabled="true" \
    --region "$REGION"

if [ $? -eq 0 ]; then
    print_success "Stealth automation deployed successfully"
else
    print_error "Failed to deploy stealth automation"
    exit 1
fi

# Step 3: Get deployment information
print_status "Step 3: Retrieving deployment information..."

# Get DynamoDB table name
DYNAMODB_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STEALTH_STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='SessionStateTableName'].OutputValue" \
    --output text)

# Get Lambda function name
LAMBDA_FUNCTION=$(aws cloudformation describe-stacks \
    --stack-name "$AUTOMATION_STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='StealthScraperLambdaArn'].OutputValue" \
    --output text)

# Get EventBridge rules count
RULES_COUNT=$(aws cloudformation describe-stacks \
    --stack-name "$AUTOMATION_STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EventBridgeRulesCount'].OutputValue" \
    --output text)

# Step 4: Display summary
echo ""
echo "🎉 Stealth Mode Deployment Complete!"
echo "===================================="
echo ""
print_success "Infrastructure Components:"
echo "  📊 DynamoDB Table: $DYNAMODB_TABLE"
echo "  🔧 Lambda Function: stealth-trigger-scraper"
echo "  ⏰ EventBridge Rules: $RULES_COUNT distributed sessions"
echo "  🔄 Step Functions: stealth-scraper-orchestrator"
echo ""

print_status "Stealth Session Schedule (JST):"
echo "  🌅 Morning Sessions:"
echo "    - 05:00 PM: morning-1 (ALL properties from 3-4 randomized Tokyo areas)"
echo "    - 06:30 PM: morning-2 (ALL properties from 3-4 randomized Tokyo areas)"
echo "  🌞 Afternoon Sessions:"
echo "    - 09:15 PM: afternoon-1 (ALL properties from 3-4 randomized Tokyo areas)"
echo "    - 11:45 PM: afternoon-2 (ALL properties from 3-4 randomized Tokyo areas)"
echo "  🌆 Evening Sessions:"
echo "    - 01:20 AM+1: evening-1 (ALL properties from 3-4 randomized Tokyo areas)"
echo "    - 03:10 AM+1: evening-2 (ALL properties from 3-4 randomized Tokyo areas)"
echo "  🌙 Night Sessions:"
echo "    - 05:35 AM+1: night-1 (ALL properties from 3-4 randomized Tokyo areas)"
echo "    - 07:55 AM+1: night-2 (ALL properties from 3-4 randomized Tokyo areas)"
echo ""

print_warning "Next Steps:"
echo "  1. Deploy/update your compute stack with the latest scraper code"
echo "  2. Test a single session manually:"
echo "     aws lambda invoke --function-name stealth-trigger-scraper \\"
echo "       --payload '{\"session_id\":\"test-1\",\"max_properties\":3}' /tmp/response.json"
echo "  3. Monitor session state in DynamoDB table: $DYNAMODB_TABLE"
echo "  4. Check CloudWatch logs for 'stealth-trigger-scraper' function"
echo ""

print_success "Complete Market Coverage Stealth mode is now active! 🥷"
echo "The scraper will automatically run 8 distributed sessions daily."
echo "Each session processes ALL properties from 3-4 randomized Tokyo areas."
echo "Complete Tokyo market coverage with unpredictable daily patterns."