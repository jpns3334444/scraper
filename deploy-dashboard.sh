#!/bin/bash
# Dashboard deployment script
set -e

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-tokyo-real-estate-dashboard}"
AI_STACK_NAME="${AI_STACK_NAME:-tokyo-real-estate-ai}"
BUCKET_NAME="ai-scraper-artifacts-$REGION"
TEMPLATE_FILE="$SCRIPT_DIR/dashboard-stack.yaml"

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
warn() { echo -e "${Y}WARNING:${NC} $1"; }
info() { echo -e "${B}INFO:${NC} $1"; }

echo "🚀 Real Estate Dashboard Deployment"
echo "===================================="

# Change to the script's directory
cd "$SCRIPT_DIR"

# Check prerequisites
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"
[ -f "$TEMPLATE_FILE" ] || error "CloudFormation template $TEMPLATE_FILE not found"
[ -f "../dashboard/index.html" ] || error "Dashboard HTML not found"

status "Prerequisites OK"

# Check if AI stack exists and get dashboard API function name
info "Checking AI stack..."
if ! aws cloudformation describe-stacks --stack-name $AI_STACK_NAME --region $REGION >/dev/null 2>&1; then
    error "AI stack '$AI_STACK_NAME' not found. Please deploy the AI stack first."
fi

# Get the dashboard API function name from the AI stack
DASHBOARD_API_FUNCTION=$(aws cloudformation describe-stacks \
    --stack-name $AI_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardAPIFunctionName`].OutputValue' \
    --output text)

if [ -z "$DASHBOARD_API_FUNCTION" ] || [ "$DASHBOARD_API_FUNCTION" = "None" ]; then
    error "Dashboard API function not found in AI stack. Please ensure the AI stack includes the dashboard_api function."
fi

status "✅ AI stack exists with dashboard API function: $DASHBOARD_API_FUNCTION"

# Deploy CloudFormation stack (without duplicate dashboard API function)
status "Deploying dashboard stack..."
aws cloudformation deploy \
  --template-file $TEMPLATE_FILE \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_IAM \
  --region $REGION \
  --parameter-overrides \
      AIStackName=$AI_STACK_NAME \
      DashboardAPIFunctionName=$DASHBOARD_API_FUNCTION

status "✅ CloudFormation stack deployed"

# Get stack outputs
info "Retrieving stack outputs..."
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardAPIEndpoint`].OutputValue' \
    --output text)

WEBSITE_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardWebsiteURL`].OutputValue' \
    --output text)

BUCKET_NAME_OUTPUT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardBucketName`].OutputValue' \
    --output text)

# Update index.html with API endpoint
status "Updating dashboard HTML with API endpoint..."
cp ../dashboard/index.html /tmp/index.html
sed -i.bak "s|https://YOUR_API_GATEWAY_URL/properties|${API_ENDPOINT}/properties|g" /tmp/index.html
rm /tmp/index.html.bak

# Upload dashboard HTML to S3
status "Uploading dashboard to S3..."
aws s3 cp /tmp/index.html s3://$BUCKET_NAME_OUTPUT/index.html --region $REGION --content-type text/html

# Clean up temp file
rm /tmp/index.html

# Success summary
echo ""
status "🎉 Dashboard deployment completed successfully!"
echo ""
echo "📋 Dashboard Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  API Endpoint: $API_ENDPOINT"
echo "  Website URL: $WEBSITE_URL"
echo "  Using existing dashboard API function: $DASHBOARD_API_FUNCTION"
echo ""
echo "🌐 Access your dashboard at:"
echo "  $WEBSITE_URL"
echo ""
echo "💡 Next Steps:"
echo "  1. Open the dashboard URL in your browser"
echo "  2. The dashboard will automatically load property data"
echo "  3. Use filters to search and sort properties"
echo "  4. Filter settings are saved in your browser's localStorage"
echo ""
echo "🔧 Troubleshooting:"
echo "  - If no data appears, check that the DynamoDB table has data"
echo "  - Check CloudWatch logs for the dashboard-api Lambda function"
echo "  - Ensure CORS is working properly (check browser console)"

# Make script executable
chmod +x "$SCRIPT_DIR/deploy-dashboard.sh"