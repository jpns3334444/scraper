#!/usr/bin/env bash
set -euo pipefail

# Find repo root (directory containing this scripts/ folder)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CFG_FILE="$REPO_ROOT/config.json"

if [ ! -f "$CFG_FILE" ]; then
  echo "Config not found: $CFG_FILE" >&2
  exit 1
fi

# Parse JSON config and export as environment variables
parse_json_config() {
  local json_file="$1"

  # Check if jq is available
  if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required to parse config.json" >&2
    exit 1
  fi

  # Extract flat values from nested JSON structure
  eval "$(jq -r '
    def extract(prefix):
      . as $obj |
      if type == "object" then
        to_entries[] |
        if .key | startswith("_") then empty
        else
          if .value | type == "object" then
            .value | extract(if prefix == "" then .key else prefix + "_" + .key end)
          else
            "export " + (if prefix == "" then .key else .key end) + "=\"" + (.value | tostring) + "\""
          end
        end
      else empty end;
    extract("")
  ' "$json_file")"
}

parse_json_config "$CFG_FILE"

# Minimal validation - check required variables
need() {
  local v="$1"
  if [ -z "${!v:-}" ]; then
    echo "Missing required config var: $v" >&2
    exit 1
  fi
}

# Validate core settings
need PROJECT
need AWS_REGION
need AI_STACK

# Validate S3 buckets
need DEPLOYMENT_BUCKET_PREFIX
need OUTPUT_BUCKET

# Validate DynamoDB tables
need DDB_PROPERTIES
need DDB_URL_TRACKING
need DDB_USER_PREFERENCES

# Export commonly used derived values
export DEPLOYMENT_BUCKET="${DEPLOYMENT_BUCKET_PREFIX}-${AWS_REGION}"

# Export full Lambda function names (all in unified stack now)
export LAMBDA_URL_COLLECTOR_FULL="${AI_STACK}-url-collector"
export LAMBDA_PROPERTY_PROCESSOR_FULL="${AI_STACK}-property-processor"
export LAMBDA_PROPERTY_ANALYZER_FULL="${AI_STACK}-property-analyzer"
export LAMBDA_FAVORITE_ANALYZER_FULL="${AI_STACK}-favorite-analyzer"
export LAMBDA_DASHBOARD_API_FULL="${AI_STACK}-dashboard-api"
export LAMBDA_FAVORITES_API_FULL="${AI_STACK}-favorites-api"
