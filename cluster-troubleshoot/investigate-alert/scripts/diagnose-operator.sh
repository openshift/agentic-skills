#!/bin/bash
# ClusterOperator diagnostics: Available, Progressing, Degraded conditions.
#
# Usage: diagnose-operator.sh [operator_name]
#   If no operator name given, lists all operators with non-healthy conditions.

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access

OPERATOR_NAME="${1:-}"

if [[ -n "$OPERATOR_NAME" ]]; then
  CO_JSON=$(oc get clusteroperator "$OPERATOR_NAME" -o json 2>/dev/null) || \
    error_json "NOT_FOUND" "ClusterOperator '$OPERATOR_NAME' not found" "List operators with: oc get clusteroperators"
  require_json "$CO_JSON" "ClusterOperator $OPERATOR_NAME"

  echo "$CO_JSON" | jq '{
    operators: [{
      name: .metadata.name,
      available: (.status.conditions[] | select(.type=="Available") | .status == "True"),
      progressing: (.status.conditions[] | select(.type=="Progressing") | .status == "True"),
      degraded: (.status.conditions[] | select(.type=="Degraded") | .status == "True"),
      versions: [.status.versions[]? | {(.name): .version}] | add // {},
      conditions: .status.conditions
    }]
  }'
else
  CO_JSON=$(oc get clusteroperators -o json 2>/dev/null) || \
    error_json "CLUSTER_ERROR" "Cannot list ClusterOperators"
  require_json "$CO_JSON" "ClusterOperator list"

  echo "$CO_JSON" | jq '{
    operators: [.items[] | {
      name: .metadata.name,
      available: (.status.conditions[] | select(.type=="Available") | .status == "True"),
      progressing: (.status.conditions[] | select(.type=="Progressing") | .status == "True"),
      degraded: (.status.conditions[] | select(.type=="Degraded") | .status == "True"),
      versions: [.status.versions[]? | {(.name): .version}] | add // {}
    }],
    summary: {
      total: (.items | length),
      available: [.items[] | select(.status.conditions[] | select(.type=="Available" and .status=="True"))] | length,
      degraded: [.items[] | select(.status.conditions[] | select(.type=="Degraded" and .status=="True"))] | length,
      progressing: [.items[] | select(.status.conditions[] | select(.type=="Progressing" and .status=="True"))] | length
    }
  }'
fi
