#!/bin/bash
# Unified deployment script for US Real Estate AI Stack
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
warn() { echo -e "${Y}WARNING:${NC} $1"; }
info() { echo -e "${B}INFO:${NC} $1"; }

# Load config
. "$REPO_ROOT/scripts/cfg.sh"

REGION="$AWS_REGION"
STACK_NAME="$AI_STACK"
BUCKET_NAME="$DEPLOYMENT_BUCKET"
OUTPUT_BUCKET="$OUTPUT_BUCKET"
LAYER_VERSION_FILE="$REPO_ROOT/lambda/.layer-version"
TEMPLATE_FILE="$REPO_ROOT/stack.yaml"
CURRENT_OPENAI_VERSION="${OPENAI_VERSION:-$(python3 -c "import json; print(json.load(open('config.json'))['layers']['OPENAI_VERSION'])" 2>/dev/null || echo "1.99.3")}"

echo "🚀 US Real Estate AI - Unified Deployment"
echo "=========================================="

cd "$REPO_ROOT"

# Prerequisites
command -v docker >/dev/null || error "Docker not found"
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"
[ -f "$TEMPLATE_FILE" ] || error "CloudFormation template $TEMPLATE_FILE not found"

status "Prerequisites OK"

# S3 bucket setup
info "Checking S3 bucket..."
aws s3 mb s3://$BUCKET_NAME --region $REGION 2>/dev/null && status "Created bucket $BUCKET_NAME" || info "Bucket exists"
aws s3api put-bucket-versioning --bucket $BUCKET_NAME --region $REGION --versioning-configuration Status=Enabled 2>/dev/null || true

# Build OpenAI layer if needed
NEED_LAYER_BUILD=false
if [ ! -f "$LAYER_VERSION_FILE" ]; then
    NEED_LAYER_BUILD=true
elif [ "$(cat $LAYER_VERSION_FILE)" != "$CURRENT_OPENAI_VERSION" ]; then
    NEED_LAYER_BUILD=true
elif ! aws s3 ls s3://$BUCKET_NAME/layers/openai-layer.zip --region $REGION >/dev/null 2>&1; then
    NEED_LAYER_BUILD=true
fi

if [ "$NEED_LAYER_BUILD" = true ]; then
    status "Building OpenAI layer..."
    cat > Dockerfile.temp << EOF
FROM python:3.12-slim
RUN pip install openai==$CURRENT_OPENAI_VERSION jinja2 --target /layer/python/
WORKDIR /layer
RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*
RUN zip -r openai-layer.zip python/
EOF
    docker build -t openai-layer-builder -f Dockerfile.temp .
    CONTAINER_ID=$(docker create openai-layer-builder)
    docker cp "$CONTAINER_ID:/layer/openai-layer.zip" ./openai-layer.zip
    docker rm "$CONTAINER_ID"
    rm Dockerfile.temp
    docker rmi openai-layer-builder 2>/dev/null || true

    aws s3 cp openai-layer.zip s3://$BUCKET_NAME/layers/openai-layer.zip --region $REGION
    echo "$CURRENT_OPENAI_VERSION" > $LAYER_VERSION_FILE
    rm openai-layer.zip
    status "✅ OpenAI layer built and uploaded"
else
    status "✅ OpenAI layer up to date (v$CURRENT_OPENAI_VERSION)"
fi

LAYER_OBJECT_VERSION=$(aws s3api head-object --bucket $BUCKET_NAME --key layers/openai-layer.zip --region $REGION --query VersionId --output text)

# Find Python
PYTHON_CMD=""
for py_cmd in python3 python py; do
    if command -v $py_cmd >/dev/null 2>&1 && $py_cmd -c "import sys" >/dev/null 2>&1; then
        PYTHON_CMD="$py_cmd"
        break
    fi
done
[ -n "$PYTHON_CMD" ] || error "Python not found"

# Package Lambda functions
status "Packaging Lambda functions..."

# Worker functions
declare -A WORKER_VERSIONS
for func in url_collector property_processor property_analyzer favorite_analyzer; do
    [ -d "lambda/workers/$func" ] || error "Worker lambda/workers/$func not found"
    info "Packaging worker: $func..."

    # Install dependencies for scraper functions
    if [ "$func" == "url_collector" ] || [ "$func" == "property_processor" ]; then
        DEPS_DIR="lambda/workers/$func/deps"
        rm -rf "$DEPS_DIR"
        mkdir -p "$DEPS_DIR"
        info "Building $func dependencies in Docker (for Lambda compatibility)..."
        docker run --rm --user "$(id -u):$(id -g)" -v "$(pwd)/$DEPS_DIR:/deps" python:3.12-slim bash -c \
            "pip install curl_cffi beautifulsoup4 lxml Pillow -t /deps --no-cache-dir --quiet" || \
            error "Failed to build $func dependencies"
    elif [ "$func" != "favorite_analyzer" ]; then
        DEPS_DIR="lambda/workers/$func/deps"
        mkdir -p "$DEPS_DIR"
        pip install requests beautifulsoup4 Pillow --target "$DEPS_DIR" --no-cache-dir --quiet
    fi

    $PYTHON_CMD -c "
