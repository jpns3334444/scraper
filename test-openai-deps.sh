#!/bin/bash
# Test ONLY openai-deps layer with Python 3.12
set -e

# Color output for better UX
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

print_status "Testing openai-deps layer..."

# Verify layer exists
if [ ! -d "lambda-layers/openai-deps/python" ]; then
    print_error "Layer lambda-layers/openai-deps/python not found"
    print_status "Run ./build-openai-deps.sh first to create the layer"
    exit 1
fi

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

print_status "🎉 openai-deps layer test passed successfully!"