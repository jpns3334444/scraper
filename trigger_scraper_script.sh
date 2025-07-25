#!/bin/bash
set -euo pipefail

# Dead-simple Lambda + EC2 log monitor with color-coded output
# Usage: ./trigger_scraper_script.sh [mode] [session_id]

# ─── Colours ───────────────────────────────────────────────────────────────────
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'       # reset

# ─── Vars ──────────────────────────────────────────────────────────────────────
MODE=${1:-testing}
SESSION_ID=${2:-manual-$(date +%s)}
LAMBDA_FUNCTION="trigger-scraper"
LOG_GROUP_NAME="/aws/lambda/$LAMBDA_FUNCTION"
START_TIME=$(($(date +%s) * 1000))   # CloudWatch needs ms

# ─── Kick the Lambda ───────────────────────────────────────────────────────────
echo -e "${GREEN}🚀  TRIGGERING LAMBDA: $LAMBDA_FUNCTION${NC}"
echo -e "${YELLOW}Mode: $MODE | Session: $SESSION_ID${NC}"

aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type Event \
  --payload "{\"mode\":\"$MODE\",\"session_id\":\"$SESSION_ID\"}" \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json

echo -e "${GREEN}Lambda triggered. Response:${NC}"
cat /tmp/response.json
echo

# ─── Find freshest Lambda log-stream ───────────────────────────────────────────
sleep 3
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP_NAME" \
  --order-by LastEventTime --descending --limit 1 \
  --query 'logStreams[0].logStreamName' --output text)

[[ "$LOG_STREAM" != "None" ]] \
  && echo -e "${GREEN}Found log stream: $LOG_STREAM${NC}" \
  || echo -e "${YELLOW}Warning: Could not find log stream yet${NC}"

# ─── Pick up EC2 instance ID from CFN output ──────────────────────────────────
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name scraper-compute-stack \
  --query "Stacks[0].Outputs[?OutputKey=='ScraperInstanceId'].OutputValue" \
  --output text)
echo -e "${YELLOW}Instance ID: $INSTANCE_ID${NC}"

# ─── Monitor loop ──────────────────────────────────────────────────────────────
echo -e "${GREEN}=== MONITORING LOGS (ctrl-c to abort) ===${NC}"
echo -e "${BLUE}🔷 = Lambda logs${NC}"
echo -e "${ORANGE}🔶 = EC2 run.log${NC}"
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
    aws logs get-log-events \
      --log-group-name "$LOG_GROUP_NAME" \
      --log-stream-name "$LOG_STREAM" \
      --query 'events[*].message' --output text 2>/dev/null > "${LAMBDA_LOG_FILE}.new" || true

    NEW_COUNT=$(wc -l < "${LAMBDA_LOG_FILE}.new")
    if (( NEW_COUNT > LAST_LAM_COUNT )); then
      tail -n +"$((LAST_LAM_COUNT + 1))" "${LAMBDA_LOG_FILE}.new" | while read -r line; do
        [[ -z "$line" ]] && continue
        echo -e "${BLUE}🔷 $line${NC}"
        [[ "$line" == *"Command status: Success"* || "$line" == *"Command status: Failed"* ]] && LAMBDA_COMPLETE=true
      done
      LAST_LAM_COUNT=$NEW_COUNT
      cp "${LAMBDA_LOG_FILE}.new" "$LAMBDA_LOG_FILE"
    fi
  fi

  # ── EC2 stream (CloudWatch) ────────────────────────────────────────────
  if [[ -n "$INSTANCE_ID" && "$INSTANCE_ID" != "None" ]]; then
    CW_ARGS=(--log-group-name "scraper-logs" --log-stream-names "$INSTANCE_ID" --start-time "$START_TIME")
    [[ -n "$EC2_NEXT_TOKEN" ]] && CW_ARGS+=(--next-token "$EC2_NEXT_TOKEN")
    
    EC2_JSON=$(aws logs filter-log-events "${CW_ARGS[@]}" 2>/dev/null || echo '{}')
    EC2_NEXT_TOKEN=$(echo "$EC2_JSON" | jq -r '.nextToken // empty' 2>/dev/null || true)
    
    # 1) print every new message
    echo "$EC2_JSON" | jq -r '.events[].message // empty' 2>/dev/null | while read -r line; do
      [[ -z "$line" ]] && continue
      if [[ "$line" == "{"* ]]; then
        msg=$(echo "$line" | jq -r '.message // empty' 2>/dev/null) || msg="$line"
        echo -e "${ORANGE}🔶 ${msg:-$line}${NC}"
      else
        echo -e "${ORANGE}🔶 $line${NC}"
      fi
    done
    
    # 2) separate completion check (runs in *parent* shell)
    if echo "$EC2_JSON" | grep -q -E 'Job summary written|summary\.json uploaded|scraping completed successfully'; then
      SCRAPING_COMPLETE=true
    fi
  fi

  # ── Exit conditions ─────────────────────────────────────────────────────────
  if [[ "$SCRAPING_COMPLETE" == true ]]; then
    echo -e "${GREEN}🛑 Scraping completed successfully (marker found).${NC}"
    sleep 3
    break
  fi

  [[ "$LAMBDA_COMPLETE" == true ]] && \
      echo -e "${YELLOW}[${ts}] Lambda done – waiting on EC2…${NC}" || \
      echo -e "${YELLOW}[${ts}] monitoring…${NC}"
  sleep 2
done

# ─── Show latest S3 artefacts ─────────────────────────────────────────────────
echo -e "\n${GREEN}=== FINAL S3 OUTPUTS ===${NC}"
aws s3 ls s3://tokyo-real-estate-ai-data/scraper-output/ --recursive \
  | grep -E "${SESSION_ID}|$(date +%Y-%m-%d)" | tail -10

echo -e "${GREEN}Done.${NC}"
