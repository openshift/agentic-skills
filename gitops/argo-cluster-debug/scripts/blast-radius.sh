#!/bin/bash
# blast-radius.sh — List all managed resources of an Argo CD Application
# and identify which are unhealthy or out of sync.
#
# Usage: blast-radius.sh <app-name> <namespace> [kubectl-cmd]
# Example: blast-radius.sh my-app openshift-gitops oc
#
# Exit codes:
#   0 — success (all resources healthy and synced)
#   1 — usage error or Application not found
#   2 — Application found but has unhealthy or out-of-sync resources
#
# Requirements: jq must be installed.

set -euo pipefail

# --- Argument parsing -----------------------------------------------------------

usage() {
  echo "Usage: $(basename "$0") <app-name> <namespace> [kubectl-cmd]" >&2
  echo "" >&2
  echo "Arguments:" >&2
  echo "  app-name     Name of the Argo CD Application resource" >&2
  echo "  namespace    Namespace where the Application CR lives (e.g. openshift-gitops)" >&2
  echo "  kubectl-cmd  CLI to use: oc or kubectl (default: oc)" >&2
  echo "" >&2
  echo "Example:" >&2
  echo "  $(basename "$0") my-app openshift-gitops oc" >&2
  exit 1
}

if [ $# -lt 2 ]; then
  usage
fi

APP="$1"
NS="$2"
KCTL="${3:-oc}"

# --- Dependency checks ----------------------------------------------------------

if ! command -v "$KCTL" >/dev/null 2>&1; then
  echo "ERROR: '$KCTL' is not installed or not in PATH" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: 'jq' is required but not installed" >&2
  exit 1
fi

# --- Fetch Application ----------------------------------------------------------

echo "=== Blast Radius Analysis for Application: $APP (namespace: $NS) ==="
echo ""

# Use the fully-qualified CRD name to avoid ambiguity with app.k8s.io
RESOURCES=$("$KCTL" -n "$NS" get applications.argoproj.io "$APP" -o json 2>&1) || {
  echo "ERROR: Could not retrieve Application '$APP' in namespace '$NS'" >&2
  echo "Command: $KCTL -n $NS get applications.argoproj.io $APP -o json" >&2
  echo "Output: $RESOURCES" >&2
  exit 1
}

if [ -z "$RESOURCES" ]; then
  echo "ERROR: Empty response when retrieving Application '$APP'" >&2
  exit 1
fi

# Verify we got valid JSON back
if ! echo "$RESOURCES" | jq empty 2>/dev/null; then
  echo "ERROR: Response is not valid JSON" >&2
  echo "Response (first 500 chars): $(echo "$RESOURCES" | head -c 500)" >&2
  exit 1
fi

# --- Check whether .status.resources exists at all ------------------------------

HAS_RESOURCES=$(echo "$RESOURCES" | jq -r 'if .status.resources then "yes" else "no" end')

if [ "$HAS_RESOURCES" = "no" ]; then
  echo "WARNING: Application '$APP' has no .status.resources field." >&2
  echo "This typically means the Application has never been synced," >&2
  echo "or the controller has not yet populated the resource tree." >&2
  echo ""

  # Still print what we can: sync and health status
  SYNC_STATUS=$(echo "$RESOURCES" | jq -r '.status.sync.status // "Unknown"')
  HEALTH_STATUS=$(echo "$RESOURCES" | jq -r '.status.health.status // "Unknown"')
  OP_PHASE=$(echo "$RESOURCES" | jq -r '.status.operationState.phase // "None"')

  echo "Application status:"
  echo "  Sync:      $SYNC_STATUS"
  echo "  Health:    $HEALTH_STATUS"
  echo "  Last op:   $OP_PHASE"
  echo ""

  # Print conditions if any
  COND_COUNT=$(echo "$RESOURCES" | jq -r '[.status.conditions // [] | .[]] | length')
  if [ "$COND_COUNT" -gt 0 ]; then
    echo "=== Conditions ==="
    echo "$RESOURCES" | jq -r '
      .status.conditions // [] | .[] |
      "  \(.type): \(.message // "no message")"
    '
    echo ""
  fi

  exit 2
fi

# --- Compute summary counts -----------------------------------------------------

TOTAL=$(echo "$RESOURCES" | jq -r '[.status.resources[] ] | length')
HEALTHY=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.health.status == "Healthy")] | length')
SYNCED=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.status == "Synced")] | length')
DEGRADED=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.health.status == "Degraded")] | length')
PROGRESSING=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.health.status == "Progressing")] | length')
SUSPENDED=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.health.status == "Suspended")] | length')
MISSING=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.health.status == "Missing")] | length')
UNKNOWN_HEALTH=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.health.status == null or .health.status == "Unknown")] | length')
OUTOFSYNC=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.status == "OutOfSync")] | length')
UNKNOWN_SYNC=$(echo "$RESOURCES" | jq -r '[.status.resources[] | select(.status == null or .status == "Unknown")] | length')

