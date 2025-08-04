#!/bin/bash
# Windows-compatible deployment script that only builds layer when needed
set -e

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-tokyo-real-estate-ai}"
BUCKET_NAME="ai-scraper-artifacts-$REGION"
LAYER_VERSION_FILE="$SCRIPT_DIR/.layer-version"
TEMPLATE_FILE="$SCRIPT_DIR/ai-stack.yaml"
CURRENT_OPENAI_VERSION="1.95.0"  # Update this when you want to rebuild layer

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
warn() { echo -e "${Y}WARNING:${NC} $1"; }
info() { echo -e "${B}INFO:${NC} $1"; }

echo "🚀 AI Stack Smart Deployment (Windows Compatible)"
echo "================================================="

# Change to the script's directory to resolve relative paths
cd "$SCRIPT_DIR"

# Check prerequisites
command -v docker >/dev/null || error "Docker not found"
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"
[ -f "$TEMPLATE_FILE" ] || error "CloudFormation template $TEMPLATE_FILE not found"

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

# Check if we need to build the OpenAI layer
NEED_LAYER_BUILD=false

if [ ! -f "$LAYER_VERSION_FILE" ]; then
    info "No layer version file found - will build layer"
    NEED_LAYER_BUILD=true
else
    STORED_VERSION=$(cat $LAYER_VERSION_FILE)
    if [ "$STORED_VERSION" != "$CURRENT_OPENAI_VERSION" ]; then
        info "OpenAI version changed ($STORED_VERSION → $CURRENT_OPENAI_VERSION) - will rebuild layer"
        NEED_LAYER_BUILD=true
    else
        # Check if layer exists in S3
        if ! aws s3 ls s3://$BUCKET_NAME/layers/openai-layer.zip --region $REGION >/dev/null 2>&1; then
            info "Layer missing from S3 - will rebuild layer"
            NEED_LAYER_BUILD=true
        else
            status "✅ OpenAI layer up to date (v$CURRENT_OPENAI_VERSION) - skipping build"
        fi
    fi
fi

# Build OpenAI layer if needed (Windows-compatible approach)
if [ "$NEED_LAYER_BUILD" = true ]; then
    status "Building OpenAI layer (Windows-compatible method)..."
    
    # Create temporary Dockerfile for Windows compatibility
    cat > Dockerfile.temp << EOF
FROM python:3.12-slim
RUN pip install openai==$CURRENT_OPENAI_VERSION jinja2 --target /layer/python/
WORKDIR /layer
RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*
RUN zip -r openai-layer.zip python/
EOF
    
    # Build image and extract layer
    docker build -t openai-layer-builder -f Dockerfile.temp .
    
    # Create container and copy file out
    CONTAINER_ID=$(docker create openai-layer-builder)
    docker cp "$CONTAINER_ID:/layer/openai-layer.zip" ./openai-layer.zip
    docker rm "$CONTAINER_ID"
    
    # Cleanup
    rm Dockerfile.temp
    docker rmi openai-layer-builder
    
    [ -f openai-layer.zip ] || error "OpenAI layer build failed"
    
    LAYER_SIZE=$(du -sh openai-layer.zip | cut -f1)
    status "✅ OpenAI layer built ($LAYER_SIZE)"
    
    # Upload to S3 (fixed S3 key to match CloudFormation)
    aws s3 cp openai-layer.zip s3://$BUCKET_NAME/layers/openai-layer.zip --region $REGION
    status "✅ Layer uploaded to S3"
    
    # ── grab the version ID we just wrote ─────────────────────────────
    LAYER_OBJECT_VERSION=$(aws s3api head-object \
    --bucket $BUCKET_NAME \
    --key layers/openai-layer.zip \
    --region $REGION \
    --query VersionId --output text)
    # Save version
    echo "$CURRENT_OPENAI_VERSION" > $LAYER_VERSION_FILE
    
    # Cleanup
    rm openai-layer.zip
else
    info "Skipping layer build - using cached version"
fi

# Always package Lambda functions (these change frequently) - Windows compatible ZIP
status "Packaging Lambda functions..."

# Initialize version variables
URL_COLLECTOR_VERSION="latest"
PROPERTY_PROCESSOR_VERSION="latest"
PROPERTY_ANALYZER_VERSION="latest"
DASHBOARD_API_VERSION="latest"
FAVORITES_API_VERSION="latest"
FAVORITE_ANALYZER_VERSION="latest"

