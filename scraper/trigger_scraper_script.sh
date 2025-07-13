#!/bin/bash

# Dead simple Lambda + EC2 log monitor
# Usage: ./monitor.sh [mode] [session_id]

MODE=${1:-testing}
SESSION_ID=${2:-manual-$(date +%s)}
LAMBDA_FUNCTION="trigger-scraper"

echo "🚀 TRIGGERING LAMBDA: $LAMBDA_FUNCTION"
echo "Mode: $MODE | Session: $SESSION_ID"

# Trigger Lambda
PAYLOAD="{\"mode\": \"$MODE\", \"session_id\": \"$SESSION_ID\"}"
aws lambda invoke --function-name "$LAMBDA_FUNCTION" --payload "$PAYLOAD" /tmp/response.json
echo "Lambda triggered. Response:"
cat /tmp/response.json
echo ""

# Get instance ID
INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name scraper-compute-stack --query "Stacks[0].Outputs[?OutputKey=='ScraperInstanceId'].OutputValue" --output text 2>/dev/null)
echo "Instance ID: $INSTANCE_ID"

# Start monitoring
START_TIME=$(($(date +%s) * 1000))
LAST_LAMBDA_COUNT=0
LAST_EC2_COUNT=0
NO_NEW_LOGS_COUNT=0

echo ""
echo "=== MONITORING LOGS ==="

while true; do
    echo "[$(date +'%H:%M:%S')] Checking logs..."
    
    # Check Lambda logs
    LAMBDA_LOGS=$(aws logs filter-log-events \
        --log-group-name "/aws/lambda/trigger-scraper" \
        --start-time $START_TIME \
        --query 'events[*].message' \
        --output text 2>/dev/null || echo "")
    
    LAMBDA_COUNT=$(echo "$LAMBDA_LOGS" | wc -l)
    
    if [[ $LAMBDA_COUNT -gt $LAST_LAMBDA_COUNT ]]; then
        echo "NEW LAMBDA LOGS:"
        echo "$LAMBDA_LOGS" | tail -n +$((LAST_LAMBDA_COUNT + 1))
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
                echo "NEW EC2 LOGS:"
                echo "$EC2_LOGS" | tail -n +$((LAST_EC2_COUNT + 1))
                LAST_EC2_COUNT=$EC2_COUNT
                NO_NEW_LOGS_COUNT=0
            fi
        fi
    fi
    
    # Exit if no new logs for 20 seconds (4 checks * 5 second intervals)
    if [[ $LAMBDA_COUNT -eq $LAST_LAMBDA_COUNT ]] && [[ $EC2_COUNT -eq $LAST_EC2_COUNT ]]; then
        ((NO_NEW_LOGS_COUNT++))
        if [[ $NO_NEW_LOGS_COUNT -ge 20 ]]; then
            echo "No new logs for 100 seconds. Exiting."
            break
        fi
    fi
    
    sleep 5
done

echo ""
echo "=== FINAL CHECK ==="
echo "S3 Results:"
aws s3 ls s3://tokyo-real-estate-ai-data/scraper-output/ --recursive | tail -5 2>/dev/null || echo "No S3 results"

echo "Done."