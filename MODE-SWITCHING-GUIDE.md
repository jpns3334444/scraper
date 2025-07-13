# Consolidated Scraper Infrastructure - Mode Switching Guide

## Overview

The scraper infrastructure has been consolidated into a single deployment with event-driven mode configuration. All stealth capabilities are now integrated into the main stacks with runtime behavior controlled entirely by event payloads.

## Quick Start

### Single Deployment Command
```bash
cd scraper/
./deploy-all.sh  # Deploys everything including all stealth capabilities
```

### Development Cycle
```bash
# After updating scraper code:
./deploy-compute.sh --recreate  # Just recreate EC2 instance (~3 minutes)
```

## Available Modes

### 1. Testing Mode
- **Properties**: Limited to 5 properties
- **Areas**: Single area (chofu-city by default)
- **Stealth**: Disabled
- **Use Case**: Quick testing and validation

### 2. Normal Mode  
- **Properties**: Up to 500 properties
- **Areas**: Single area (configurable)
- **Stealth**: Disabled
- **Use Case**: Standard daily scraping

### 3. Stealth Mode (Default)
- **Properties**: Up to 10,000 properties
- **Areas**: All Tokyo areas with distribution logic
- **Stealth**: Enabled with behavioral mimicry
- **Use Case**: Production data collection

## Mode Configuration

### EventBridge Rules (Default Configuration)

**Stealth Mode Rules (ENABLED by default):**
- `stealth-scraper-morning-1` - 08:00 UTC (17:00 JST)
- `stealth-scraper-morning-2` - 09:30 UTC (18:30 JST)  
- `stealth-scraper-afternoon-1` - 12:15 UTC (21:15 JST)
- `stealth-scraper-afternoon-2` - 14:45 UTC (23:45 JST)
- `stealth-scraper-evening-1` - 16:20 UTC (01:20 JST+1)
- `stealth-scraper-evening-2` - 18:10 UTC (03:10 JST+1)
- `stealth-scraper-night-1` - 20:35 UTC (05:35 JST+1)
- `stealth-scraper-night-2` - 22:55 UTC (07:55 JST+1)

**Testing/Normal Mode Rules (DISABLED by default):**
- `testing-session-rule` - 17:00 UTC (02:00 JST+1)
- `normal-session-rule` - 17:00 UTC (02:00 JST+1)

## Mode Switching

### Switch to Testing Mode
```bash
# Disable stealth sessions
for session in morning-1 morning-2 afternoon-1 afternoon-2 evening-1 evening-2 night-1 night-2; do
  aws events disable-rule --name "stealth-scraper-$session"
done

# Enable testing session
aws events enable-rule --name "testing-session-rule"
```

### Switch to Normal Mode
```bash
# Disable stealth sessions  
for session in morning-1 morning-2 afternoon-1 afternoon-2 evening-1 evening-2 night-1 night-2; do
  aws events disable-rule --name "stealth-scraper-$session"
done

# Enable normal session
aws events enable-rule --name "normal-session-rule"
```

### Switch to Stealth Mode (Default)
```bash
# Enable stealth sessions
for session in morning-1 morning-2 afternoon-1 afternoon-2 evening-1 evening-2 night-1 night-2; do
  aws events enable-rule --name "stealth-scraper-$session"  
done

# Disable other sessions
aws events disable-rule --name "testing-session-rule"
aws events disable-rule --name "normal-session-rule"
```

## Manual Testing

### Test Different Modes
```bash
# Test testing mode
aws lambda invoke --function-name trigger-scraper \
  --payload '{"mode": "testing", "single_area": "chofu-city"}' /tmp/test-response.json

# Test normal mode  
aws lambda invoke --function-name trigger-scraper \
  --payload '{"mode": "normal", "single_area": "shibuya-city"}' /tmp/normal-response.json

# Test stealth mode
aws lambda invoke --function-name trigger-scraper \
  --payload '{"mode": "stealth", "session_id": "manual-test", "max_properties": 10000}' /tmp/stealth-response.json
```

### Run Validation Tests
```bash
python3 test-mode-switching.py
```

## Environment Variables Passed to Scraper

The Lambda function sets these environment variables based on the event payload:

- `MODE`: "testing", "normal", or "stealth"
- `SESSION_ID`: Unique identifier for the session
- `MAX_PROPERTIES`: Maximum number of properties to scrape
- `STEALTH_MODE`: "true" or "false"
- `ENTRY_POINT`: Entry point for stealth mode
- `AREAS`: Comma-separated list of areas (for testing/normal modes)

## Infrastructure Components

### DynamoDB Table
- **Name**: `scraper-session-state`
- **Purpose**: Track session state and prevent duplicate runs
- **TTL**: 7 days

### Step Functions
- **Name**: `stealth-scraper-orchestrator`
- **Purpose**: Orchestrate session initialization, scraping, and state updates

### Lambda Functions
- **trigger-scraper**: Main scraper trigger with mode configuration
- **stealth-initialize-session**: Initialize session state
- **stealth-update-session**: Update session completion state

## Benefits

✅ **Single Deployment**: `./deploy-all.sh` deploys everything
✅ **Event-Driven Configuration**: Mode controlled by event payload, not stack parameters  
✅ **Instant Mode Switching**: Enable/disable EventBridge rules to change behavior
✅ **Manual Testing Flexibility**: Pass any mode in Lambda invoke payload
✅ **Clean Codebase**: Eliminated separate stealth stack files
✅ **No Stack Redeployments**: Change modes by enabling/disabling EventBridge rules
✅ **Development Friendly**: Keep `deploy-compute.sh` for quick code updates

## Monitoring

- **CloudWatch Logs**: Check logs for each Lambda function
- **DynamoDB**: Monitor session state in `scraper-session-state` table
- **SNS Notifications**: Email alerts for scraper job results
- **EventBridge**: Monitor rule execution in EventBridge console

## Troubleshooting

### Check Rule Status
```bash
aws events describe-rule --name "stealth-scraper-morning-1"
```

### Check Session State
```bash
aws dynamodb scan --table-name scraper-session-state
```

### View Lambda Logs
```bash
aws logs tail /aws/lambda/trigger-scraper --follow
```

### Validate Templates
```bash
aws cloudformation validate-template --template-body file://scraper-infra/infra-stack.yaml
aws cloudformation validate-template --template-body file://scraper-infra/automation-stack.yaml
```