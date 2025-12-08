#!/bin/bash
# US Real Estate Frontend API Stack deployment script
set -e

# Get the directory of this script (repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

# Colors and functions first
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; cleanup_and_exit 1; }
warn() { echo -e "${Y}WARNING:${NC} $1"; }
info() { echo -e "${B}INFO:${NC} $1"; }

# Load centralized config
. "$REPO_ROOT/scripts/cfg.sh"

# Configuration from centralized config
REGION="$AWS_REGION"
STACK_NAME="$FRONTEND_STACK"
AI_STACK_NAME="$AI_STACK"
BUCKET_NAME="$DEPLOYMENT_BUCKET"
BCRYPT_LAYER_VERSION_FILE="$REPO_ROOT/.frontend-bcrypt-layer-version"
TEMPLATE_FILE="$REPO_ROOT/frontend-stack.yaml"
CURRENT_BCRYPT_VERSION="${BCRYPT_VERSION:-4.1.2}"
NEED_BCRYPT_LAYER_BUILD=false


# Cleanup function
cleanup_and_exit() {
    local exit_code=${1:-0}

    info "Cleaning up temporary files..."

    # Remove temporary Docker files if they exist
    [ -f "$REPO_ROOT/Dockerfile.bcrypt" ] && rm -f "$REPO_ROOT/Dockerfile.bcrypt" && info "Removed Dockerfile.bcrypt"

    # Remove temporary zip files
    [ -f "$REPO_ROOT/frontend-bcrypt-layer.zip" ] && rm -f "$REPO_ROOT/frontend-bcrypt-layer.zip" && info "Removed frontend-bcrypt-layer.zip"
    [ -f "$REPO_ROOT/dashboard_api.zip" ] && rm -f "$REPO_ROOT/dashboard_api.zip" && info "Removed dashboard_api.zip"
    [ -f "$REPO_ROOT/favorites_api.zip" ] && rm -f "$REPO_ROOT/favorites_api.zip" && info "Removed favorites_api.zip"
    [ -f "$REPO_ROOT/register_user.zip" ] && rm -f "$REPO_ROOT/register_user.zip" && info "Removed register_user.zip"
    [ -f "$REPO_ROOT/login_user.zip" ] && rm -f "$REPO_ROOT/login_user.zip" && info "Removed login_user.zip"

    # Note: We keep the .frontend-bcrypt-layer-version file as it's used for caching
    # Only remove it if explicitly requested or on error during bcrypt build
    if [ "$exit_code" -ne 0 ] && [ "$NEED_BCRYPT_LAYER_BUILD" = true ]; then
        warn "Build failed during bcrypt layer creation, removing version file for retry"
        [ -f "$BCRYPT_LAYER_VERSION_FILE" ] && rm -f "$BCRYPT_LAYER_VERSION_FILE"
    fi

    status "✅ Cleanup completed"
    exit $exit_code
}

# Set up trap to ensure cleanup on exit
trap cleanup_and_exit EXIT

echo "🚀 Frontend API Stack Deployment"
echo "================================="

# Change to repo root
cd "$REPO_ROOT"
echo "DEBUG: REPO_ROOT=$REPO_ROOT"

# Check prerequisites
command -v docker >/dev/null || { echo "Docker not found"; cleanup_and_exit 1; }
command -v aws >/dev/null || { echo "AWS CLI not found"; cleanup_and_exit 1; }
aws sts get-caller-identity >/dev/null || { echo "AWS credentials not configured"; cleanup_and_exit 1; }
[ -f "$TEMPLATE_FILE" ] || { echo "CloudFormation template $TEMPLATE_FILE not found"; cleanup_and_exit 1; }

# Debug Python availability
info "Checking Python availability..."
for py_cmd in python3 python py python.exe; do
    if command -v $py_cmd >/dev/null 2>&1; then
        if $py_cmd -c "import sys; print('✓ ' + sys.executable + ' - Python ' + sys.version)" 2>/dev/null; then
            info "Found working Python: $py_cmd"
        else
            warn "Found $py_cmd but it doesn't work properly"
        fi
    fi
done

status "Prerequisites OK"

# Create S3 bucket if needed
info "Checking S3 bucket..."
aws s3 mb s3://$BUCKET_NAME --region $REGION 2>/dev/null && status "Created bucket $BUCKET_NAME" || info "Bucket $BUCKET_NAME exists"

# Check if we need to build the Bcrypt layer (already initialized above)

if [ ! -f "$BCRYPT_LAYER_VERSION_FILE" ]; then
    info "No bcrypt layer version file found - will build layer"
    NEED_BCRYPT_LAYER_BUILD=true
