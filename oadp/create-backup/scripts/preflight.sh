#!/bin/bash
# Preflight: verify the OADP install is healthy enough to take a backup.
# Checks the DPA is reconciled, the Velero deployment is available, the
# node-agent DaemonSet is ready (needed for filesystem backups), and the
# selected BackupStorageLocation is Available and writable.
#
# Usage: preflight.sh [--dpa <name>] [--storage-location <name>]
#
# Output: JSON { ready, namespace, dpa, storage_location, default_fs_backup, available_bsls,
#                checks:[{name,status,detail}], blockers:[...] }

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command oc
check_cluster_access

DPA_NAME=""
STORAGE_LOCATION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dpa|--storage-location)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || error_json "MISSING_ARG" "$1 requires a value"
      if [[ "$1" == "--dpa" ]]; then DPA_NAME="$2"; else STORAGE_LOCATION="$2"; fi
      shift 2 ;;
    *) error_json "UNKNOWN_ARG" "Unknown option: $1" ;;
  esac
done

NS=$(oadp_namespace)
# resolve_dpa runs in a command substitution and prints a JSON error on failure;
# surface that captured JSON rather than letting set -e discard it silently.
DPA_NAME=$(resolve_dpa "$NS" "$DPA_NAME") || { printf '%s\n' "$DPA_NAME"; exit 1; }

CHECKS='[]'
BLOCKERS='[]'

add_check() {
  # name status detail  (status: ok|warn|error)
  CHECKS=$(echo "$CHECKS" | jq --arg n "$1" --arg s "$2" --arg d "$3" \
    '. + [{name:$n, status:$s, detail:$d}]')
  if [[ "$2" == "error" ]]; then
    BLOCKERS=$(echo "$BLOCKERS" | jq --arg d "$3" '. + [$d]')
  fi
}

# 1. DPA reconciled
DPA_JSON=$(oc get dataprotectionapplication "$DPA_NAME" -n "$NS" -o json 2>/dev/null) || \
  error_json "NOT_FOUND" "DPA $DPA_NAME not found in $NS" "Verify the DPA name and namespace"
require_json "$DPA_JSON" "DPA"
RECONCILED=$(echo "$DPA_JSON" | jq -r 'last(.status.conditions[]? | select(.type=="Reconciled") | .status) // ""')
if [[ "$RECONCILED" == "True" ]]; then
  add_check "dpa_reconciled" "ok" "DPA $DPA_NAME is reconciled"
else
  REASON=$(echo "$DPA_JSON" | jq -r 'last(.status.conditions[]? | select(.type=="Reconciled") | .message) // ""')
  add_check "dpa_reconciled" "error" "DPA $DPA_NAME is not reconciled: ${REASON:-unknown}"
fi

# 2. Velero deployment available
VELERO_JSON=$(oc get deployment velero -n "$NS" -o json 2>/dev/null) || VELERO_JSON=""
if [[ -z "$VELERO_JSON" ]]; then
  add_check "velero_deployment" "error" "Velero deployment not found in $NS"
else
  AVAIL=$(echo "$VELERO_JSON" | jq -r '.status.availableReplicas // 0')
  if [[ "$AVAIL" -ge 1 ]]; then
    add_check "velero_deployment" "ok" "Velero deployment has $AVAIL available replica(s)"
  else
    add_check "velero_deployment" "error" "Velero deployment has no available replicas"
  fi
fi

# 3. node-agent DaemonSet (required for filesystem/data-mover backups)
NA_JSON=$(oc get daemonset node-agent -n "$NS" -o json 2>/dev/null) || NA_JSON=""
FS_DISABLED=$(echo "$DPA_JSON" | jq -r '.spec.configuration.velero.disableFsBackup // false')
DEFAULT_FS_BACKUP=$(echo "$DPA_JSON" | jq -r '(.spec.configuration.velero // {}) as $v | if $v.defaultVolumesToFsBackup != null then $v.defaultVolumesToFsBackup else ($v.defaultVolumesToFSBackup // false) end')
if [[ "$FS_DISABLED" == "true" ]]; then
  add_check "node_agent" "warn" "DPA disables filesystem backup; do not use --fs-backup"
elif [[ -z "$NA_JSON" ]]; then
  add_check "node_agent" "warn" "node-agent DaemonSet not found; filesystem and data-mover backups will fail (snapshot-only backups are unaffected)"
