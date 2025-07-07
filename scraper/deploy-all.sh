#!/bin/bash
set -e

# === Configuration ===
REGION="ap-northeast-1"
KEY_NAME="lifull-key"
OUTPUT_BUCKET="lifull-scrape-tokyo"
NOTIFICATION_EMAIL="${NOTIFICATION_EMAIL:-}"
NOTIFICATION_ENABLED="${NOTIFICATION_ENABLED:-true}"

# Stack names
S3_STACK_NAME="s3-bucket-stack"
INFRA_STACK_NAME="scraper-infra-stack"
COMPUTE_STACK_NAME="scraper-compute-stack"
AUTOMATION_STACK_NAME="scraper-automation-stack"

# === Get GitHub token from AWS Secrets Manager ===
SECRET_NAME="github-token"
echo "🔐 Retrieving GitHub token from AWS Secrets Manager..."
GITHUB_TOKEN=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_NAME" \
  --region "$REGION" \
  --query SecretString \
  --output text 2>/dev/null || echo "")

if [ -z "$GITHUB_TOKEN" ]; then
  echo "⚠️  GitHub token not found in AWS Secrets Manager."
  echo "Please create a secret named '$SECRET_NAME' with your GitHub token:"
  echo "aws secretsmanager create-secret --name '$SECRET_NAME' --secret-string 'ghp_your_token_here' --region '$REGION'"
  echo "Then run this script again."
  exit 1
fi

# === Dynamically fetch public IPs ===
MY_IPV4="$(curl -s -4 ifconfig.me)/32"
MY_IPV6_RAW="$(curl -s -6 ifconfig.me || true)"
MY_IPV6="${MY_IPV6_RAW:-::}/128"

echo "🔧 Deployment Configuration:"
echo "  Region: $REGION"
echo "  Output Bucket: $OUTPUT_BUCKET"
echo "  Notification Email: ${NOTIFICATION_EMAIL:-"(not set)"}"
echo "  Notification Enabled: $NOTIFICATION_ENABLED"
echo

# === Deploy S3 Bucket Stack ===
echo "📦 Deploying S3 bucket stack..."
if ! aws cloudformation describe-stacks --stack-name "$S3_STACK_NAME" --region "$REGION" > /dev/null 2>&1; then
  aws cloudformation create-stack \
    --stack-name "$S3_STACK_NAME" \
    --template-body file://s3-bucket-stack.yaml \
    --parameters ParameterKey=BucketName,ParameterValue="$OUTPUT_BUCKET" \
    --region "$REGION"
  
  echo "Waiting for S3 bucket stack to complete..."
  aws cloudformation wait stack-create-complete --stack-name "$S3_STACK_NAME" --region "$REGION"
  echo "✅ S3 bucket stack created successfully"
else
  echo "✅ S3 bucket stack already exists"
fi

# === Deploy Infrastructure Stack ===
echo "🏗️  Deploying infrastructure stack..."
aws cloudformation deploy \
  --stack-name "$INFRA_STACK_NAME" \
  --template-file infra-stack.yaml \
  --parameter-overrides \
      MyIPv4="$MY_IPV4" \
      MyIPv6="$MY_IPV6" \
      OutputBucket="$OUTPUT_BUCKET" \
      NotificationEmail="$NOTIFICATION_EMAIL" \
      NotificationEnabled="$NOTIFICATION_ENABLED" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION"

echo "✅ Infrastructure stack deployed successfully"

# === Deploy Compute Stack ===
echo "💻 Deploying compute stack..."
aws cloudformation deploy \
  --stack-name "$COMPUTE_STACK_NAME" \
  --template-file compute-stack.yaml \
  --parameter-overrides \
      KeyName="$KEY_NAME" \
      OutputBucket="$OUTPUT_BUCKET" \
      InfraStackName="$INFRA_STACK_NAME" \
  --region "$REGION"

echo "✅ Compute stack deployed successfully"

# === Deploy Automation Stack ===
echo "🤖 Deploying automation stack..."
aws cloudformation deploy \
  --stack-name "$AUTOMATION_STACK_NAME" \
  --template-file automation-stack.yaml \
  --parameter-overrides \
      InfraStackName="$INFRA_STACK_NAME" \
      NotificationEnabled="$NOTIFICATION_ENABLED" \
  --region "$REGION"

echo "✅ Automation stack deployed successfully"

echo
echo "🎉 All stacks deployed successfully!"
echo
echo "📋 Stack Information:"
echo "  S3 Bucket: $S3_STACK_NAME"
echo "  Infrastructure: $INFRA_STACK_NAME"
echo "  Compute: $COMPUTE_STACK_NAME"
echo "  Automation: $AUTOMATION_STACK_NAME"
echo
echo "🚀 To test the scraper, run:"
echo "  aws lambda invoke --function-name trigger-scraper --payload '{}' /tmp/response.json --region $REGION"