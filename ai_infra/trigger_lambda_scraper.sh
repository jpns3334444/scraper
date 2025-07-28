#!/bin/bash
set -euo pipefail

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --max-properties N     Maximum number of properties to scrape (default: 0 = unlimited)"
    echo "  --areas AREAS          Comma-separated list of areas (default: auto-detect all)"
    echo "  --max-threads N        Maximum concurrent threads (default: 2)"
    echo "  --batch-size N         DynamoDB batch size (default: 25, max: 25)"
    echo "  --dynamodb-table NAME  DynamoDB table name (default: tokyo-real-estate-ai-RealEstateAnalysis)"
    echo "  --batch-mode           Enable batch processing mode"
    echo "  --batch-area-size N    Number of areas per batch (default: 5)"
    echo "  --batch-number N       Current batch number (default: 1)"
    echo "  --total-batches N      Total number of batches (default: 0 = auto-calculate)"
    echo "  --session-id ID        Custom session ID (default: lambda-TIMESTAMP)"
    echo "  --sync                 Use synchronous invocation (get immediate response)"
    echo "  --help, -h             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                                          # Run with all defaults"
    echo "  $0 --max-properties 10                     # Limit to 10 properties for testing"
    echo "  $0 --areas 'chofu-city,shibuya-ku'         # Scrape specific areas"
    echo "  $0 --batch-mode --batch-area-size 3        # Enable batch mode with 3 areas per batch"
    echo "  $0 --sync --max-properties 5               # Synchronous run with 5 properties"
}

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'

# Function to log with timestamp
log() {
    echo -e "${PURPLE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Default values
MAX_PROPERTIES=""
AREAS=""
MAX_THREADS=""
BATCH_SIZE=""
DYNAMODB_TABLE=""
BATCH_MODE=""
BATCH_AREA_SIZE=""
BATCH_NUMBER=""
TOTAL_BATCHES=""
SESSION_ID=""
SYNC_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --max-properties)
            MAX_PROPERTIES="$2"
            shift 2
            ;;
        --areas)
            AREAS="$2"
            shift 2
            ;;
        --max-threads)
            MAX_THREADS="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --dynamodb-table)
            DYNAMODB_TABLE="$2"
            shift 2
            ;;
        --batch-mode)
            BATCH_MODE="true"
            shift
            ;;
        --batch-area-size)
            BATCH_AREA_SIZE="$2"
            shift 2
            ;;
        --batch-number)
            BATCH_NUMBER="$2"
            shift 2
            ;;
        --total-batches)
            TOTAL_BATCHES="$2"
            shift 2
            ;;
        --session-id)
            SESSION_ID="$2"
            shift 2
            ;;
        --sync)
            SYNC_MODE=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Set defaults for empty values
[[ -z "$SESSION_ID" ]] && SESSION_ID="lambda-$(date +%s)"

# Configuration
LAMBDA_FUNCTION="tokyo-real-estate-ai-scraper"
LAMBDA_LOG_GROUP="/aws/lambda/tokyo-real-estate-ai-scraper"
REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"

# Create separator line
SEPARATOR=$(printf '=%.0s' {1..80})

echo -e "${GREEN}${SEPARATOR}${NC}"
echo -e "${GREEN}🚀 TOKYO REAL ESTATE SCRAPER - LAMBDA TRIGGER${NC}"
echo -e "${GREEN}${SEPARATOR}${NC}"

