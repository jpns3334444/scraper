#!/bin/bash
# Test Lambda layers work with Python 3.12
# Verifies all packages can be imported and shows versions
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
print_status "Starting Lambda layer verification..."

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or running"
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    print_error "Docker daemon is not running"
    exit 1
fi

# Verify layers exist
for layer in python-deps openai-deps; do
    if [ ! -d "lambda-layers/$layer/python" ]; then
        print_error "Layer lambda-layers/$layer/python not found"
        print_status "Run ./build-layers.sh first to create the layers"
        exit 1
    fi
done

# Test python-deps layer
print_status "Testing python-deps layer..."
print_status "Verifying imports: pandas, numpy, boto3, pytz"

if ! docker run --rm \
    -v "$(pwd)/lambda-layers/python-deps:/opt" \
    -v "$(pwd)/test-python-deps.py:/test.py" \
    --entrypoint /bin/bash \
    public.ecr.aws/lambda/python:3.12 \
    -c "python3 /test.py"; then
    print_error "python-deps layer test failed"
    exit 1
fi

# Test openai-deps layer
print_status "Testing openai-deps layer..."
print_status "Verifying imports: openai, requests, python-json-logger"

if ! docker run --rm \
    -v "$(pwd)/lambda-layers/openai-deps:/opt" \
    -v "$(pwd)/test-openai-deps.py:/test.py" \
    --entrypoint /bin/bash \
    public.ecr.aws/lambda/python:3.12 \
    -c "python3 /test.py"; then
    print_error "openai-deps layer test failed"
    exit 1
fi

# Test combined layer usage (simulate Lambda function environment)
print_status "Testing combined layer usage..."
print_status "Simulating Lambda function environment with both layers"

if ! docker run --rm \
    -v "$(pwd)/lambda-layers/python-deps:/opt/python-deps" \
    -v "$(pwd)/lambda-layers/openai-deps:/opt/openai-deps" \
    -v "$(pwd)/test-combined.py:/test.py" \
    --entrypoint /bin/bash \
    public.ecr.aws/lambda/python:3.12 \
    -c "python3 /test.py"; then
    print_error "Combined layer test failed"
    exit 1
fi

# Check for Python version compatibility
print_status "Verifying Python 3.12 compatibility..."
python_version=$(docker run --rm --entrypoint /bin/bash public.ecr.aws/lambda/python:3.12 -c "python3 --version")
print_status "Runtime Python version: $python_version"

# Summary
print_status "All layer tests passed successfully!"
print_status "[OK] python-deps layer: pandas, numpy, boto3, pytz"
print_status "[OK] openai-deps layer: openai, requests, python-json-logger"
print_status "[OK] Combined layer compatibility verified"
print_status "[OK] Python 3.12 compatibility confirmed"
print_status ""
print_status "Layers are ready for deployment!"
print_status "Next step: Run ./deploy-enhanced.sh to deploy with CloudFormation"