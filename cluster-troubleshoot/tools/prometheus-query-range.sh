#!/bin/bash
# Run a PromQL range query with configurable time window and step.
#
# Usage: prometheus-query-range.sh '<promql>' [duration] [step]
#   duration: lookback period (default: 1h). Supports: Ns, Nm, Nh, Nd
#   step:     resolution (default: 60s)

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3
require_arg "${1:-}" "PromQL expression" "Usage: prometheus-query-range.sh '<promql>' [duration] [step]"

PROMQL="$1"
DURATION="${2:-1h}"
STEP="${3:-60s}"

# Parse duration to seconds
parse_duration() {
  local val="$1"
  local num="${val%[smhd]}"
  local unit="${val##*[0-9]}"
  case "$unit" in
    s) echo "$num" ;;
    m) echo $((num * 60)) ;;
    h) echo $((num * 3600)) ;;
    d) echo $((num * 86400)) ;;
    *) error_json "INVALID_ARG" "Invalid duration format: $val" "Use: Ns, Nm, Nh, or Nd (e.g. 30m, 1h, 1d)" ;;
  esac
}

SECONDS_AGO=$(parse_duration "$DURATION")
END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START=$(date -u -d "${SECONDS_AGO} seconds ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) || \
  START=$(date -u -d "@$(($(date +%s) - SECONDS_AGO))" +%Y-%m-%dT%H:%M:%SZ)

QUERY=$(urlencode "$PROMQL")
prometheus_get "/api/v1/query_range?query=${QUERY}&start=${START}&end=${END}&step=${STEP}" | jq .
