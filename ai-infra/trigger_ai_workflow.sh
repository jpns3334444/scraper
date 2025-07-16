#!/bin/bash
set -euo pipefail

# AI Workflow Trigger & Monitor - Step Functions + Lambda Log Streaming
# Usage:
#   ./trigger_ai_workflow.sh [date] [region] [--all]
#   ./trigger_ai_workflow.sh [date] [region] --filter "Regex|Pattern"
#
# ─── Colours ───────────────────────────────────────────────────────────────────
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'       # reset

# ─── Log‑filter options ────────────────────────────────────────────────────────
# Default: only show “important” lines. Override with --all, --filter, or env.
DEFAULT_FILTER="ERROR|Exception|FAIL|Lambda_WARNING|Traceback|NoSuchBucket"
LOG_FILTER="${LOG_FILTER:-$DEFAULT_FILTER}"

DATE=${1:-$(date +%Y-%m-%d)}
REGION=${2:-ap-northeast-1}
# Optional 3rd/4th args
FLAG=${3:-}
CUSTOM_REGEX=${4:-}

case "$FLAG" in
  --all)
    LOG_FILTER=""
    ;;
  --filter)
    LOG_FILTER="$CUSTOM_REGEX"
    ;;
esac

if [[ -n "$LOG_FILTER" ]]; then
  echo -e "${YELLOW}ℹ Showing only important log lines (pattern: ${LOG_FILTER})${NC}"
else
  echo -e "${CYAN}ℹ Showing ALL log lines${NC}"
fi

# ─── Configuration ─────────────────────────────────────────────────────────────
STACK_NAME="ai-scraper-dev"
STATE_MACHINE_NAME="${STACK_NAME}-ai-analysis"
START_TIME=$(($(date +%s) * 1000))   # CloudWatch needs ms

# Lambda function names
ETL_FUNCTION="${STACK_NAME}-etl"
PROMPT_FUNCTION="${STACK_NAME}-prompt-builder"
LLM_FUNCTION="${STACK_NAME}-llm-batch"
REPORT_FUNCTION="${STACK_NAME}-report-sender"

# ─── Get State Machine ARN ─────────────────────────────────────────────────────
echo -e "${GREEN}🔍 Looking up State Machine ARN...${NC}"
STATE_MACHINE_ARN=$(aws stepfunctions list-state-machines \
  --region "$REGION" \
  --query "stateMachines[?name=='$STATE_MACHINE_NAME'].stateMachineArn" \
  --output text)

if [[ -z "$STATE_MACHINE_ARN" || "$STATE_MACHINE_ARN" == "None" ]]; then
  echo -e "${RED}❌ State machine '$STATE_MACHINE_NAME' not found in region $REGION${NC}"
  echo -e "${YELLOW}💡 Available state machines:${NC}"
  aws stepfunctions list-state-machines --region "$REGION" --query "stateMachines[].name" --output table
  exit 1
fi

echo -e "${GREEN}✅ Found State Machine: $STATE_MACHINE_ARN${NC}"

# ─── Trigger Step Functions ────────────────────────────────────────────────────
echo -e "${GREEN}🚀 TRIGGERING AI WORKFLOW${NC}"
echo -e "${YELLOW}Date: $DATE | Region: $REGION${NC}"
echo -e "${CYAN}State Machine: $STATE_MACHINE_NAME${NC}"

EXECUTION_NAME="ai-workflow-$(date +%Y%m%d-%H%M%S)"
EXECUTION_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --name "$EXECUTION_NAME" \
  --input "{\"date\":\"$DATE\"}" \
  --region "$REGION" \
  --query 'executionArn' --output text)

echo -e "${GREEN}✅ Execution started: $EXECUTION_NAME${NC}"
echo -e "${CYAN}Execution ARN: $EXECUTION_ARN${NC}"
echo

# ─── Helper Functions ──────────────────────────────────────────────────────────
get_latest_log_stream() {
  local function_name="$1"
  local log_group="/aws/lambda/$function_name"
  
  aws logs describe-log-streams \
    --log-group-name "$log_group" \
    --order-by LastEventTime --descending --limit 1 \
    --region "$REGION" \
    --query 'logStreams[0].logStreamName' --output text 2>/dev/null || echo "None"
}