import zipfile, os
func_name, output_zip = '$func', '$func.zip'
with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
    func_dir = f'lambda/workers/{func_name}'
    for root, dirs, files in os.walk(func_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for file in files:
            if file.endswith('.pyc'): continue
            file_path = os.path.join(root, file)
            if '/deps/' in file_path:
                arc_name = os.path.relpath(file_path, os.path.join(func_dir, 'deps'))
            else:
                arc_name = os.path.relpath(file_path, func_dir)
            zipf.write(file_path, arc_name)
print(f'Created {output_zip}')
"
    aws s3 cp $func.zip s3://$BUCKET_NAME/functions/$func.zip --region $REGION
    WORKER_VERSIONS[$func]=$(aws s3api head-object --bucket $BUCKET_NAME --key functions/$func.zip --region $REGION --query VersionId --output text)
    rm $func.zip
    [ -d "lambda/workers/$func/deps" ] && rm -rf "lambda/workers/$func/deps"
    status "✅ $func packaged (${WORKER_VERSIONS[$func]})"
done

# API functions
declare -A API_VERSIONS
for func in dashboard favorites; do
    [ -d "lambda/api/$func" ] || error "API lambda/api/$func not found"
    info "Packaging API: $func..."

    $PYTHON_CMD -c "
import zipfile, os
func_name, output_zip = '$func', '$func.zip'
with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
    func_dir = f'lambda/api/{func_name}'
    for root, dirs, files in os.walk(func_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for file in files:
            if file.endswith('.pyc'): continue
            file_path = os.path.join(root, file)
            arc_name = os.path.relpath(file_path, func_dir)
            zipf.write(file_path, arc_name)
print(f'Created {output_zip}')
"
    aws s3 cp $func.zip s3://$BUCKET_NAME/functions/$func.zip --region $REGION
    API_VERSIONS[$func]=$(aws s3api head-object --bucket $BUCKET_NAME --key functions/$func.zip --region $REGION --query VersionId --output text)
    rm $func.zip
    status "✅ $func packaged (${API_VERSIONS[$func]})"
done

# Check for rollback state
STACK_STATUS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DOES_NOT_EXIST")
if [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ]; then
    warn "Stack in ROLLBACK_COMPLETE - deleting..."
    aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION
    aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION
    status "✅ Old stack deleted"
fi

# Deploy CloudFormation
status "Deploying CloudFormation stack..."
aws cloudformation deploy \
  --template-file stack.yaml \
  --stack-name $STACK_NAME \
  --capabilities CAPABILITY_IAM \
  --region $REGION \
  --parameter-overrides \
      DeploymentBucket=$BUCKET_NAME \
      OutputBucket=$OUTPUT_BUCKET \
      URLCollectorCodeVersion=${WORKER_VERSIONS[url_collector]} \
      PropertyProcessorCodeVersion=${WORKER_VERSIONS[property_processor]} \
      PropertyAnalyzerCodeVersion=${WORKER_VERSIONS[property_analyzer]} \
      FavoriteAnalyzerCodeVersion=${WORKER_VERSIONS[favorite_analyzer]} \
      DashboardAPICodeVersion=${API_VERSIONS[dashboard]} \
      FavoritesAPICodeVersion=${API_VERSIONS[favorites]} \
      OpenAILayerObjectVersion=$LAYER_OBJECT_VERSION

status "✅ CloudFormation stack deployed"

# Get outputs
API_ENDPOINT=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' --output text)

echo ""
status "🎉 Deployment completed successfully!"
echo ""
echo "📋 Stack Details:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo ""
echo "🔧 API Endpoint (use this in Vercel):"
echo "  NEXT_PUBLIC_API_URL=$API_ENDPOINT"
echo ""
echo "🧪 Test Commands:"
echo "  # Test URL Collector"
echo "  aws lambda invoke --function-name $STACK_NAME-url-collector --payload '{}' /tmp/response.json --region $REGION && cat /tmp/response.json"
echo ""
echo "  # Test Property Processor"
echo "  aws lambda invoke --function-name $STACK_NAME-property-processor --payload '{\"max_properties\":5}' /tmp/response.json --region $REGION && cat /tmp/response.json"
echo ""
echo "  # Test Dashboard API"
echo "  curl -s '$API_ENDPOINT/properties' | head -c 500"
echo ""
