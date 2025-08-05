#!/bin/bash
# Auth CORS Diagnostic Script for Tokyo Real Estate Dashboard
set -e

# Colors for output
R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m' B='\033[0;34m' NC='\033[0m'
error() { echo -e "${R}✗ $1${NC}"; }
success() { echo -e "${G}✓ $1${NC}"; }
warn() { echo -e "${Y}⚠ $1${NC}"; }
info() { echo -e "${B}ℹ $1${NC}"; }

echo "🔍 Auth CORS Diagnostic Tool"
echo "==========================="
echo ""

# Get API endpoint from stack
STACK_NAME="${STACK_NAME:-tokyo-real-estate-dashboard}"
REGION="${AWS_REGION:-ap-northeast-1}"

info "Getting API endpoint from stack: $STACK_NAME"
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text 2>/dev/null)

if [ -z "$API_ENDPOINT" ]; then
    error "Failed to get API endpoint from CloudFormation stack"
    exit 1
fi

success "API Endpoint: $API_ENDPOINT"
echo ""

# Test endpoints
REGISTER_URL="${API_ENDPOINT}/auth/register"
LOGIN_URL="${API_ENDPOINT}/auth/login"

echo "📋 Testing Auth Endpoints"
echo "========================"
echo "Register: $REGISTER_URL"
echo "Login:    $LOGIN_URL"
echo ""

# Test OPTIONS request (preflight)
echo "🔧 Testing CORS Preflight (OPTIONS)"
echo "===================================="

test_options() {
    local url=$1
    local endpoint_name=$2
    
    echo ""
    echo "Testing $endpoint_name OPTIONS:"
    echo "--------------------------------"
    
    response=$(curl -s -X OPTIONS "$url" \
        -H "Origin: http://localhost:3000" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: content-type" \
        -i)
    
    # Check if we got a response
    if [ -z "$response" ]; then
        error "No response from $endpoint_name OPTIONS request"
        return 1
    fi
    
    # Extract status code
    status_line=$(echo "$response" | head -n1)
    echo "Status: $status_line"
    
    # Check for CORS headers
    echo ""
    echo "CORS Headers:"
    echo "$response" | grep -i "access-control" || warn "No CORS headers found!"
    
    # Check specific headers
    if echo "$response" | grep -qi "access-control-allow-origin"; then
        success "Access-Control-Allow-Origin present"
    else
        error "Access-Control-Allow-Origin missing"
    fi
    
    if echo "$response" | grep -qi "access-control-allow-methods"; then
        success "Access-Control-Allow-Methods present"
    else
        error "Access-Control-Allow-Methods missing"
    fi
    
    if echo "$response" | grep -qi "access-control-allow-headers"; then
        success "Access-Control-Allow-Headers present"
    else
        error "Access-Control-Allow-Headers missing"
    fi
}

test_options "$REGISTER_URL" "Register"
test_options "$LOGIN_URL" "Login"

# Test actual POST requests
echo ""
echo ""
echo "🔧 Testing Actual POST Requests"
echo "==============================="

test_post() {
    local url=$1
    local endpoint_name=$2
    local payload=$3
    
    echo ""
    echo "Testing $endpoint_name POST:"
    echo "----------------------------"
    
    response=$(curl -s -X POST "$url" \
        -H "Content-Type: application/json" \
        -H "Origin: http://localhost:3000" \
        -d "$payload" \
        -i)
    
    # Extract status code
    status_line=$(echo "$response" | head -n1)
    echo "Status: $status_line"
    
    # Check for CORS headers
    echo ""
    echo "CORS Headers in Response:"
    echo "$response" | grep -i "access-control" || warn "No CORS headers in response!"
    
    # Show response body
    echo ""
    echo "Response Body:"
    echo "$response" | tail -n1 | jq . 2>/dev/null || echo "$response" | tail -n1
}

# Test with invalid payloads to trigger validation errors
echo ""
info "Testing with empty payload (should trigger validation error):"
test_post "$REGISTER_URL" "Register" '{}'
test_post "$LOGIN_URL" "Login" '{}'

echo ""
info "Testing with partial payload (should trigger validation error):"
test_post "$REGISTER_URL" "Register" '{"email":"test@example.com"}'
test_post "$LOGIN_URL" "Login" '{"email":"test@example.com"}'

# Test Lambda functions directly
echo ""
echo ""
echo "🔧 Testing Lambda Functions Directly"
echo "===================================="

test_lambda() {
    local function_name=$1
    local payload=$2
    
    echo ""
    echo "Testing $function_name:"
    echo "------------------------"
    
    # Create payload file
    echo "$payload" > /tmp/test-payload.json
    
    # Invoke function
    aws lambda invoke \
        --function-name $function_name \
        --payload file:///tmp/test-payload.json \
        --region $REGION \
        /tmp/lambda-response.json >/dev/null 2>&1
    
    # Check response
    if [ -f /tmp/lambda-response.json ]; then
        response=$(cat /tmp/lambda-response.json)
        echo "Lambda Response:"
        echo "$response" | jq . 2>/dev/null || echo "$response"
        
        # Check for CORS headers in response
        if echo "$response" | jq -e '.headers' >/dev/null 2>&1; then
            echo ""
            echo "Headers in Lambda response:"
            echo "$response" | jq '.headers'
            
            # Check specific headers
            if echo "$response" | jq -e '.headers."Access-Control-Allow-Origin"' >/dev/null 2>&1; then
                success "Lambda returns Access-Control-Allow-Origin"
            else
                error "Lambda missing Access-Control-Allow-Origin"
            fi
        else
            error "Lambda response missing headers object"
        fi
    else
        error "Failed to invoke Lambda function"
    fi
    
    # Cleanup
    rm -f /tmp/test-payload.json /tmp/lambda-response.json
}

# Test with API Gateway v2 event structure
api_event='{"requestContext":{"http":{"method":"POST"}},"body":"{\"email\":\"test@example.com\",\"password\":\"test\"}"}'
test_lambda "tokyo-real-estate-ai-register-user" "$api_event"
test_lambda "tokyo-real-estate-ai-login-user" "$api_event"

# Test with OPTIONS request
options_event='{"requestContext":{"http":{"method":"OPTIONS"}}}'
echo ""
info "Testing Lambda OPTIONS handling:"
test_lambda "tokyo-real-estate-ai-register-user" "$options_event"
test_lambda "tokyo-real-estate-ai-login-user" "$options_event"

# Summary
echo ""
echo ""
echo "📊 Summary"
echo "=========="
echo ""
echo "Common CORS Issues:"
echo "1. Lambda not returning CORS headers on error responses"
echo "2. API Gateway CORS configuration not matching Lambda headers"
echo "3. Missing headers in Lambda response structure"
echo "4. Incorrect event structure parsing in Lambda"
echo ""
echo "If CORS errors persist:"
echo "- Check CloudWatch logs for Lambda errors"
echo "- Ensure Lambda returns headers object in ALL responses"
echo "- Verify API Gateway integration type is AWS_PROXY"
echo "- Check that preflight OPTIONS requests are handled"
echo ""

# Check recent Lambda logs
echo "💡 Recent Lambda Errors (if any):"
echo "================================"

check_logs() {
    local function_name=$1
    echo ""
    echo "Checking $function_name logs:"
    aws logs tail /aws/lambda/$function_name --since 5m --region $REGION 2>/dev/null | grep -i error || echo "No recent errors found"
}

check_logs "tokyo-real-estate-ai-register-user"
check_logs "tokyo-real-estate-ai-login-user"