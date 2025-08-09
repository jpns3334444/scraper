#!/usr/bin/env bash
# Example script showing how to use the centralized config system

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load centralized config
. "$SCRIPT_DIR/cfg.sh"

echo "🔧 Centralized Config Example"
echo "============================="
echo ""

# Display loaded config values
echo "📋 Core Configuration:"
echo "  Project: $PROJECT"
echo "  Region: $AWS_REGION"
echo "  AI Stack: $AI_STACK"
echo "  Frontend Stack: $FRONTEND_STACK"
echo ""

echo "☁️ AWS Resources:"
echo "  Deployment Bucket: $DEPLOYMENT_BUCKET"
echo "  Output Bucket: $OUTPUT_BUCKET"
echo "  DynamoDB Properties: $DDB_PROPERTIES"
echo "  DynamoDB URLs: $DDB_URL_TRACKING"
echo ""

echo "⚡ Lambda Functions:"
echo "  URL Collector: $LAMBDA_URL_COLLECTOR_FULL"
echo "  Property Processor: $LAMBDA_PROPERTY_PROCESSOR_FULL"
echo "  Dashboard API: $LAMBDA_DASHBOARD_API_FULL"
echo ""

echo "🚀 Example Usage:"
echo ""

echo "1. Deploy AI Stack:"
echo "   ./deploy-ai.sh"
echo ""

echo "2. Deploy Frontend:"
echo "   front-end/deploy-frontend.sh"
echo ""

echo "3. Update a Lambda function:"
echo "   ./update-lambda.sh property_processor"
echo ""

echo "4. Trigger a Lambda with config-aware script:"
echo "   ./trigger-lambda.sh --function property-processor --max-properties 10"
echo ""

echo "5. Use CloudFormation parameters from config:"
echo '   PARAMS_FILE="$(./scripts/cfn-params.sh /tmp/params.json ai)"'
echo '   aws cloudformation deploy --parameter-overrides file://"$PARAMS_FILE" ...'
echo ""

echo "6. Clear DynamoDB tables (uses config for table names):"
echo "   python3 clear-dydb.py"
echo ""

echo "✅ All scripts now use the centralized config!"
echo "   Edit config.json to change resource names"