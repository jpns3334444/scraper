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
log "  Lambda Function: ${BLUE}$LAMBDA_FUNCTION${NC}"
log "  Region: ${BLUE}$REGION${NC}"
log "  Log Group: ${BLUE}$EC2_LOG_GROUP${NC}"
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
else
    log "${RED}✗ Lambda function not found: $LAMBDA_FUNCTION${NC}"
    exit 1
fi
echo ""

# Step 3: Check EC2 instances BEFORE triggering
log "${YELLOW}STEP 3: Checking EC2 instances BEFORE triggering Lambda...${NC}"
EC2_INSTANCES=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=tokyo-real-estate-scraper" \
  --region "$REGION" \
  --query "Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,LaunchTime,PublicIpAddress]" \
  --output text)

if [[ -z "$EC2_INSTANCES" ]]; then
    log "${RED}✗ No EC2 instances found with tag Name=tokyo-real-estate-scraper${NC}"
else
    log "${GREEN}✓ Found EC2 instance(s):${NC}"
    echo "$EC2_INSTANCES" | while read -r instance_id state type launch_time public_ip; do
        log "  Instance: ${BLUE}$instance_id${NC}"
        log "    State: ${state}"
        log "    Type: ${type}"
        log "    Public IP: ${public_ip:-none}"
        log "    Launch Time: ${launch_time}"
    done
fi
echo ""