else
    STORED_BCRYPT_VERSION=$(cat $BCRYPT_LAYER_VERSION_FILE)
    if [ "$STORED_BCRYPT_VERSION" != "$CURRENT_BCRYPT_VERSION" ]; then
        info "Bcrypt version changed ($STORED_BCRYPT_VERSION → $CURRENT_BCRYPT_VERSION) - will rebuild layer"
        NEED_BCRYPT_LAYER_BUILD=true
    else
        # Check if layer exists in S3
        if ! aws s3 ls s3://$BUCKET_NAME/layers/frontend-bcrypt-layer.zip --region $REGION >/dev/null 2>&1; then
            info "Bcrypt layer missing from S3 - will rebuild layer"
            NEED_BCRYPT_LAYER_BUILD=true
        else
            status "✅ Bcrypt layer up to date (v$CURRENT_BCRYPT_VERSION) - skipping build"
        fi
    fi
fi

# Get Bcrypt layer version
if [ "$NEED_BCRYPT_LAYER_BUILD" = false ]; then
    info "Retrieving existing Bcrypt layer version ID..."
    BCRYPT_LAYER_OBJECT_VERSION=$(aws s3api head-object \
        --bucket $BUCKET_NAME \
        --key layers/frontend-bcrypt-layer.zip \
        --region $REGION \
        --query VersionId --output text)
    info "Bcrypt layer version ID: $BCRYPT_LAYER_OBJECT_VERSION"
fi

# Build Bcrypt layer if needed (Windows-compatible approach)
if [ "$NEED_BCRYPT_LAYER_BUILD" = true ]; then
    status "Building Bcrypt layer (Windows-compatible method)..."
    
    # Create temporary Dockerfile for Windows compatibility
    cat > Dockerfile.bcrypt << EOF
FROM python:3.12-slim
RUN pip install bcrypt==$CURRENT_BCRYPT_VERSION --target /layer/python/
WORKDIR /layer
RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*
RUN zip -r frontend-bcrypt-layer.zip python/
EOF
    
    # Build image and extract layer
    docker build -t frontend-bcrypt-layer-builder -f Dockerfile.bcrypt .
    
    # Create container and copy file out
    CONTAINER_ID=$(docker create frontend-bcrypt-layer-builder)
    docker cp "$CONTAINER_ID:/layer/frontend-bcrypt-layer.zip" ./frontend-bcrypt-layer.zip
    docker rm "$CONTAINER_ID"
    
    # Cleanup Docker artifacts immediately
    rm -f Dockerfile.bcrypt
    docker rmi frontend-bcrypt-layer-builder
    
    [ -f frontend-bcrypt-layer.zip ] || { echo "Bcrypt layer build failed"; cleanup_and_exit 1; }
    
    BCRYPT_LAYER_SIZE=$(du -sh frontend-bcrypt-layer.zip | cut -f1)
    status "✅ Bcrypt layer built ($BCRYPT_LAYER_SIZE)"
    
    # Upload to S3
    aws s3 cp frontend-bcrypt-layer.zip s3://$BUCKET_NAME/layers/frontend-bcrypt-layer.zip --region $REGION
    status "✅ Bcrypt layer uploaded to S3"
    
    # Get the version ID we just wrote
    BCRYPT_LAYER_OBJECT_VERSION=$(aws s3api head-object \
        --bucket $BUCKET_NAME \
        --key layers/frontend-bcrypt-layer.zip \
        --region $REGION \
        --query VersionId --output text)
    
    # Save version
    echo "$CURRENT_BCRYPT_VERSION" > $BCRYPT_LAYER_VERSION_FILE
    
    # Cleanup zip file immediately after upload
    rm -f frontend-bcrypt-layer.zip
else
    info "Skipping bcrypt layer build - using cached version"
fi

# Always package Lambda functions (these change frequently) - Windows compatible ZIP
status "Packaging Lambda functions..."

# Initialize version variables
DASHBOARD_API_VERSION="latest"
FAVORITES_API_VERSION="latest"
REGISTER_USER_VERSION="latest"
LOGIN_USER_VERSION="latest"

for func in dashboard_api favorites_api register_user login_user; do
    [ -d "lambda/$func" ] || { echo "Function directory lambda/$func not found"; cleanup_and_exit 1; }
    
    info "Packaging $func..."
    
    # Windows-compatible ZIP creation using Python - try multiple Python commands
    PYTHON_CMD=""
    for py_cmd in python3 python py python.exe; do
        if command -v $py_cmd >/dev/null 2>&1; then
            # Test if it actually works (not just the Windows Store redirect)
            if $py_cmd -c "import sys; print('Python works')" >/dev/null 2>&1; then
                PYTHON_CMD="$py_cmd"
                info "Using Python command: $py_cmd"
                break
            fi
        fi
    done
    
    # Use Python method with shared modules
    [ -n "$PYTHON_CMD" ] || { echo "Python not found - required for packaging"; cleanup_and_exit 1; }
    
    $PYTHON_CMD -c "
import zipfile
import os
import sys

