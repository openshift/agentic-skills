#!/bin/bash
# Shared functions for investigate-alert tools.
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
    error_json "MISSING_TOOL" "$cmd is not available on PATH" "Install $cmd or verify the container image includes it"
  fi
}

require_env() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    error_json "NOT_CONFIGURED" "$var_name is not set" "Run: eval \$(bash tools/prometheus-setup.sh)"
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

# --- Cluster access ---

check_cluster_access() {
  if ! oc whoami &>/dev/null; then
    error_json "AUTH_FAILED" "Cannot authenticate to cluster" "Run: oc login <cluster-url>"
  fi
}

# --- URL encoding ---

urlencode() {
  printf '%s' "$1" | python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read()))"
}

# --- Date helpers ---

compute_cutoff() {
  local minutes="$1"
  date -u -d "${minutes} minutes ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || \
    date -u -d "@$(($(date +%s) - minutes * 60))" +%Y-%m-%dT%H:%M:%SZ
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

# --- Prometheus helpers ---

prometheus_get() {
  local path="$1"
  require_env TOKEN
  require_env THANOS_URL

  local http_code
  local tmpfile
  local stderr_file
  tmpfile=$(mktemp)
  stderr_file=$(mktemp)
  trap 'rm -f "$tmpfile" "$stderr_file"' RETURN

  wget -qO "$tmpfile" --no-check-certificate \
    --header="Authorization: Bearer $TOKEN" \
    --server-response \
    "https://${THANOS_URL}${path}" 2>"$stderr_file" || true

  http_code=$(grep "HTTP/" "$stderr_file" 2>/dev/null | tail -1 | awk '{print $2}') || true

  if [[ ! -s "$tmpfile" ]]; then
    error_json "PROMETHEUS_ERROR" "No response from Prometheus at ${THANOS_URL}${path}" \
      "Verify TOKEN and THANOS_URL with: eval \$(bash tools/prometheus-setup.sh)"
  fi

  if [[ -n "$http_code" && "$http_code" -ge 400 ]] 2>/dev/null; then
    local body
    body=$(cat "$tmpfile")
    case "$http_code" in
      401) error_json "AUTH_EXPIRED" "Prometheus returned 401 Unauthorized" \
             "Token may have expired. Re-run: eval \$(bash tools/prometheus-setup.sh)" ;;
      403) error_json "FORBIDDEN" "Prometheus returned 403 Forbidden" \
             "ServiceAccount lacks cluster-monitoring-view ClusterRoleBinding" ;;
      *)   error_json "PROMETHEUS_HTTP_${http_code}" "Prometheus returned HTTP ${http_code}" \
             "Response: ${body:0:200}" ;;
    esac
  fi

  cat "$tmpfile"
}
