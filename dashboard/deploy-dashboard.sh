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
[ -f "../ai_infra/lambda/dashboard_api/app.py" ] || error "Dashboard API code not found"

status "Prerequisites OK"

# Check if AI stack exists
info "Checking AI stack..."
if ! aws cloudformation describe-stacks --stack-name $AI_STACK_NAME --region $REGION >/dev/null 2>&1; then
    error "AI stack '$AI_STACK_NAME' not found. Please deploy the AI stack first."
fi
status "✅ AI stack exists"

# Package Dashboard API Lambda function
status "Packaging Dashboard API function..."

# Create Lambda directory if needed
mkdir -p ../ai_infra/lambda/dashboard_api

# Find working Python command
PYTHON_CMD=""
for py_cmd in python3 python py python.exe; do
    if command -v $py_cmd >/dev/null 2>&1; then
        if $py_cmd -c "import sys; print('Python works')" >/dev/null 2>&1; then
            PYTHON_CMD="$py_cmd"
            info "Using Python command: $py_cmd"
            break
        fi
    fi
done

if [ -n "$PYTHON_CMD" ]; then
    # Use Python method
    $PYTHON_CMD -c "
import zipfile
import os
import sys

def create_zip(source_dir, output_zip):
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                # Skip .pyc files
                if file.endswith('.pyc'):
                    continue
                    
                file_path = os.path.join(root, file)
                arc_name = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arc_name)

create_zip('../ai_infra/lambda/dashboard_api', 'dashboard_api.zip')
print('Created dashboard_api.zip')
"
else
    # Fallback to zip command
    warn "Python not found, using zip command"
    (cd ../ai_infra/lambda/dashboard_api && zip -r ../../../dashboard/dashboard_api.zip .)
fi

[ -f "dashboard_api.zip" ] || error "Failed to create dashboard_api.zip"

# Upload to S3
aws s3 cp dashboard_api.zip s3://$BUCKET_NAME/functions/dashboard_api.zip --region $REGION
DASHBOARD_API_VERSION=$(aws s3api head-object --bucket $BUCKET_NAME --key functions/dashboard_api.zip --region $REGION --query 'VersionId' --output text)

rm dashboard_api.zip
status "✅ Dashboard API packaged and uploaded (version: $DASHBOARD_API_VERSION)"

# Deploy CloudFormation stack
status "Deploying dashboard stack..."
aws cloudformation deploy \
  --template-file $TEMPLATE_FILE \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_IAM \
  --region $REGION \
  --parameter-overrides \
      AIStackName=$AI_STACK_NAME \
      DeploymentBucket=$BUCKET_NAME \
      DashboardAPICodeVersion=$DASHBOARD_API_VERSION

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
sed -i.bak "s|https://YOUR_API_GATEWAY_URL/properties|${API_ENDPOINT}/properties|g" index.html
rm index.html.bak

# Upload dashboard HTML to S3
status "Uploading dashboard to S3..."
aws s3 cp index.html s3://$BUCKET_NAME_OUTPUT/index.html --region $REGION --content-type text/html

# Success summary
echo ""
status "🎉 Dashboard deployment completed successfully!"
echo ""
echo "📋 Dashboard Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  API Endpoint: $API_ENDPOINT"
echo "  Website URL: $WEBSITE_URL"
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