def create_zip(func_name, output_zip):
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add function-specific files
        func_dir = f'lambda/{func_name}'
        if os.path.exists(func_dir):
            for root, dirs, files in os.walk(func_dir):
                # Skip __pycache__ directories
                dirs[:] = [d for d in dirs if d != '__pycache__']
                
                for file in files:
                    # Skip .pyc files
                    if file.endswith('.pyc'):
                        continue
                        
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, func_dir)
                    zipf.write(file_path, arc_name)
        
        # Add common module if exists
        common_dir = 'lambda/common'
        if os.path.exists(common_dir):
            for root, dirs, files in os.walk(common_dir):
                # Skip __pycache__ directories
                dirs[:] = [d for d in dirs if d != '__pycache__']
                
                for file in files:
                    # Skip .pyc files
                    if file.endswith('.pyc'):
                        continue
                        
                    file_path = os.path.join(root, file)
                    # Preserve directory structure in zip
                    arc_name = os.path.relpath(file_path, 'lambda')
                    zipf.write(file_path, arc_name)

create_zip('$func', '$func.zip')
print('Created $func.zip with shared modules')
"
    
    [ -f "$func.zip" ] || { echo "Failed to create $func.zip"; cleanup_and_exit 1; }
    
    # Upload to S3 and capture version
    aws s3 cp $func.zip s3://$BUCKET_NAME/frontend-functions/$func.zip --region $REGION
    
    # Get the S3 object version
    OBJECT_VERSION=$(aws s3api head-object --bucket $BUCKET_NAME --key frontend-functions/$func.zip --region $REGION --query 'VersionId' --output text)
    
    # Store version in appropriate variable
    case $func in
        dashboard_api)
            DASHBOARD_API_VERSION="$OBJECT_VERSION"
            ;;
        favorites_api)
            FAVORITES_API_VERSION="$OBJECT_VERSION"
            ;;
        register_user)
            REGISTER_USER_VERSION="$OBJECT_VERSION"
            ;;
        login_user)
            LOGIN_USER_VERSION="$OBJECT_VERSION"
            ;;
    esac
    
    # Clean up zip file immediately after upload
    rm -f $func.zip
    
    status "✅ $func packaged and uploaded (version: $OBJECT_VERSION)"
done

# Check if stack is in ROLLBACK_COMPLETE state and delete if needed
STACK_STATUS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DOES_NOT_EXIST")

if [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ]; then
    warn "Stack is in ROLLBACK_COMPLETE state - deleting and recreating..."
    aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION
    
    info "Waiting for stack deletion to complete..."
    aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION
    status "✅ Stack deleted successfully"
fi

# Always get the layer version ID (whether we built it or not)
if [ -z "$BCRYPT_LAYER_OBJECT_VERSION" ]; then
    info "Retrieving existing Bcrypt layer version ID..."
    BCRYPT_LAYER_OBJECT_VERSION=$(aws s3api head-object \
        --bucket $BUCKET_NAME \
        --key layers/frontend-bcrypt-layer.zip \
        --region $REGION \
        --query VersionId --output text)
    info "Bcrypt layer version ID: $BCRYPT_LAYER_OBJECT_VERSION"
fi

# Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file frontend-stack.yaml \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $REGION \
  --parameter-overrides \
      AIStackName=$AI_STACK_NAME \
      DeploymentBucket=$BUCKET_NAME \
      DashboardAPICodeVersion=$DASHBOARD_API_VERSION \
      FavoritesAPICodeVersion=$FAVORITES_API_VERSION \
      RegisterUserCodeVersion=$REGISTER_USER_VERSION \
      LoginUserCodeVersion=$LOGIN_USER_VERSION \
      BcryptLayerObjectVersion=$BCRYPT_LAYER_OBJECT_VERSION

status "✅ CloudFormation stack deployed"

# Get stack outputs
info "Retrieving stack information..."
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

DASHBOARD_API_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

FAVORITES_API_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FavoritesAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

# Success summary
echo ""
status "🎉 Frontend API Stack deployed successfully!"
echo ""
echo "📋 Stack Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  Bucket: $BUCKET_NAME"
echo "  Bcrypt Layer: v$CURRENT_BCRYPT_VERSION"
echo ""
echo "🔧 Stack Resources:"
echo "  Dashboard API Function: $DASHBOARD_API_FUNCTION_ARN"
echo "  Favorites API Function: $FAVORITES_API_FUNCTION_ARN"
echo ""
echo "🔧 API Endpoint (use this in Vercel):"
echo "  NEXT_PUBLIC_API_URL=$API_ENDPOINT"
echo ""
echo "🧪 Test Commands:"
echo "  # Test Dashboard API function"
echo "  aws lambda invoke --function-name $STACK_NAME-dashboard-api --payload '{}' dashboard-api-response.json --region $REGION"
echo ""
echo "  # Test Favorites API function"
echo "  aws lambda invoke --function-name $STACK_NAME-favorites-api --payload '{\"userId\":\"test\"}' favorites-api-response.json --region $REGION"
echo ""
echo "💡 Next Deployments:"
echo "  - Layer will be cached (fast deployments)"
echo "  - Only Lambda functions will be rebuilt"
echo "  - To force layer rebuild: rm $BCRYPT_LAYER_VERSION_FILE"

# The trap will automatically call cleanup_and_exit when script ends successfully