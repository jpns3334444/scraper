#!/bin/bash
set -e

# === Configuration ===
STACK_NAME="scraper-stack"
TEMPLATE_FILE="scraper-stack.yaml"
KEY_NAME="lifull-key"
OUTPUT_BUCKET="lifull-scrape-tokyo"
REGION="ap-northeast-1"
NOTIFICATION_EMAIL="${NOTIFICATION_EMAIL:-}"
NOTIFICATION_ENABLED="${NOTIFICATION_ENABLED:-true}"
# Get GitHub token from AWS Secrets Manager
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

# === Display Configuration ===
echo "🔧 Deployment Configuration:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  Output Bucket: $OUTPUT_BUCKET"
echo "  Notification Email: ${NOTIFICATION_EMAIL:-"(not set)"}"
echo "  Notification Enabled: $NOTIFICATION_ENABLED"
echo

# === Validate Template ===
echo "Validating CloudFormation template..."
if ! aws cloudformation validate-template --template-body "file://$TEMPLATE_FILE" --region "$REGION" > /dev/null 2>&1; then
  echo "❌ Template validation failed"
  exit 1
else
  echo "✅ Template is valid."
fi

# === Clean up ROLLBACK_COMPLETE ===
STACK_STATUS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].StackStatus" \
  --output text 2>/dev/null || true)

if [[ "$STACK_STATUS" == "ROLLBACK_COMPLETE" ]]; then
  echo "⚠️ Stack is in ROLLBACK_COMPLETE. Deleting..."
  aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
  echo "Waiting for stack to be deleted..."
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
fi

# === Create change set ===
echo "Creating change set..."
CHANGE_SET_NAME="manual-deploy-$(date +%s)"

# **⬇️ NEW: Detect if stack exists and set change set type accordingly**
if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" > /dev/null 2>&1; then
  CHANGE_SET_TYPE="UPDATE"
else
  CHANGE_SET_TYPE="CREATE"
fi

if ! aws cloudformation create-change-set \
  --stack-name "$STACK_NAME" \
  --template-body "file://$TEMPLATE_FILE" \
  --change-set-name "$CHANGE_SET_NAME" \
  --change-set-type $CHANGE_SET_TYPE \
  --parameters \
      ParameterKey=KeyName,ParameterValue="$KEY_NAME" \
      ParameterKey=MyIPv4,ParameterValue="$MY_IPV4" \
      ParameterKey=MyIPv6,ParameterValue="$MY_IPV6" \
      ParameterKey=OutputBucket,ParameterValue="$OUTPUT_BUCKET" \
      ParameterKey=CreateBucket,ParameterValue=false \
      ParameterKey=NotificationEmail,ParameterValue="$NOTIFICATION_EMAIL" \
      ParameterKey=NotificationEnabled,ParameterValue="$NOTIFICATION_ENABLED" \
      ParameterKey=GitHubToken,ParameterValue="$GITHUB_TOKEN" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region "$REGION"; then
    echo "❌ Failed to create change set."
    exit 1
fi

echo "Waiting for change set to be created..."
aws cloudformation wait change-set-create-complete \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$REGION"

echo "Executing change set..."
aws cloudformation execute-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$REGION"

# === Real-time event stream ===
echo "📡 Streaming stack events..."

LAST_EVENT_ID=""
while true; do
  STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null)

  if [[ "$STACK_STATUS" == "CREATE_COMPLETE" || "$STACK_STATUS" == "UPDATE_COMPLETE" ]]; then
    echo -e "\n✅ Stack operation completed successfully: $STACK_STATUS"
    break

  elif [[ "$STACK_STATUS" == "ROLLBACK_COMPLETE" || "$STACK_STATUS" == "CREATE_FAILED" ]]; then
    echo -e "\n❌ Stack creation failed: $STACK_STATUS"
    aws cloudformation describe-stack-events \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --query "StackEvents[?contains(ResourceStatus, 'FAILED')].[Timestamp,LogicalResourceId,ResourceStatusReason]" \
      --output table
    exit 1
  fi

  EVENT=$(aws cloudformation describe-stack-events \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackEvents[0].[EventId, Timestamp, LogicalResourceId, ResourceStatus, ResourceStatusReason]" \
    --output text)

  EVENT_ID=$(echo "$EVENT" | awk '{print $1}')
  if [[ "$EVENT_ID" != "$LAST_EVENT_ID" ]]; then
    echo "$EVENT" | cut -f2-
    LAST_EVENT_ID="$EVENT_ID"
  fi

  sleep 5
done