# Distinguish zero (verified healthy) from "field not present" (unknown)
echo "Total managed resources: $TOTAL"
echo ""
echo "  Health breakdown:"
echo "    Healthy:      $HEALTHY"
echo "    Degraded:     $DEGRADED"
echo "    Progressing:  $PROGRESSING"
echo "    Suspended:    $SUSPENDED"
echo "    Missing:      $MISSING"
if [ "$UNKNOWN_HEALTH" -gt 0 ]; then
  echo "    Unknown:      $UNKNOWN_HEALTH  (health status not reported by Argo CD)"
fi
echo ""
echo "  Sync breakdown:"
echo "    Synced:       $SYNCED"
echo "    OutOfSync:    $OUTOFSYNC"
if [ "$UNKNOWN_SYNC" -gt 0 ]; then
  echo "    Unknown:      $UNKNOWN_SYNC  (sync status not reported by Argo CD)"
fi
echo ""

# --- Problem resources ----------------------------------------------------------

PROBLEM_COUNT=$((DEGRADED + OUTOFSYNC + MISSING + UNKNOWN_HEALTH + UNKNOWN_SYNC))

if [ "$PROBLEM_COUNT" -gt 0 ]; then
  echo "=== Problem Resources ($PROBLEM_COUNT) ==="
  echo "$RESOURCES" | jq -r '
    .status.resources[] |
    select(
      (.health.status != "Healthy" and .health.status != "Progressing" and .health.status != "Suspended")
      or .health.status == null
      or (.status != "Synced")
      or .status == null
    ) |
    "\(.group // "core")/\(.kind)  \(.namespace // "cluster-scoped")/\(.name)  health=\(.health.status // "<none>")  sync=\(.status // "<none>")"
  '
  echo ""
fi

# --- Progressing resources (informational, not necessarily a problem) -----------

if [ "$PROGRESSING" -gt 0 ]; then
  echo "=== Progressing Resources ($PROGRESSING) ==="
  echo "  (These may be actively reconciling; re-check after 60 seconds.)"
  echo "$RESOURCES" | jq -r '
    .status.resources[] |
    select(.health.status == "Progressing") |
    "\(.group // "core")/\(.kind)  \(.namespace // "cluster-scoped")/\(.name)  sync=\(.status // "<none>")"
  '
  echo ""
fi

# --- All managed resources ------------------------------------------------------

echo "=== All Managed Resources ($TOTAL) ==="
echo "$RESOURCES" | jq -r '
  .status.resources[] |
  "\(.group // "core")/\(.kind)  \(.namespace // "cluster-scoped")/\(.name)  health=\(.health.status // "<none>")  sync=\(.status // "<none>")"
' | sort
echo ""

# --- Application-level status summary -------------------------------------------

echo "=== Application Status ==="
SYNC_STATUS=$(echo "$RESOURCES" | jq -r '.status.sync.status // "Unknown"')
HEALTH_STATUS=$(echo "$RESOURCES" | jq -r '.status.health.status // "Unknown"')
OP_PHASE=$(echo "$RESOURCES" | jq -r '.status.operationState.phase // "None"')
OP_MESSAGE=$(echo "$RESOURCES" | jq -r '.status.operationState.message // "none"')
REVISION=$(echo "$RESOURCES" | jq -r '.status.sync.revision // "unknown"')

echo "  Sync status:    $SYNC_STATUS"
echo "  Health status:  $HEALTH_STATUS"
echo "  Last operation: $OP_PHASE"
echo "  Last message:   $OP_MESSAGE"
echo "  Revision:       $(echo "$REVISION" | head -c 12)"
echo ""

# Print conditions if any
COND_COUNT=$(echo "$RESOURCES" | jq -r '[.status.conditions // [] | .[]] | length')
if [ "$COND_COUNT" -gt 0 ]; then
  echo "=== Conditions ($COND_COUNT) ==="
  echo "$RESOURCES" | jq -r '
    .status.conditions // [] | .[] |
    "  \(.type): \(.message // "no message")"
  '
  echo ""
fi

# --- Exit code reflects health --------------------------------------------------

if [ "$PROBLEM_COUNT" -gt 0 ]; then
  echo "Result: $PROBLEM_COUNT resource(s) need attention."
  exit 2
else
  echo "Result: All $TOTAL resources are healthy and synced."
  exit 0
fi
