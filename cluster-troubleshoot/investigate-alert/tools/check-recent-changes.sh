#!/bin/bash
# Detect recent changes that may have caused an issue: rollouts, image pulls,
# and scaling events.
#
# Usage: check-recent-changes.sh [namespace] [minutes]
#   namespace: target namespace (default: current). Cluster-level changes always included.
#   minutes:   time window (default: 60)

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access

NAMESPACE="${1:-}"
MINUTES="${2:-60}"

NS_ARGS=()
if [[ -n "$NAMESPACE" ]]; then
  NS_ARGS=(-n "$NAMESPACE")
fi

# Deployment rollout status in namespace
DEPLOYMENTS="[]"
if [[ -n "$NAMESPACE" ]]; then
  DEPLOY_JSON=$(oc get deployments "${NS_ARGS[@]}" -o json 2>/dev/null) || DEPLOY_JSON='{"items":[]}'
  require_json "$DEPLOY_JSON" "deployment list"
  DEPLOYMENTS=$(echo "$DEPLOY_JSON" | jq '[.items[] | select(
      (.status.conditions[]? | select(.type=="Progressing" and .status=="True" and (.reason? == "NewReplicaSetAvailable" or .reason? == "ReplicaSetUpdated")))
      or (.status.unavailableReplicas // 0) > 0
    ) | {
      name: .metadata.name,
      namespace: .metadata.namespace,
      ready: "\(.status.readyReplicas // 0)/\(.spec.replicas // 0)",
      updated: (.status.updatedReplicas // 0),
      unavailable: (.status.unavailableReplicas // 0),
      last_update: (.status.conditions[] | select(.type=="Progressing") | .lastUpdateTime)
    }]' 2>/dev/null || echo "[]")
fi

CUTOFF=$(compute_cutoff "$MINUTES")

# Fetch events once, filter into rollout and image-pull categories
ALL_EVENTS=$(oc get events "${NS_ARGS[@]}" --sort-by='.lastTimestamp' -o json 2>/dev/null) || \
  ALL_EVENTS='{"items":[]}'
require_json "$ALL_EVENTS" "events"

ROLLOUT_EVENTS=$(echo "$ALL_EVENTS" | jq --arg cutoff "$CUTOFF" '[
    .items[]
    | select(.lastTimestamp >= $cutoff or .lastTimestamp == null)
    | select(.reason | test("ScalingReplicaSet|DeploymentRollback|Scheduled|Pulled|Created|Started|Killing"; "i"))
    | {
        time: .lastTimestamp,
        reason: .reason,
        object: "\(.involvedObject.kind)/\(.involvedObject.name)",
        namespace: .involvedObject.namespace,
        message: .message
      }
  ]' 2>/dev/null || echo "[]")

IMAGE_EVENTS=$(echo "$ALL_EVENTS" | jq --arg cutoff "$CUTOFF" '[
    .items[]
    | select(.lastTimestamp >= $cutoff or .lastTimestamp == null)
    | select(.reason == "Pulled" or .reason == "Pulling")
    | {
        time: .lastTimestamp,
        object: "\(.involvedObject.kind)/\(.involvedObject.name)",
        namespace: .involvedObject.namespace,
        message: .message
      }
  ]' 2>/dev/null || echo "[]")

jq -n \
  --arg ns "${NAMESPACE:-cluster}" \
  --arg minutes "$MINUTES" \
  --argjson rollouts "$ROLLOUT_EVENTS" \
  --argjson images "$IMAGE_EVENTS" \
  --argjson deployments "$DEPLOYMENTS" \
  '{
    namespace: $ns,
    time_window_minutes: ($minutes | tonumber),
    rollout_events: $rollouts,
    image_pull_events: $images,
    active_rollouts: $deployments
  }'
