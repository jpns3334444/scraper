#!/bin/bash

# --- Configuration ---
REGION="ap-northeast-1"  # change if you're in another region
TAG_NAME="MarketScraper"

# --- Get instance ID ---
INSTANCE_ID=$(aws ec2 describe-instances \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=$TAG_NAME" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text)

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  echo "❌ No running EC2 instance found with Name=$TAG_NAME in $REGION"
  exit 1
fi

echo "📡 Connecting to EC2 instance: $INSTANCE_ID ..."
aws ssm start-session --target "$INSTANCE_ID" --region "$REGION"
