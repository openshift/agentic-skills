#!/bin/bash
# blast-radius.sh — List all managed resources of an Argo CD Application
# and identify which are unhealthy or out of sync.
#
# Usage: blast-radius.sh <app-name> <namespace> [kubectl-cmd]
# Example: blast-radius.sh my-app openshift-gitops oc

set -euo pipefail

APP="${1:?Usage: blast-radius.sh <app-name> <namespace> [kubectl-cmd]}"
NS="${2:?Usage: blast-radius.sh <app-name> <namespace> [kubectl-cmd]}"
KCTL="${3:-oc}"

echo "=== Blast Radius Analysis for Application: $APP (namespace: $NS) ==="
echo ""

# Get all managed resources
RESOURCES=$($KCTL -n "$NS" get applications.argoproj.io "$APP" -o json 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$RESOURCES" ]; then
  echo "ERROR: Could not retrieve Application '$APP' in namespace '$NS'"
  exit 1
fi

# Summary
TOTAL=$(echo "$RESOURCES" | jq -r '[.status.resources // [] | .[] ] | length')
HEALTHY=$(echo "$RESOURCES" | jq -r '[.status.resources // [] | .[] | select(.health.status == "Healthy")] | length')
SYNCED=$(echo "$RESOURCES" | jq -r '[.status.resources // [] | .[] | select(.status == "Synced")] | length')
DEGRADED=$(echo "$RESOURCES" | jq -r '[.status.resources // [] | .[] | select(.health.status == "Degraded")] | length')
OUTOFSYNC=$(echo "$RESOURCES" | jq -r '[.status.resources // [] | .[] | select(.status == "OutOfSync")] | length')
MISSING=$(echo "$RESOURCES" | jq -r '[.status.resources // [] | .[] | select(.health.status == "Missing")] | length')

echo "Total managed resources: $TOTAL"
echo "  Healthy/Synced: $HEALTHY/$SYNCED"
echo "  Degraded: $DEGRADED"
echo "  OutOfSync: $OUTOFSYNC"
echo "  Missing: $MISSING"
echo ""

# List unhealthy or out-of-sync resources
if [ "$DEGRADED" -gt 0 ] || [ "$OUTOFSYNC" -gt 0 ] || [ "$MISSING" -gt 0 ]; then
  echo "=== Problem Resources ==="
  echo "$RESOURCES" | jq -r '
    .status.resources // [] | .[] |
    select(.health.status != "Healthy" or .status != "Synced") |
    "\(.group // "core")/\(.kind) \(.namespace // "cluster-scoped")/\(.name) health=\(.health.status // "Unknown") sync=\(.status // "Unknown")"
  '
  echo ""
fi

# List all resources for full picture
echo "=== All Managed Resources ==="
echo "$RESOURCES" | jq -r '
  .status.resources // [] | .[] |
  "\(.group // "core")/\(.kind) \(.namespace // "cluster-scoped")/\(.name) health=\(.health.status // "Unknown") sync=\(.status // "Unknown")"
'
