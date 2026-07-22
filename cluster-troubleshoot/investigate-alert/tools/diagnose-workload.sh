#!/bin/bash
# Workload diagnostics: Deployment, StatefulSet, or DaemonSet status,
# replica counts, conditions, and rollout history.
#
# Usage: diagnose-workload.sh <name> [namespace] [kind]
#   kind: deployment, statefulset, daemonset (default: auto-detect)

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access
require_arg "${1:-}" "workload name" "Usage: diagnose-workload.sh <name> [namespace] [kind]"

WORKLOAD_NAME="$1"
NAMESPACE="${2:-}"
KIND="${3:-}"

NS_ARGS=()
if [[ -n "$NAMESPACE" ]]; then
  NS_ARGS=(-n "$NAMESPACE")
fi

# Auto-detect kind if not specified
if [[ -z "$KIND" ]]; then
  for try_kind in deployment statefulset daemonset; do
    if oc get "$try_kind" "$WORKLOAD_NAME" "${NS_ARGS[@]}" &>/dev/null; then
      KIND="$try_kind"
      break
    fi
  done
  if [[ -z "$KIND" ]]; then
    error_json "NOT_FOUND" "No deployment, statefulset, or daemonset named '$WORKLOAD_NAME' found" \
      "Verify the name and namespace"
  fi
fi

WL_JSON=$(oc get "$KIND" "$WORKLOAD_NAME" "${NS_ARGS[@]}" -o json 2>/dev/null) || \
  error_json "NOT_FOUND" "$KIND '$WORKLOAD_NAME' not found"
require_json "$WL_JSON" "$KIND $WORKLOAD_NAME"

# Get rollout history
HISTORY=$(oc rollout history "$KIND/$WORKLOAD_NAME" "${NS_ARGS[@]}" 2>/dev/null || echo "")

# Build output based on kind
case "$KIND" in
  deployment)
    echo "$WL_JSON" | jq --arg hist "$HISTORY" '{
      kind: "Deployment",
      name: .metadata.name,
      namespace: .metadata.namespace,
      replicas: {
        desired: (.spec.replicas // 0),
        ready: (.status.readyReplicas // 0),
        available: (.status.availableReplicas // 0),
        updated: (.status.updatedReplicas // 0),
        unavailable: (.status.unavailableReplicas // 0)
      },
      strategy: .spec.strategy.type,
      conditions: .status.conditions,
      containers: [.spec.template.spec.containers[] | {name, image}],
      rollout_history: $hist
    }'
    ;;
  statefulset)
    echo "$WL_JSON" | jq --arg hist "$HISTORY" '{
      kind: "StatefulSet",
      name: .metadata.name,
      namespace: .metadata.namespace,
      replicas: {
        desired: (.spec.replicas // 0),
        ready: (.status.readyReplicas // 0),
        current: (.status.currentReplicas // 0),
        updated: (.status.updatedReplicas // 0)
      },
      update_strategy: .spec.updateStrategy.type,
      conditions: .status.conditions,
      containers: [.spec.template.spec.containers[] | {name, image}],
      volume_claims: [.spec.volumeClaimTemplates[]? | .metadata.name],
      rollout_history: $hist
    }'
    ;;
  daemonset)
    echo "$WL_JSON" | jq --arg hist "$HISTORY" '{
      kind: "DaemonSet",
      name: .metadata.name,
      namespace: .metadata.namespace,
      replicas: {
        desired: (.status.desiredNumberScheduled // 0),
        ready: (.status.numberReady // 0),
        available: (.status.numberAvailable // 0),
        misscheduled: (.status.numberMisscheduled // 0),
        unavailable: (.status.numberUnavailable // 0)
      },
      update_strategy: .spec.updateStrategy.type,
      conditions: .status.conditions,
      containers: [.spec.template.spec.containers[] | {name, image}],
      rollout_history: $hist
    }'
    ;;
  *)
    error_json "UNSUPPORTED_KIND" "Unsupported workload kind: $KIND" \
      "Supported kinds: deployment, statefulset, daemonset"
    ;;
esac
