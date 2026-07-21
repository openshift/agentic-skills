#!/bin/bash
# Node diagnostics: conditions, capacity, allocatable, taints, kubelet info.
#
# Usage: diagnose-node.sh [node_name]
#   If no node name given, shows all nodes with non-Ready conditions.

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access

NODE_NAME="${1:-}"

if [[ -n "$NODE_NAME" ]]; then
  NODE_JSON=$(oc get node "$NODE_NAME" -o json 2>/dev/null) || \
    error_json "NOT_FOUND" "Node '$NODE_NAME' not found" "List nodes with: oc get nodes"
  require_json "$NODE_JSON" "node $NODE_NAME"

  echo "$NODE_JSON" | jq '{
    nodes: [{
      name: .metadata.name,
      labels: (.metadata.labels | with_entries(select(.key | test("node-role|kubernetes.io/os|topology")))),
      conditions: .status.conditions,
      capacity: .status.capacity,
      allocatable: .status.allocatable,
      taints: (.spec.taints // []),
      unschedulable: (.spec.unschedulable // false),
      kubelet_version: .status.nodeInfo.kubeletVersion,
      os_image: .status.nodeInfo.osImage,
      container_runtime: .status.nodeInfo.containerRuntimeVersion
    }]
  }'
else
  # Show all nodes, flagging unhealthy ones
  NODES_JSON=$(oc get nodes -o json 2>/dev/null) || \
    error_json "CLUSTER_ERROR" "Cannot list nodes"
  require_json "$NODES_JSON" "node list"

  echo "$NODES_JSON" | jq '{
    nodes: [.items[] | {
      name: .metadata.name,
      labels: (.metadata.labels | with_entries(select(.key | test("node-role|kubernetes.io/os|topology")))),
      ready: (.status.conditions[] | select(.type=="Ready") | .status == "True"),
      conditions: [.status.conditions[] | select(.status != "False" or .type == "Ready")],
      taints: (.spec.taints // []),
      unschedulable: (.spec.unschedulable // false),
      kubelet_version: .status.nodeInfo.kubeletVersion
    }],
    summary: {
      total: (.items | length),
      ready: [.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="True"))] | length,
      not_ready: [.items[] | select(.status.conditions[] | select(.type=="Ready" and .status!="True"))] | length
    }
  }'
fi
