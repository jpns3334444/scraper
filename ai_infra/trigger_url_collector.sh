#!/bin/bash
set -euo pipefail

# Handle Ctrl+C
trap 'echo ""; echo "🛑 Stopped"; exit 0' INT

# Configuration
LAMBDA_FUNCTION="tokyo-real-estate-ai-url-collector"
REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"
SESSION_ID="url-collector-$(date +%s)-$$"
LOG_LEVEL="INFO" # Default log level

# Build payload from arguments
PAYLOAD="{\"session_id\":\"$SESSION_ID\""

while [[ $# -gt 0 ]]; do
  case $1 in
    --areas) PAYLOAD="$PAYLOAD,\"areas\":\"$2\""; shift 2 ;;
    --max-concurrent-areas) PAYLOAD="$PAYLOAD,\"max_concurrent_areas\":$2"; shift 2 ;;
    --debug) LOG_LEVEL="DEBUG"; PAYLOAD="$PAYLOAD,\"log_level\":\"DEBUG\""; shift ;;
    --log-level) LOG_LEVEL="$2"; PAYLOAD="$PAYLOAD,\"log_level\":\"$2\""; shift 2 ;;
    --sync) SYNC_MODE=true; shift ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --areas AREAS                    Comma-separated list of areas (default: auto-detect all)"
      echo "  --max-concurrent-areas N         Max concurrent area processing (default: 5)"
      echo "  --debug                          Enable debug logging"
      echo "  --log-level LEVEL               Set log level (INFO, DEBUG, WARNING, ERROR)"
      echo "  --sync                          Wait for completion (synchronous mode)"
      echo "  --help                          Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0                              # Process all areas"
      echo "  $0 --areas \"chofu-city,shibuya-ku\" # Process specific areas"
      echo "  $0 --debug --sync              # Debug mode with sync execution"
      exit 0
      ;;
    *) shift ;;
  esac
done

PAYLOAD="$PAYLOAD}"

# Trigger Lambda
echo "🔗 Triggering URL Collector with session: $SESSION_ID (Log level: $LOG_LEVEL)"
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
  /tmp/url-collector-response.json >/dev/null 2>&1 || { echo "❌ Failed to trigger Lambda"; exit 1; }

if [[ "${SYNC_MODE:-false}" == "true" ]]; then
  echo "✅ Lambda completed"
  echo "📄 Response:"
  cat /tmp/url-collector-response.json | python3 -m json.tool 2>/dev/null || cat /tmp/url-collector-response.json
else
  echo "✅ Lambda triggered"
  echo "📊 Streaming logs..."
  
  # Stream logs filtered by session ID using built-in filter
  sleep 2 # Give Lambda time to start
  
  # Start session ID logs in background
  aws logs tail "/aws/lambda/$LAMBDA_FUNCTION" \
    --region "$REGION" \
    --follow \
    --since 30s \
    --filter-pattern "\"$SESSION_ID\"" \
    --format short 2>/dev/null &
  SESSION_PID=$!
  
  # Also stream ERROR logs in parallel
  aws logs tail "/aws/lambda/$LAMBDA_FUNCTION" \
    --region "$REGION" \
    --follow \
    --since 30s \
    --filter-pattern "ERROR" \
    --format short 2>/dev/null &
  ERROR_PID=$!
  
  # Wait for either process to finish or user interrupt
  wait $SESSION_PID $ERROR_PID 2>/dev/null || echo "Log streaming ended"
  
  # Clean up background processes
  kill $SESSION_PID $ERROR_PID 2>/dev/null || true
fi

echo "✨ Done!"