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

echo -e "${GREEN}🚀 TRIGGERING SCRAPER${NC}"
echo -e "${YELLOW}Mode: $MODE | Session: $SESSION_ID | Full Load: $FULL_MODE${NC}"
echo ""

# Build payload with full mode
PAYLOAD="{\"mode\":\"$MODE\",\"session_id\":\"$SESSION_ID\",\"full_mode\":$FULL_MODE}"

# Invoke Lambda
aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type Event \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json

echo -e "${GREEN}Lambda triggered. Response:${NC}"
cat /tmp/response.json
echo ""

# Wait a moment for logs to start
echo -e "${YELLOW}Waiting for logs to start...${NC}"
sleep 3

echo -e "${GREEN}=== MONITORING LAMBDA LOGS ===${NC}"
echo -e "${BLUE}All output (including EC2 scraper output) will appear here${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop monitoring${NC}"
echo ""

# Tail Lambda logs - this now includes all EC2 output
aws logs tail "$LOG_GROUP_NAME" --follow --since 5m --format short | while IFS= read -r line; do
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
done