#!/bin/bash
# Lightweight script to quickly update the scraper lambda function code
set -e

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-tokyo-real-estate-ai}"
BUCKET_NAME="ai-scraper-artifacts-$REGION"
FUNCTION_NAME="$STACK_NAME-scraper"

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
info() { echo -e "${B}INFO:${NC} $1"; }

echo "⚡ Quick Scraper Lambda Update"
echo "============================="

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check prerequisites
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"
[ -d "lambda/scraper" ] || error "Scraper lambda directory not found"

# Install scraper dependencies
info "Installing scraper dependencies..."
DEPS_DIR="lambda/scraper/deps"
mkdir -p "$DEPS_DIR"

if ! timeout 300 pip install requests beautifulsoup4 Pillow --target "$DEPS_DIR" --no-cache-dir; then
    error "Failed to install scraper dependencies"
fi

# Package the function (Windows-compatible)
status "Packaging scraper function..."

# Find working Python command
PYTHON_CMD=""
for py_cmd in python3 python py python.exe; do
    if command -v $py_cmd >/dev/null 2>&1; then
        if $py_cmd -c "import sys" >/dev/null 2>&1; then
            PYTHON_CMD="$py_cmd"
            break
        fi
    fi
done

if [ -n "$PYTHON_CMD" ]; then
    # Use Python to create zip
    $PYTHON_CMD -c "
import zipfile
import os

def create_zip():
    with zipfile.ZipFile('scraper.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add scraper function files
        func_dir = 'lambda/scraper'
        for root, dirs, files in os.walk(func_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for file in files:
                if file.endswith('.pyc'):
                    continue
                file_path = os.path.join(root, file)
                # Handle deps directory specially
                if '/deps/' in file_path:
                    arc_name = os.path.relpath(file_path, os.path.join(func_dir, 'deps'))
                else:
                    arc_name = os.path.relpath(file_path, func_dir)
                zipf.write(file_path, arc_name)
        
        # Add shared modules
        shared_dirs = ['lambda/util', 'analysis', 'schemas', 'notifications', 'snapshots']
        for shared_dir in shared_dirs:
            if os.path.exists(shared_dir):
                for root, dirs, files in os.walk(shared_dir):
                    dirs[:] = [d for d in dirs if d != '__pycache__']
                    for file in files:
                        if file.endswith('.pyc'):
                            continue
                        file_path = os.path.join(root, file)
                        if shared_dir.startswith('lambda/'):
                            arc_name = os.path.relpath(file_path, 'lambda')
                        else:
                            arc_name = file_path
                        zipf.write(file_path, arc_name)

create_zip()
print('Scraper function packaged')
"
else
    error "Python not found - cannot package function"
fi

[ -f "scraper.zip" ] || error "Failed to create scraper.zip"

# Update Lambda function directly
status "Updating Lambda function code..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://scraper.zip \
    --region "$REGION" > /dev/null

# Cleanup
rm scraper.zip
rm -rf "lambda/scraper/deps"

status "✅ Scraper lambda updated successfully!"

# Show test command
echo ""
echo "🧪 Test the updated function:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"max_properties\":5}' test-response.json --region $REGION"
echo ""
echo "  # Or use the trigger script:"
echo "  ./trigger_lambda_scraper.sh --max-properties 5 --sync"