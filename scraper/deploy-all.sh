#!/bin/bash
set -e

# === Configuration ===
REGION="ap-northeast-1"
KEY_NAME="lifull-key"
OUTPUT_BUCKET="tokyo-real-estate-ai-data"
NOTIFICATION_EMAIL="${NOTIFICATION_EMAIL:-}"
NOTIFICATION_ENABLED="${NOTIFICATION_ENABLED:-true}"

# Stack names  
INFRA_STACK_NAME="tokyo-real-estate-infra"
COMPUTE_STACK_NAME="tokyo-real-estate-compute"
AUTOMATION_STACK_NAME="tokyo-real-estate-automation"

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
echo "  S3 Bucket: $OUTPUT_BUCKET (existing bucket)"
echo "  Infrastructure: $INFRA_STACK_NAME"
echo "  Compute: $COMPUTE_STACK_NAME"
echo "  Automation: $AUTOMATION_STACK_NAME"
echo
echo "🚀 To test the scraper, run:"
echo "  aws lambda invoke --function-name tokyo-real-estate-trigger --payload '{}' /tmp/response.json --region $REGION"
echo
echo "💡 Next Steps:"
echo "  1. Deploy the AI infrastructure:"
echo "     cd ../ai_infra && ./deploy-ai.sh"
echo "  2. Deploy the dashboard (after AI stack):"
echo "     cd ../dashboard && ./deploy-dashboard.sh"