# Step 4: Check CloudWatch log group
log "${YELLOW}STEP 4: Checking CloudWatch log group...${NC}"
if aws logs describe-log-groups --log-group-name-prefix "$EC2_LOG_GROUP" --region "$REGION" | jq -r ".logGroups[].logGroupName" | grep -q "^${EC2_LOG_GROUP}$"; then
    log "${GREEN}✓ CloudWatch log group exists: $EC2_LOG_GROUP${NC}"
    
    # Check recent log streams
    RECENT_STREAMS=$(aws logs describe-log-streams \
      --log-group-name "$EC2_LOG_GROUP" \
      --order-by LastEventTime \
      --descending \
      --limit 3 \
      --region "$REGION" \
      --query "logStreams[*].[logStreamName,lastEventTime]" \
      --output text 2>/dev/null || echo "")
    
    if [[ -n "$RECENT_STREAMS" ]]; then
        log "  Recent log streams:"
        echo "$RECENT_STREAMS" | while read -r stream_name last_event; do
            if [[ -n "$last_event" ]] && [[ "$last_event" != "None" ]]; then
                last_event_date=$(date -d @$((last_event/1000)) '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "Unknown")
                log "    ${stream_name}: Last event at ${last_event_date}"
            else
                log "    ${stream_name}: No recent events"
            fi
        done
    else
        log "  ${YELLOW}⚠ No log streams found${NC}"
    fi
else
    log "${RED}✗ CloudWatch log group not found: $EC2_LOG_GROUP${NC}"
    log "  ${YELLOW}This will be created when EC2 starts logging${NC}"
fi
echo ""

# Step 5: Trigger Lambda
log "${YELLOW}STEP 5: Triggering Lambda function...${NC}"
PAYLOAD="{\"mode\":\"$MODE\",\"session_id\":\"$SESSION_ID\",\"full_mode\":$FULL_MODE}"
log "  Payload: $PAYLOAD"

INVOKE_START=$(date +%s)
INVOKE_OUTPUT=$(aws lambda invoke \
  --function-name "$LAMBDA_FUNCTION" \
  --invocation-type Event \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  --region "$REGION" \
  /tmp/response.json 2>&1)
INVOKE_STATUS=$?

if [[ $INVOKE_STATUS -eq 0 ]]; then
    log "${GREEN}✓ Lambda invoked successfully${NC}"
    log "  Response: $(cat /tmp/response.json)"
    log "  Status Code: $(cat /tmp/response.json | jq -r .StatusCode 2>/dev/null || echo 'Unknown')"
else
    log "${RED}✗ Lambda invocation failed${NC}"
    log "  Error: $INVOKE_OUTPUT"
    exit 1
fi
echo ""

# Step 6: Wait and check EC2 status
log "${YELLOW}STEP 6: Waiting for EC2 instance to start/update...${NC}"
WAIT_COUNT=0
MAX_WAITS=30  # 30 seconds

while [[ $WAIT_COUNT -lt $MAX_WAITS ]]; do
    sleep 1
    WAIT_COUNT=$((WAIT_COUNT + 1))
    
    # Check instance status
    INSTANCE_INFO=$(aws ec2 describe-instances \
      --filters "Name=tag:Name,Values=tokyo-real-estate-scraper" \
                "Name=instance-state-name,Values=running,pending" \
      --region "$REGION" \
      --query "Reservations[0].Instances[0]" \
      --output json 2>/dev/null)
    
    if [[ -n "$INSTANCE_INFO" ]] && [[ "$INSTANCE_INFO" != "null" ]]; then
        INSTANCE_ID=$(echo "$INSTANCE_INFO" | jq -r .InstanceId)
        INSTANCE_STATE=$(echo "$INSTANCE_INFO" | jq -r .State.Name)
        
        if [[ "$INSTANCE_STATE" == "running" ]]; then
            log "${GREEN}✓ Instance is running: $INSTANCE_ID${NC}"
            break
        else
            log "  Instance $INSTANCE_ID is $INSTANCE_STATE... (attempt $WAIT_COUNT/$MAX_WAITS)"
        fi
    else
        log "  No running/pending instance found yet... (attempt $WAIT_COUNT/$MAX_WAITS)"
    fi
done

if [[ -z "$INSTANCE_ID" ]] || [[ "$INSTANCE_ID" == "null" ]]; then
    log "${RED}✗ Failed to find running EC2 instance after $MAX_WAITS seconds${NC}"
    exit 1
fi
echo ""

# Step 7: Check SSM agent status
log "${YELLOW}STEP 7: Checking SSM agent on EC2 instance...${NC}"
SSM_CHECK_COUNT=0
SSM_MAX_CHECKS=20

while [[ $SSM_CHECK_COUNT -lt $SSM_MAX_CHECKS ]]; do
    SSM_INFO=$(aws ssm describe-instance-information \
      --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
      --region "$REGION" \
      --output json 2>/dev/null)
    
    if [[ -n "$SSM_INFO" ]] && [[ $(echo "$SSM_INFO" | jq '.InstanceInformationList | length') -gt 0 ]]; then
        PING_STATUS=$(echo "$SSM_INFO" | jq -r .InstanceInformationList[0].PingStatus)
        LAST_PING=$(echo "$SSM_INFO" | jq -r .InstanceInformationList[0].LastPingDateTime)
        AGENT_VERSION=$(echo "$SSM_INFO" | jq -r .InstanceInformationList[0].AgentVersion)
        
        log "${GREEN}✓ SSM agent is online${NC}"
        log "  Ping Status: $PING_STATUS"
        log "  Agent Version: $AGENT_VERSION"
        log "  Last Ping: $LAST_PING"
        break
    else
        SSM_CHECK_COUNT=$((SSM_CHECK_COUNT + 1))
        log "  SSM agent not ready yet... (attempt $SSM_CHECK_COUNT/$SSM_MAX_CHECKS)"
        sleep 1
    fi
done

if [[ $SSM_CHECK_COUNT -eq $SSM_MAX_CHECKS ]]; then
    log "${RED}✗ SSM agent not responding after $SSM_MAX_CHECKS attempts${NC}"
fi
echo ""

# Step 8: Check CloudWatch agent
log "${YELLOW}STEP 8: Checking CloudWatch agent on EC2 instance...${NC}"
CW_AGENT_CHECK=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -m ec2 -a status"]' \
  --region "$REGION" \
  --output json 2>/dev/null)

if [[ -n "$CW_AGENT_CHECK" ]]; then
    COMMAND_ID=$(echo "$CW_AGENT_CHECK" | jq -r .Command.CommandId)
    log "  Checking CloudWatch agent status (Command ID: $COMMAND_ID)..."
    
    sleep 3
    
    CW_STATUS=$(aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --output json 2>/dev/null || echo "{}")
    
    CW_OUTPUT=$(echo "$CW_STATUS" | jq -r .StandardOutputContent 2>/dev/null || echo "")
    if [[ -n "$CW_OUTPUT" ]]; then
        if echo "$CW_OUTPUT" | grep -q "running"; then
            log "${GREEN}✓ CloudWatch agent is running${NC}"
        else
            log "${YELLOW}⚠ CloudWatch agent status:${NC}"
        fi
        echo "$CW_OUTPUT" | sed 's/^/    /'
    else
        log "${YELLOW}⚠ Could not determine CloudWatch agent status${NC}"
    fi
else
    log "${RED}✗ Failed to check CloudWatch agent status${NC}"
fi
echo ""

# Step 9: Check if scraper script exists
log "${YELLOW}STEP 9: Checking if scraper script exists on EC2...${NC}"
SCRIPT_CHECK=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["ls -la /home/ubuntu/scrape.py"]' \
  --region "$REGION" \
  --output json 2>/dev/null)

if [[ -n "$SCRIPT_CHECK" ]]; then
    COMMAND_ID=$(echo "$SCRIPT_CHECK" | jq -r .Command.CommandId)
    sleep 2
    
    SCRIPT_STATUS=$(aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --output json 2>/dev/null || echo "{}")
    
    SCRIPT_OUTPUT=$(echo "$SCRIPT_STATUS" | jq -r .StandardOutputContent 2>/dev/null || echo "")
    if [[ -n "$SCRIPT_OUTPUT" ]] && [[ ! "$SCRIPT_OUTPUT" =~ "No such file" ]]; then
        log "${GREEN}✓ Scraper script exists${NC}"
        log "  $SCRIPT_OUTPUT"
    else
        log "${RED}✗ Scraper script not found at /home/ubuntu/scrape.py${NC}"
    fi
else
    log "${RED}✗ Failed to check for scraper script${NC}"
fi
echo ""

# Step 10: Check running processes
log "${YELLOW}STEP 10: Checking if scraper is running...${NC}"
PROCESS_CHECK=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["ps aux | grep -E \"python.*scrape.py|SESSION_ID\" | grep -v grep"]' \
  --region "$REGION" \
  --output json 2>/dev/null)

if [[ -n "$PROCESS_CHECK" ]]; then
    COMMAND_ID=$(echo "$PROCESS_CHECK" | jq -r .Command.CommandId)
    sleep 2
    
    PROCESS_STATUS=$(aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --output json 2>/dev/null || echo "{}")
    
    PROCESS_OUTPUT=$(echo "$PROCESS_STATUS" | jq -r .StandardOutputContent 2>/dev/null || echo "")
    if [[ -n "$PROCESS_OUTPUT" ]]; then
        log "${GREEN}✓ Found running processes:${NC}"
        echo "$PROCESS_OUTPUT" | sed 's/^/    /'
    else
        log "${YELLOW}⚠ No scraper process found (might not have started yet)${NC}"
    fi
fi
echo ""

# Step 11: Start tailing logs
log "${YELLOW}STEP 11: Starting log tail...${NC}"
log "  Log Group: ${BLUE}$EC2_LOG_GROUP${NC}"
log "  Instance: ${BLUE}$INSTANCE_ID${NC}"
log "  Session: ${BLUE}$SESSION_ID${NC}"
echo ""

log "${GREEN}${SEPARATOR}${NC}"
log "${GREEN}📊 STREAMING EC2 LOGS - Press Ctrl+C to stop${NC}"
log "${GREEN}${SEPARATOR}${NC}"
echo ""

# Check if log group exists before tailing
if aws logs describe-log-groups --log-group-name-prefix "$EC2_LOG_GROUP" --region "$REGION" | jq -r ".logGroups[].logGroupName" | grep -q "^${EC2_LOG_GROUP}$"; then
    # Tail logs
    aws logs tail "$EC2_LOG_GROUP" \
      --follow \
      --format short \
      --region "$REGION" \
      --since 2m | while read -r line; do
        # Extract just the message if it's JSON
        if [[ "$line" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[[:space:]]\{ ]]; then
            timestamp=$(echo "$line" | cut -d' ' -f1)
            json=$(echo "$line" | cut -d' ' -f2-)
            message=$(echo "$json" | jq -r .message 2>/dev/null || echo "$line")
            echo "$timestamp $message"
        else
            echo "$line"
        fi
    done
else
    log "${RED}✗ Log group $EC2_LOG_GROUP still doesn't exist${NC}"
    log "${YELLOW}Waiting for CloudWatch agent to create it...${NC}"
    
    # Wait for log group to be created
    WAIT_FOR_LOGS=0
    while [[ $WAIT_FOR_LOGS -lt 60 ]]; do
        if aws logs describe-log-groups --log-group-name-prefix "$EC2_LOG_GROUP" --region "$REGION" | jq -r ".logGroups[].logGroupName" | grep -q "^${EC2_LOG_GROUP}$"; then
            log "${GREEN}✓ Log group created!${NC}"
            aws logs tail "$EC2_LOG_GROUP" \
              --follow \
              --format short \
              --region "$REGION" \
              --since 2m
            break
        else
            WAIT_FOR_LOGS=$((WAIT_FOR_LOGS + 1))
            log "  Still waiting for log group... ($WAIT_FOR_LOGS/60)"
            sleep 1
        fi
    done
    
    if [[ $WAIT_FOR_LOGS -eq 60 ]]; then
        log "${RED}✗ Log group never appeared. Check CloudWatch agent configuration.${NC}"
        exit 1
    fi
fi