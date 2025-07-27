#!/bin/bash
set -euo pipefail

# Function to show usage
show_usage() {
    echo "Usage: $0 [MODE] [SESSION_ID] [--full]"
    echo ""
    echo "Arguments:"
    echo "  MODE        Scraper mode (default: testing)"
    echo "  SESSION_ID  Session identifier (default: manual-TIMESTAMP)"
    echo "  --full, -f  Enable full load mode (scrapes all properties)"
    echo ""
    echo "Examples:"
    echo "  $0                    # Run in testing mode"
    echo "  $0 production         # Run in production mode"
    echo "  $0 testing my-session # Run with custom session ID"
    echo "  $0 -f                 # Run in testing mode with full load"
    echo "  $0 production --full  # Run in production mode with full load"
}

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
NC='\033[0m'

# Parse arguments
MODE="testing"
SESSION_ID=""
FULL_MODE=false
POSITIONAL_ARGS=()

# Process arguments
for arg in "$@"; do
    case $arg in
        --help|-h)
            show_usage
            exit 0
            ;;
        --full|-f)
            FULL_MODE=true
            ;;
        *)
            POSITIONAL_ARGS+=("$arg")
            ;;
    esac
done

# Process positional arguments
if [[ ${#POSITIONAL_ARGS[@]} -ge 1 ]]; then
    MODE="${POSITIONAL_ARGS[0]}"
fi
if [[ ${#POSITIONAL_ARGS[@]} -ge 2 ]]; then
    SESSION_ID="${POSITIONAL_ARGS[1]}"
fi

# Set defaults  
[[ -z "$SESSION_ID" ]] && SESSION_ID="manual-$(date +%s)"

# Variables
LAMBDA_FUNCTION="tokyo-real-estate-trigger"
LOG_GROUP_NAME="/aws/lambda/$LAMBDA_FUNCTION"
START_TIME=$(($(date +%s) * 1000))  # Milliseconds for CloudWatch

echo -e "${GREEN}🚀 TRIGGERING SCRAPER${NC}"
echo -e "${YELLOW}Mode: $MODE | Session: $SESSION_ID | Full Load: $FULL_MODE${NC}"
echo ""

# Build payload with full mode
PAYLOAD="{\"mode\":\"$MODE\",\"session_id\":\"$SESSION_ID\",\"full_mode\":$FULL_MODE}"

# Invoke Lambda and get request ID
INVOKE_RESULT=$(aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type Event \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json 2>&1)

echo -e "${GREEN}Lambda triggered. Response:${NC}"
cat /tmp/response.json
echo ""

# Wait for logs to start and find the log stream
echo -e "${YELLOW}Waiting for logs to start...${NC}"
sleep 5

# Find the most recent log stream
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP_NAME" \
  --order-by LastEventTime \
  --descending \
  --limit 1 \
  --query 'logStreams[0].logStreamName' \
  --output text)

if [[ "$LOG_STREAM" == "None" ]] || [[ -z "$LOG_STREAM" ]]; then
    echo -e "${RED}Error: Could not find log stream${NC}"
    exit 1
fi

echo -e "${GREEN}=== MONITORING LAMBDA LOGS ===${NC}"
echo -e "${BLUE}Log Stream: $LOG_STREAM${NC}"
echo -e "${BLUE}Session: $SESSION_ID${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop monitoring${NC}"
echo ""

# Monitor logs for this specific execution
LAST_TOKEN=""
while true; do
    # Get log events
    if [[ -z "$LAST_TOKEN" ]]; then
        RESPONSE=$(aws logs get-log-events \
            --log-group-name "$LOG_GROUP_NAME" \
            --log-stream-name "$LOG_STREAM" \
            --start-time "$START_TIME" \
            --start-from-head \
            2>/dev/null || echo '{"events": []}')
    else
        RESPONSE=$(aws logs get-log-events \
            --log-group-name "$LOG_GROUP_NAME" \
            --log-stream-name "$LOG_STREAM" \
            --start-time "$START_TIME" \
            --next-token "$LAST_TOKEN" \
            2>/dev/null || echo '{"events": []}')
    fi
    
    # Extract next token
    NEW_TOKEN=$(echo "$RESPONSE" | jq -r '.nextForwardToken // empty')
    
    # Process events
    echo "$RESPONSE" | jq -r '.events[].message' 2>/dev/null | while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        
        # Only show lines from our session
        if [[ "$line" == *"$SESSION_ID"* ]] || [[ "$line" == *"[EC2]"* ]] || [[ "$line" == *"[EC2-ERR]"* ]]; then
            # Color code the output
            if [[ "$line" == *"[EC2]"* ]]; then
                # EC2 output in green
                echo -e "${GREEN}$line${NC}"
            elif [[ "$line" == *"[EC2-ERR]"* ]] || [[ "$line" == *"ERROR"* ]] || [[ "$line" == *"❌"* ]]; then
                # Errors in red
                echo -e "${RED}$line${NC}"
            elif [[ "$line" == *"✅"* ]] || [[ "$line" == *"SUCCESS"* ]] || [[ "$line" == *"successful"* ]]; then
                # Success messages in green
                echo -e "${GREEN}$line${NC}"
            elif [[ "$line" == *"🚀"* ]] || [[ "$line" == *"🏃"* ]] || [[ "$line" == *"📋"* ]]; then
                # Status messages in blue
                echo -e "${BLUE}$line${NC}"
            elif [[ "$line" == *"⏳"* ]] || [[ "$line" == *"⚠️"* ]]; then
                # Warnings in yellow
                echo -e "${YELLOW}$line${NC}"
            else
                # Default output
                echo "$line"
            fi
        fi
    done
    
    # Check if we got new events
    if [[ "$NEW_TOKEN" == "$LAST_TOKEN" ]]; then
        # No new events, wait a bit
        sleep 2
    fi
    
    LAST_TOKEN="$NEW_TOKEN"
done