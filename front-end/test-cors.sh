#!/bin/bash
# CORS Smoke Test Script

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
info() { echo -e "${B}INFO:${NC} $1"; }
success() { echo -e "${G}✅ $1${NC}"; }
error() { echo -e "${R}❌ $1${NC}"; }

# Get API endpoint from stack outputs
STACK_NAME="${STACK_NAME:-tokyo-real-estate-frontend}"
REGION="${AWS_REGION:-ap-northeast-1}"

API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FrontendApiEndpoint`].OutputValue' \
    --output text 2>/dev/null)

if [ -z "$API_ENDPOINT" ]; then
    error "Could not get API endpoint from stack. Is the stack deployed?"
    exit 1
fi

# S3 website URL for origin testing
S3_ORIGIN="http://tre-frontend-static-901472985889.s3-website-ap-northeast-1.amazonaws.com"

echo "🔍 CORS Smoke Test"
echo "=================="
echo "API Endpoint: $API_ENDPOINT"
echo "Test Origin: $S3_ORIGIN"
echo ""

# Function to test endpoint
test_endpoint() {
    local path="$1"
    local method="${2:-OPTIONS}"
    
    echo -n "Testing $method $path ... "
    
    # Run curl and capture headers
    response=$(curl -s -i -X $method \
        -H "Origin: $S3_ORIGIN" \
        "$API_ENDPOINT/$path" 2>&1)
    
    # Extract status code
    status_code=$(echo "$response" | grep -E "^HTTP" | tail -1 | awk '{print $2}')
    
    # Check for CORS headers
    has_origin=$(echo "$response" | grep -i "access-control-allow-origin: $S3_ORIGIN" | wc -l)
    has_credentials=$(echo "$response" | grep -i "access-control-allow-credentials: true" | wc -l)
    has_methods=$(echo "$response" | grep -i "access-control-allow-methods:" | wc -l)
    has_headers=$(echo "$response" | grep -i "access-control-allow-headers:" | wc -l)
    
    if [ "$status_code" = "200" ] && [ "$has_origin" -gt 0 ] && [ "$has_credentials" -gt 0 ] && [ "$has_methods" -gt 0 ] && [ "$has_headers" -gt 0 ]; then
        success "200 OK with all CORS headers"
        return 0
    else
        error "Failed (Status: $status_code, Origin: $has_origin, Creds: $has_credentials, Methods: $has_methods, Headers: $has_headers)"
        
        # Show actual headers for debugging
        echo "  Response headers:"
        echo "$response" | grep -i "access-control-" | sed 's/^/    /'
        return 1
    fi
}

# Test all endpoints
echo "Testing OPTIONS requests:"
echo "------------------------"

endpoints=("properties" "favorites" "favorites/user/test" "favorites/123" "hidden" "hidden/user/test" "hidden/123" "auth/register" "auth/login")
failed=0

for endpoint in "${endpoints[@]}"; do
    if ! test_endpoint "$endpoint" "OPTIONS"; then
        ((failed++))
    fi
done

echo ""
echo "Testing GET requests:"
echo "--------------------"

# Test actual GET requests
if ! test_endpoint "properties?limit=1" "GET"; then
    ((failed++))
fi

echo ""
echo "Testing error paths (404):"
echo "-------------------------"

# Test non-existent path to check gateway responses
if curl -s -i -X GET -H "Origin: $S3_ORIGIN" "$API_ENDPOINT/nonexistent" | grep -i "access-control-allow-origin: $S3_ORIGIN" >/dev/null; then
    success "404 returns CORS headers"
else
    error "404 missing CORS headers"
    ((failed++))
fi

echo ""
echo "Summary:"
echo "--------"
if [ $failed -eq 0 ]; then
    success "All CORS tests passed!"
    exit 0
else
    error "$failed test(s) failed"
    exit 1
fi