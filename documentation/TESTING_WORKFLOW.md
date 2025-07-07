# Testing Workflow for Scraper Development

## Complete Testing Sequence

Use this testing workflow when making changes to the scraper. Copy this as part of your prompt to LLMs working on improvements.

### Phase 1: Local Development Testing (15 seconds)
```bash
# Test locally with limited data (5 listings only)
python3 scrape.py
```
**Expected Output:**
- 🧪 LOCAL TESTING MODE indicators
- Processes only 5 listings from 1 page
- Skips S3 upload
- Completes in ~15 seconds

### Phase 2: Infrastructure Testing (2-5 minutes)

#### Step 1: Deploy/Update Infrastructure
```bash
# Deploy or update CloudFormation stack
./deploy.sh
```

#### Step 2: Test Lambda Trigger Function
```bash
# Get Lambda function name
LAMBDA_FUNCTION=$(aws lambda list-functions --query "Functions[?FunctionName=='trigger-scraper'].FunctionName" --output text)

# Test Lambda function manually
aws lambda invoke \
  --function-name $LAMBDA_FUNCTION \
  --payload '{}' \
  /tmp/lambda-response.json

# Check response
cat /tmp/lambda-response.json
```

**Expected Lambda Response:**
```json
{
  "statusCode": 200,
  "body": "{\"command_id\": \"abc123...\", \"status\": \"Success\", \"duration\": 120.5}"
}
```

#### Step 3: Verify Scraper Execution
```bash
# Check latest SSM command execution
aws ssm list-command-invocations \
  --max-items 1 \
  --query "CommandInvocations[0].[CommandId,Status,StandardOutputContent]" \
  --output table

# Check S3 for output files
aws s3 ls s3://lifull-scrape-tokyo/scraper-output/ --recursive

# Check CloudWatch logs
aws logs describe-log-streams \
  --log-group-name scraper-logs \
  --order-by LastEventTime \
  --descending \
  --max-items 1
```

### Phase 3: Scheduler Testing (Optional)

#### Test EventBridge Schedule
```bash
# Check scheduled rule
aws events list-rules --name-prefix "trigger-scraper"

# Manually trigger the scheduled event (for immediate testing)
aws events put-events \
  --entries '[{
    "Source": "manual.test",
    "DetailType": "Test Scheduler",
    "Detail": "{}",
    "Resources": ["arn:aws:events:ap-northeast-1:ACCOUNT:rule/trigger-scraper-rule"]
  }]'
```

#### Verify Schedule Configuration
```bash
# Check current schedule (should be daily at 2 AM JST = 17:00 UTC)
aws events describe-rule --name trigger-scraper-rule \
  --query "ScheduleExpression" \
  --output text
```

### Phase 4: End-to-End Validation

#### Check Complete Pipeline
```bash
# 1. Verify all components
echo "=== INFRASTRUCTURE STATUS ==="
aws cloudformation describe-stacks \
  --stack-name scraper-stack \
  --query "Stacks[0].StackStatus" \
  --output text

# 2. Check EC2 instance
echo "=== EC2 STATUS ==="
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=MarketScraper" \
  --query "Reservations[0].Instances[0].State.Name" \
  --output text

# 3. Verify latest scraper run
echo "=== LATEST SCRAPER OUTPUT ==="
aws s3 ls s3://lifull-scrape-tokyo/scraper-output/ --recursive | tail -1

# 4. Check notifications (if enabled)
echo "=== SNS TOPIC ==="
aws sns list-subscriptions-by-topic \
  --topic-arn $(aws sns list-topics --query "Topics[?contains(TopicArn, 'scraper-notifications')].TopicArn" --output text)
```

## Testing Checklist

### ✅ Quick Development Cycle (2-3 minutes)
- [ ] Local testing passes (15 seconds)
- [ ] Lambda trigger works (30 seconds)
- [ ] Scraper completes successfully (1-2 minutes)
- [ ] Output appears in S3

### ✅ Full Integration Testing (5-10 minutes)
- [ ] CloudFormation stack healthy
- [ ] EC2 instance running and accessible
- [ ] GitHub token retrieval from Secrets Manager works
- [ ] Lambda function executes without errors
- [ ] SSM commands execute successfully on EC2
- [ ] Scraper runs in production mode (full data set)
- [ ] Data uploads to S3 correctly
- [ ] CloudWatch logging works
- [ ] SNS notifications sent (if configured)

### ✅ Scheduler Testing (Optional)
- [ ] EventBridge rule configured correctly
- [ ] Schedule expression is correct (cron(0 17 * * ? *))
- [ ] Manual trigger test works
- [ ] Scheduled execution works (wait for next scheduled time or modify schedule temporarily)

## Troubleshooting Common Issues

### Local Testing Fails
```bash
# Check Python dependencies
python3 -c "import pandas, requests, boto3, bs4; print('All dependencies OK')"

# Check internet connectivity
curl -I https://www.homes.co.jp
```

### Lambda Trigger Fails
```bash
# Check Lambda logs
aws logs filter-log-events \
  --log-group-name /aws/lambda/trigger-scraper \
  --start-time $(date -d '10 minutes ago' +%s)000

# Check Lambda permissions
aws lambda get-policy --function-name trigger-scraper
```

### SSM Command Fails
```bash
# Check SSM agent status
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=i-0cef6a939c97eb546"

# Check recent command failures
aws ssm list-command-invocations \
  --filter "key=Status,value=Failed" \
  --max-items 5
```

### S3 Upload Fails
```bash
# Check S3 bucket permissions
aws s3api get-bucket-policy --bucket lifull-scrape-tokyo

# Check EC2 IAM role permissions
aws iam list-attached-role-policies --role-name ScraperRole
```

## Time Estimates

| Testing Phase | Duration | Purpose |
|---------------|----------|---------|
| Local Testing | 15 seconds | Syntax/logic validation |
| Lambda Trigger | 30 seconds | Function integration test |
| Production Run | 2-5 minutes | Full system validation |
| Infrastructure Deploy | 8-12 minutes | Complete stack updates |
| Scheduler Test | Variable | Schedule validation |

## Testing Commands Reference

```bash
# Copy these environment variables for testing
export REGION="ap-northeast-1"
export STACK_NAME="scraper-stack"
export BUCKET_NAME="lifull-scrape-tokyo"
export INSTANCE_TAG="MarketScraper"

# Quick status check
aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].StackStatus" --output text && \
aws ec2 describe-instances --filters "Name=tag:Name,Values=$INSTANCE_TAG" --query "Reservations[0].Instances[0].State.Name" --output text && \
aws s3 ls s3://$BUCKET_NAME/scraper-output/ | tail -1
```

This workflow ensures thorough testing while minimizing development time. Use local testing for rapid iteration, Lambda testing for integration validation, and scheduler testing for production readiness.