#!/bin/bash
# Poll a Velero Backup until it reaches a terminal phase or a timeout.
#
# Usage: monitor-backup.sh --name <backup> [--timeout <seconds>] [--interval <seconds>]
#
# Terminal phases: Completed, PartiallyFailed, Failed, FailedValidation.
# Output: JSON { name, namespace, phase, terminal, timed_out, progress, start_timestamp, completion_timestamp }

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command oc
check_cluster_access

NAME=""
TIMEOUT=1800
INTERVAL=15
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name|--timeout|--interval)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || error_json "MISSING_ARG" "$1 requires a value"
      case "$1" in
        --name) NAME="$2" ;;
        --timeout) TIMEOUT="$2" ;;
        --interval) INTERVAL="$2" ;;
      esac
      shift 2 ;;
    *) error_json "UNKNOWN_ARG" "Unknown option: $1" ;;
  esac
done

require_arg "$NAME" "--name" "Usage: monitor-backup.sh --name <backup> [--timeout <seconds>] [--interval <seconds>]"
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || error_json "INVALID_TIMEOUT" "--timeout must be a non-negative integer"
[[ "$INTERVAL" =~ ^[0-9]+$ ]] || error_json "INVALID_INTERVAL" "--interval must be a positive integer"
TIMEOUT=$((10#$TIMEOUT))
INTERVAL=$((10#$INTERVAL))
[[ "$INTERVAL" -gt 0 ]] || error_json "INVALID_INTERVAL" "--interval must be a positive integer"

NS=$(oadp_namespace)

is_terminal() {
  case "$1" in
    Completed|PartiallyFailed|Failed|FailedValidation) return 0 ;;
    *) return 1 ;;
  esac
}

ELAPSED=0
PHASE=""
BACKUP_JSON=""
TIMED_OUT=false
while true; do
  BACKUP_JSON=$(oc get backup "$NAME" -n "$NS" -o json 2>/dev/null) || \
    error_json "NOT_FOUND" "Backup $NAME not found in $NS" "Verify the backup name and OADP_NAMESPACE"
  require_json "$BACKUP_JSON" "Backup"
  PHASE=$(echo "$BACKUP_JSON" | jq -r '.status.phase // "New"')
  if is_terminal "$PHASE"; then
    break
  fi
  if [[ "$ELAPSED" -ge "$TIMEOUT" ]]; then
    TIMED_OUT=true
    break
  fi
  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

TERMINAL=false
is_terminal "$PHASE" && TERMINAL=true

echo "$BACKUP_JSON" | jq \
  --argjson terminal "$TERMINAL" \
  --argjson timed_out "$TIMED_OUT" \
  '{
     name: .metadata.name,
     namespace: .metadata.namespace,
     phase: (.status.phase // "New"),
     terminal: $terminal,
     timed_out: $timed_out,
     progress: (.status.progress // {}),
     warnings: (.status.warnings // 0),
     errors: (.status.errors // 0),
     start_timestamp: (.status.startTimestamp // null),
     completion_timestamp: (.status.completionTimestamp // null)
   }'
