#!/bin/bash
# Get events sorted by time for a namespace or cluster-wide.
#
# Usage: get-events.sh [namespace] [minutes]
#   namespace: target namespace, or '--all' for cluster-wide (default: current)
#   minutes:   only show events from last N minutes (default: 60)

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access

NAMESPACE="${1:-}"
MINUTES="${2:-60}"

NS_ARGS=()
if [[ "$NAMESPACE" == "--all" || "$NAMESPACE" == "-A" ]]; then
  NS_ARGS=(-A)
  NAMESPACE="all"
elif [[ -n "$NAMESPACE" ]]; then
  NS_ARGS=(-n "$NAMESPACE")
fi

CUTOFF=$(compute_cutoff "$MINUTES")

EVENTS_JSON=$(oc get events "${NS_ARGS[@]}" --sort-by='.lastTimestamp' -o json 2>/dev/null) || \
  error_json "CLUSTER_ERROR" "Cannot list events"
require_json "$EVENTS_JSON" "events"

# Filter to recent events and extract key fields
echo "$EVENTS_JSON" | jq --arg cutoff "$CUTOFF" --arg ns "${NAMESPACE:-current}" --argjson minutes "$MINUTES" '{
  namespace: $ns,
  time_window_minutes: $minutes,
  events: [
    .items[]
    | select(.lastTimestamp >= $cutoff or .lastTimestamp == null)
    | {
        time: .lastTimestamp,
        type: .type,
        reason: .reason,
        object: "\(.involvedObject.kind)/\(.involvedObject.name)",
        namespace: .involvedObject.namespace,
        message: .message,
        count: .count
      }
  ] | .[-100:],
  total_in_window: ([
    .items[]
    | select(.lastTimestamp >= $cutoff or .lastTimestamp == null)
  ] | length)
}'
