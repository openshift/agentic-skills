#!/bin/bash
# List all currently firing alerts from Prometheus.
#
# Usage: get-firing-alerts.sh [filter]
#   filter: optional grep pattern to filter alert names

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3

FILTER="${1:-}"

RESPONSE=$(prometheus_get "/api/v1/alerts")

if [[ -n "$FILTER" ]]; then
  ALERTS=$(echo "$RESPONSE" | jq --arg f "$FILTER" \
    '[.data.alerts[] | select(.state=="firing") | select(.labels.alertname | test($f; "i"))]')
else
  ALERTS=$(echo "$RESPONSE" | jq '[.data.alerts[] | select(.state=="firing")]')
fi

COUNT=$(echo "$ALERTS" | jq 'length')
printf '{"total_firing":%d,"alerts":%s}\n' "$COUNT" "$ALERTS"
