#!/bin/bash
# Local testing script for AI pipeline
set -e

FUNCTION_NAME=$1
EVENT_FILE=$2

if [ -z "$FUNCTION_NAME" ] || [ -z "$EVENT_FILE" ]; then
  echo "Usage: $0 <function_name> <event_file>"
  echo "Example: $0 etl test-events/etl-event.json"
  echo "Available functions: etl, prompt_builder, llm_batch, report_sender, dynamodb_writer"
  exit 1
fi

# Change to the script's directory
cd "$(dirname "${BASH_SOURCE[0]}")"

# Run the Python test runner
python3 test_runner.py "$FUNCTION_NAME" "$EVENT_FILE"
