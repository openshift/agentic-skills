#!/bin/bash
# Pod diagnostics: status, conditions, container statuses, events, and logs.
#
# Usage: diagnose-pod.sh <name-or-selector> [namespace] [--logs]
#   If <name-or-selector> contains '=', it is treated as a label selector.
#   Samples up to 3 pods when using a label selector.

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access
require_arg "${1:-}" "pod name or label selector" "Usage: diagnose-pod.sh <name-or-selector> [namespace] [--logs]"

TARGET="$1"
NAMESPACE="${2:-}"
INCLUDE_LOGS=false

# Parse flags from remaining args
for arg in "$@"; do
  if [[ "$arg" == "--logs" ]]; then
    INCLUDE_LOGS=true
  fi
done

NS_ARGS=()
if [[ -n "$NAMESPACE" && "$NAMESPACE" != "--logs" ]]; then
  NS_ARGS=(-n "$NAMESPACE")
fi

# Determine if target is a label selector or pod name
if [[ "$TARGET" == *"="* ]]; then
  POD_JSON=$(oc get pods -l "$TARGET" "${NS_ARGS[@]}" -o json 2>/dev/null) || \
    error_json "NOT_FOUND" "No pods matching selector '$TARGET'" "Verify the label selector and namespace"
  require_json "$POD_JSON" "pod list"
  POD_NAMES=$(echo "$POD_JSON" | jq -r '.items[].metadata.name' | head -3)
else
  POD_JSON=$(oc get pod "$TARGET" "${NS_ARGS[@]}" -o json 2>/dev/null) || \
    error_json "NOT_FOUND" "Pod '$TARGET' not found" "Check the pod name and namespace"
  require_json "$POD_JSON" "pod"
  POD_NAMES="$TARGET"
fi

if [[ -z "$POD_NAMES" ]]; then
  error_json "NOT_FOUND" "No pods found matching '$TARGET'"
fi

RESULTS="[]"

while IFS= read -r POD_NAME; do
  [[ -z "$POD_NAME" ]] && continue

  # Get pod details
  POD_DETAIL=$(oc get pod "$POD_NAME" "${NS_ARGS[@]}" -o json 2>/dev/null) || continue
  require_json "$POD_DETAIL" "pod $POD_NAME"
  POD_NS=$(echo "$POD_DETAIL" | jq -r '.metadata.namespace')

  # Extract key fields
  POD_INFO=$(echo "$POD_DETAIL" | jq '{
    name: .metadata.name,
    namespace: .metadata.namespace,
    phase: .status.phase,
    conditions: .status.conditions,
    container_statuses: .status.containerStatuses,
    init_container_statuses: .status.initContainerStatuses,
    owner_references: .metadata.ownerReferences,
    node_name: .spec.nodeName,
    restart_count: ([.status.containerStatuses[]?.restartCount] | add // 0)
  }')

  # Get events for this pod
  EVENTS=$(oc get events -n "$POD_NS" \
    --field-selector "involvedObject.name=$POD_NAME" \
    --sort-by='.lastTimestamp' -o json 2>/dev/null | \
    jq '[.items[-10:] | .[] | {
      time: .lastTimestamp,
      type: .type,
      reason: .reason,
      message: .message,
      count: .count
    }]' 2>/dev/null || echo "[]")

  POD_INFO=$(echo "$POD_INFO" | jq --argjson events "$EVENTS" '. + {events: $events}')

  # Get logs if requested
  if [[ "$INCLUDE_LOGS" == "true" ]]; then
    CONTAINERS=$(echo "$POD_DETAIL" | jq -r '.spec.containers[].name')
    LOGS_OBJ="{}"
    while IFS= read -r CONTAINER; do
      [[ -z "$CONTAINER" ]] && continue
      CONTAINER_LOGS=$(oc logs "$POD_NAME" -n "$POD_NS" -c "$CONTAINER" --tail=50 2>/dev/null || echo "(logs unavailable)")
      LOGS_ARRAY=$(echo "$CONTAINER_LOGS" | jq -R . | jq -s .)
      LOGS_OBJ=$(echo "$LOGS_OBJ" | jq --arg c "$CONTAINER" --argjson l "$LOGS_ARRAY" '. + {($c): $l}')
    done <<< "$CONTAINERS"
    POD_INFO=$(echo "$POD_INFO" | jq --argjson logs "$LOGS_OBJ" '. + {logs: $logs}')
  fi

  RESULTS=$(echo "$RESULTS" | jq --argjson pod "$POD_INFO" '. + [$pod]')
done <<< "$POD_NAMES"

echo "$RESULTS" | jq '{pods: .}'
