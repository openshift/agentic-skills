#!/bin/bash
# Create a Velero Backup through the OADP CLI for one or more namespaces.
#
# By default this creates a new Backup on the cluster. If the current identity
# lacks permission, it returns the manifest and the RBAC an admin can grant.
#
# Usage:
#   create-backup.sh --namespaces <ns1,ns2> [options]
#
# Options:
#   --namespaces <list>        Comma-separated namespaces to back up (required)
#   --name <name>              Backup name (default: <first-ns>-backup-<timestamp>)
#   --selector <k=v,k=v>       Label selector to limit backed-up resources
#   --storage-location <name>  BackupStorageLocation name (default: unique default BSL)
#   --ttl <duration>           Backup retention, e.g. 720h (default: Velero default)
#   --fs-backup                Use filesystem backup for volumes (defaultVolumesToFsBackup=true)
#   --snapshot-volumes         Take volume snapshots (snapshotVolumes=true)
#   --dpa <name>               DPA name (default: the only DPA in the namespace)
#   --emit-only                Do not create; only return the CLI preview and command
#
# Output: JSON { created, backup_name, namespace, storage_location, manifest, create_command?, rbac?, note }

SCRIPT_DIR="$(dirname "$0")"
. "$SCRIPT_DIR/common.sh"

require_command jq
require_command oc
check_cluster_access

NAMESPACES=""
NAME=""
SELECTOR=""
STORAGE_LOCATION=""
TTL=""
FS_BACKUP=false
SNAPSHOT_VOLUMES=false
DPA_NAME=""
EMIT_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespaces|--name|--selector|--storage-location|--ttl|--dpa)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || error_json "MISSING_ARG" "$1 requires a value"
      case "$1" in
        --namespaces) NAMESPACES="$2" ;;
        --name) NAME="$2" ;;
        --selector) SELECTOR="$2" ;;
        --storage-location) STORAGE_LOCATION="$2" ;;
        --ttl) TTL="$2" ;;
        --dpa) DPA_NAME="$2" ;;
      esac
      shift 2 ;;
    --fs-backup) FS_BACKUP=true; shift ;;
    --snapshot-volumes) SNAPSHOT_VOLUMES=true; shift ;;
    --emit-only) EMIT_ONLY=true; shift ;;
    *) error_json "UNKNOWN_ARG" "Unknown option: $1" ;;
  esac
done

require_arg "$NAMESPACES" "--namespaces" "Usage: create-backup.sh --namespaces <ns1,ns2> [options]"
[[ "$NAMESPACES" != *$'\n'* && "$NAMESPACES" != *$'\r'* ]] || \
  error_json "INVALID_NAMESPACE" "Namespace list must be a single comma-separated line"
if [[ "$FS_BACKUP" == "true" && "$SNAPSHOT_VOLUMES" == "true" ]]; then
  error_json "CONFLICTING_OPTIONS" "Choose one volume method: --fs-backup or --snapshot-volumes"
fi

