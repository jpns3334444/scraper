#!/bin/bash
set -euo pipefail

# Handle Ctrl+C
trap 'echo ""; echo "🛑 Stopped"; exit 0' INT

# Configuration
LAMBDA_FUNCTION="tokyo-real-estate-ai-property-processor"
REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"
SESSION_ID="property-processor-$(date +%s)-$$"
LOG_LEVEL="INFO" # Default log level

# Build payload from arguments
PAYLOAD="{\"session_id\":\"$SESSION_ID\""

while [[ $# -gt 0 ]]; do
  case $1 in
    --max-properties) PAYLOAD="$PAYLOAD,\"max_properties\":$2"; shift 2 ;;
    --max-runtime-minutes) PAYLOAD="$PAYLOAD,\"max_runtime_minutes\":$2"; shift 2 ;;
    --debug) LOG_LEVEL="DEBUG"; PAYLOAD="$PAYLOAD,\"log_level\":\"DEBUG\""; shift ;;
    --log-level) LOG_LEVEL="$2"; PAYLOAD="$PAYLOAD,\"log_level\":\"$2\""; shift 2 ;;
    --sync) SYNC_MODE=true; shift ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --max-properties N              Max properties to process in this run (default: unlimited)"
      echo "  --max-runtime-minutes N         Max runtime before stopping (default: 14 minutes)"
      echo "  --debug                         Enable debug logging"
      echo "  --log-level LEVEL              Set log level (INFO, DEBUG, WARNING, ERROR)"
      echo "  --sync                         Wait for completion (synchronous mode)"
      echo "  --help                         Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0                             # Process all unprocessed URLs"
      echo "  $0 --max-properties 10         # Process only 10 properties"
      echo "  $0 --max-runtime-minutes 5     # Run for max 5 minutes"
      echo "  $0 --debug --sync             # Debug mode with sync execution"
      exit 0
      ;;
    *) shift ;;
  esac
done

PAYLOAD="$PAYLOAD}"

# Trigger Lambda
echo "⚙️ Triggering Property Processor with session: $SESSION_ID (Log level: $LOG_LEVEL)"
if [[ "${SYNC_MODE:-false}" == "true" ]]; then
  echo "⏳ Running in synchronous mode..."
  INVOCATION_TYPE="RequestResponse"
else
  echo "🚀 Running in asynchronous mode..."
  INVOCATION_TYPE="Event"
fi

aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type "$INVOCATION_TYPE" \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  --region "$REGION" \
  /tmp/property-processor-response.json >/dev/null 2>&1 || { echo "❌ Failed to trigger Lambda"; exit 1; }

if [[ "${SYNC_MODE:-false}" == "true" ]]; then
  echo "✅ Lambda completed"
  echo "📄 Response:"
  cat /tmp/property-processor-response.json | python3 -m json.tool 2>/dev/null || cat /tmp/property-processor-response.json
else
  echo "✅ Lambda triggered"
  echo "📊 Streaming logs..."
  
  # Stream logs filtered by session ID using built-in filter
  sleep 2 # Give Lambda time to start
  
  aws logs tail "/aws/lambda/$LAMBDA_FUNCTION" \
    --region "$REGION" \
    --follow \
    --since 30s \
    --filter-pattern "\"$SESSION_ID\"" \
    --format short 2>/dev/null || echo "Log streaming ended"
fi

echo "✨ Done!"