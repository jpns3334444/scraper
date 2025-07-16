# AI Real Estate Analysis - Operations Runbook

## Daily Operations

### Normal Operation Flow

The system runs automatically every day at 03:00 JST (18:00 UTC) with the following expected timeline:

```
03:00 JST - EventBridge triggers Step Functions
03:01 JST - ETL processing begins (2-3 minutes)
03:04 JST - Prompt building begins (3-5 minutes)
03:09 JST - OpenAI Batch job created
03:09-04:00 JST - Batch processing (varies: 10-50 minutes)
04:00 JST - Report generation and delivery (1-2 minutes)
04:02 JST - Slack and email notifications sent
```

### Success Indicators

1. **Slack notification received** with property analysis
2. **Email report delivered** to configured address
3. **S3 objects created**:
   - `clean/YYYY-MM-DD/listings.jsonl`
   - `prompts/YYYY-MM-DD/payload.json`
   - `batch_output/YYYY-MM-DD/response.json`
   - `reports/YYYY-MM-DD/report.md`

### Quick Health Check

```bash
# Check latest execution
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:STACK-ai-analysis \
  --max-items 1

# Check S3 for today's data
aws s3 ls s3://tokyo-real-estate-ai-data/reports/$(date +%Y-%m-%d)/

# Check CloudWatch logs for errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/STACK-etl \
  --start-time $(date -d "today" +%s)000
```

## Troubleshooting Guide

### 1. Step Functions Execution Failed

#### Symptoms
- No Slack/email notification received
- Step Functions console shows "FAILED" status

#### Diagnosis Steps
```bash
# Get latest execution details
aws stepfunctions list-executions \
  --state-machine-arn STATE_MACHINE_ARN \
  --status-filter FAILED \
  --max-items 5

# Get execution history
aws stepfunctions get-execution-history \
  --execution-arn EXECUTION_ARN
```

#### Common Causes & Solutions

**ETL Step Failed**
- **Cause**: CSV file missing or malformed
- **Check**: `aws s3 ls s3://tokyo-real-estate-ai-data/raw/$(date +%Y-%m-%d)/`
- **Solution**: Verify scraper infrastructure is running

**Prompt Builder Failed**
- **Cause**: JSONL file empty or S3 permissions issue
- **Check**: CloudWatch logs for specific error
- **Solution**: Review IAM permissions, check S3 bucket policy

**LLM Batch Failed**
- **Cause**: OpenAI API issues, rate limits, or invalid API key
- **Check**: OpenAI API status, verify SSM parameter
- **Solution**: Update API key, check OpenAI account limits

**Report Sender Failed**
- **Cause**: Slack webhook invalid, SES configuration issue
- **Check**: Test webhook URL, verify SES sender email
- **Solution**: Update webhook URL, configure SES identity

### 2. No Properties Found

#### Symptoms
- Report says "No top picks found, report skipped"
- Empty analysis results

#### Diagnosis
```bash
# Check raw data volume
aws s3 ls s3://tokyo-real-estate-ai-data/raw/$(date +%Y-%m-%d)/ --human-readable

# Check processed JSONL
aws s3 cp s3://tokyo-real-estate-ai-data/clean/$(date +%Y-%m-%d)/listings.jsonl - | wc -l
```

#### Solutions
- **Low listing count**: Normal market variation, monitor trend
- **Data quality issues**: Check CSV format, validate scraper
- **Filtering too strict**: Adjust ranking criteria in prompt

### 3. OpenAI Batch Job Stuck

#### Symptoms
- Step Functions execution running for >2 hours
- LLM Batch Lambda timeout

#### Diagnosis
```bash
# Check OpenAI batch status
curl -H "Authorization: Bearer $OPENAI_API_KEY" \
  https://api.openai.com/v1/batches/$BATCH_ID
```

#### Solutions
```bash
# Cancel stuck batch
curl -X POST -H "Authorization: Bearer $OPENAI_API_KEY" \
  https://api.openai.com/v1/batches/$BATCH_ID/cancel

# Manually restart Step Functions
aws stepfunctions start-execution \
  --state-machine-arn STATE_MACHINE_ARN \
  --input '{"date":"2025-07-07"}'
```

### 4. High OpenAI Costs

#### Symptoms
- Cost alerts triggered
- Unexpected token usage

#### Investigation
```bash
# Check daily metrics
aws cloudwatch get-metric-statistics \
  --namespace AI-RealEstate/Costs \
  --metric-name DailyOpenAICost \
  --start-time $(date -d "7 days ago" --iso-8601) \
  --end-time $(date --iso-8601) \
  --period 86400 \
  --statistics Average,Maximum
```

#### Cost Optimization Actions
1. **Reduce listing count**:
   ```python
   # In prompt_builder/app.py
   return sorted_listings[:50]  # Reduce from 100 to 50
   ```

2. **Limit photos per listing**:
   ```python
   # In prompt_builder/app.py
   interior_photos = listing.get('interior_photos', [])[:10]  # Reduce from 20 to 10
   ```

3. **Adjust analysis frequency**:
   ```yaml
   # In ai-stack.yaml
   ScheduleExpression: 'cron(0 18 * * 1,3,5 *)'  # Mon, Wed, Fri only
   ```

## Manual Operations

### Manual Execution

To run analysis for a specific date:

```bash
# Start execution with custom date
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:STACK-ai-analysis \
  --name manual-$(date +%Y%m%d-%H%M%S) \
  --input '{"date":"2025-07-07"}'
```

### Reprocess Failed Day

