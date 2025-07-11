#!/bin/bash
# Enhanced Lambda layer rebuild for Python 3.12 with error checking
# Replaces Python 3.8 compiled packages with Python 3.12 compatible versions
set -e

# Color output for better UX
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}WARNING:${NC} $1"
}

# Pre-flight checks
print_status "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or running"
    print_status "Please install Docker and try again"
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    print_error "Docker daemon is not running"
    print_status "Please start Docker and try again"
    exit 1
fi

print_status "Docker is available and running"

# Verify we're in the right directory
if [ ! -d "lambda-layers" ]; then
    print_error "lambda-layers directory not found"
    print_status "Please run this script from the project root directory"
    exit 1
fi

# Clean old layers
print_status "Cleaning existing layers..."
chmod -R 777 lambda-layers/*/python 2>/dev/null || true
rm -rf lambda-layers/python-deps/python || true
rm -rf lambda-layers/openai-deps/python || true

# Create directories if they don't exist
mkdir -p lambda-layers/python-deps
mkdir -p lambda-layers/openai-deps

print_status "Starting Lambda layer rebuild with Python 3.12..."

# Build python-deps layer (pandas, numpy, boto3, pytz - latest versions)
print_status "Building python-deps layer with Python 3.12..."
print_status "Installing: pandas, numpy, boto3, pytz (latest versions)"

if ! docker run --rm -v "$(pwd)/lambda-layers/python-deps:/output" \
    --entrypoint /bin/bash \
    public.ecr.aws/lambda/python:3.12 \
    -c "pip install pandas numpy boto3 pytz -t /output/python/ --no-cache-dir --upgrade --force-reinstall"; then
    print_error "Failed to build python-deps layer"
    exit 1
fi

print_status "✅ python-deps layer built successfully"

# Build openai-deps layer (OpenAI + dependencies - latest versions)  
print_status "Building openai-deps layer with Python 3.12..."
print_status "Installing: openai, requests, python-json-logger (latest versions)"

if ! docker run --rm -v "$(pwd)/lambda-layers/openai-deps:/output" \
    --entrypoint /bin/bash \
    public.ecr.aws/lambda/python:3.12 \
    -c "pip install openai requests python-json-logger -t /output/python/ --no-cache-dir --upgrade --force-reinstall"; then
    print_error "Failed to build openai-deps layer"
    exit 1
fi

print_status "✅ openai-deps layer built successfully"

# Verify layers were created properly
print_status "Verifying layer structure..."

for layer in python-deps openai-deps; do
    layer_path="lambda-layers/$layer/python"
    if [ ! -d "$layer_path" ]; then
        print_error "Layer directory $layer_path not created"
        exit 1
    fi
    
    # Check if layer has content
    if [ -z "$(ls -A "$layer_path")" ]; then
        print_error "Layer directory $layer_path is empty"
        exit 1
    fi
    
    print_status "✅ $layer layer structure verified"
done

# Check for old Python compiled files (should be gone now)
print_status "Checking for old Python compiled files..."
old_files=$(find lambda-layers/ -name "*.cpython-38-*" -o -name "*.cpython-39-*" 2>/dev/null || true)
if [ -n "$old_files" ]; then
    print_warning "Found old Python compiled files (these should be gone):"
    echo "$old_files"
else
    print_status "✅ No old Python compiled files found"
fi

# Show layer sizes
print_status "Layer size summary:"
for layer in python-deps openai-deps; do
    size=$(du -sh "lambda-layers/$layer" | cut -f1)
    print_status "  $layer: $size"
done

print_status "🎉 All layers built successfully with Python 3.12!"
print_status "Next step: Run ./test-layers.sh to verify imports work"