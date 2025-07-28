#!/bin/bash
set -euo pipefail

# Function to show usage
show_usage() {
    echo "Usage: $0 [MODE] [SESSION_ID] [--full] [--max-properties N] [--areas AREAS]"
    echo ""
    echo "Arguments:"
    echo "  MODE                   Scraper mode (default: testing)"
    echo "  SESSION_ID             Session identifier (default: manual-TIMESTAMP)"
    echo "  --full, -f             Enable full load mode (scrapes all properties)"
    echo "  --max-properties N     Limit to N properties (useful for testing full load)"
    echo "  --areas AREAS          Comma-separated list of areas (e.g., 'chofu-city,shibuya-ku')"
    echo ""
    echo "Examples:"
    echo "  $0                                        # Run in testing mode"
    echo "  $0 production                             # Run in production mode"
    echo "  $0 testing my-session                     # Run with custom session ID"
    echo "  $0 -f                                     # Run in testing mode with full load"
    echo "  $0 production --full                      # Run in production mode with full load"
    echo "  $0 --full --max-properties 5              # Full load but limit to 5 properties (single area)"
    echo "  $0 --full --max-properties 5 --areas chofu-city  # Explicit area selection"
    echo "  $0 production --full --max-properties 100 --areas 'chofu-city,shibuya-ku'  # Test with 2 areas"
}

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
PURPLE='\033[0;35m'
NC='\033[0m'

# Function to log with timestamp
log() {
    echo -e "${PURPLE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Parse arguments
MODE="testing"
SESSION_ID=""
FULL_MODE=false
MAX_PROPERTIES=""
AREAS=""
POSITIONAL_ARGS=()

# Process arguments
i=1
while [[ $i -le $# ]]; do
    arg="${!i}"
    case $arg in
        --help|-h)
            show_usage
            exit 0
            ;;
        --full|-f)
            FULL_MODE=true
            ;;
        --max-properties)
            i=$((i + 1))
            if [[ $i -le $# ]]; then
                MAX_PROPERTIES="${!i}"
            else
                echo "Error: --max-properties requires a number"
                exit 1
            fi
            ;;
        --areas)
            i=$((i + 1))
            if [[ $i -le $# ]]; then
                AREAS="${!i}"
            else
                echo "Error: --areas requires a comma-separated list"
                exit 1
            fi
            ;;
        *)
            POSITIONAL_ARGS+=("$arg")
            ;;
    esac
    i=$((i + 1))
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

# Determine testing scenario
IS_TESTING_SCENARIO=false
if [[ "$FULL_MODE" == "true" ]] && [[ -n "$MAX_PROPERTIES" ]] && [[ "$MAX_PROPERTIES" -le 50 ]]; then
    IS_TESTING_SCENARIO=true
fi

# Variables
LAMBDA_FUNCTION="tokyo-real-estate-trigger"
EC2_LOG_GROUP="scraper-logs"
REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"

# Create separator line
SEPARATOR=$(printf '=%.0s' {1..80})

echo -e "${GREEN}${SEPARATOR}${NC}"
echo -e "${GREEN}🚀 TOKYO REAL ESTATE SCRAPER TRIGGER - DETAILED DIAGNOSTIC MODE${NC}"
echo -e "${GREEN}${SEPARATOR}${NC}"

log "${YELLOW}Configuration:${NC}"
log "  Mode: ${BLUE}$MODE${NC}"
log "  Session ID: ${BLUE}$SESSION_ID${NC}"
log "  Full Load: ${BLUE}$FULL_MODE${NC}"
log "  Max Properties: ${BLUE}${MAX_PROPERTIES:-unlimited}${NC}"
log "  Areas: ${BLUE}${AREAS:-auto-detect}${NC}"
if [[ "$IS_TESTING_SCENARIO" == "true" ]]; then
    log "  ${YELLOW}⚡ TESTING SCENARIO DETECTED - Will use single area for efficiency${NC}"
fi
log "  Lambda Function: ${BLUE}$LAMBDA_FUNCTION${NC}"
log "  Region: ${BLUE}$REGION${NC}"
log "  Log Group: ${BLUE}$EC2_LOG_GROUP${NC}"
echo ""

# ... [Keep all the existing AWS credential checks, Lambda checks, etc. - lines 70-300+] ...

# Step 5: Trigger Lambda (MODIFIED)
log "${YELLOW}STEP 5: Triggering Lambda function...${NC}"
PAYLOAD="{\"mode\":\"$MODE\",\"session_id\":\"$SESSION_ID\",\"full_mode\":$FULL_MODE"

if [[ -n "$MAX_PROPERTIES" ]]; then
    PAYLOAD="$PAYLOAD,\"max_properties\":$MAX_PROPERTIES"
fi

if [[ -n "$AREAS" ]]; then
    PAYLOAD="$PAYLOAD,\"areas\":\"$AREAS\""
fi

PAYLOAD="$PAYLOAD}"

log "  Payload: $PAYLOAD"

# ... [Rest of the script remains the same] ...