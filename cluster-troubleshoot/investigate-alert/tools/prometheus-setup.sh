#!/bin/bash
# Establish Prometheus access credentials for the session.
# Prints export commands to stdout for eval.
#
# Usage: eval $(bash tools/prometheus-setup.sh)

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command oc
require_command jq
check_cluster_access

TOKEN=$(oc whoami -t 2>/dev/null) || \
  error_json "AUTH_FAILED" "Cannot get bearer token" "Run: oc login <cluster-url>"

THANOS_URL=$(oc get route thanos-querier -n openshift-monitoring -o jsonpath='{.spec.host}' 2>/dev/null) || \
  error_json "ROUTE_NOT_FOUND" "thanos-querier route not found in openshift-monitoring" \
    "Verify the openshift-monitoring namespace exists and the route is exposed"

if [[ -z "$THANOS_URL" ]]; then
  error_json "ROUTE_NOT_FOUND" "thanos-querier route has no host" \
    "Check: oc get route thanos-querier -n openshift-monitoring"
fi

printf 'export TOKEN=%q\n' "$TOKEN"
printf 'export THANOS_URL=%q\n' "$THANOS_URL"
