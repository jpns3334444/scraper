# Scraper Project Context & Testing Workflow

## Project Overview

I'm working on a web scraper project that targets homes.co.jp (Japanese real estate website). The project consists of:

### 1. **scrape.py** - Python HTTP-based scraper using requests/BeautifulSoup that:
- Scrapes property listings from homes.co.jp/mansion/chuko/tokyo/chofu-city/list
- Uses session management and realistic browser headers to avoid detection
- Extracts property details (title, price, specifications) from individual listing pages
- Uses threading for parallel processing (2 threads max)
- Saves results to CSV and uploads to S3
- Implements structured JSON logging

### 2. **scraper-stack.yaml** - AWS CloudFormation template that creates:
- EC2 instance (t3.small, Ubuntu 22.04) with scraper code
- IAM roles with permissions for S3, CloudWatch, Secrets Manager
- S3 bucket for storing scraped data
- Lambda function for triggering scraper via SSM
- EventBridge rule for daily scheduled runs (2 AM JST)
- SNS notifications for job status
- CloudWatch logging integration

### 3. **deploy.sh** - Deployment script that:
- Retrieves GitHub token from AWS Secrets Manager
- Validates CloudFormation template
- Handles stack creation/updates with change sets
- Streams deployment events in real-time
- Manages IP whitelisting for SSH access

### 4. **ssm-scraper.sh** - Utility script for SSM session management to EC2 instance

## Current Status
The project is functional but needs improvements for production use. See the improvement priorities below.

## Testing Workflow

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

### Testing Checklist

#### ✅ Quick Development Cycle (2-3 minutes)
- [ ] Local testing passes (15 seconds)
- [ ] Lambda trigger works (30 seconds)
- [ ] Scraper completes successfully (1-2 minutes)
- [ ] Output appears in S3

#### ✅ Full Integration Testing (5-10 minutes)
- [ ] CloudFormation stack healthy
- [ ] EC2 instance running and accessible
- [ ] GitHub token retrieval from Secrets Manager works
- [ ] Lambda function executes without errors
- [ ] SSM commands execute successfully on EC2
- [ ] Scraper runs in production mode (full data set)
- [ ] Data uploads to S3 correctly
- [ ] CloudWatch logging works
- [ ] SNS notifications sent (if configured)

## Improvement Priorities

### High Priority Improvements

#### 2. Code Quality & Maintainability

**scrape.py**
- **Rate Limiting**: Add exponential backoff and better retry logic
- **Error Handling**: Improve exception handling in `extract_property_details:142`
- **Configuration**: Extract hardcoded values to environment variables or config file
- **Logging**: Replace print statements with proper logging framework
- **Data Validation**: Add validation for extracted property data
- **Resource Management**: Ensure proper cleanup of HTTP sessions

**Infrastructure (scraper-stack.yaml)**
- **AMI ID**: Hardcoded Ubuntu AMI (`ami-09013b9396188007c:148`) should be parameterized
- **Instance Type**: Make instance type configurable via parameter
- **Security Groups**: Add egress rules for better security posture
- **Error Handling**: Improve CloudFormation error handling and rollback scenarios

#### 3. Monitoring & Observability
- **CloudWatch Metrics**: Add custom metrics for scraper performance
- **Alerting**: Set up alerts for scraper failures and performance issues
- **Structured Logging**: Implement proper JSON logging format consistently
- **Health Checks**: Add health check endpoints or status reporting

#### 4. Reliability & Resilience
- **Circuit Breaker**: Implement circuit breaker pattern for external API calls
- **Dead Letter Queue**: Add SQS DLQ for failed scraper jobs
- **Graceful Shutdown**: Handle interruption signals properly
- **Data Persistence**: Add backup mechanisms for scraped data

### Medium Priority Improvements

#### 5. Performance Optimization
- **Connection Pooling**: Implement HTTP connection pooling
- **Caching**: Add caching for repeated requests
- **Parallel Processing**: Optimize threading strategy and resource usage
- **Memory Management**: Monitor and optimize memory usage patterns

#### 6. Data Quality
- **Schema Validation**: Define and validate data schemas
- **Data Deduplication**: Implement duplicate detection and removal
- **Data Enrichment**: Add data quality checks and enrichment
- **Export Formats**: Support multiple export formats (JSON, Parquet, etc.)

## Files Requiring Changes

### Critical Changes
- `deploy.sh` - Remove hardcoded GitHub token ✅ **COMPLETED**
- `scrape.py` - Improve error handling and logging
- `scraper-stack.yaml` - Parameterize AMI ID and improve security

### Recommended Changes
- Add `requirements.txt` for Python dependencies
- Add `config.yaml` for scraper configuration
- Add `tests/` directory for test files
- Add `.gitignore` to exclude sensitive files

## Security Recommendations
- Use AWS Secrets Manager for sensitive configuration ✅ **IMPLEMENTED**
- Implement least privilege IAM policies
- Add VPC endpoint for S3 access
- Enable CloudTrail logging for audit trails
- Use encrypted S3 buckets for data storage

## Environment Variables for Testing
```bash
export REGION="ap-northeast-1"
export STACK_NAME="scraper-stack"
export BUCKET_NAME="lifull-scrape-tokyo"
export INSTANCE_TAG="MarketScraper"
```

## Quick Status Check Command
```bash
aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].StackStatus" --output text && \
aws ec2 describe-instances --filters "Name=tag:Name,Values=$INSTANCE_TAG" --query "Reservations[0].Instances[0].State.Name" --output text && \
aws s3 ls s3://$BUCKET_NAME/scraper-output/ | tail -1
```

This comprehensive context ensures efficient development sessions with proper testing workflow and clear improvement priorities.