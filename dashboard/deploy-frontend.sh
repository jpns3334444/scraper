#!/bin/bash
# Tokyo Real Estate Frontend Stack deployment script
set -e

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
warn() { echo -e "${Y}WARNING:${NC} $1"; }
info() { echo -e "${B}INFO:${NC} $1"; }

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-tokyo-real-estate-frontend}"
STACK_PREFIX="${STACK_PREFIX:-tre-frontend}"
AI_STACK_NAME="${AI_STACK_NAME:-tokyo-real-estate-ai}"
DEPLOYMENT_BUCKET="${DEPLOYMENT_BUCKET:-ai-scraper-artifacts-$REGION}"
TEMPLATE_FILE="$SCRIPT_DIR/front-end-stack.yaml"

# Verify deployment bucket exists
info "Checking deployment bucket '$DEPLOYMENT_BUCKET'..."
if ! aws s3 ls s3://$DEPLOYMENT_BUCKET/ --region $REGION >/dev/null 2>&1; then
    error "Deployment bucket '$DEPLOYMENT_BUCKET' not found. Please run deploy-ai.sh first to create it."
fi

# Verify AI stack exists and has required exports
info "Verifying AI stack exports..."
if ! aws cloudformation describe-stacks --stack-name $AI_STACK_NAME --region $REGION >/dev/null 2>&1; then
    error "AI stack '$AI_STACK_NAME' not found. Please deploy the AI stack first."
fi

info "Using AI stack: $AI_STACK_NAME"
info "Using deployment bucket: $DEPLOYMENT_BUCKET"

echo "🚀 Tokyo Real Estate Frontend Stack Deployment"
echo "============================================="

# Change to the script's directory
cd "$SCRIPT_DIR"

# Check prerequisites
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"
[ -f "$TEMPLATE_FILE" ] || error "CloudFormation template $TEMPLATE_FILE not found"
[ -f "index.html" ] || error "Dashboard HTML file index.html not found"

status "Prerequisites OK"

# Validate CloudFormation template
status "Validating CloudFormation template..."
aws cloudformation validate-template \
    --template-body file://$TEMPLATE_FILE \
    --region $REGION >/dev/null || error "Template validation failed"

status "✅ Template validation passed"

# The DynamoDB tables are now managed by the AI stack
# Frontend stack will import them via CloudFormation exports

# Deploy CloudFormation stack
status "Deploying frontend stack..."
aws cloudformation deploy \
    --template-file $TEMPLATE_FILE \
    --stack-name $STACK_NAME \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $REGION \
    --parameter-overrides \
        StackNamePrefix=$STACK_PREFIX \
        AIStackName=$AI_STACK_NAME \
        DeploymentBucket=$DEPLOYMENT_BUCKET \
    --no-fail-on-empty-changeset

if [ $? -eq 0 ]; then
    status "✅ CloudFormation stack deployed successfully"
else
    error "CloudFormation deployment failed"
fi

# Get stack outputs
info "Retrieving stack outputs..."
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FrontendApiEndpoint`].OutputValue' \
    --output text 2>/dev/null)

WEBSITE_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`StaticSiteURL`].OutputValue' \
    --output text 2>/dev/null)

S3_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' \
    --output text 2>/dev/null)

# Get all Lambda function ARNs for reference
DASHBOARD_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

FAVORITES_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FavoritesAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

# Validate outputs
[ -n "$API_ENDPOINT" ] || error "Failed to get API endpoint from stack outputs"
[ -n "$WEBSITE_URL" ] || error "Failed to get website URL from stack outputs"
[ -n "$S3_BUCKET" ] || error "Failed to get S3 bucket name from stack outputs"

# Update index.html with API endpoint
status "Updating dashboard HTML with API endpoint..."
# Create a backup first
cp index.html index.html.bak

# Replace both API_URL and FAVORITES_API_URL (since they're now the same)
sed -i.tmp "s|const API_URL = '[^']*';|const API_URL = '${API_ENDPOINT}';|g" index.html
sed -i.tmp "s|const FAVORITES_API_URL = '[^']*';|const FAVORITES_API_URL = API_URL;|g" index.html
rm -f index.html.tmp

# Verify the replacement worked
if grep -q "$API_ENDPOINT" index.html; then
    status "✅ API endpoint updated in HTML"
else
    warn "API endpoint replacement may not have worked properly"
    info "Please manually update the API_URL constant in index.html to: $API_ENDPOINT"
fi

# Upload dashboard HTML to S3
status "Uploading dashboard to S3..."
aws s3 cp index.html s3://$S3_BUCKET/index.html \
    --region $REGION \
    --content-type text/html \
    --cache-control "no-cache" || error "Failed to upload HTML to S3"

status "✅ Dashboard uploaded successfully"

# Test the API endpoint
status "Testing API endpoint..."
if curl -s --max-time 10 "${API_ENDPOINT}/properties?limit=1" >/dev/null; then
    status "✅ API endpoint is responding"
else
    warn "API endpoint test failed - dashboard may still be initializing"
fi

# Restore original HTML file
mv index.html.bak index.html

# Success summary
echo ""
status "🎉 Frontend stack deployment completed successfully!"
echo ""
echo "📋 Frontend Stack Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  AI Stack: $AI_STACK_NAME"
echo "  Deployment Bucket: $DEPLOYMENT_BUCKET"
echo "  S3 Bucket: $S3_BUCKET"
echo ""
echo "🔎 Lambda Functions Deployed:"
echo "  Dashboard API: $(basename $DASHBOARD_FUNCTION_ARN 2>/dev/null || echo 'N/A')"
echo "  Favorites API: $(basename $FAVORITES_FUNCTION_ARN 2>/dev/null || echo 'N/A')"
echo "  Register User: $STACK_PREFIX-register-user"
echo "  Login User: $STACK_PREFIX-login-user"
echo ""
echo "🌐 Access your dashboard at:"
echo "  $WEBSITE_URL"
echo ""
echo "🔧 Unified API Endpoint (all routes):"
echo "  $API_ENDPOINT"
echo "  Routes: /properties, /favorites/*, /hidden/*, /auth/*"
echo ""
echo "💡 Next Steps:"
echo "  1. Open the dashboard URL in your browser"
echo "  2. Register a new user account or login"
echo "  3. Browse properties and add favorites"
echo "  4. All API calls now go through a single endpoint"
echo ""
echo "🔧 Troubleshooting:"
echo "  - Test properties endpoint: curl '${API_ENDPOINT}/properties?limit=5'"
echo "  - Test auth endpoint: curl -X OPTIONS '${API_ENDPOINT}/auth/register'"
echo "  - Check CloudWatch logs for any Lambda function issues"
echo "  - Ensure AI stack '$AI_STACK_NAME' is deployed with data"
echo ""
echo "🗑️  To delete the stack:"
echo "  aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
echo ""
echo "📝 Usage:"
echo "  DEPLOYMENT_BUCKET=your-bucket ./deploy-frontend.sh"
echo "  AWS_REGION=ap-northeast-1 STACK_NAME=my-frontend ./deploy-frontend.sh"
echo ""