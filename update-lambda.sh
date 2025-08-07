#!/bin/bash
# Dynamic Lambda function updater - works with any lambda in the project
set -e

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"
STACK_NAME="${STACK_NAME:-tokyo-real-estate-ai}"

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
status() { echo -e "${G}[$(date +'%H:%M:%S')]${NC} $1"; }
error() { echo -e "${R}ERROR:${NC} $1"; exit 1; }
info() { echo -e "${B}INFO:${NC} $1"; }
warning() { echo -e "${Y}WARNING:${NC} $1"; }

# Usage function
usage() {
    cat << EOF
Usage: $0 [OPTIONS] <lambda_folder>

Update AWS Lambda function code dynamically for any lambda in the project.

Arguments:
    lambda_folder    Name of the lambda folder (e.g., scraper, url_collector, property_processor)

Options:
    -h, --help       Show this help message
    -r, --region     AWS region (default: $REGION)
    -s, --stack      Stack name (default: $STACK_NAME)
    --skip-deps      Skip dependency installation
    --dry-run        Show what would be done without actually doing it

Examples:
    $0 scraper                    # Update scraper lambda
    $0 url_collector              # Update url_collector lambda
    $0 property_processor         # Update property_processor lambda
    $0 property_analyzer          # Update property_analyzer lambda
    $0 -r us-west-2 analyzer      # Update analyzer lambda in us-west-2

EOF
    exit 0
}

# Parse arguments
LAMBDA_FOLDER=""
SKIP_DEPS=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -s|--stack)
            STACK_NAME="$2"
            shift 2
            ;;
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -*)
            error "Unknown option: $1"
            ;;
        *)
            LAMBDA_FOLDER="$1"
            shift
            ;;
    esac
done

# Validate lambda folder argument
[ -z "$LAMBDA_FOLDER" ] && error "Lambda folder name required. Use -h for help."

# Header
echo "⚡ Dynamic Lambda Function Updater"
echo "=================================="
echo "Lambda: $LAMBDA_FOLDER"
echo "Region: $REGION"
echo "Stack:  $STACK_NAME"
echo ""

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check prerequisites
command -v aws >/dev/null || error "AWS CLI not found"
aws sts get-caller-identity >/dev/null || error "AWS credentials not configured"

# Check if lambda directory exists
LAMBDA_DIR="lambda/$LAMBDA_FOLDER"
[ -d "$LAMBDA_DIR" ] || error "Lambda directory not found: $LAMBDA_DIR"

# Determine function name pattern based on lambda type
# Frontend functions have different naming pattern
if [[ "$LAMBDA_FOLDER" == "register_user" || "$LAMBDA_FOLDER" == "login_user" || "$LAMBDA_FOLDER" == "dashboard_api" || "$LAMBDA_FOLDER" == "favorites_api" ]]; then
    # Frontend stack pattern: tokyo-real-estate-frontend-function-name
    FUNCTION_NAME="tokyo-real-estate-frontend-${LAMBDA_FOLDER//_/-}"
    STACK_NAME="tokyo-real-estate-dashboard"  # Override stack name for frontend functions
else
    # Main AI stack pattern: stack-name-lambda-folder
    FUNCTION_NAME="$STACK_NAME-${LAMBDA_FOLDER//_/-}"
fi

# Try to find the actual function name from AWS
info "Looking for Lambda function..."
ACTUAL_FUNCTION_NAME=$(aws lambda list-functions --region "$REGION" --query "Functions[?starts_with(FunctionName, '$FUNCTION_NAME')].FunctionName" --output text 2>/dev/null | head -n1)

if [ -z "$ACTUAL_FUNCTION_NAME" ]; then
    # Try alternative patterns
    if [[ "$LAMBDA_FOLDER" == "register_user" || "$LAMBDA_FOLDER" == "login_user" ]]; then
        # Try with different frontend prefixes
        for prefix in "tre-frontend" "tokyo-real-estate-dashboard"; do
            FUNCTION_NAME="$prefix-${LAMBDA_FOLDER//_/-}"
            ACTUAL_FUNCTION_NAME=$(aws lambda list-functions --region "$REGION" --query "Functions[?starts_with(FunctionName, '$FUNCTION_NAME')].FunctionName" --output text 2>/dev/null | head -n1)
            [ -n "$ACTUAL_FUNCTION_NAME" ] && break
        done
    else
        # Try main stack alternative pattern
        FUNCTION_NAME="$STACK_NAME-${LAMBDA_FOLDER//_/-}-function"
        ACTUAL_FUNCTION_NAME=$(aws lambda list-functions --region "$REGION" --query "Functions[?starts_with(FunctionName, '$FUNCTION_NAME')].FunctionName" --output text 2>/dev/null | head -n1)
    fi
fi

if [ -z "$ACTUAL_FUNCTION_NAME" ]; then
    error "Could not find Lambda function matching pattern: $FUNCTION_NAME*"
fi

FUNCTION_NAME="$ACTUAL_FUNCTION_NAME"
info "Found Lambda function: $FUNCTION_NAME"

