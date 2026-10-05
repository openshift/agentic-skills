#!/bin/bash
# Verify a completed Velero Backup and summarize its outcome, including
# volume-level results (filesystem PodVolumeBackups and CSI/data-mover
# DataUploads). Produces actionable guidance when the backup did not fully
# succeed.
#
# Usage: verify-backup.sh --name <backup>
#
# Output: JSON {
#   name, phase, succeeded, namespaces, storage_location, warnings, errors,
#   items_backed_up, total_items, volume_snapshots,
#   volume_backups: { pod_volume_backups:{by_phase}, data_uploads:{by_phase} },
#   inspection_errors: [ ... ], guidance: [ ... ]
# }

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command oc
check_cluster_access

NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || error_json "MISSING_ARG" "$1 requires a value"
      NAME="$2"; shift 2 ;;
    *) error_json "UNKNOWN_ARG" "Unknown option: $1" ;;
  esac
done

require_arg "$NAME" "--name" "Usage: verify-backup.sh --name <backup>"

NS=$(oadp_namespace)

BACKUP_JSON=$(oc get backup "$NAME" -n "$NS" -o json 2>/dev/null) || \
  error_json "NOT_FOUND" "Backup $NAME not found in $NS" "Verify the backup name and OADP_NAMESPACE"
require_json "$BACKUP_JSON" "Backup"

PHASE=$(echo "$BACKUP_JSON" | jq -r '.status.phase // "New"')
WARNINGS=$(echo "$BACKUP_JSON" | jq -r '.status.warnings // 0')
ERRORS=$(echo "$BACKUP_JSON" | jq -r '.status.errors // 0')

# Volume backup summaries, keyed by the velero.io/backup-name label.
INSPECTION_ERRORS='[]'
phase_counts() {
  # $1 = resource kind
  local kind="$1"
  local json
  if ! json=$(oc get "$kind" -n "$NS" -l "velero.io/backup-name=$NAME" -o json 2>&1); then
    INSPECTION_ERRORS=$(jq --arg k "$kind" --arg detail "$json" '. + ["Cannot list " + $k + ": " + $detail]' <<< "$INSPECTION_ERRORS")
    PHASE_COUNTS='null'
    return
  fi
  require_json "$json" "$kind list"
  PHASE_COUNTS=$(jq '[.items[].status.phase // "Unknown"] | group_by(.) | map({(.[0]): length}) | add // {}' <<< "$json")
}

phase_counts podvolumebackups.velero.io
PVB_COUNTS=$PHASE_COUNTS
phase_counts datauploads.velero.io
DU_COUNTS=$PHASE_COUNTS

# Build guidance
GUIDANCE='[]'
add_guidance() { GUIDANCE=$(echo "$GUIDANCE" | jq --arg g "$1" '. + [$g]'); }

case "$PHASE" in
  Completed)
    if [[ "$WARNINGS" -gt 0 ]]; then
      add_guidance "Backup completed with $WARNINGS warning(s). Inspect with oc oadp -n $NS backup describe $NAME --details."
    fi
    ;;
  PartiallyFailed)
    add_guidance "Backup partially failed with $ERRORS error(s) and $WARNINGS warning(s). Some resources or volumes were not backed up."
    add_guidance "Inspect with oc oadp -n $NS backup describe $NAME --details and oc oadp -n $NS backup logs $NAME."
    add_guidance "Investigate CSI, data mover, and PodVolumeBackup failures for backup $NAME. Use the OADP diagnose skill if available."
    ;;
  Failed)
    add_guidance "Backup failed with $ERRORS error(s). Inspect with oc oadp -n $NS backup describe $NAME --details and oc oadp -n $NS backup logs $NAME."
    add_guidance "Investigate Velero, CSI, and data mover failures for backup $NAME. Use the OADP diagnose skill if available."
    ;;
  FailedValidation)
    REASONS=$(echo "$BACKUP_JSON" | jq -r '(.status.validationErrors // []) | join("; ")')
    add_guidance "Backup failed validation before running: ${REASONS:-see spec}. Fix the Backup spec (e.g. namespace names, storage location) and recreate."
    ;;
  New|InProgress|"")
    add_guidance "Backup is not in a terminal phase yet (phase: ${PHASE:-New}). Wait for it to finish with monitor-backup.sh --name $NAME before verifying."
    ;;
  *)
    add_guidance "Unexpected phase: $PHASE. Inspect with oc oadp -n $NS backup describe $NAME --details."
    ;;
esac

SUCCEEDED=false
[[ "$PHASE" == "Completed" && "$ERRORS" -eq 0 ]] && SUCCEEDED=true
if [[ "$SUCCEEDED" == true ]] && {
  jq -e 'any((. // {} | keys[]); . != "Completed")' <<< "$PVB_COUNTS" >/dev/null ||
  jq -e 'any((. // {} | keys[]); . != "Completed")' <<< "$DU_COUNTS" >/dev/null;
}; then
  SUCCEEDED=false
  add_guidance "A volume operation did not complete. Use the OADP diagnose skill before claiming the backup succeeded."
fi
if [[ "$SUCCEEDED" == true ]] && jq -e '
  (.status.csiVolumeSnapshotsAttempted // 0) > (.status.csiVolumeSnapshotsCompleted // 0) or
  (.status.volumeSnapshotsAttempted // 0) > (.status.volumeSnapshotsCompleted // 0)
' <<< "$BACKUP_JSON" >/dev/null; then
  SUCCEEDED=false
  add_guidance "Fewer volume snapshots completed than attempted. Inspect CSI or native snapshot failures with the OADP diagnose skill."
fi
if [[ $(jq 'length' <<< "$INSPECTION_ERRORS") -gt 0 ]]; then
  add_guidance "Volume results could not be fully inspected. Check read access to PodVolumeBackups and DataUploads."
fi

jq -n \
  --arg name "$NAME" \
  --argjson namespaces "$(echo "$BACKUP_JSON" | jq '.spec.includedNamespaces // []')" \
  --arg storage_location "$(echo "$BACKUP_JSON" | jq -r '.spec.storageLocation // ""')" \
  --arg phase "$PHASE" \
  --argjson succeeded "$SUCCEEDED" \
  --argjson warnings "$WARNINGS" \
  --argjson errors "$ERRORS" \
  --argjson items_backed_up "$(echo "$BACKUP_JSON" | jq '.status.progress.itemsBackedUp // 0')" \
  --argjson total_items "$(echo "$BACKUP_JSON" | jq '.status.progress.totalItems // 0')" \
  --argjson pvb "$PVB_COUNTS" \
  --argjson du "$DU_COUNTS" \
  --argjson volume_snapshots "$(echo "$BACKUP_JSON" | jq '{attempted:(.status.volumeSnapshotsAttempted // 0), completed:(.status.volumeSnapshotsCompleted // 0), csi_attempted:(.status.csiVolumeSnapshotsAttempted // 0), csi_completed:(.status.csiVolumeSnapshotsCompleted // 0)}')" \
  --argjson inspection_errors "$INSPECTION_ERRORS" \
  --argjson guidance "$GUIDANCE" \
  '{
     name:$name, phase:$phase, succeeded:$succeeded,
     namespaces:$namespaces, storage_location:$storage_location,
     warnings:$warnings, errors:$errors,
     items_backed_up:$items_backed_up, total_items:$total_items,
     volume_snapshots:$volume_snapshots,
     volume_backups: { pod_volume_backups:$pvb, data_uploads:$du },
     inspection_errors:$inspection_errors,
     guidance:$guidance
   }'
