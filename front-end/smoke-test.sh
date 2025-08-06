#!/bin/bash
# CORS Smoke Test

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
    echo "❌ Could not get API endpoint from stack $STACK_NAME"
    exit 1
fi

ORIGIN="http://tre-frontend-static-901472985889.s3-website-ap-northeast-1.amazonaws.com"

echo "🔍 CORS Smoke Test"
echo "=================="
echo "API: $API"
echo "Origin: $ORIGIN"
echo ""

echo "Testing OPTIONS /properties:"
curl -i -X OPTIONS -H "Origin: $ORIGIN" "$API/properties?limit=1" | grep -i 'access-control'

echo ""
echo "Expected headers:"
echo "  Access-Control-Allow-Origin: $ORIGIN"
echo "  Access-Control-Allow-Credentials: true"