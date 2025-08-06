#!/bin/bash
# CORS Verification Script

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
success() { echo -e "${G}✅ $1${NC}"; }
error() { echo -e "${R}❌ $1${NC}"; }
info() { echo -e "${B}INFO:${NC} $1"; }

# Configuration
STACK_NAME="${STACK_NAME:-tokyo-real-estate-frontend}"
REGION="${AWS_REGION:-ap-northeast-1}"

# Get API endpoint
API=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`FrontendApiEndpoint`].OutputValue' \
    --output text 2>/dev/null)

if [ -z "$API" ]; then
    error "Could not get API endpoint from stack $STACK_NAME"
    exit 1
fi

# Test origin
ORIGIN="http://tre-frontend-static-901472985889.s3-website-ap-northeast-1.amazonaws.com"

echo "🔍 CORS Verification Test"
echo "========================"
echo "API: $API"
echo "Origin: $ORIGIN"
echo ""

# Test function
test_cors() {
    local path="$1"
    echo -n "Testing OPTIONS $path ... "
    
    response=$(curl -s -I -H "Origin: $ORIGIN" -X OPTIONS "$API/$path?limit=1" 2>&1)
    
    origin_header=$(echo "$response" | grep -i "access-control-allow-origin:" | tr -d '\r')
    credentials_header=$(echo "$response" | grep -i "access-control-allow-credentials:" | tr -d '\r')
    
    if [[ "$origin_header" == *"$ORIGIN"* ]] && [[ "$credentials_header" == *"true"* ]]; then
        success "PASS"
        echo "    $origin_header"
        echo "    $credentials_header"
    else
        error "FAIL"
        echo "    Expected Origin: $ORIGIN"
        echo "    Expected Credentials: true"
        echo "    Actual response headers:"
        echo "$response" | grep -i "access-control-" | sed 's/^/    /'
    fi
    echo ""
}

# Test all endpoints
endpoints=("properties" "hidden" "favorites" "users" "auth")

for endpoint in "${endpoints[@]}"; do
    test_cors "$endpoint"
done

echo "Summary: Test completed. If all tests passed, CORS should work in the browser."