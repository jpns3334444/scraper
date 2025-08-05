#!/bin/bash
# Tokyo Real Estate Dashboard deployment script
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
STACK_NAME="${STACK_NAME:-tokyo-real-estate-dashboard}"
STACK_PREFIX="${STACK_PREFIX:-tre-dash}"
AI_STACK_NAME="${AI_STACK_NAME:-tokyo-real-estate-ai}"
TEMPLATE_FILE="$SCRIPT_DIR/dashboard-stack.yaml"

# Auto-detect resources from AI stack
info "Getting resources from AI stack..."
DYNAMODB_TABLE=$(aws cloudformation describe-stacks \
    --stack-name $AI_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DynamoDBTableName`].OutputValue' \
    --output text 2>/dev/null)

FAVORITES_API_ARN=$(aws cloudformation describe-stacks \
    --stack-name $AI_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FavoritesAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

# Get the favorites table name (construct it based on the AI stack naming pattern)
FAVORITES_TABLE_NAME="${AI_STACK_NAME}-user-favorites"

if [ -z "$DYNAMODB_TABLE" ] || [ "$DYNAMODB_TABLE" = "None" ]; then
    error "Could not get DynamoDB table name from AI stack '$AI_STACK_NAME'"
fi

if [ -z "$FAVORITES_API_ARN" ] || [ "$FAVORITES_API_ARN" = "None" ]; then
    error "Could not get Favorites API Lambda ARN from AI stack '$AI_STACK_NAME'"
fi

info "Using DynamoDB table: $DYNAMODB_TABLE"
info "Using Favorites table: $FAVORITES_TABLE_NAME" 
info "Using Favorites API ARN: $FAVORITES_API_ARN"

echo "🚀 Tokyo Real Estate Dashboard Deployment"
echo "=========================================="

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

# Check if DynamoDB table exists
info "Checking DynamoDB table '$DYNAMODB_TABLE'..."
if ! aws dynamodb describe-table --table-name $DYNAMODB_TABLE --region $REGION >/dev/null 2>&1; then
    error "DynamoDB table '$DYNAMODB_TABLE' not found. Please ensure the analysis table exists."
fi
status "✅ DynamoDB table exists"

# Deploy CloudFormation stack
status "Deploying dashboard stack..."
aws cloudformation deploy \
    --template-file $TEMPLATE_FILE \
    --stack-name $STACK_NAME \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $REGION \
    --parameter-overrides \
        StackNamePrefix=$STACK_PREFIX \
        DynamoDBTableName=$DYNAMODB_TABLE \
        FavoritesTableName=$FAVORITES_TABLE_NAME \
        FavoritesApiLambdaArn=$FAVORITES_API_ARN \
        AIStackName=$AI_STACK_NAME \
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
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
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

LAMBDA_FUNCTION=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`LambdaFunctionName`].OutputValue' \
    --output text 2>/dev/null)

# Validate outputs
[ -n "$API_ENDPOINT" ] || error "Failed to get API endpoint from stack outputs"
[ -n "$WEBSITE_URL" ] || error "Failed to get website URL from stack outputs"
[ -n "$S3_BUCKET" ] || error "Failed to get S3 bucket name from stack outputs"

# Update index.html with API endpoint
status "Updating dashboard HTML with API endpoint..."
# Create a backup first
cp index.html index.html.bak

# Replace the API_URL in the JavaScript
sed -i.tmp "s|const API_URL = '[^']*';|const API_URL = '${API_ENDPOINT}';|g" index.html
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
status "🎉 Dashboard deployment completed successfully!"
echo ""
echo "📋 Dashboard Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  DynamoDB Table: $DYNAMODB_TABLE"
echo "  Lambda Function: $LAMBDA_FUNCTION"
echo "  S3 Bucket: $S3_BUCKET"
echo ""
echo "🌐 Access your dashboard at:"
echo "  $WEBSITE_URL"
echo ""
echo "🔧 API Endpoint:"
echo "  $API_ENDPOINT/properties"
echo ""
echo "💡 Next Steps:"
echo "  1. Open the dashboard URL in your browser"
echo "  2. The dashboard will automatically load property data from DynamoDB"
echo "  3. Use the terminal-style interface to filter and sort properties"
echo "  4. Properties are loaded with GET /properties?limit=1000"
echo ""
echo "🔧 Troubleshooting:"
echo "  - If no data appears, check that the '$DYNAMODB_TABLE' table has property records"
echo "  - Check CloudWatch logs for the Lambda function: /aws/lambda/$LAMBDA_FUNCTION"
echo "  - Test API directly: curl '${API_ENDPOINT}/properties?limit=5'"
echo "  - Ensure your properties have the expected fields (district, price, recommendation, etc.)"
echo ""
echo "🗑️  To delete the stack:"
echo "  aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
echo ""