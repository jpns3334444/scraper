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

# Colours
BLUE='\033[0;34m'; ORANGE='\033[0;33m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

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

# Vars
LAMBDA_FUNCTION="tokyo-real-estate-trigger"
LOG_GROUP_NAME="/aws/lambda/$LAMBDA_FUNCTION"
START_TIME=$(($(date +%s) * 1000))   # CloudWatch needs ms

echo -e "${GREEN}🚀  TRIGGERING LAMBDA: $LAMBDA_FUNCTION${NC}"
echo -e "${YELLOW}Mode: $MODE | Session: $SESSION_ID | Full Load: $FULL_MODE${NC}"

# Build payload with full mode
PAYLOAD="{\"mode\":\"$MODE\",\"session_id\":\"$SESSION_ID\",\"full_mode\":$FULL_MODE}"

aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type Event \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json

echo -e "${GREEN}Lambda triggered. Response:${NC}"
cat /tmp/response.json
echo

sleep 3
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP_NAME" \
  --order-by LastEventTime --descending --limit 1 \
  --query 'logStreams[0].logStreamName' --output text)

[[ "$LOG_STREAM" != "None" ]] \
  && echo -e "${GREEN}Found log stream: $LOG_STREAM${NC}" \
  || echo -e "${YELLOW}Warning: Could not find log stream yet${NC}"

INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name tokyo-real-estate-compute \
  --query "Stacks[0].Outputs[?OutputKey=='ScraperInstanceId'].OutputValue" \
  --output text)
echo -e "${YELLOW}Instance ID: $INSTANCE_ID${NC}"

echo -e "${GREEN}=== MONITORING LOGS (ctrl-c to abort) ===${NC}"
echo -e "${BLUE}🔷 = Lambda logs (shows full execution: instance start, scraper run, completion)${NC}"
echo -e "${ORANGE}🔶 = EC2 run.log (direct scraper output, may not appear if CloudWatch agent is initializing)${NC}"
echo

LAMBDA_LOG_FILE="/tmp/lambda_logs_${SESSION_ID}.txt"
> "$LAMBDA_LOG_FILE"
LAST_LAM_COUNT=0
EC2_NEXT_TOKEN=""

LAMBDA_COMPLETE=false
SCRAPING_COMPLETE=false

while true; do
  ts=$(date +'%H:%M:%S')

  # ── Lambda stream ───────────────────────────────────────────────────────────
  if [[ -n "$LOG_STREAM" && "$LOG_STREAM" != "None" && "$LAMBDA_COMPLETE" == false ]]; then
    if ! aws logs get-log-events \
      --log-group-name "$LOG_GROUP_NAME" \
      --log-stream-name "$LOG_STREAM" \
      --start-time "$START_TIME" \
      --query 'events[*].message' --output text > "${LAMBDA_LOG_FILE}.new" 2>&1; then
      echo -e "${YELLOW}Warning: Failed to fetch lambda logs${NC}" >&2
      touch "${LAMBDA_LOG_FILE}.new"
    fi

    NEW_COUNT=$(wc -l < "${LAMBDA_LOG_FILE}.new")
    if (( NEW_COUNT > LAST_LAM_COUNT )); then
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        echo -e "${BLUE}🔷 $line${NC}"
        if [[ "$line" == *"Command status: Success"* || "$line" == *"Command status: Failed"* ]]; then
          LAMBDA_COMPLETE=true
        fi
      done < <(tail -n +"$((LAST_LAM_COUNT + 1))" "${LAMBDA_LOG_FILE}.new")
      LAST_LAM_COUNT=$NEW_COUNT
      cp "${LAMBDA_LOG_FILE}.new" "$LAMBDA_LOG_FILE"
    fi
  fi

  # ── EC2 stream (CloudWatch) ────────────────────────────────────────────
  if [[ -n "$INSTANCE_ID" && "$INSTANCE_ID" != "None" ]]; then
    # First check if the log stream exists
    if ! aws logs describe-log-streams --log-group-name "scraper-logs" --log-stream-name-prefix "$INSTANCE_ID" --query 'logStreams[0].logStreamName' --output text >/dev/null 2>&1; then
      echo -e "${YELLOW}No EC2 log stream found for $INSTANCE_ID${NC}"
      echo -e "${YELLOW}Note: Instance starts fresh each time, CloudWatch agent may need time to initialize${NC}"
    else
      CW_ARGS=(--log-group-name "scraper-logs" --log-stream-names "$INSTANCE_ID" --start-time "$START_TIME")
      [[ -n "$EC2_NEXT_TOKEN" ]] && CW_ARGS+=(--next-token "$EC2_NEXT_TOKEN")

      if ! EC2_JSON=$(aws logs filter-log-events "${CW_ARGS[@]}" 2>&1); then
        echo -e "${YELLOW}Warning: Failed to fetch EC2 logs: $(echo "$EC2_JSON" | head -1)${NC}" >&2
        EC2_JSON='{}'
      fi
      EC2_NEXT_TOKEN=$(echo "$EC2_JSON" | jq -r '.nextToken // empty' 2>/dev/null || true)

      # print new messages
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "$line" == "{"* ]]; then
          if msg=$(echo "$line" | jq -r '.message // empty' 2>/dev/null); then
            echo -e "${ORANGE}🔶 ${msg}${NC}"
          else
            echo -e "${ORANGE}🔶 $line${NC}"
          fi
        else
          echo -e "${ORANGE}🔶 $line${NC}"
        fi
      done < <(echo "$EC2_JSON" | jq -r '.events[].message // empty' 2>/dev/null || echo "")

      # completion check
      if echo "$EC2_JSON" | grep -q -E 'Job summary written|summary\.json uploaded|scraping completed successfully'; then
        SCRAPING_COMPLETE=true
      fi
    fi
  fi

  # ── Exit conditions ─────────────────────────────────────────────────────────
  if [[ "$SCRAPING_COMPLETE" == true ]]; then
    echo -e "${GREEN}🛑 Scraping completed successfully (marker found).${NC}"
    sleep 3
    break
  fi

  if [[ "$LAMBDA_COMPLETE" == true ]]; then
    echo -e "${YELLOW}[${ts}] Lambda done – waiting on EC2…${NC}"
  else
    echo -e "${YELLOW}[${ts}] monitoring…${NC}"
  fi
  sleep 2
done

echo -e "\n${GREEN}=== FINAL S3 OUTPUTS ===${NC}"
aws s3 ls s3://tokyo-real-estate-ai-data/scraper-output/ --recursive \
  | grep -E "${SESSION_ID}|$(date +%Y-%m-%d)" | tail -10 || true

echo -e "${GREEN}Done.${NC}"