```bash
# Check if source data exists
aws s3 ls s3://tokyo-real-estate-ai-data/raw/2025-07-07/

# Clean up partial results
aws s3 rm s3://tokyo-real-estate-ai-data/clean/2025-07-07/ --recursive
aws s3 rm s3://tokyo-real-estate-ai-data/prompts/2025-07-07/ --recursive
aws s3 rm s3://tokyo-real-estate-ai-data/batch_output/2025-07-07/ --recursive
aws s3 rm s3://tokyo-real-estate-ai-data/reports/2025-07-07/ --recursive

# Restart execution
aws stepfunctions start-execution \
  --state-machine-arn STATE_MACHINE_ARN \
  --name reprocess-20250707 \
  --input '{"date":"2025-07-07"}'
```

### Test Individual Components

```bash
# Test ETL Lambda
aws lambda invoke \
  --function-name STACK-etl \
  --payload '{"date":"2025-07-07"}' \
  response.json

# Test Prompt Builder
aws lambda invoke \
  --function-name STACK-prompt-builder \
  --payload '{"date":"2025-07-07","bucket":"tokyo-real-estate-ai-data","jsonl_key":"clean/2025-07-07/listings.jsonl"}' \
  response.json

# Test Report Sender (with mock data)
aws lambda invoke \
  --function-name STACK-report-sender \
  --payload '{"date":"2025-07-07","batch_result":{"top_picks":[],"runners_up":[],"market_notes":""}}' \
  response.json
```

## Configuration Management

### Environment Variables

Update Lambda environment variables:

```bash
# Update bucket name
aws lambda update-function-configuration \
  --function-name STACK-etl \
  --environment Variables='{OUTPUT_BUCKET=new-bucket-name}'

# Update email addresses
aws lambda update-function-configuration \
  --function-name STACK-report-sender \
  --environment Variables='{EMAIL_FROM=new-from@example.com,EMAIL_TO=new-to@example.com}'
```

### SSM Parameters

Update stored secrets:

```bash
# Update OpenAI API key
aws ssm put-parameter \
  --name "/ai-scraper/STACK-NAME/openai-api-key" \
  --value "new-api-key" \
  --type SecureString \
  --overwrite

# Update Slack webhook
aws ssm put-parameter \
  --name "/ai-scraper/STACK-NAME/slack-hook-url" \
  --value "https://hooks.slack.com/new-webhook" \
  --type SecureString \
  --overwrite
```

### Ranking Logic Adjustments

To modify property selection criteria, update the system prompt in `lambda/prompt_builder/app.py`:

```python
SYSTEM_PROMPT = """You are an aggressive Tokyo condo investor.
Goal: pick the FIVE best bargains in this feed.

Rank strictly by:
- lowest price_per_m2 versus 3-year ward median (WEIGHT: 40%)
- structural / cosmetic risks visible in PHOTOS (WEIGHT: 30%)
- walking minutes to nearest station (WEIGHT: 20%)
- south or southeast exposure, open view, balcony usability (WEIGHT: 10%)

Focus on:
- Properties under ¥400,000/m²
- Age < 25 years
- Walk time < 15 minutes
- No visible structural issues

Return JSON only: {...}
"""
```

## Monitoring & Alerting

### Key Metrics to Monitor

1. **Step Functions Execution Success Rate**
   - Target: >95%
   - Alert if <90% over 7 days

2. **Daily Cost**
   - Target: <$2.00/day
   - Alert if >$3.00/day

3. **Listings Processed**
   - Expected: 50-200/day
   - Alert if <10 or >500/day

4. **Report Delivery Success**
   - Target: 100%
   - Alert on any failure

### Custom CloudWatch Dashboards

Create monitoring dashboard:

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/States", "ExecutionsFailed", "StateMachineName", "STACK-ai-analysis"],
          ["AWS/States", "ExecutionsSucceeded", "StateMachineName", "STACK-ai-analysis"]
        ],
        "period": 86400,
        "stat": "Sum",
        "region": "us-east-1",
        "title": "Daily Executions"
      }
    }
  ]
}
```

## Rollback Procedures

### Code Rollback

```bash
# Rollback to previous Lambda version
aws lambda update-function-code \
  --function-name STACK-etl \
  --image-uri ACCOUNT.dkr.ecr.REGION.amazonaws.com/ai-scraper-etl:previous-tag

# Rollback CloudFormation stack
aws cloudformation update-stack \
  --stack-name STACK-NAME \
  --template-url https://s3.amazonaws.com/templates/previous-version.yaml
```

### Emergency Disable

```bash
# Disable EventBridge rule
aws events disable-rule --name STACK-daily-analysis

# Or delete the rule entirely
aws events delete-rule --name STACK-daily-analysis
```

## Performance Optimization

### Lambda Performance Tuning

1. **Memory allocation**:
   ```bash
   # Increase memory for faster processing
   aws lambda update-function-configuration \
     --function-name STACK-llm-batch \
     --memory-size 1536
   ```

2. **Timeout adjustment**:
   ```bash
   # Increase timeout for batch processing
   aws lambda update-function-configuration \
     --function-name STACK-llm-batch \
     --timeout 3600
   ```

### OpenAI Batch Optimization

1. **Request batching**: Group multiple requests in single batch job
2. **Parallel processing**: Use multiple smaller batches instead of one large batch
3. **Result caching**: Cache frequently requested analysis results

## Disaster Recovery

### Data Backup
- S3 versioning enabled on tokyo-real-estate-ai-data bucket
- Cross-region replication recommended for critical data
- CloudFormation templates stored in version control

### Recovery Procedures
1. **Complete system rebuild**: Deploy from CloudFormation template
2. **Data recovery**: Restore from S3 versioned objects
3. **Configuration restore**: Import from backed-up SSM parameters

### Testing Recovery
```bash
# Test deployment in different region
aws cloudformation create-stack \
  --stack-name test-recovery-stack \
  --template-body file://infra/ai-stack.yaml \
  --region us-west-2
```