NS_ARR=()
IFS=',' read -ra RAW_NS_ARR <<< "$NAMESPACES"
for n in "${RAW_NS_ARR[@]}"; do
  if [[ ${#n} -gt 63 || ! "$n" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
    error_json "INVALID_NAMESPACE" "Invalid namespace name: $n" "Use comma-separated Kubernetes namespace names without spaces"
  fi
  NS_ARR+=("$n")
done
[[ ${#NS_ARR[@]} -gt 0 && "$NAMESPACES" != *, ]] || error_json "INVALID_NAMESPACE" "Namespace list contains an empty name"

if [[ -z "$NAME" ]]; then
  FIRST_NS="${NS_ARR[0]}"
  NAME="${FIRST_NS:0:39}-backup-$(date +%Y%m%d%H%M%S)"
fi
if [[ ${#NAME} -gt 63 || ! "$NAME" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  error_json "INVALID_NAME" "Invalid backup name: $NAME" "Use a DNS label of at most 63 characters"
fi
if [[ -n "$TTL" && ! "$TTL" =~ ^([0-9]+(h|m|s))+$ ]]; then
  error_json "INVALID_TTL" "Invalid TTL: $TTL" "Use a duration such as 720h or 1h30m"
fi

if [[ -n "$SELECTOR" ]]; then
  [[ "$SELECTOR" != *$'\n'* && "$SELECTOR" != *$'\r'* ]] || \
    error_json "INVALID_SELECTOR" "Selector must be a single comma-separated line"
  IFS=',' read -ra SEL_ARR <<< "$SELECTOR"
  [[ "$SELECTOR" != *, ]] || error_json "INVALID_SELECTOR" "Selector has an empty final pair"
  for pair in "${SEL_ARR[@]}"; do
    if [[ "$pair" != *=* || "$pair" == =* ]]; then
      error_json "INVALID_SELECTOR" "Invalid label selector pair: $pair" "Use key=value pairs separated by commas"
    fi
    key=${pair%%=*}
    val=${pair#*=}
    label_name=${key##*/}
    if [[ ${#label_name} -gt 63 || ! "$label_name" =~ ^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$ ]]; then
      error_json "INVALID_SELECTOR" "Invalid label key: $key"
    fi
    if [[ "$key" == */* ]]; then
      label_prefix=${key%/*}
      if [[ ${#label_prefix} -gt 253 || ! "$label_prefix" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]]; then
        error_json "INVALID_SELECTOR" "Invalid label key prefix: $key"
      fi
    fi
    if [[ ${#val} -gt 63 || ( -n "$val" && ! "$val" =~ ^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$ ) ]]; then
      error_json "INVALID_SELECTOR" "Invalid label value for $key"
    fi
  done
fi

NS=$(oadp_namespace)
for n in "${NS_ARR[@]}"; do
  oc get namespace "$n" -o name &>/dev/null || \
    error_json "NAMESPACE_NOT_FOUND" "Cannot read namespace $n" "Confirm the namespace exists and the identity can read it"
done

set --
[[ -n "$DPA_NAME" ]] && set -- "$@" --dpa "$DPA_NAME"
[[ -n "$STORAGE_LOCATION" ]] && set -- "$@" --storage-location "$STORAGE_LOCATION"
PREFLIGHT_JSON=$(bash "$SCRIPT_DIR/preflight.sh" "$@") || { printf '%s\n' "$PREFLIGHT_JSON"; exit 1; }
if [[ $(jq -r '.ready' <<< "$PREFLIGHT_JSON") != true ]]; then
  jq -n --argjson p "$PREFLIGHT_JSON" \
    '{error:true, code:"PREFLIGHT_FAILED", message:"OADP is not ready to create this backup", preflight:$p}'
  exit 1
fi
STORAGE_LOCATION=$(jq -r '.storage_location' <<< "$PREFLIGHT_JSON")
if [[ "$FS_BACKUP" == "true" && $(jq -r '.checks[] | select(.name=="node_agent") | .status' <<< "$PREFLIGHT_JSON") != ok ]]; then
  error_json "FS_BACKUP_UNAVAILABLE" "Filesystem backup requires a ready node-agent DaemonSet and must be enabled in the DPA"
fi
if [[ "$FS_BACKUP" == "false" && "$SNAPSHOT_VOLUMES" == "false" && $(jq -r '.default_fs_backup' <<< "$PREFLIGHT_JSON") == true && $(jq -r '.checks[] | select(.name=="node_agent") | .status' <<< "$PREFLIGHT_JSON") != ok ]]; then
  error_json "FS_BACKUP_UNAVAILABLE" "The DPA defaults to filesystem backup, but node-agent is not ready or filesystem backup is disabled"
fi

# The OADP CLI builds the exact Backup resource it will submit. Its -o json
# option prints that resource without creating it.
CLI_ARGS=(oadp -n "$NS" backup create "$NAME"
  --storage-location "$STORAGE_LOCATION"
  --include-namespaces "$NAMESPACES")
[[ -n "$SELECTOR" ]] && CLI_ARGS+=(--selector "$SELECTOR")
[[ -n "$TTL" ]] && CLI_ARGS+=(--ttl "$TTL")
if [[ "$FS_BACKUP" == true ]]; then
  CLI_ARGS+=(--default-volumes-to-fs-backup=true --snapshot-volumes=false)
elif [[ "$SNAPSHOT_VOLUMES" == true ]]; then
  CLI_ARGS+=(--default-volumes-to-fs-backup=false --snapshot-volumes=true)
fi
CREATE_CMD=$(printf ' %q' oc "${CLI_ARGS[@]}")
CREATE_CMD=${CREATE_CMD# }
MANIFEST=$(oc "${CLI_ARGS[@]}" -o json 2>&1) || \
  error_json "CLI_PREVIEW_FAILED" "OADP CLI could not preview Backup $NAME: $MANIFEST" \
    "Install oc-oadp and configure its admin mode, then check the command and current cluster access"
require_json "$MANIFEST" "OADP CLI backup preview"
NAMESPACES_JSON=$(printf '%s\n' "${NS_ARR[@]}" | jq -R . | jq -s .)
if ! jq -e --arg name "$NAME" --arg ns "$NS" \
  --arg sl "$STORAGE_LOCATION" --argjson namespaces "$NAMESPACES_JSON" \
  --argjson fs "$FS_BACKUP" --argjson snapshots "$SNAPSHOT_VOLUMES" \
  '.kind == "Backup" and .metadata.name == $name and .metadata.namespace == $ns
   and .spec.storageLocation == $sl and .spec.includedNamespaces == $namespaces
   and (if $fs then .spec.defaultVolumesToFsBackup == true and .spec.snapshotVolumes == false
        elif $snapshots then .spec.defaultVolumesToFsBackup == false and .spec.snapshotVolumes == true
        else true end)' \
  <<< "$MANIFEST" >/dev/null; then
  error_json "INVALID_PREVIEW" "OADP CLI preview does not match the requested Backup in $NS"
fi

emit_result() {
  # created note [create_command] [rbac]
  local created="$1"; local note="$2"; local create_cmd="${3:-}"; local rbac="${4:-}"
  jq -n \
    --argjson created "$created" \
    --arg name "$NAME" \
    --arg ns "$NS" \
    --arg sl "$STORAGE_LOCATION" \
    --arg manifest "$MANIFEST" \
    --arg create_cmd "$create_cmd" \
    --arg rbac "$rbac" \
    --arg note "$note" \
    '{created:$created, backup_name:$name, namespace:$ns, storage_location:$sl, manifest:$manifest, note:$note}
     + (if $create_cmd != "" then {create_command:$create_cmd} else {} end)
     + (if $rbac != "" then {rbac:$rbac} else {} end)'
}

if [[ "$EMIT_ONLY" == "true" ]]; then
  emit_result false "emit-only mode: run the OADP CLI command to start the backup, then monitor with monitor-backup.sh --name ${NAME}" "$CREATE_CMD" ""
  exit 0
fi

if ! can_create_backups "$NS"; then
  RBAC="$(backup_rbac_snippet "$NS")"
  emit_result false "current identity cannot create and read backups.velero.io in ${NS}; an admin can grant the RBAC below, then run the OADP CLI command" "$CREATE_CMD" "$RBAC"
  exit 0
fi

# Create a new object. Never patch an existing backup with the same name.
if CREATE_OUTPUT=$(oc "${CLI_ARGS[@]}" 2>&1); then
  emit_result true "backup ${NAME} created in ${NS}; monitor progress with monitor-backup.sh --name ${NAME}" "" ""
else
  error_json "CREATE_FAILED" "Failed to create Backup ${NAME} in ${NS}: $CREATE_OUTPUT" \
    "Check the API error and retry with a new backup name after fixing the cause"
fi