# Handle dependencies
if [ "$SKIP_DEPS" = false ]; then
    # Check for requirements.txt
    REQUIREMENTS_FILE="$LAMBDA_DIR/requirements.txt"
    if [ -f "$REQUIREMENTS_FILE" ]; then
        info "Found requirements.txt, installing dependencies..."
        
        DEPS_DIR="$LAMBDA_DIR/deps"
        mkdir -p "$DEPS_DIR"
        
        # Read requirements and install
        if [ "$DRY_RUN" = true ]; then
            echo "Would install:"
            cat "$REQUIREMENTS_FILE"
        else
            # Install each requirement
            while IFS= read -r requirement || [ -n "$requirement" ]; do
                # Skip empty lines and comments
                [[ -z "$requirement" || "$requirement" =~ ^[[:space:]]*# ]] && continue
                
                info "Installing: $requirement"
                if ! timeout 300 pip install "$requirement" --target "$DEPS_DIR" --no-cache-dir; then
                    warning "Failed to install $requirement, continuing..."
                fi
            done < "$REQUIREMENTS_FILE"
        fi
    else
        info "No requirements.txt found, skipping dependency installation"
    fi
else
    info "Skipping dependency installation (--skip-deps flag)"
fi

# Find Python command
find_python() {
    for py_cmd in python3 python py python.exe; do
        if command -v $py_cmd >/dev/null 2>&1; then
            if $py_cmd -c "import sys" >/dev/null 2>&1; then
                echo "$py_cmd"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_CMD=$(find_python) || error "Python not found"
info "Using Python: $PYTHON_CMD"

# Package the function
status "Packaging $LAMBDA_FOLDER function..."

ZIP_FILE="${LAMBDA_FOLDER}.zip"

if [ "$DRY_RUN" = true ]; then
    info "Would create $ZIP_FILE with:"
    echo "  - Lambda function files from $LAMBDA_DIR"
    echo "  - Shared modules: util, analysis, schemas, notifications, snapshots"
    [ -d "$LAMBDA_DIR/deps" ] && echo "  - Dependencies from $LAMBDA_DIR/deps"
else
    # Use Python to create zip
    $PYTHON_CMD -c "
import zipfile
import os
import sys

lambda_folder = '$LAMBDA_FOLDER'
lambda_dir = f'lambda/{lambda_folder}'
zip_file = f'{lambda_folder}.zip'

def create_zip():
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        files_added = 0
        
        # Add lambda function files
        for root, dirs, files in os.walk(lambda_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for file in files:
                if file.endswith('.pyc') or file == 'requirements.txt':
                    continue
                file_path = os.path.join(root, file)
                # Handle deps directory specially
                if '/deps/' in file_path.replace(os.sep, '/'):
                    arc_name = os.path.relpath(file_path, os.path.join(lambda_dir, 'deps'))
                else:
                    arc_name = os.path.relpath(file_path, lambda_dir)
                zipf.write(file_path, arc_name)
                files_added += 1
        
        # Add shared modules (if they exist)
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
                        files_added += 1
        
        print(f'Packaged {files_added} files into {zip_file}')

try:
    create_zip()
except Exception as e:
    print(f'Error creating zip: {e}', file=sys.stderr)
    sys.exit(1)
"
    [ $? -eq 0 ] || error "Failed to create zip file"
fi

[ -f "$ZIP_FILE" ] || error "Failed to create $ZIP_FILE"

# Get zip file size
ZIP_SIZE=$(du -h "$ZIP_FILE" 2>/dev/null | cut -f1) || ZIP_SIZE="unknown"
info "Package size: $ZIP_SIZE"

# Update Lambda function
if [ "$DRY_RUN" = true ]; then
    info "Would update Lambda function: $FUNCTION_NAME"
else
    status "Updating Lambda function code..."
    if aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" > /dev/null; then
        status "✅ Lambda function updated successfully!"
    else
        error "Failed to update Lambda function"
    fi
fi

# Cleanup
if [ "$DRY_RUN" = false ]; then
    rm -f "$ZIP_FILE"
    [ -d "$LAMBDA_DIR/deps" ] && rm -rf "$LAMBDA_DIR/deps"
fi

# Show test commands
echo ""
echo "🧪 Test the updated function:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' test-response.json --region $REGION"

# Show specific test commands based on lambda type
case "$LAMBDA_FOLDER" in
    scraper)
        echo ""
        echo "  # Scraper-specific test:"
        echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"max_properties\":5}' test-response.json --region $REGION"
        echo "  # Or use: ./trigger_lambda_scraper.sh --max-properties 5 --sync"
        ;;
    url_collector)
        echo ""
        echo "  # URL Collector test:"
        echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"areas\":\"chofu-city\"}' test-response.json --region $REGION"
        ;;
    property_processor)
        echo ""
        echo "  # Property Processor test:"
        echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"max_runtime_minutes\":5}' test-response.json --region $REGION"
        ;;
    property_analyzer)
        echo ""
        echo "  # Property Analyzer test:"
        echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"days_back\":7}' test-response.json --region $REGION"
        echo "  # Or use: ./trigger-lambda.sh --function property-analyzer --sync"
        ;;
esac

echo ""