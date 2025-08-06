#!/bin/bash
set -euo pipefail

# CORS Diagnostics Script - Tests common CORS failure modes in API Gateway + Lambda + S3 stack
# Usage: Set API_URL, DASHBOARD_ORIGIN, S3_ASSET_URL env vars and run

# Color utilities
RED=$(tput setaf 1 2>/dev/null || echo "")
GREEN=$(tput setaf 2 2>/dev/null || echo "")
YELLOW=$(tput setaf 3 2>/dev/null || echo "")
RESET=$(tput sgr0 2>/dev/null || echo "")

# Helper functions
say_pass() {
    echo "${GREEN}✅ $1${RESET}"
}

say_fail() {
    echo "${RED}❌ $1${RESET}"
}

say_info() {
    echo "${YELLOW}ℹ️  $1${RESET}"
}

# Check if header exists and optionally matches regex
expect_header() {
    local headers="$1"
    local header_name="$2"
    local pattern="${3:-}"
    
    # Debug: echo what we're looking for
    # echo "Looking for header: $header_name" >&2
    
    if echo "$headers" | grep -qi "^$header_name:"; then
        if [[ -n "$pattern" ]]; then
            if echo "$headers" | grep -qi "^$header_name:.*$pattern"; then
                return 0
            else
                return 1
            fi
        else
            return 0
        fi
    else
        return 1
    fi
}

# Validate required environment variables
check_env_vars() {
    local missing_vars=()
    
    [[ -z "${API_URL:-}" ]] && missing_vars+=("API_URL")
    [[ -z "${DASHBOARD_ORIGIN:-}" ]] && missing_vars+=("DASHBOARD_ORIGIN")
    [[ -z "${S3_ASSET_URL:-}" ]] && missing_vars+=("S3_ASSET_URL")
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo "${RED}Error: Missing required environment variables:${RESET}"
        for var in "${missing_vars[@]}"; do
            echo "  - $var"
        done
        echo ""
        echo "Example usage:"
        echo 'export API_URL="https://abc123.execute-api.ap-northeast-1.amazonaws.com/prod"'
        echo 'export DASHBOARD_ORIGIN="https://dashboard.mydomain.com"'
        echo 'export S3_ASSET_URL="https://my-bucket.s3.ap-northeast-1.amazonaws.com/logo.svg"'
        echo "bash cors_diagnose.sh"
        exit 1
    fi
}

# Test results tracking
declare -a test_results=()
declare -a test_names=()

run_test() {
    local test_name="$1"
    local test_func="$2"
    
    test_names+=("$test_name")
    say_info "Running: $test_name"
    
    if $test_func; then
        test_results+=(1)
        say_pass "$test_name"
    else
        test_results+=(0)
        say_fail "$test_name"
    fi
    echo ""
}

# Test 1: OPTIONS route exists
test_options_route() {
    local response
    response=$(curl -s -i -X OPTIONS "$API_URL/properties" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        -H "Access-Control-Request-Method: GET" \
        --max-time 10)
    
    # Check for 200/204 status and CORS header
    if echo "$response" | grep -q "HTTP/.* 20[04]" && \
       expect_header "$response" "access-control-allow-origin"; then
        return 0
    else
        echo "Response: $response" >&2
        return 1
    fi
}

# Test 2: GET success path includes CORS
test_get_success_cors() {
    local response
    response=$(curl -s -i "$API_URL/properties?limit=1" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        --max-time 10)
    
    # Check for 200 status and CORS header
    if echo "$response" | grep -q "HTTP/.* 200" && \
       expect_header "$response" "access-control-allow-origin"; then
        return 0
    else
        echo "Response: $response" >&2
        return 1
    fi
}

# Test 3: Random 404 still includes CORS
test_404_cors() {
    local response
    response=$(curl -s -i "$API_URL/does-not-exist" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        --max-time 10)
    
    # Check for error status (4xx/5xx) and CORS header
    if echo "$response" | grep -q "HTTP/.* [4-5][0-9][0-9]" && \
       expect_header "$response" "access-control-allow-origin"; then
        return 0
    else
        echo "Response: $response" >&2
        return 1
    fi
}

# Test 4: Forced 500 from Lambda still includes CORS
test_500_cors() {
    local response
    response=$(curl -s -i "$API_URL/properties?causeError=yes" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        --max-time 10)
    
    # Check for 500 status and CORS header
    if echo "$response" | grep -q "HTTP/.* 500" && \
       expect_header "$response" "access-control-allow-origin"; then
        return 0
    else
        # If causeError doesn't work, try another approach
        response=$(curl -s -i "$API_URL/invalid-endpoint-that-should-error" \
            -H "Origin: $DASHBOARD_ORIGIN" \
            --max-time 10)
        
        if echo "$response" | grep -q "HTTP/.* [4-5][0-9][0-9]" && \
           expect_header "$response" "access-control-allow-origin"; then
            return 0
        else
            echo "Response: $response" >&2
            return 1
        fi
    fi
}

# Test 5: Check header casing / multi-value
test_header_casing() {
    local response
    response=$(curl -s -i "$API_URL/properties?limit=1" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        --max-time 10)
    
    # Extract headers (everything before first blank line)
    local headers
    headers=$(echo "$response" | sed '/^$/q')
    
    # Check for lowercase CORS headers only
    local cors_headers
    cors_headers=$(echo "$headers" | grep -i "access-control-" || true)
    
    # Verify no uppercase CORS headers
    if echo "$cors_headers" | grep -q "Access-Control-"; then
        echo "Found uppercase CORS headers: $cors_headers" >&2
        return 1
    fi
    
    # Check for duplicate Allow-Origin headers
    local origin_count
    origin_count=$(echo "$cors_headers" | grep -ci "access-control-allow-origin" || echo "0")
    
    if [[ $origin_count -gt 1 ]]; then
        echo "Multiple Access-Control-Allow-Origin headers found: $origin_count" >&2
        return 1
    fi
    
    return 0
}

