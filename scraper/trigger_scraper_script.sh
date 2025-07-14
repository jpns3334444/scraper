#!/bin/bash

# Dead simple Lambda + EC2 log monitor with color-coded output
# Usage: ./monitor.sh [mode] [session_id]

# Color definitions
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

MODE=${1:-testing}
SESSION_ID=${2:-manual-$(date +%s)}
LAMBDA_FUNCTION="trigger-scraper"

echo -e "${GREEN}🚀 TRIGGERING LAMBDA: $LAMBDA_FUNCTION${NC}"
echo -e "${YELLOW}Mode: $MODE | Session: $SESSION_ID${NC}"

# Trigger Lambda
PAYLOAD='{"mode": "'$MODE'", "session_id": "'$SESSION_ID'"}'
aws lambda invoke --function-name "$LAMBDA_FUNCTION" --payload "$PAYLOAD" --cli-binary-format raw-in-base64-out /tmp/response.json
echo -e "${GREEN}Lambda triggered. Response:${NC}"
cat /tmp/response.json
echo ""

# Get instance ID
INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name scraper-compute-stack --query "Stacks[0].Outputs[?OutputKey=='ScraperInstanceId'].OutputValue" --output text 2>/dev/null)
echo -e "${YELLOW}Instance ID: $INSTANCE_ID${NC}"

# Start monitoring
START_TIME=$(($(date +%s) * 1000))
LAST_LAMBDA_COUNT=0
LAST_EC2_COUNT=0
NO_NEW_LOGS_COUNT=0

echo ""
echo -e "${GREEN}=== MONITORING LOGS ===${NC}"

while true; do
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] Checking logs...${NC}"
    
    # Check Lambda logs
    LAMBDA_LOGS=$(aws logs filter-log-events \
        --log-group-name "/aws/lambda/trigger-scraper" \
        --start-time $START_TIME \
        --query 'events[*].message' \
        --output text 2>/dev/null || echo "")
    
    LAMBDA_COUNT=$(echo "$LAMBDA_LOGS" | wc -l)
    
    if [[ $LAMBDA_COUNT -gt $LAST_LAMBDA_COUNT ]]; then
        echo -e "${BLUE}🔷 === LAMBDA LOGS ===${NC}"
        echo "$LAMBDA_LOGS" | tail -n +$((LAST_LAMBDA_COUNT + 1)) | sed "s/^/  ${BLUE}LAMBDA:${NC} /"
        echo -e "${BLUE}🔷 === END LAMBDA ===${NC}"
        LAST_LAMBDA_COUNT=$LAMBDA_COUNT
        NO_NEW_LOGS_COUNT=0
    fi
    
    # Check EC2 logs if we have instance
    if [[ -n "$INSTANCE_ID" ]]; then
        COMMAND_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters 'commands=["tail -20 /var/log/scraper/run.log 2>/dev/null || echo NO_LOGS"]' \
            --query 'Command.CommandId' \
            --output text 2>/dev/null)
        
        if [[ -n "$COMMAND_ID" ]]; then
            sleep 2
            EC2_LOGS=$(aws ssm get-command-invocation \
                --command-id "$COMMAND_ID" \
                --instance-id "$INSTANCE_ID" \
                --query 'StandardOutputContent' \
                --output text 2>/dev/null || echo "NO_LOGS")
            
            EC2_COUNT=$(echo "$EC2_LOGS" | wc -l)
            
            if [[ "$EC2_LOGS" != "NO_LOGS" && $EC2_COUNT -gt $LAST_EC2_COUNT ]]; then
                echo -e "${ORANGE}🔶 === EC2 LOGS ===${NC}"
                echo "$EC2_LOGS" | tail -n +$((LAST_EC2_COUNT + 1)) | sed "s/^/  ${ORANGE}EC2:${NC} /"
                echo -e "${ORANGE}🔶 === END EC2 ===${NC}"
                LAST_EC2_COUNT=$EC2_COUNT
                NO_NEW_LOGS_COUNT=0
            fi
        fi
    fi
    
    # Exit if no new logs for 20 seconds (4 checks * 5 second intervals)
    if [[ $LAMBDA_COUNT -eq $LAST_LAMBDA_COUNT ]] && [[ $EC2_COUNT -eq $LAST_EC2_COUNT ]]; then
        ((NO_NEW_LOGS_COUNT++))
        if [[ $NO_NEW_LOGS_COUNT -ge 20 ]]; then
            echo -e "${YELLOW}No new logs for 100 seconds. Exiting.${NC}"
            break
        fi
    fi
    
    sleep 5
done

echo ""
echo -e "${GREEN}=== FINAL CHECK ===${NC}"
echo -e "${YELLOW}S3 Results:${NC}"
aws s3 ls s3://tokyo-real-estate-ai-data/scraper-output/ --recursive | tail -5 2>/dev/null || echo "No S3 results"

echo -e "${GREEN}Done.${NC}"