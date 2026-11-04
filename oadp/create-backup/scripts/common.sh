#!/bin/bash
# Shared functions for the create-backup skill tools.
# Source this file: . "$(dirname "$0")/common.sh"

set -euo pipefail

# --- JSON output helpers ---

error_json() {
  local code="$1"
  local message="$2"
  local suggestion="${3:-}"
  if [[ -n "$suggestion" ]]; then
    jq -n --arg c "$code" --arg m "$message" --arg s "$suggestion" \
      '{error:true, code:$c, message:$m, suggestion:$s}'
  else
    jq -n --arg c "$code" --arg m "$message" \
      '{error:true, code:$c, message:$m}'
  fi
  exit 1
}

# --- Argument and environment validation ---

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" &>/dev/null; then
    if [[ "$cmd" == "jq" ]]; then
      printf '%s\n' '{"error":true,"code":"MISSING_TOOL","message":"jq is not available on PATH","suggestion":"Install jq or verify the container image includes it"}'
      exit 1
    fi
    error_json "MISSING_TOOL" "$cmd is not available on PATH" "Install $cmd or verify the container image includes it"
  fi
}

require_arg() {
  local value="$1"
  local name="$2"
  local usage="${3:-}"
  if [[ -z "$value" ]]; then
    if [[ -n "$usage" ]]; then
      error_json "MISSING_ARG" "$name is required" "$usage"
    else
      error_json "MISSING_ARG" "$name is required"
    fi
  fi
}

# --- JSON validation ---

require_json() {
  local input="$1"
  local context="${2:-API response}"
  if ! echo "$input" | jq empty 2>/dev/null; then
    error_json "INVALID_JSON" "Failed to parse ${context} as JSON" \
      "The cluster API returned unexpected output"
  fi
}

# --- Cluster access ---

check_cluster_access() {
  if ! oc whoami &>/dev/null; then
    error_json "AUTH_FAILED" "Cannot authenticate to cluster" "Run: oc login <cluster-url>"
  fi
}

# --- OADP helpers ---

# The namespace where OADP/Velero is installed. Override with OADP_NAMESPACE.
oadp_namespace() {
  echo "${OADP_NAMESPACE:-openshift-adp}"
}

# Resolve the DataProtectionApplication name in the OADP namespace.
# Prints the name, or errors if zero / more than one exist and none was given.
resolve_dpa() {
  local ns="$1"
  local given="${2:-}"
  if [[ -n "$given" ]]; then
    echo "$given"
    return 0
  fi
  local names
  names=$(oc get dataprotectionapplication -n "$ns" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null) || \
    error_json "NOT_FOUND" "No DataProtectionApplication found in namespace $ns" \
      "Install OADP and create a DPA, or set OADP_NAMESPACE to the correct namespace"
  local count
  count=$(echo "$names" | wc -w | tr -d ' ')
  if [[ "$count" -eq 0 ]]; then
    error_json "NOT_FOUND" "No DataProtectionApplication found in namespace $ns" \
      "Create a DPA before backing up, or set OADP_NAMESPACE"
  elif [[ "$count" -gt 1 ]]; then
    error_json "AMBIGUOUS_DPA" "Multiple DPAs found in namespace $ns: $names" \
      "Pass the DPA name explicitly with --dpa <name>"
  fi
  echo "$names"
}

# Return 0 if the current identity can create Backup CRs in the namespace.
# Also check 'get', which monitoring and verification need after creation.
can_create_backups() {
  local ns="$1"
  oc auth can-i -q create backups.velero.io -n "$ns" &>/dev/null \
    && oc auth can-i -q get backups.velero.io -n "$ns" &>/dev/null
}

# Emit a Role and RoleBinding for the authenticated identity. Preflight already
# requires read access to the DPA, Velero deployment, and storage locations.
backup_rbac_snippet() {
  local ns="$1"
  local identity kind subject_extra=""
  identity=$(oc whoami)
  kind="User"
  if [[ "$identity" == system:serviceaccount:*:* ]]; then
    kind="ServiceAccount"
    subject_extra=${identity#system:serviceaccount:}
    subject_extra="    namespace: ${subject_extra%%:*}"
    identity=${identity##*:}
  else
    subject_extra="    apiGroup: rbac.authorization.k8s.io"
  fi
  cat <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: oadp-create-backup
  namespace: ${ns}
rules:
  - apiGroups: ["velero.io"]
    resources: ["backups"]
    verbs: ["get", "list", "create"]
  - apiGroups: ["velero.io"]
    resources: ["podvolumebackups", "datauploads"]
    verbs: ["list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  generateName: oadp-create-backup-
  namespace: ${ns}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: oadp-create-backup
subjects:
  - kind: ${kind}
    name: ${identity}
${subject_extra}
EOF
}
