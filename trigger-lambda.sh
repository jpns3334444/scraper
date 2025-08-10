#!/bin/bash
set -euo pipefail

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load centralized config
. "$SCRIPT_DIR/scripts/cfg.sh"

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

# Configuration from centralized config
REGION="$AWS_REGION"
LOG_LEVEL="INFO" # Default log level
FUNCTION_NAME=""
DEFAULT_BUCKET="$OUTPUT_BUCKET"

# Function mapping: folder name -> AWS Lambda function name
declare -A FUNCTION_MAP=(
    ["url-collector"]="$LAMBDA_URL_COLLECTOR_FULL"
    ["property-processor"]="$LAMBDA_PROPERTY_PROCESSOR_FULL"
    ["property-analyzer"]="$LAMBDA_PROPERTY_ANALYZER_FULL"
    ["favorite-analyzer"]="$LAMBDA_FAVORITE_ANALYZER_FULL"
    ["dashboard-api"]="$LAMBDA_DASHBOARD_API_FULL"
    ["favorites-api"]="$LAMBDA_FAVORITES_API_FULL"
    ["register-user"]="$LAMBDA_REGISTER_USER_FULL"
    ["login-user"]="$LAMBDA_LOGIN_USER_FULL"
    # Legacy functions that might still exist
    ["scraper"]="${AI_STACK}-scraper"
    ["etl"]="${AI_STACK}-etl"
    ["prompt-builder"]="${AI_STACK}-prompt-builder"
    ["llm-batch"]="${AI_STACK}-llm-batch"
    ["report-sender"]="${AI_STACK}-report-sender"
    ["dynamodb-writer"]="${AI_STACK}-dynamodb-writer"
    ["snapshot-generator"]="${AI_STACK}-snapshot-generator"
    ["daily-digest"]="${AI_STACK}-daily-digest"
)

# Generate session ID first
SESSION_ID="${FUNCTION_NAME:-lambda}-$(date +%s)-$$"

# Check if first argument is a function name (doesn't start with --)
if [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; then
    # First argument is function name - convert underscores to hyphens
    FUNCTION_NAME="${1//_/-}"
    shift
fi

# Build payload from arguments
PAYLOAD="{\"session_id\":\"$SESSION_ID\""

# Add default bucket to payload
PAYLOAD="$PAYLOAD,\"output_bucket\":\"$DEFAULT_BUCKET\""
OUTPUT_BUCKET="$DEFAULT_BUCKET"

# If we got function name from positional arg, validate and set it up
if [[ -n "$FUNCTION_NAME" ]]; then
    if [[ -z "${FUNCTION_MAP[$FUNCTION_NAME]:-}" ]]; then
        echo "❌ Unknown function: $FUNCTION_NAME"
        echo "Available functions: ${!FUNCTION_MAP[*]}"
        exit 1
    fi
    LAMBDA_FUNCTION="${FUNCTION_MAP[$FUNCTION_NAME]}"
    SESSION_ID="${FUNCTION_NAME}-$(date +%s)-$$"
    PAYLOAD="{\"session_id\":\"$SESSION_ID\",\"output_bucket\":\"$DEFAULT_BUCKET\""
fi

while [[ $# -gt 0 ]]; do
  case $1 in
    --function)
        # Keep backward compatibility with --function flag
        FUNCTION_NAME="$2"
        if [[ -z "${FUNCTION_MAP[$FUNCTION_NAME]:-}" ]]; then
            echo "❌ Unknown function: $FUNCTION_NAME"
            echo "Available functions: ${!FUNCTION_MAP[*]}"
            exit 1
        fi
        LAMBDA_FUNCTION="${FUNCTION_MAP[$FUNCTION_NAME]}"
        SESSION_ID="${FUNCTION_NAME}-$(date +%s)-$$"
        PAYLOAD="{\"session_id\":\"$SESSION_ID\",\"output_bucket\":\"$DEFAULT_BUCKET\""
        shift 2 ;;
    --parallel-instances) PARALLEL_INSTANCES="$2"; shift 2 ;;
    -p) PARALLEL_INSTANCES="$2"; shift 2 ;;
    --output-bucket) OUTPUT_BUCKET="$2"; PAYLOAD="${PAYLOAD%,\"output_bucket\":*}},\"output_bucket\":\"$2\""; shift 2 ;;
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
      echo "Usage: $0 <function-name> [OPTIONS]"
      echo "   or: $0 --function <function-name> [OPTIONS]"
      echo ""
      echo "Examples:"
      echo "  $0 property-processor -p 5"
      echo "  $0 property_processor -p 5    # underscores converted to hyphens"
      echo "  $0 url-collector --max-properties 1000"
      echo ""
      echo "Available Functions: ${!FUNCTION_MAP[*]}"
      echo ""
      echo "Options:"
      echo "  --function FUNC             Lambda function to trigger (alternative to positional arg)"
      echo "  --parallel-instances N      Launch N parallel Lambda instances"
      echo "  -p N                        Launch N parallel Lambda instances (shortcut)"
      echo "  --output-bucket BUCKET      S3 bucket for output (default: $DEFAULT_BUCKET)"
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
    echo "❌ Error: function name is required"
    echo ""
    echo "Usage: $0 <function-name> [OPTIONS]"
    echo "   or: $0 --function <function-name> [OPTIONS]"
    echo ""
    echo "Available functions: ${!FUNCTION_MAP[*]}"
    exit 1
