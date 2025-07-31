#!/bin/bash
set -euo pipefail

# Handle Ctrl+C
cleanup() {
    echo ""
    echo "🛑 Stopped"
    # Kill any background log processes
    if [[ -n "${SESSION_PID:-}" ]]; then
        kill $SESSION_PID 2>/dev/null || true
    fi
    if [[ -n "${ERROR_PID:-}" ]]; then
        kill $ERROR_PID 2>/dev/null || true
    fi
    exit 0
}
trap cleanup INT

# Configuration
REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"
LOG_LEVEL="INFO" # Default log level
FUNCTION_NAME=""

# Function mapping: folder name -> AWS Lambda function name
declare -A FUNCTION_MAP=(
    ["scraper"]="tokyo-real-estate-ai-scraper"
    ["url-collector"]="tokyo-real-estate-ai-url-collector" 
    ["property-processor"]="tokyo-real-estate-ai-property-processor"
    ["property-analyzer"]="tokyo-real-estate-ai-property-analyzer"
    ["etl"]="tokyo-real-estate-ai-etl"
    ["prompt-builder"]="tokyo-real-estate-ai-prompt-builder"
    ["llm-batch"]="tokyo-real-estate-ai-llm-batch"
    ["report-sender"]="tokyo-real-estate-ai-report-sender"
    ["dynamodb-writer"]="tokyo-real-estate-ai-dynamodb-writer"
    ["snapshot-generator"]="tokyo-real-estate-ai-snapshot-generator"
    ["daily-digest"]="tokyo-real-estate-ai-daily-digest"
)

# Generate session ID first
SESSION_ID="${FUNCTION_NAME:-lambda}-$(date +%s)-$$"

# Build payload from arguments
PAYLOAD="{\"session_id\":\"$SESSION_ID\""

while [[ $# -gt 0 ]]; do
  case $1 in
    --function)
        FUNCTION_NAME="$2"
        if [[ -z "${FUNCTION_MAP[$FUNCTION_NAME]:-}" ]]; then
            echo "❌ Unknown function: $FUNCTION_NAME"
            echo "Available functions: ${!FUNCTION_MAP[*]}"
            exit 1
        fi
        LAMBDA_FUNCTION="${FUNCTION_MAP[$FUNCTION_NAME]}"
        SESSION_ID="${FUNCTION_NAME}-$(date +%s)-$$"
        PAYLOAD="{\"session_id\":\"$SESSION_ID\""
        shift 2 ;;
    --max-properties) PAYLOAD="$PAYLOAD,\"max_properties\":$2"; shift 2 ;;
    --areas) PAYLOAD="$PAYLOAD,\"areas\":\"$2\""; shift 2 ;;
    --max-concurrent-areas) PAYLOAD="$PAYLOAD,\"max_concurrent_areas\":$2"; shift 2 ;;
    --max-runtime-minutes) PAYLOAD="$PAYLOAD,\"max_runtime_minutes\":$2"; shift 2 ;;
    --batch-mode) PAYLOAD="$PAYLOAD,\"batch_mode\":true"; shift ;;
    --batch-area-size) PAYLOAD="$PAYLOAD,\"batch_area_size\":$2"; shift 2 ;;
    --batch-number) PAYLOAD="$PAYLOAD,\"batch_number\":$2"; shift 2 ;;
    --debug) LOG_LEVEL="DEBUG"; PAYLOAD="$PAYLOAD,\"log_level\":\"DEBUG\""; shift ;;
    --log-level) LOG_LEVEL="$2"; PAYLOAD="$PAYLOAD,\"log_level\":\"$2\""; shift 2 ;;
    --sync) SYNC_MODE=true; shift ;;
    --help)
      echo "Usage: $0 --function <function-name> [OPTIONS]"
      echo ""
      echo "Available Functions: ${!FUNCTION_MAP[*]}"
      echo ""
      echo "Options:"
      echo "  --function FUNC             Lambda function to trigger (required)"
      echo "  --max-properties N          Max properties to process"
      echo "  --areas AREAS               Comma-separated list of areas"
      echo "  --max-concurrent-areas N    Max concurrent area processing"
      echo "  --max-runtime-minutes N     Max runtime before stopping"
      echo "  --batch-mode                Enable batch processing mode"
      echo "  --batch-area-size N         Batch area size"
      echo "  --batch-number N            Batch number"
      echo "  --debug                     Enable debug logging"
      echo "  --log-level LEVEL           Set log level"
      echo "  --sync                      Wait for completion"
      echo "  --help                      Show this help message"
      exit 0
      ;;
    *) shift ;;
  esac
done

# Validate required function parameter
if [[ -z "$FUNCTION_NAME" ]]; then
    echo "❌ Error: --function is required"
    echo "Available functions: ${!FUNCTION_MAP[*]}"
    exit 1
fi

PAYLOAD="$PAYLOAD}"

# Trigger Lambda (based on working url-collector pattern)
echo "🔗 Triggering $FUNCTION_NAME with session: $SESSION_ID (Log level: $LOG_LEVEL)"
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
  /tmp/${FUNCTION_NAME}-response.json >/dev/null 2>&1 || { echo "❌ Failed to trigger Lambda"; exit 1; }

if [[ "${SYNC_MODE:-false}" == "true" ]]; then
  echo "✅ Lambda completed"
  echo "📄 Response:"
  cat /tmp/${FUNCTION_NAME}-response.json | python3 -m json.tool 2>/dev/null || cat /tmp/${FUNCTION_NAME}-response.json
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