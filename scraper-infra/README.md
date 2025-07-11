# CloudFormation Templates (Scraper Infrastructure)

CloudFormation templates for deploying the EC2-based scraper infrastructure.

## Templates

- `s3-bucket-stack.yaml` - S3 bucket for storing scraper outputs
- `infra-stack.yaml` - VPC, security groups, IAM roles  
- `compute-stack.yaml` - EC2 instance for running the scraper
- `automation-stack.yaml` - Automated deployment and scheduling
- `stealth-*.yaml` - Enhanced stealth capabilities for scraping

## Deployment Order

1. **S3 Bucket** (one-time):
   ```bash
   aws cloudformation create-stack \
     --stack-name scraper-s3 \
     --template-body file://s3-bucket-stack.yaml
   ```

2. **Infrastructure** (VPC, security):
   ```bash
   aws cloudformation create-stack \
     --stack-name scraper-infra \
     --template-body file://infra-stack.yaml \
     --capabilities CAPABILITY_IAM
   ```

3. **Compute** (EC2 instance):
   ```bash
   aws cloudformation create-stack \
     --stack-name scraper-compute \
     --template-body file://compute-stack.yaml \
     --parameters ParameterKey=KeyName,ParameterValue=your-key-name
   ```

4. **Automation** (optional):
   ```bash
   aws cloudformation create-stack \
     --stack-name scraper-automation \
     --template-body file://automation-stack.yaml
   ```

## Output

These stacks create the infrastructure that runs the scraper daily and outputs data to S3, which is then processed by the AI analysis system.

## Relationship to AI System  

The scraper infrastructure is **complementary** to the AI analysis system:
- **Scraper**: Collects raw data (this directory)
- **AI Analysis**: Processes the data (`/lambda/`, `/infra/ai-stack.yaml`)

Both systems work together in the complete workflow.