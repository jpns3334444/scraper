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

## 🏗️ **MODULAR ARCHITECTURE (NEW - Dec 2024)**

The project now uses a **4-stack modular architecture** for efficient testing and deployment:

### **Stack 1: S3 Bucket Stack** (`s3-bucket-stack.yaml`)
- **Purpose**: Persistent data storage
- **Contents**: S3 bucket with versioning
- **Deploy frequency**: Once (rarely changes)
- **Command**: `aws cloudformation create-stack --stack-name s3-bucket-stack --template-body file://s3-bucket-stack.yaml`

### **Stack 2: Infrastructure Stack** (`infra-stack.yaml`)  
- **Purpose**: Core infrastructure that rarely changes
- **Contents**: IAM roles, security groups, SNS topics
- **Deploy frequency**: Rarely (only when permissions change)
- **Exports**: Role ARNs, Security Group IDs for other stacks
- **Command**: `aws cloudformation deploy --stack-name scraper-infra-stack --template-file infra-stack.yaml`

### **Stack 3: Compute Stack** (`compute-stack.yaml`) ⚡
- **Purpose**: EC2 instance only - **FREQUENTLY RECREATED FOR TESTING**
- **Contents**: Single EC2 instance with UserData script for GitHub clone
- **Deploy frequency**: **Every code change** (2-3 minutes)
- **GitHub Integration**: Clones from `master` branch with token from Secrets Manager
- **Command**: `./deploy-compute.sh --recreate` (fast testing)

### **Stack 4: Automation Stack** (`automation-stack.yaml`)
- **Purpose**: Scheduling and triggering logic
- **Contents**: Lambda function + EventBridge rule
- **Deploy frequency**: Only when Lambda logic changes
- **Features**: Dynamically finds EC2 instances by "MarketScraper" tag (no hardcoded IDs)

## 🚀 **DEPLOYMENT SCRIPTS**

### **deploy-all.sh** - Deploy complete architecture
```bash
./deploy-all.sh  # Deploys all 4 stacks in sequence
```

### **deploy-compute.sh** - Fast testing workflow ⚡
```bash
./deploy-compute.sh --recreate  # Delete + recreate EC2 in ~3 minutes
```

### **Legacy Scripts (Deprecated)**
- ~~`deploy.sh`~~ - Old monolithic deployment (use deploy-all.sh instead)
- ~~`scraper-stack.yaml`~~ - Old monolithic template (replaced by 4 separate stacks)

## 🎯 **CURRENT STATUS (WORKING)**
✅ **GitHub Integration Fixed**: EC2 instances successfully pull code from `master` branch  
✅ **Modular Architecture**: 4-stack split enables fast testing cycles  
✅ **Dynamic Discovery**: Lambda finds EC2 instances by tag (no hardcoded IDs)  
✅ **Fast Testing**: Compute stack recreates in ~3 minutes vs ~10 minutes for full monolith

## 🧪 **NEW TESTING WORKFLOW**

### **Phase 1: Local Development Testing (15 seconds)**
```bash
python3 scrape.py  # Test locally with limited data (5 listings only)
```

### **Phase 2: Quick Infrastructure Testing (3 minutes)** ⚡
```bash
# Fast compute stack recreation for code changes
./deploy-compute.sh --recreate

# Test Lambda trigger (finds EC2 automatically by tag)
aws lambda invoke --function-name trigger-scraper --payload '{}' /tmp/response.json
cat /tmp/response.json
```

**Expected Response (Working):**
```json
{
  "statusCode": 200, 
  "body": "{\"command_id\": \"7223d04a-6879-48c2-9d50-43fd2d45f7a3\", \"status\": \"Success\", \"instance_id\": \"i-07557a973d41aa46f\"}"
}
```

### **Phase 3: Full Architecture Deployment (8-10 minutes)**
```bash
./deploy-all.sh  # Only needed for infrastructure changes
```

### **Verification Commands**
```bash
# Check scraper logs for GitHub integration
INSTANCE_ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=MarketScraper" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].InstanceId" --output text)
aws ssm send-command --instance-ids $INSTANCE_ID --document-name "AWS-RunShellScript" --parameters 'commands=["tail -30 /var/log/scraper/run.log"]' --region ap-northeast-1

# Check S3 for output files
aws s3 ls s3://lifull-scrape-tokyo/scraper-output/ --recursive
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