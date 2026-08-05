#!/bin/bash
# Fetch the alerting rule definition: PromQL expression, thresholds,
# duration, labels, and annotations (description, summary, runbook_url).
#
# Usage: fetch-alert-rule.sh <alert_name>

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3
require_arg "${1:-}" "alert name" "Usage: fetch-alert-rule.sh <alert_name>"

ALERT_NAME="$1"

RESPONSE=$(prometheus_get "/api/v1/rules?type=alert")
RULE=$(echo "$RESPONSE" | jq --arg name "$ALERT_NAME" \
  '[.data.groups[].rules[] | select(.name==$name and .type=="alerting")] | first // empty')

if [[ -z "$RULE" || "$RULE" == "null" ]]; then
  jq -n --arg name "$ALERT_NAME" '{alert_name: $name, found: false}'
else
  echo "$RULE" | jq --arg name "$ALERT_NAME" '{
    alert_name: $name,
    found: true,
    expr: .query,
    duration: .duration,
    labels: .labels,
    annotations: .annotations
  }'
fi
