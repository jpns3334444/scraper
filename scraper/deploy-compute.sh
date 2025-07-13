#!/bin/bash
set -e

# === Configuration ===
REGION="ap-northeast-1"
KEY_NAME="lifull-key"
OUTPUT_BUCKET="tokyo-real-estate-ai-data"
INFRA_STACK_NAME="scraper-infra-stack"
COMPUTE_STACK_NAME="scraper-compute-stack"

echo "💻 Deploying compute stack for testing..."

# === Option to delete and recreate ===
if [ "$1" == "--recreate" ]; then
  echo "🗑️  Deleting existing compute stack..."
  aws cloudformation delete-stack --stack-name "$COMPUTE_STACK_NAME" --region "$REGION" || true
  echo "Waiting for compute stack deletion..."
  aws cloudformation wait stack-delete-complete --stack-name "$COMPUTE_STACK_NAME" --region "$REGION" || true
  echo "✅ Compute stack deleted"
fi

echo "🚀 Deploying compute stack..."
aws cloudformation deploy \
  --stack-name "$COMPUTE_STACK_NAME" \
  --template-file compute-stack.yaml \
  --parameter-overrides \
      KeyName="$KEY_NAME" \
      OutputBucket="$OUTPUT_BUCKET" \
      InfraStackName="$INFRA_STACK_NAME" \
  --region "$REGION"

echo "✅ Compute stack deployed successfully"

# Get the instance ID
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name "$COMPUTE_STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ScraperInstanceId'].OutputValue" \
  --output text)

PUBLIC_IP=$(aws cloudformation describe-stacks \
  --stack-name "$COMPUTE_STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ScraperPublicIP'].OutputValue" \
  --output text)

echo
echo "📋 Compute Stack Information:"
echo "  Instance ID: $INSTANCE_ID"
echo "  Public IP: $PUBLIC_IP"
echo
echo "🔍 To check instance logs:"
echo "  aws ssm send-command --instance-ids $INSTANCE_ID --document-name 'AWS-RunShellScript' --parameters 'commands=[\"tail -20 /var/log/scraper/run.log\"]' --region $REGION"
echo
echo "🧪 To test the scraper:"
echo "  aws lambda invoke --function-name trigger-scraper --payload '{}' /tmp/response.json --region $REGION"