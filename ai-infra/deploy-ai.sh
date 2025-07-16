#!/bin/bash
# Windows-compatible deployment script that only builds layer when needed
set -e

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-ai-scraper-dev}"
BUCKET_NAME="ai-scraper-artifacts-$REGION"
LAYER_VERSION_FILE=".layer-version"
CURRENT_OPENAI_VERSION="1.95.0"  # Update this when you want to rebuild layer

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
warn() { echo -e "${Y}WARNING:${NC} $1"; }
info() { echo -e "${B}INFO:${NC} $1"; }

echo "🚀 AI Stack Smart Deployment (Windows Compatible)"
echo "================================================="

# Check prerequisites
command -v docker >/dev/null || error "Docker not found"
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"
[ -f "ai-stack.yaml" ] || error "CloudFormation template ai-stack.yaml not found"

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
RUN pip install openai==$CURRENT_OPENAI_VERSION --target /layer/python/
WORKDIR /layer
RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*
RUN zip -r openai-layer.zip python/
EOF
    
    # Build image and extract layer - Windows compatible volume mount
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
ETL_VERSION="latest"
PROMPT_BUILDER_VERSION="latest"
LLM_BATCH_VERSION="latest"
REPORT_SENDER_VERSION="latest"

for func in etl prompt_builder llm_batch report_sender; do
    [ -d "lambda/$func" ] || error "Function directory lambda/$func not found"
    
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

create_zip('lambda/$func', '$func.zip')
print('Created $func.zip')
"
    else
        # Fallback to PowerShell
        warn "Python not found, using PowerShell as fallback"
        powershell.exe -Command "
            \$source = 'lambda/$func'
            \$destination = './$func.zip'
            
            if (Test-Path \$destination) { Remove-Item \$destination -Force }
            
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            
            # Create temporary directory for filtered files
            \$tempDir = New-TemporaryFile | %{ rm \$_; mkdir \$_ }
            
            # Copy files excluding .pyc and __pycache__
            Get-ChildItem -Path \$source -Recurse | Where-Object {
                \$_.Extension -ne '.pyc' -and 
                \$_.FullName -notlike '*__pycache__*' -and
                -not \$_.PSIsContainer
            } | ForEach-Object {
                \$relativePath = \$_.FullName.Substring(\$source.Length + 1)
                \$destPath = Join-Path \$tempDir \$relativePath
                \$destDir = Split-Path \$destPath
                if (-not (Test-Path \$destDir)) { New-Item -ItemType Directory -Path \$destDir -Force | Out-Null }
                Copy-Item \$_.FullName \$destPath
            }
            
            # Create zip file
            [System.IO.Compression.ZipFile]::CreateFromDirectory(\$tempDir, \$destination)
            
            # Cleanup
            Remove-Item \$tempDir -Recurse -Force
            
            Write-Host 'Created $func.zip using PowerShell'
        "
    fi
    
    [ -f "$func.zip" ] || error "Failed to create $func.zip"
    
    # Upload to S3 and capture version
    aws s3 cp $func.zip s3://$BUCKET_NAME/functions/$func.zip --region $REGION
    
    # Get the S3 object version
    OBJECT_VERSION=$(aws s3api head-object --bucket $BUCKET_NAME --key functions/$func.zip --region $REGION --query 'VersionId' --output text)
    
    # Store version in appropriate variable
    case $func in
        etl)
            ETL_VERSION="$OBJECT_VERSION"
            ;;
        prompt_builder)
            PROMPT_BUILDER_VERSION="$OBJECT_VERSION"
            ;;
        llm_batch)
            LLM_BATCH_VERSION="$OBJECT_VERSION"
            ;;
        report_sender)
            REPORT_SENDER_VERSION="$OBJECT_VERSION"
            ;;
    esac
    
    rm $func.zip
    
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
      ETLCodeVersion=$ETL_VERSION \
      PromptBuilderCodeVersion=$PROMPT_BUILDER_VERSION \
      LLMBatchCodeVersion=$LLM_BATCH_VERSION \
      ReportSenderCodeVersion=$REPORT_SENDER_VERSION \
      OpenAILayerObjectVersion=$LAYER_OBJECT_VERSION

status "✅ CloudFormation stack deployed"

# Get stack outputs
info "Retrieving stack information..."
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
    --output text 2>/dev/null)

ETL_FUNCTION_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ETLFunctionArn`].OutputValue' \
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
echo "  State Machine: $STATE_MACHINE_ARN"
echo "  ETL Function: $ETL_FUNCTION_ARN"
echo ""
echo "🧪 Test Commands:"
echo "  # Test ETL function"
echo "  aws lambda invoke --function-name $STACK_NAME-etl --payload '{\"date\":\"$(date +%Y-%m-%d)\"}' test-response.json --region $REGION"
echo ""
echo "  # Run full AI workflow"
echo "  aws stepfunctions start-execution --state-machine-arn $STATE_MACHINE_ARN --input '{\"date\":\"$(date +%Y-%m-%d)\"}' --region $REGION"
echo ""
echo "💡 Next Deployments:"
echo "  - Layer will be cached (fast deployments)"
echo "  - Only Lambda functions will be rebuilt"
echo "  - To force layer rebuild: rm $LAYER_VERSION_FILE"