log "${YELLOW}Configuration:${NC}"
log "  Lambda Function: ${BLUE}$LAMBDA_FUNCTION${NC}"
log "  Session ID: ${BLUE}$SESSION_ID${NC}"
log "  Region: ${BLUE}$REGION${NC}"
log "  Invocation Type: ${BLUE}$(if [[ "$SYNC_MODE" == "true" ]]; then echo "Synchronous"; else echo "Asynchronous"; fi)${NC}"
[[ -n "$MAX_PROPERTIES" ]] && log "  Max Properties: ${BLUE}$MAX_PROPERTIES${NC}"
[[ -n "$AREAS" ]] && log "  Areas: ${BLUE}$AREAS${NC}"
[[ -n "$MAX_THREADS" ]] && log "  Max Threads: ${BLUE}$MAX_THREADS${NC}"
[[ -n "$BATCH_SIZE" ]] && log "  Batch Size: ${BLUE}$BATCH_SIZE${NC}"
[[ -n "$DYNAMODB_TABLE" ]] && log "  DynamoDB Table: ${BLUE}$DYNAMODB_TABLE${NC}"
if [[ "$BATCH_MODE" == "true" ]]; then
    log "  Batch Mode: ${BLUE}ENABLED${NC}"
    [[ -n "$BATCH_AREA_SIZE" ]] && log "  Batch Area Size: ${BLUE}$BATCH_AREA_SIZE${NC}"
    [[ -n "$BATCH_NUMBER" ]] && log "  Batch Number: ${BLUE}$BATCH_NUMBER${NC}"
    [[ -n "$TOTAL_BATCHES" ]] && log "  Total Batches: ${BLUE}$TOTAL_BATCHES${NC}"
fi
echo ""

# Step 1: Check AWS credentials
log "${YELLOW}STEP 1: Checking AWS credentials...${NC}"
if aws sts get-caller-identity &>/dev/null; then
    CALLER_INFO=$(aws sts get-caller-identity)
    log "${GREEN}✓ AWS credentials valid${NC}"
    log "  Account: $(echo $CALLER_INFO | jq -r .Account)"
    log "  User/Role: $(echo $CALLER_INFO | jq -r .Arn)"
else
    log "${RED}✗ AWS credentials not configured or invalid${NC}"
    exit 1
fi
echo ""

# Step 2: Check if Lambda function exists
log "${YELLOW}STEP 2: Checking Lambda function...${NC}"
if aws lambda get-function --function-name "$LAMBDA_FUNCTION" --region "$REGION" &>/dev/null; then
    log "${GREEN}✓ Lambda function exists: $LAMBDA_FUNCTION${NC}"
    LAMBDA_INFO=$(aws lambda get-function-configuration --function-name "$LAMBDA_FUNCTION" --region "$REGION")
    log "  Runtime: $(echo $LAMBDA_INFO | jq -r .Runtime)"
    log "  Timeout: $(echo $LAMBDA_INFO | jq -r .Timeout) seconds"
    log "  Memory: $(echo $LAMBDA_INFO | jq -r .MemorySize) MB"
    log "  Handler: $(echo $LAMBDA_INFO | jq -r .Handler)"
else
    log "${RED}✗ Lambda function not found: $LAMBDA_FUNCTION${NC}"
    exit 1
fi
echo ""

# Step 3: Build payload
log "${YELLOW}STEP 3: Building Lambda payload...${NC}"
PAYLOAD="{\"session_id\":\"$SESSION_ID\""

[[ -n "$MAX_PROPERTIES" ]] && PAYLOAD="$PAYLOAD,\"max_properties\":$MAX_PROPERTIES"
[[ -n "$AREAS" ]] && PAYLOAD="$PAYLOAD,\"areas\":\"$AREAS\""
[[ -n "$MAX_THREADS" ]] && PAYLOAD="$PAYLOAD,\"max_threads\":$MAX_THREADS"
[[ -n "$BATCH_SIZE" ]] && PAYLOAD="$PAYLOAD,\"batch_size\":$BATCH_SIZE"
[[ -n "$DYNAMODB_TABLE" ]] && PAYLOAD="$PAYLOAD,\"dynamodb_table\":\"$DYNAMODB_TABLE\""
[[ "$BATCH_MODE" == "true" ]] && PAYLOAD="$PAYLOAD,\"batch_mode\":true"
[[ -n "$BATCH_AREA_SIZE" ]] && PAYLOAD="$PAYLOAD,\"batch_area_size\":$BATCH_AREA_SIZE"
[[ -n "$BATCH_NUMBER" ]] && PAYLOAD="$PAYLOAD,\"batch_number\":$BATCH_NUMBER"
[[ -n "$TOTAL_BATCHES" ]] && PAYLOAD="$PAYLOAD,\"total_batches\":$TOTAL_BATCHES"