for func in url_collector property_processor property_analyzer dashboard_api favorites_api favorite_analyzer; do
    [ -d "lambda/$func" ] || error "Function directory lambda/$func not found"
    
    info "Packaging $func..."
    
    # Handle scraper-specific dependencies
    if [ "$func" = "url_collector" ] || [ "$func" = "property_processor" ] || [ "$func" = "property_analyzer" ]; then
        info "Installing scraper dependencies..."
        
        # Create temporary directory for dependencies
        DEPS_DIR="lambda/$func/deps"
        mkdir -p "$DEPS_DIR"
        
        # Install required packages with progress output
        info "Installing: requests, beautifulsoup4, Pillow..."
        if ! timeout 300 pip install requests beautifulsoup4 Pillow --target "$DEPS_DIR" --no-cache-dir; then
            error "Failed to install scraper dependencies (timeout or error)"
        fi
        
        info "✅ Scraper dependencies installed to $DEPS_DIR"
    fi
    
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
    
    # Use Python method with shared modules (Linux only)
    [ -n "$PYTHON_CMD" ] || error "Python not found - required for packaging"
    
    $PYTHON_CMD -c "
import zipfile
import os
import sys
import shutil

def create_zip(func_name, output_zip):
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add function-specific files
        func_dir = f'lambda/{func_name}'
        if os.path.exists(func_dir):
            for root, dirs, files in os.walk(func_dir):
                # Skip __pycache__ directories and handle deps specially
                dirs[:] = [d for d in dirs if d != '__pycache__']
                
                for file in files:
                    # Skip .pyc files
                    if file.endswith('.pyc'):
                        continue
                        
                    file_path = os.path.join(root, file)
                    
                    # Handle deps directory specially for scraper functions
                    if func_name in ['url_collector', 'property_processor', 'property_analyzer'] and '/deps/' in file_path:
                        # Put deps contents at root level for imports
                        arc_name = os.path.relpath(file_path, os.path.join(func_dir, 'deps'))
                    else:
                        arc_name = os.path.relpath(file_path, func_dir)
                    
                    zipf.write(file_path, arc_name)
        
        # Add shared modules (util, analysis, schemas, etc.)
        shared_dirs = ['lambda/util', 'analysis', 'schemas', 'notifications', 'snapshots']
        for shared_dir in shared_dirs:
            if os.path.exists(shared_dir):
                for root, dirs, files in os.walk(shared_dir):
                    # Skip __pycache__ directories
                    dirs[:] = [d for d in dirs if d != '__pycache__']
                    
                    for file in files:
                        # Skip .pyc files
                        if file.endswith('.pyc'):
                            continue
                            
                        file_path = os.path.join(root, file)
                        # Preserve directory structure in zip
                        if shared_dir.startswith('lambda/'):
                            arc_name = os.path.relpath(file_path, 'lambda')
                        else:
                            arc_name = file_path
                        zipf.write(file_path, arc_name)

create_zip('$func', '$func.zip')
print('Created $func.zip with shared modules')
"
    
    [ -f "$func.zip" ] || error "Failed to create $func.zip"
    
    # Upload to S3 and capture version
    aws s3 cp $func.zip s3://$BUCKET_NAME/functions/$func.zip --region $REGION
    
    # Get the S3 object version
    OBJECT_VERSION=$(aws s3api head-object --bucket $BUCKET_NAME --key functions/$func.zip --region $REGION --query 'VersionId' --output text)
    
    # Store version in appropriate variable
    case $func in
        url_collector)
            URL_COLLECTOR_VERSION="$OBJECT_VERSION"
            ;;
        property_processor)
            PROPERTY_PROCESSOR_VERSION="$OBJECT_VERSION"
            ;;
        property_analyzer)
            PROPERTY_ANALYZER_VERSION="$OBJECT_VERSION"
            ;;
        dashboard_api)
            DASHBOARD_API_VERSION="$OBJECT_VERSION"
            ;;
        favorites_api)
            FAVORITES_API_VERSION="$OBJECT_VERSION"
            ;;
        favorite_analyzer)
            FAVORITE_ANALYZER_VERSION="$OBJECT_VERSION"
            ;;
    esac
    
    rm $func.zip
    
    # Clean up scraper dependencies
    if [ "$func" = "url_collector" ] || [ "$func" = "property_processor" ] || [ "$func" = "property_analyzer" ]; then
        rm -rf "lambda/$func/deps"
        info "Cleaned up $func dependencies"
    fi
    
    status "✅ $func packaged and uploaded (version: $OBJECT_VERSION)"
done

