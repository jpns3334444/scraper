#!/bin/bash
# Build ONLY python-deps layer with Python 3.12
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

# Pre-flight checks
print_status "Building python-deps layer with Python 3.12..."

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or running"
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    print_error "Docker daemon is not running"
    exit 1
fi

# Clean and create directory
print_status "Setting up python-deps directory..."
rm -rf lambda-layers/python-deps
mkdir -p lambda-layers/python-deps

# Build python-deps layer
print_status "Installing: pandas, numpy, boto3, pytz"

if ! docker run --rm -v "$(pwd)/lambda-layers/python-deps:/output" \
    --entrypoint /bin/bash \
    public.ecr.aws/lambda/python:3.12 \
    -c "pip install pandas numpy boto3 pytz -t /output/python/ --no-cache-dir"; then
    print_error "Failed to build python-deps layer"
    exit 1
fi

print_status "✅ python-deps layer built successfully"

# Verify layer was created properly
layer_path="lambda-layers/python-deps/python"
if [ ! -d "$layer_path" ]; then
    print_error "Layer directory $layer_path not created"
    exit 1
fi

# Check if layer has content
if [ -z "$(ls -A "$layer_path")" ]; then
    print_error "Layer directory $layer_path is empty"
    exit 1
fi

print_status "✅ python-deps layer structure verified"

# Show layer size
size=$(du -sh "lambda-layers/python-deps" | cut -f1)
print_status "python-deps layer size: $size"

print_status "🎉 python-deps layer built successfully!"
print_status "Next step: Run ./test-python-deps.sh to verify imports work"