stream_lambda_logs() {
  local function_name="$1"
  local color="$2"
  local emoji="$3"
  local log_group="/aws/lambda/$function_name"
  local last_timestamp=0
  
  while true; do
    local log_stream
    log_stream=$(get_latest_log_stream "$function_name")
    
    if [[ "$log_stream" != "None" && -n "$log_stream" ]]; then
      # Get new log events since last check
      local events
      events=$(aws logs get-log-events \
        --log-group-name "$log_group" \
        --log-stream-name "$log_stream" \
        --start-time "$last_timestamp" \
        --region "$REGION" \
        --query 'events[*].[timestamp,message]' --output text 2>/dev/null || echo "")
      
      if [[ -n "$events" ]]; then
        while read -r timestamp message; do
          # Skip empty lines and validate timestamp is numeric
          if [[ -n "$timestamp" && "$timestamp" =~ ^[0-9]+$ && "$timestamp" -gt "$last_timestamp" ]]; then
            # Trim whitespace
            clean_message=$(echo "$message" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            
            # Filter noise
            if [[ -n "$LOG_FILTER" && ! "$clean_message" =~ $LOG_FILTER ]]; then
              continue
            fi
            
            # Remove AWS boilerplate (RequestId, REPORT)
            clean_message=$(echo "$clean_message" | sed -E 's/(RequestId:|REPORT ).*//')
            
            [[ -n "$clean_message" ]] && \
              echo -e "${color}${emoji} [$function_name] $clean_message${NC}"
          fi
        done <<< "$events"
        # Update last_timestamp for next iteration
        last_timestamp=$(echo "$events" | tail -1 | awk '{print $1}')
      fi
    fi
    
    sleep 2
  done
}

# ─── Monitor Execution Status ──────────────────────────────────────────────────
monitor_execution() {
  echo -e "${GREEN}=== MONITORING STEP FUNCTIONS EXECUTION ===${NC}"
  echo -e "${BLUE}🔷 = ETL Function${NC}"
  echo -e "${ORANGE}🔶 = Prompt Builder${NC}"
  echo -e "${PURPLE}🔸 = LLM Batch${NC}"
  echo -e "${CYAN}🔹 = Report Sender${NC}"
  echo -e "${YELLOW}⚡ = Step Functions${NC}"
  echo

  # Start background log streaming for each Lambda function
  stream_lambda_logs "$ETL_FUNCTION"    "$BLUE"    "🔷" & ETL_PID=$!
  stream_lambda_logs "$PROMPT_FUNCTION" "$ORANGE"  "🔶" & PROMPT_PID=$!
  stream_lambda_logs "$LLM_FUNCTION"    "$PURPLE"  "🔸" & LLM_PID=$!
  stream_lambda_logs "$REPORT_FUNCTION" "$CYAN"    "🔹" & REPORT_PID=$!

  # Monitor Step Functions execution status
  while true; do
    local status
    status=$(aws stepfunctions describe-execution \
      --execution-arn "$EXECUTION_ARN" \
      --region "$REGION" \
      --query 'status' --output text 2>/dev/null || echo "UNKNOWN")
    
    local timestamp
    timestamp=$(date +'%H:%M:%S')
    
    case "$status" in
      "RUNNING")
        echo -e "${YELLOW}⚡ [$timestamp] Step Functions: RUNNING${NC}"
        ;;
      "SUCCEEDED")
        echo -e "${GREEN}⚡ [$timestamp] Step Functions: SUCCEEDED ✅${NC}"
        break
        ;;
      "FAILED"|"ABORTED"|"TIMED_OUT")
        echo -e "${RED}⚡ [$timestamp] Step Functions: $status ❌${NC}"
        echo -e "${RED}📋 Execution History:${NC}"
        aws stepfunctions get-execution-history \
          --execution-arn "$EXECUTION_ARN" \
          --region "$REGION" \
          --query 'events[?type==`ExecutionFailed` || type==`TaskFailed`].[timestamp,type,executionFailedEventDetails.cause]' \
          --output table
        break
        ;;
      *)
        echo -e "${YELLOW}⚡ [$timestamp] Step Functions: $status${NC}"
        ;;
    esac
    
    sleep 5
  done

  # Stop background log streaming
  echo -e "${YELLOW}🛑 Stopping log streams...${NC}"
  kill "$ETL_PID" "$PROMPT_PID" "$LLM_PID" "$REPORT_PID" 2>/dev/null || true
  wait "$ETL_PID" "$PROMPT_PID" "$LLM_PID" "$REPORT_PID" 2>/dev/null || true
}

# ─── Cleanup on Exit ───────────────────────────────────────────────────────────
cleanup() {
  echo -e "\n${YELLOW}🧹 Cleaning up background processes...${NC}"
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT

# ─── Main Monitoring Loop ──────────────────────────────────────────────────────
monitor_execution

# ─── Show Final Results ────────────────────────────────────────────────────────
echo -e "\n${GREEN}=== FINAL RESULTS ===${NC}"

EXECUTION_OUTPUT=$(aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --region "$REGION" \
  --query 'output' --output text 2>/dev/null || echo "")

if [[ -n "$EXECUTION_OUTPUT" && "$EXECUTION_OUTPUT" != "None" ]]; then
  echo -e "${GREEN}📋 Execution Output:${NC}"
  echo "$EXECUTION_OUTPUT" | jq . 2>/dev/null || echo "$EXECUTION_OUTPUT"
fi

echo -e "\n${GREEN}📁 S3 Outputs for $DATE:${NC}"
aws s3 ls s3://tokyo-real-estate-ai-data/ --recursive | grep "$DATE" | tail -20 || echo "No outputs found"

echo -e "\n${GREEN}📄 Generated Reports:${NC}"
aws s3 ls s3://tokyo-real-estate-ai-data/reports/ --recursive | grep "$DATE" | tail -10 || echo "No reports found"

echo -e "${GREEN}✅ AI Workflow monitoring complete.${NC}"
echo -e "${CYAN}🔗 View execution in AWS Console:${NC}"
echo "https://console.aws.amazon.com/states/home?region=$REGION#/executions/details/$EXECUTION_ARN"