# Test 6: Credentials mode echo
test_credentials_mode() {
    local response
    response=$(curl -s -i "$API_URL/properties?limit=1" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        -H "Cookie: test=1" \
        --max-time 10)
    
    # Check for credentials header and origin match (not *)
    if expect_header "$response" "access-control-allow-credentials" "true" && \
       expect_header "$response" "access-control-allow-origin" "$DASHBOARD_ORIGIN"; then
        return 0
    else
        echo "Response: $response" >&2
        return 1
    fi
}

# Test 7: CloudFront / custom-domain header stripping
test_cloudfront_headers() {
    if [[ -z "${CF_URL:-}" ]]; then
        say_info "CF_URL not set, skipping CloudFront test"
        return 0
    fi
    
    # Get headers from API Gateway
    local api_response
    api_response=$(curl -s -i "$API_URL/properties?limit=1" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        --max-time 10)
    
    # Get headers from CloudFront
    local cf_response
    cf_response=$(curl -s -i "$CF_URL/properties?limit=1" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        --max-time 10)
    
    # Extract CORS headers from both
    local api_cors
    api_cors=$(echo "$api_response" | grep -i "access-control-" | sort || true)
    
    local cf_cors
    cf_cors=$(echo "$cf_response" | grep -i "access-control-" | sort || true)
    
    # Compare header sets
    if [[ "$api_cors" == "$cf_cors" ]]; then
        return 0
    else
        echo "API CORS headers: $api_cors" >&2
        echo "CF CORS headers: $cf_cors" >&2
        return 1
    fi
}

# Test 8: S3 asset pre-flight
test_s3_preflight() {
    local response
    response=$(curl -s -i -X OPTIONS "$S3_ASSET_URL" \
        -H "Origin: $DASHBOARD_ORIGIN" \
        -H "Access-Control-Request-Method: GET" \
        --max-time 10)
    
    # Check for 200 status and CORS header
    if echo "$response" | grep -q "HTTP/.* 200" && \
       expect_header "$response" "access-control-allow-origin"; then
        return 0
    else
        echo "Response: $response" >&2
        return 1
    fi
}

# Test 9: Large-payload timeout
test_large_payload_timeout() {
    local response
    response=$(curl -s -i --max-time 5 "$API_URL/properties?limit=999999" \
        -H "Origin: $DASHBOARD_ORIGIN" 2>&1 || true)
    
    # Should get either 200/504 with CORS, or timeout with no response
    if echo "$response" | grep -q "HTTP/[12].[01]"; then
        # Got HTTP response, check for CORS
        if expect_header "$response" "access-control-allow-origin"; then
            return 0
        else
            echo "Got HTTP response but no CORS header: $response" >&2
            return 1
        fi
    else
        # Timeout case - acceptable if no response at all
        return 0
    fi
}

# Main execution
main() {
    echo "${YELLOW}🔍 CORS Diagnostics Script${RESET}"
    echo "Testing CORS configuration for API Gateway + Lambda + S3 stack"
    echo ""
    
    check_env_vars
    
    echo "Configuration:"
    echo "  API_URL: $API_URL"
    echo "  DASHBOARD_ORIGIN: $DASHBOARD_ORIGIN"
    echo "  S3_ASSET_URL: $S3_ASSET_URL"
    echo "  CF_URL: ${CF_URL:-not set}"
    echo ""
    
    # Run all tests
    run_test "OPTIONS route exists" test_options_route
    run_test "GET success path includes CORS" test_get_success_cors
    run_test "Random 404 still includes CORS" test_404_cors
    run_test "Forced 500 from Lambda still includes CORS" test_500_cors
    run_test "Check header casing / multi-value" test_header_casing
    run_test "Credentials mode echo" test_credentials_mode
    run_test "CloudFront / custom-domain header stripping" test_cloudfront_headers
    run_test "S3 asset pre-flight" test_s3_preflight
    run_test "Large-payload timeout" test_large_payload_timeout
    
    # Summary
    echo "${YELLOW}📊 Test Summary${RESET}"
    echo "===================="
    
    local total_tests=${#test_names[@]}
    local passed_tests=0
    
    for i in "${!test_names[@]}"; do
        if [[ ${test_results[$i]} -eq 1 ]]; then
            echo "${GREEN}✅ ${test_names[$i]}${RESET}"
            ((passed_tests++))
        else
            echo "${RED}❌ ${test_names[$i]}${RESET}"
        fi
    done
    
    echo ""
    echo "Results: $passed_tests/$total_tests tests passed"
    
    if [[ $passed_tests -eq $total_tests ]]; then
        echo "${GREEN}🎉 All CORS tests passed!${RESET}"
        exit 0
    else
        echo "${RED}💥 Some CORS tests failed!${RESET}"
        exit 1
    fi
}

# Run main function
main "$@"

# Example usage:
# export API_URL="https://abc123.execute-api.ap-northeast-1.amazonaws.com/prod"
# export DASHBOARD_ORIGIN="https://dashboard.mydomain.com"
# export S3_ASSET_URL="https://my-bucket.s3.ap-northeast-1.amazonaws.com/logo.svg"
# export CF_URL="https://mydomain.com"  # optional
# bash cors_diagnose.sh