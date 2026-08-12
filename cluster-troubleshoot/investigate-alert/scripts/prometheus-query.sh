#!/bin/bash
# Run an instant PromQL query (current value).
#
# Usage: prometheus-query.sh '<promql>'

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3
require_arg "${1:-}" "PromQL expression" "Usage: prometheus-query.sh '<promql>'"

QUERY=$(urlencode "$1")
prometheus_get "/api/v1/query?query=${QUERY}" | jq .