PAYLOAD="$PAYLOAD}"

log "  Payload: ${BLUE}$PAYLOAD${NC}"
echo ""

# Step 4: Invoke Lambda
log "${YELLOW}STEP 4: Invoking Lambda function...${NC}"

if [[ "$SYNC_MODE" == "true" ]]; then
    # Synchronous invocation
    INVOCATION_TYPE="RequestResponse"
    log "  Using synchronous invocation (RequestResponse)..."
else
    # Asynchronous invocation
    INVOCATION_TYPE="Event"
    log "  Using asynchronous invocation (Event)..."
fi

INVOKE_START=$(date +%s)
RESPONSE_FILE="/tmp/lambda_response_$(date +%s).json"

INVOKE_OUTPUT=$(aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type "$INVOCATION_TYPE" \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  --region "$REGION" \
  "$RESPONSE_FILE" 2>&1)

INVOKE_STATUS=$?

if [[ $INVOKE_STATUS -eq 0 ]]; then
    log "${GREEN}✓ Lambda invoked successfully${NC}"
    
    if [[ -f "$RESPONSE_FILE" ]]; then
        RESPONSE_CONTENT=$(cat "$RESPONSE_FILE")
        log "  Response: ${BLUE}$RESPONSE_CONTENT${NC}"
        
        if [[ "$SYNC_MODE" == "true" ]]; then
            # For synchronous calls, check if there was an error in the function
            if echo "$RESPONSE_CONTENT" | jq -e '.errorMessage' >/dev/null 2>&1; then
                log "${RED}✗ Lambda function returned an error:${NC}"
                echo "$RESPONSE_CONTENT" | jq -r '.errorMessage' | sed 's/^/    /'
                exit 1
            fi
        fi
    fi
else
    log "${RED}✗ Lambda invocation failed${NC}"
    log "  Error: $INVOKE_OUTPUT"
    exit 1
fi
echo ""

# Step 5: Stream logs
if [[ "$SYNC_MODE" == "true" ]]; then
    log "${YELLOW}STEP 5: Fetching recent logs from completed execution...${NC}"
    
    # For synchronous execution, get recent logs
    aws logs tail "$LAMBDA_LOG_GROUP" \
      --region "$REGION" \
      --since 5m \
      --format short \
      --filter-pattern "[timestamp, request_id, level=\"INFO\"]" 2>/dev/null || {
        log "${YELLOW}⚠ Could not fetch recent logs. Log group might not exist yet.${NC}"
    }
else
    log "${YELLOW}STEP 5: Streaming Lambda logs...${NC}"
    log "  Log Group: ${BLUE}$LAMBDA_LOG_GROUP${NC}"
    log "  Session: ${BLUE}$SESSION_ID${NC}"
    echo ""
    
    log "${GREEN}${SEPARATOR}${NC}"
    log "${GREEN}📊 STREAMING LAMBDA LOGS - Press Ctrl+C to stop${NC}"
    log "${GREEN}${SEPARATOR}${NC}"
    echo ""
    
    # Wait a moment for the function to start
    sleep 2
    
    # Tail logs with follow
    aws logs tail "$LAMBDA_LOG_GROUP" \
      --follow \
      --format short \
      --region "$REGION" \
      --since 1m 2>/dev/null || {
        log "${YELLOW}⚠ Could not tail logs. Trying to create log group or waiting for first logs...${NC}"
        
        # Wait for log group to be created and try again
        sleep 5
        aws logs tail "$LAMBDA_LOG_GROUP" \
          --follow \
          --format short \
          --region "$REGION" \
          --since 2m 2>/dev/null || {
            log "${RED}✗ Could not access Lambda logs. Check function execution in AWS Console.${NC}"
        }
    }
fi

# Cleanup
[[ -f "$RESPONSE_FILE" ]] && rm -f "$RESPONSE_FILE"

echo ""
log "${GREEN}${SEPARATOR}${NC}"
log "${GREEN}🎉 Scraper trigger completed successfully!${NC}"
log "${GREEN}${SEPARATOR}${NC}"