else
  DESIRED=$(echo "$NA_JSON" | jq -r '.status.desiredNumberScheduled // 0')
  READY=$(echo "$NA_JSON" | jq -r '.status.numberReady // 0')
  if [[ "$DESIRED" -gt 0 && "$READY" -eq "$DESIRED" ]]; then
    add_check "node_agent" "ok" "node-agent ready ($READY/$DESIRED)"
  else
    add_check "node_agent" "warn" "node-agent not fully ready ($READY/$DESIRED); filesystem and data-mover backups may fail"
  fi
fi

# 4. Select the actual BSL Velero will use, then check that it is writable.
BSL_JSON=$(oc get backupstoragelocation -n "$NS" -o json 2>/dev/null) || \
  error_json "ACCESS_FAILED" "Cannot list BackupStorageLocations in $NS" "Check BSL read permission and cluster access"
require_json "$BSL_JSON" "BSL list"
AVAILABLE_BSLS=$(echo "$BSL_JSON" | jq '[.items[] | select(.status.phase=="Available" and .spec.accessMode!="ReadOnly") | .metadata.name]')
if [[ -z "$STORAGE_LOCATION" ]]; then
  DEFAULT_BSLS=$(echo "$BSL_JSON" | jq '[.items[] | select(.spec.default==true) | .metadata.name]')
  DEFAULT_COUNT=$(echo "$DEFAULT_BSLS" | jq 'length')
  TOTAL=$(echo "$BSL_JSON" | jq '.items | length')
  if [[ "$DEFAULT_COUNT" -eq 1 ]]; then
    STORAGE_LOCATION=$(echo "$DEFAULT_BSLS" | jq -r '.[0]')
  elif [[ "$DEFAULT_COUNT" -gt 1 ]]; then
    add_check "backup_storage_location" "error" "Multiple default BackupStorageLocations exist. Pass --storage-location."
  elif [[ "$TOTAL" -eq 0 ]]; then
    add_check "backup_storage_location" "error" "No BackupStorageLocation exists in $NS"
  elif [[ "$TOTAL" -eq 1 ]]; then
    STORAGE_LOCATION=$(echo "$BSL_JSON" | jq -r '.items[0].metadata.name')
  else
    add_check "backup_storage_location" "error" "No unique default BackupStorageLocation. Pass --storage-location."
  fi
fi
if [[ -n "$STORAGE_LOCATION" ]]; then
  SELECTED_BSL=$(echo "$BSL_JSON" | jq --arg name "$STORAGE_LOCATION" '[.items[] | select(.metadata.name==$name)] | first // null')
  if [[ "$SELECTED_BSL" == "null" ]]; then
    add_check "backup_storage_location" "error" "BackupStorageLocation $STORAGE_LOCATION not found in $NS"
  else
    BSL_PHASE=$(echo "$SELECTED_BSL" | jq -r '.status.phase // "Unknown"')
    BSL_MODE=$(echo "$SELECTED_BSL" | jq -r 'if .spec.accessMode == null or .spec.accessMode == "" then "ReadWrite" else .spec.accessMode end')
    if [[ "$BSL_PHASE" != "Available" || "$BSL_MODE" == "ReadOnly" ]]; then
      add_check "backup_storage_location" "error" "BackupStorageLocation $STORAGE_LOCATION is $BSL_PHASE with access mode $BSL_MODE; choose an Available, writable location"
    else
      add_check "backup_storage_location" "ok" "BackupStorageLocation $STORAGE_LOCATION is Available and writable"
    fi
  fi
else
  STORAGE_LOCATION=""
fi

READY=true
if [[ $(echo "$BLOCKERS" | jq 'length') -gt 0 ]]; then
  READY=false
fi

jq -n \
  --argjson ready "$READY" \
  --arg ns "$NS" \
  --arg dpa "$DPA_NAME" \
  --arg storage_location "$STORAGE_LOCATION" \
  --argjson default_fs_backup "$DEFAULT_FS_BACKUP" \
  --argjson checks "$CHECKS" \
  --argjson blockers "$BLOCKERS" \
  --argjson available_bsls "$AVAILABLE_BSLS" \
  '{ready:$ready, namespace:$ns, dpa:$dpa, storage_location:$storage_location, default_fs_backup:$default_fs_backup, available_bsls:$available_bsls, checks:$checks, blockers:$blockers}'