fi

PAYLOAD="$PAYLOAD}"

# Trigger Lambda (based on working url-collector pattern)
echo "🔗 Triggering $FUNCTION_NAME with session: $SESSION_ID (Log level: $LOG_LEVEL)"
echo "📦 Using S3 bucket: $OUTPUT_BUCKET"
if [[ "${SYNC_MODE:-false}" == "true" ]]; then
  echo "⏳ Running in synchronous mode..."
  INVOCATION_TYPE="RequestResponse"
else
  echo "🚀 Running in asynchronous mode..."
  INVOCATION_TYPE="Event"
fi

# Debug: show payload if in debug mode
if [[ "$LOG_LEVEL" == "DEBUG" ]]; then
  echo "📋 Payload: $PAYLOAD"
fi

# Handle parallel instance launching
if [[ -n "${PARALLEL_INSTANCES:-}" ]] && [[ "$PARALLEL_INSTANCES" -gt 1 ]]; then
    echo "🚀 Launching $PARALLEL_INSTANCES parallel instances..."
    BASE_SESSION_ID="${FUNCTION_NAME}-parallel-$(date +%s)"
    
    for i in $(seq 1 $PARALLEL_INSTANCES); do
        INSTANCE_SESSION_ID="${BASE_SESSION_ID}-instance-${i}"
        INSTANCE_PAYLOAD=$(echo "$PAYLOAD" | jq --arg sid "$INSTANCE_SESSION_ID" '.session_id = $sid')
        
        echo "  🔄 Launching instance $i (session: $INSTANCE_SESSION_ID)..."
        
        aws lambda invoke \
            --function-name "$LAMBDA_FUNCTION" \
            --invocation-type "Event" \
            --payload "$INSTANCE_PAYLOAD" \
            --cli-binary-format raw-in-base64-out \
            --region "$REGION" \
            /tmp/${FUNCTION_NAME}-response-${i}.json >/dev/null 2>&1 || { echo "❌ Failed to trigger instance $i"; exit 1; }
        
        echo "  ✓ Instance $i launched"
        sleep 0.5  # Small delay between launches
    done
    
    echo "✅ All $PARALLEL_INSTANCES instances launched"
    echo "📊 Monitor progress with:"
    PARALLEL_TIMESTAMP=$(echo "$BASE_SESSION_ID" | sed 's/.*parallel-//')
    echo "  aws logs tail /aws/lambda/$LAMBDA_FUNCTION --follow --since 5m | grep parallel-${PARALLEL_TIMESTAMP}"
else
    # Single invocation (existing logic)
    aws lambda invoke \
      --function-name "$LAMBDA_FUNCTION" \
      --invocation-type "$INVOCATION_TYPE" \
      --payload "$PAYLOAD" \
      --cli-binary-format raw-in-base64-out \
      --region "$REGION" \
      /tmp/${FUNCTION_NAME}-response.json >/dev/null 2>&1 || { echo "❌ Failed to trigger Lambda"; exit 1; }
fi

# Handle log streaming for both single and parallel instances
if [[ "${SYNC_MODE:-false}" == "true" ]]; then
  if [[ -n "${PARALLEL_INSTANCES:-}" ]] && [[ "$PARALLEL_INSTANCES" -gt 1 ]]; then
    echo "⚠️  Sync mode not supported with parallel instances, switching to async mode"
    SYNC_MODE=false
  else
    echo "✅ Lambda completed"
    echo "📄 Response:"
    cat /tmp/${FUNCTION_NAME}-response.json | python3 -m json.tool 2>/dev/null || cat /tmp/${FUNCTION_NAME}-response.json
  fi
fi

if [[ "${SYNC_MODE:-false}" != "true" ]]; then
  if [[ -n "${PARALLEL_INSTANCES:-}" ]] && [[ "$PARALLEL_INSTANCES" -gt 1 ]]; then
    echo "✅ All parallel instances triggered"
    echo "📊 Streaming logs for all instances..."
    
    # For parallel instances, stream logs with a broader filter
    sleep 2 # Give Lambda time to start
    
    # Stream logs filtered by the base session ID pattern
    PARALLEL_TIMESTAMP=$(echo "$BASE_SESSION_ID" | sed 's/.*parallel-//')
    aws logs tail "/aws/lambda/$LAMBDA_FUNCTION" \
      --region "$REGION" \
      --follow \
      --since 30s \
      --filter-pattern "\"parallel-${PARALLEL_TIMESTAMP}\"" \
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
  fi
  
  # Wait for either process to finish or user interrupt
  wait $SESSION_PID $ERROR_PID 2>/dev/null || echo "Log streaming ended"
  
  # Clean up background processes
  kill $SESSION_PID $ERROR_PID 2>/dev/null || true
fi

echo "✨ Done!"