# Handle OpenAI secret
info "Checking OpenAI API secret..."
if ! aws secretsmanager describe-secret --secret-id "ai-scraper/openai-api-key" --region $REGION >/dev/null 2>&1; then
    warn "Creating OpenAI secret with placeholder value"
    aws secretsmanager create-secret \
        --name "ai-scraper/openai-api-key" \
        --secret-string "REPLACE_WITH_REAL_KEY" \
        --region $REGION >/dev/null
    echo ""
    warn "⚠️  Update the secret with your real API key:"
    echo "   aws secretsmanager update-secret --secret-id ai-scraper/openai-api-key --secret-string 'sk-your-real-key' --region $REGION"
    echo ""
else
    status "✅ OpenAI secret exists"
fi

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
if [ -z "$LAYER_OBJECT_VERSION" ]; then
    info "Retrieving existing layer version ID..."
    LAYER_OBJECT_VERSION=$(aws s3api head-object \
        --bucket $BUCKET_NAME \
        --key layers/openai-layer.zip \
        --region $REGION \
        --query VersionId --output text)
    info "Layer version ID: $LAYER_OBJECT_VERSION"
fi

# Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file ai-stack.yaml \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_IAM \
  --region $REGION \
  --parameter-overrides \
      DeploymentBucket=$BUCKET_NAME \
      OutputBucket=tokyo-real-estate-ai-data \
      EmailFrom=jpns3334444@gmail.com \
      EmailTo=jpns3334444@gmail.com \
      URLCollectorCodeVersion=$URL_COLLECTOR_VERSION \
      PropertyProcessorCodeVersion=$PROPERTY_PROCESSOR_VERSION \
      PropertyAnalyzerCodeVersion=$PROPERTY_ANALYZER_VERSION \
      DashboardAPICodeVersion=$DASHBOARD_API_VERSION \
      FavoritesAPICodeVersion=$FAVORITES_API_VERSION \
      FavoriteAnalyzerCodeVersion=$FAVORITE_ANALYZER_VERSION \
      OpenAILayerObjectVersion=$LAYER_OBJECT_VERSION

status "✅ CloudFormation stack deployed"

# Get stack outputs
info "Retrieving stack information..."
DASHBOARD_API_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

URL_COLLECTOR_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`URLCollectorFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

PROPERTY_PROCESSOR_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`PropertyProcessorFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

PROPERTY_ANALYZER_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`PropertyAnalyzerFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

FAVORITES_API_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FavoritesAPIFunctionArn`].OutputValue' \
    --output text 2>/dev/null)

# Success summary
echo ""
status "🎉 Deployment completed successfully!"
echo ""
echo "📋 Stack Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  Bucket: $BUCKET_NAME"
echo "  OpenAI Layer: v$CURRENT_OPENAI_VERSION"
echo ""
echo "🔧 Stack Resources:"
echo "  URL Collector Function: $URL_COLLECTOR_FUNCTION_ARN"
echo "  Property Processor Function: $PROPERTY_PROCESSOR_FUNCTION_ARN"
echo "  Property Analyzer Function: $PROPERTY_ANALYZER_FUNCTION_ARN"
echo "  Dashboard API Function: $DASHBOARD_API_FUNCTION_ARN"
echo "  Favorites API Function: $FAVORITES_API_FUNCTION_ARN"
echo ""
echo "🧪 Test Commands:"
echo "  # Test Dashboard API function"
echo "  aws lambda invoke --function-name $STACK_NAME-dashboard-api --payload '{}' dashboard-api-response.json --region $REGION"
echo ""
echo "  # Test URL Collector function"
echo "  aws lambda invoke --function-name $STACK_NAME-url-collector --payload '{\"areas\":\"chofu-city\"}' url-collector-response.json --region $REGION"
echo ""
echo "  # Test Property Processor function"  
echo "  aws lambda invoke --function-name $STACK_NAME-property-processor --payload '{\"max_properties\":5}' property-processor-response.json --region $REGION"
echo ""
echo "  # Test Property Analyzer function"
echo "  aws lambda invoke --function-name $STACK_NAME-property-analyzer --payload '{\"days_back\":7}' property-analyzer-response.json --region $REGION"
echo ""
echo "  # Test Favorites API function"
echo "  aws lambda invoke --function-name $STACK_NAME-favorites-api --payload '{\"userId\":\"test\"}' favorites-api-response.json --region $REGION"
echo ""
echo "  # Run scraper with trigger script"
echo "  cd $SCRIPT_DIR && ./trigger-lambda.sh --function property-processor --max-properties 5 --sync"
echo ""
echo "  # Run property analyzer with trigger script"
echo "  cd $SCRIPT_DIR && ./trigger-lambda.sh --function property-analyzer --sync"
echo ""
echo "💡 Next Deployments:"
echo "  - Layer will be cached (fast deployments)"
echo "  - Only Lambda functions will be rebuilt"
echo "  - To force layer rebuild: rm $LAYER_VERSION_FILE"