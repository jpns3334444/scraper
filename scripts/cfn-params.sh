#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load config
# shellcheck disable=SC1090
. "$SCRIPT_DIR/cfg.sh"

# Generate CloudFormation parameters JSON file
# Usage: ./scripts/cfn-params.sh [output_file] [stack_type] [code_versions...]
# stack_type: "ai" or "frontend" (default: "ai")
PARAMS_FILE="${1:-/tmp/cfn_params.json}"
STACK_TYPE="${2:-ai}"
shift 2 2>/dev/null || true

if [ "$STACK_TYPE" = "ai" ]; then
  # Base parameters for ai-stack.yaml
  cat > "$PARAMS_FILE" <<EOF
[
  {"ParameterKey":"DeploymentBucket","ParameterValue":"$DEPLOYMENT_BUCKET"},
  {"ParameterKey":"OutputBucket","ParameterValue":"$OUTPUT_BUCKET"},
  {"ParameterKey":"EmailFrom","ParameterValue":"$EMAIL_FROM"},
  {"ParameterKey":"EmailTo","ParameterValue":"$EMAIL_TO"},
  {"ParameterKey":"LeanMode","ParameterValue":"$LEAN_MODE"}
EOF

  # Add code version parameters if provided
  while [ $# -gt 1 ]; do
    param_name="$1"
    param_value="$2"
    echo "  ,{\"ParameterKey\":\"$param_name\",\"ParameterValue\":\"$param_value\"}" >> "$PARAMS_FILE"
    shift 2
  done
  
  echo "]" >> "$PARAMS_FILE"

elif [ "$STACK_TYPE" = "frontend" ]; then
  # Base parameters for front-end-stack.yaml
  cat > "$PARAMS_FILE" <<EOF
[
  {"ParameterKey":"AIStackName","ParameterValue":"$AI_STACK"},
  {"ParameterKey":"DeploymentBucket","ParameterValue":"$DEPLOYMENT_BUCKET"}
EOF

  # Add code version parameters if provided
  while [ $# -gt 1 ]; do
    param_name="$1"
    param_value="$2"
    echo "  ,{\"ParameterKey\":\"$param_name\",\"ParameterValue\":\"$param_value\"}" >> "$PARAMS_FILE"
    shift 2
  done
  
  echo "]" >> "$PARAMS_FILE"

else
  echo "Unknown stack type: $STACK_TYPE (use 'ai' or 'frontend')" >&2
  exit 1
fi

echo "$PARAMS_FILE"