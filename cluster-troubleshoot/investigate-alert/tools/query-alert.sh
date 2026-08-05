#!/bin/bash
# Query Prometheus for firing instances of a specific alert.
# Returns the full label set for each firing instance.
#
# Usage: query-alert.sh <alert_name>

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3
require_arg "${1:-}" "alert name" "Usage: query-alert.sh <alert_name>"

ALERT_NAME="$1"
if [[ ! "$ALERT_NAME" =~ ^[a-zA-Z_:][a-zA-Z0-9_:]*$ ]]; then
  error_json "INVALID_ARG" "Invalid alert name: '$ALERT_NAME'" \
    "Alert names must match ^[a-zA-Z_:][a-zA-Z0-9_:]*$"
fi
PROMQL="ALERTS{alertname=\"${ALERT_NAME}\"}"
QUERY=$(urlencode "$PROMQL")

RESPONSE=$(prometheus_get "/api/v1/query?query=${QUERY}")

echo "$RESPONSE" | jq --arg name "$ALERT_NAME" '{
  alert_name: $name,
  firing: (.data.result | length > 0),
  instance_count: (.data.result | length),
  instances: .data.result
}'
