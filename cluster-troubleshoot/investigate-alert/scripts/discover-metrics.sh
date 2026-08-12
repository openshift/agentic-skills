#!/bin/bash
# Search for Prometheus metric names matching a pattern.
#
# Usage: discover-metrics.sh <pattern>

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3
require_arg "${1:-}" "search pattern" "Usage: discover-metrics.sh <pattern>"

PATTERN="$1"

ALL_METRICS=$(prometheus_get "/api/v1/label/__name__/values")
MATCHED=$(echo "$ALL_METRICS" | jq -r '.data[]' | grep -i "$PATTERN" || true)

if [[ -z "$MATCHED" ]]; then
  jq -n --arg p "$PATTERN" '{pattern: $p, match_count: 0, metrics: []}'
else
  echo "$MATCHED" | jq -R . | jq -s --arg p "$PATTERN" \
    '{pattern: $p, match_count: length, metrics: .}'
fi
