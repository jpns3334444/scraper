#!/bin/bash
set -euo pipefail

# Configuration
LAMBDA_FUNCTION="tokyo-real-estate-ai-scraper"
REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"
SESSION_ID="lambda-$(date +%s)-$$"
LOG_LEVEL="INFO"  # Default log level

# Build payload from arguments
PAYLOAD="{\"session_id\":\"$SESSION_ID\""

while [[ $# -gt 0 ]]; do
    case $1 in
        --max-properties) PAYLOAD="$PAYLOAD,\"max_properties\":$2"; shift 2 ;;
        --areas) PAYLOAD="$PAYLOAD,\"areas\":\"$2\""; shift 2 ;;
        --batch-mode) PAYLOAD="$PAYLOAD,\"batch_mode\":true"; shift ;;
        --batch-area-size) PAYLOAD="$PAYLOAD,\"batch_area_size\":$2"; shift 2 ;;
        --batch-number) PAYLOAD="$PAYLOAD,\"batch_number\":$2"; shift 2 ;;
        --debug) LOG_LEVEL="DEBUG"; PAYLOAD="$PAYLOAD,\"log_level\":\"DEBUG\""; shift ;;
        --log-level) LOG_LEVEL="$2"; PAYLOAD="$PAYLOAD,\"log_level\":\"$2\""; shift 2 ;;
        *) shift ;;
    esac
done
PAYLOAD="$PAYLOAD}"

# Trigger Lambda
echo "🚀 Triggering Lambda with session: $SESSION_ID (Log level: $LOG_LEVEL)"
aws lambda invoke \
    --function-name "$LAMBDA_FUNCTION" \
    --invocation-type Event \
    --payload "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /dev/null >/dev/null 2>&1 || { echo "❌ Failed to trigger Lambda"; exit 1; }

echo "✅ Lambda triggered"
echo "📊 Streaming logs..."

# Stream logs filtered by session ID
sleep 2  # Give Lambda time to start
while true; do
    aws logs tail "/aws/lambda/$LAMBDA_FUNCTION" \
        --region "$REGION" \
        --follow \
        --filter-pattern "\"$SESSION_ID\"" \
        --format short 2>/dev/null || break
done

echo "✨ Done!"