#!/bin/bash
set -euo pipefail

# Dead simple Lambda + EC2 log monitor with color-coded output
# Usage: ./trigger_scraper_script.sh [mode] [session_id]

# Color definitions
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MODE=${1:-testing}
SESSION_ID=${2:-manual-$(date +%s)}
LAMBDA_FUNCTION="trigger-scraper"
LOG_GROUP_NAME="/aws/lambda/$LAMBDA_FUNCTION"

echo -e "${GREEN}🚀 TRIGGERING LAMBDA: $LAMBDA_FUNCTION${NC}"
echo -e "${YELLOW}Mode: $MODE | Session: $SESSION_ID${NC}"

# 1) Invoke Lambda
aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type Event \
  --payload '{"mode":"'"$MODE"'","session_id":"'"$SESSION_ID"'"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json

echo -e "${GREEN}Lambda triggered. Response:${NC}"
cat /tmp/response.json
echo ""

# 2) Wait a bit for log stream creation, then get the most recent log stream
sleep 3
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP_NAME" \
  --order-by LastEventTime \
  --descending \
  --limit 1 \
  --query 'logStreams[0].logStreamName' \
  --output text)

if [[ -n "$LOG_STREAM" && "$LOG_STREAM" != "None" ]]; then
  echo -e "${GREEN}Found log stream: $LOG_STREAM${NC}"
else
  echo -e "${YELLOW}Warning: Could not find log stream${NC}"
fi

# 3) Find EC2 instance
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name scraper-compute-stack \
  --query "Stacks[0].Outputs[?OutputKey=='ScraperInstanceId'].OutputValue" \
  --output text)

echo -e "${YELLOW}Instance ID: $INSTANCE_ID${NC}"

# 4) Send SSM command with inline parameters (no file needed!)
echo -e "${ORANGE}📡 Streaming run.log & waiting for new summary.json...${NC}"
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "rm -f /var/log/scraper/summary.json",
    "tail -n 0 -F /var/log/scraper/run.log & TAIL_PID=$!",
    "until [ -f /var/log/scraper/summary.json ]; do sleep 2; done",
    "kill $TAIL_PID",
    "echo \"\"",
    "echo \"=== SUMMARY.JSON ===\"",
    "cat /var/log/scraper/summary.json"
  ]' \
  --timeout-seconds 3600 \
  --query 'Command.CommandId' \
  --output text)

echo -e "${ORANGE}SSM Command ID: $COMMAND_ID${NC}"
echo ""

# 5) Poll logs & status
LAST_LAM_COUNT=0
LAST_EC2_COUNT=0
LAST_STATUS=""

echo -e "${GREEN}=== MONITORING LOGS (ctrl-c to abort) ===${NC}"
echo -e "${BLUE}🔷 = Lambda logs${NC}"
echo -e "${ORANGE}🔶 = EC2 run.log & summary.json${NC}"
echo ""

# Create temp files for tracking seen log lines
LAMBDA_LOG_FILE="/tmp/lambda_logs_${SESSION_ID}.txt"
EC2_LOG_FILE="/tmp/ec2_logs_${SESSION_ID}.txt"
> "$LAMBDA_LOG_FILE"
> "$EC2_LOG_FILE"

while true; do
  ts=$(date +'%H:%M:%S')
  echo -e "${YELLOW}[${ts}] polling...${NC}"

  # Lambda logs - use the specific log stream
  if [[ -n "$LOG_STREAM" && "$LOG_STREAM" != "None" ]]; then
    LAMBDA_LOGS=$(aws logs get-log-events \
      --log-group-name "$LOG_GROUP_NAME" \
      --log-stream-name "$LOG_STREAM" \
      --query 'events[*].message' \
      --output text 2>/dev/null || echo "")
    
    if [[ -n "$LAMBDA_LOGS" ]]; then
      # Count current lines
      echo "$LAMBDA_LOGS" > "${LAMBDA_LOG_FILE}.new"
      NEW_COUNT=$(wc -l < "${LAMBDA_LOG_FILE}.new")
      
      if (( NEW_COUNT > LAST_LAM_COUNT )); then
        # Show only new lines
        tail -n +$((LAST_LAM_COUNT + 1)) "${LAMBDA_LOG_FILE}.new" | while IFS= read -r line; do
          if [[ -n "$line" ]]; then
            echo -e "${BLUE}🔷 LAMBDA: ${line}${NC}"
          fi
        done
        LAST_LAM_COUNT=$NEW_COUNT
      fi
    fi
  fi

  # EC2 via SSM
  EC2_OUTPUT=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --query StandardOutputContent \
    --output text 2>/dev/null || echo "")
  
  if [[ -n "$EC2_OUTPUT" && "$EC2_OUTPUT" != "None" ]]; then
    # Count current lines
    echo "$EC2_OUTPUT" > "${EC2_LOG_FILE}.new"
    NEW_COUNT=$(wc -l < "${EC2_LOG_FILE}.new")
    
    if (( NEW_COUNT > LAST_EC2_COUNT )); then
      # Show only new lines
      tail -n +$((LAST_EC2_COUNT + 1)) "${EC2_LOG_FILE}.new" | while IFS= read -r line; do
        if [[ -n "$line" ]]; then
          echo -e "${ORANGE}🔶 EC2: ${line}${NC}"
        fi
      done
      LAST_EC2_COUNT=$NEW_COUNT
    fi
  fi

  # Status change
  STATUS=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --query Status \
    --output text 2>/dev/null || echo "UNKNOWN")
  
  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    echo -e "${YELLOW}📊 SSM Status: $STATUS${NC}"
    LAST_STATUS="$STATUS"
  fi

  # break when done
  if [[ "$STATUS" == "Success" || "$STATUS" == "Failed" ]]; then
    echo -e "${GREEN}🛑 Remote script completed ($STATUS).${NC}"
    
    # Show any error output if failed
    if [[ "$STATUS" == "Failed" ]]; then
      ERROR_OUTPUT=$(aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE_ID" \
        --query StandardErrorContent \
        --output text 2>/dev/null || echo "")
      if [[ -n "$ERROR_OUTPUT" && "$ERROR_OUTPUT" != "None" ]]; then
        echo -e "${ORANGE}❌ Error output:${NC}"
        echo "$ERROR_OUTPUT"
      fi
    fi
    break
  fi

  sleep 5
done

# Cleanup temp files
rm -f "$LAMBDA_LOG_FILE" "${LAMBDA_LOG_FILE}.new" "$EC2_LOG_FILE" "${EC2_LOG_FILE}.new"

# 6) Final S3 listing
echo -e "\n${GREEN}=== FINAL S3 OUTPUTS ===${NC}"
aws s3 ls s3://tokyo-real-estate-ai-data/scraper-output/ --recursive | tail -5

echo -e "${GREEN}Done.${NC}"