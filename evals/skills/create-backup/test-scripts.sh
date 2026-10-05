#!/bin/bash
# Exercise the OADP scripts with a fake oc and OADP CLI, without touching a cluster.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/../../../oadp/create-backup" && pwd)"
TEST_TMP=$(mktemp -d)
trap 'rm -rf "$TEST_TMP"' EXIT
export MOCK_CREATED_FILE="$TEST_TMP/created.json"
DEFAULT_BSL_JSON='{"items":[{"metadata":{"name":"primary"},"spec":{"default":true,"accessMode":"ReadWrite"},"status":{"phase":"Available"}}]}'
export MOCK_BSL_JSON="$DEFAULT_BSL_JSON"
export PATH="$TEST_TMP:$PATH"

cat > "$TEST_TMP/oc" <<'EOF'
#!/bin/bash
set -euo pipefail
case "$1" in
  whoami) echo "${MOCK_IDENTITY:-test-user}" ;;
  auth) [[ "${MOCK_DENY_CREATE:-0}" != 1 ]] ;;
  get)
    case "$2" in
      namespace)
        [[ "$3" == wordpress || "$3" == db ]] || exit 1
        echo "namespace/$3" ;;
      dataprotectionapplication)
        if [[ " $* " == *jsonpath* ]]; then
          echo dpa
        else
          printf '{"spec":{"configuration":{"velero":{"disableFsBackup":%s,"defaultVolumesToFsBackup":%s}}},"status":{"conditions":[{"type":"Reconciled","status":"True"}]}}\n' "${MOCK_FS_DISABLED:-false}" "${MOCK_DEFAULT_FS:-false}"
        fi ;;
      deployment)
        echo '{"status":{"availableReplicas":1}}' ;;
      daemonset)
        printf '{"status":{"desiredNumberScheduled":2,"numberReady":%s}}\n' "${MOCK_NODE_AGENT_READY:-2}" ;;
      backupstoragelocation)
        printf '%s\n' "$MOCK_BSL_JSON" ;;
      backup)
        echo '{"metadata":{"name":"wordpress-backup","namespace":"openshift-adp"},"spec":{"includedNamespaces":["wordpress"],"storageLocation":"primary"},"status":{"phase":"Completed","warnings":0,"errors":0,"progress":{"itemsBackedUp":4,"totalItems":4},"csiVolumeSnapshotsCompleted":1}}' ;;
      podvolumebackups.velero.io)
        echo '{"items":[{"status":{"phase":"Completed"}}]}' ;;
      datauploads.velero.io)
        [[ "${MOCK_DENY_DU:-0}" != 1 ]] || { echo forbidden >&2; exit 1; }
        if [[ -n "${MOCK_DU_PHASE:-}" ]]; then
          printf '{"items":[{"status":{"phase":"%s"}}]}\n' "$MOCK_DU_PHASE"
        else
          echo '{"items":[]}'
        fi ;;
      *) echo "unexpected get: $*" >&2; exit 2 ;;
    esac ;;
  oadp)
    shift
    [[ "$1" == -n ]] || exit 2
    ns="$2"; shift 2
    [[ "$1" == backup && "$2" == create ]] || exit 2
    name="$3"; shift 3
    namespaces='[]' storage='' selector='' ttl='' fs='' snapshots='' cluster='' preview=false
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --include-namespaces) [[ "$namespaces" == '[]' ]] || exit 2; namespaces=$(jq -n --arg ns "$2" '$ns | split(",")'); shift 2 ;;
        --storage-location) storage="$2"; shift 2 ;;
        --selector) selector="$2"; shift 2 ;;
        --ttl) ttl="$2"; shift 2 ;;
        --default-volumes-to-fs-backup=*) fs="${1#*=}"; shift ;;
        --snapshot-volumes=*) snapshots="${1#*=}"; shift ;;
        --include-cluster-resources=*) cluster="${1#*=}"; shift ;;
        -o) [[ "$2" == json ]] || exit 2; preview=true; shift 2 ;;
        *) echo "unexpected OADP CLI option: $1" >&2; exit 2 ;;
      esac
    done
    [[ -z "$cluster" && "$namespaces" != '[]' && -n "$storage" ]] || exit 2
    manifest=$(jq -n --arg name "$name" --arg ns "$ns" --argjson namespaces "$namespaces" \
      --arg storage "$storage" --arg selector "$selector" --arg ttl "$ttl" \
      --arg fs "$fs" --arg snapshots "$snapshots" \
      '{apiVersion:"velero.io/v1",kind:"Backup",metadata:{name:$name,namespace:$ns},
        spec:({includedNamespaces:$namespaces,storageLocation:$storage}
          + (if $selector != "" then {labelSelector:{matchLabels:($selector|split("=")|{(.[0]):.[1]})}} else {} end)
          + (if $ttl != "" then {ttl:$ttl} else {} end)
          + (if $fs != "" then {defaultVolumesToFsBackup:($fs=="true")} else {} end)
          + (if $snapshots != "" then {snapshotVolumes:($snapshots=="true")} else {} end))}')
    if [[ "$preview" == true ]]; then
      printf '%s\n' "$manifest"
    else
      printf '%s\n' "$manifest" > "$MOCK_CREATED_FILE"
      [[ "${MOCK_CREATE_FAIL:-0}" != 1 ]] || { echo 'AlreadyExists: backups.velero.io' >&2; exit 1; }
      echo "Backup request \"$name\" submitted successfully."
    fi ;;
  *) echo "unexpected oc: $*" >&2; exit 2 ;;
esac
EOF
chmod +x "$TEST_TMP/oc"

assert() {
  local expression="$1" json="$2"
  jq -e "$expression" <<< "$json" >/dev/null || { echo "assertion failed: $expression" >&2; printf '%s\n' "$json" >&2; exit 1; }
}

result=$(bash "$SKILL_DIR/scripts/preflight.sh")
assert '.ready == true and .storage_location == "primary"' "$result"

export MOCK_BSL_JSON='{"items":[{"metadata":{"name":"primary"},"spec":{"default":true,"accessMode":"ReadOnly"},"status":{"phase":"Available"}}]}'
result=$(bash "$SKILL_DIR/scripts/preflight.sh")
assert '.ready == false and (.blockers | length) == 1' "$result"
: > "$MOCK_CREATED_FILE"
if result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --name wordpress-backup); then
  echo 'read-only storage location unexpectedly accepted' >&2; exit 1
fi
assert '.code == "PREFLIGHT_FAILED" and .preflight.ready == false' "$result"
[[ ! -s "$MOCK_CREATED_FILE" ]] || { echo 'blocked preflight created a Backup' >&2; exit 1; }
export MOCK_BSL_JSON="$DEFAULT_BSL_JSON"

export MOCK_BSL_JSON='{"items":[{"metadata":{"name":"primary"},"spec":{"accessMode":"ReadWrite"},"status":{"phase":"Available"}},{"metadata":{"name":"secondary"},"spec":{"accessMode":"ReadWrite"},"status":{"phase":"Available"}}]}'
result=$(bash "$SKILL_DIR/scripts/preflight.sh")
assert '.ready == false and .storage_location == ""' "$result"
result=$(bash "$SKILL_DIR/scripts/preflight.sh" --storage-location secondary)
assert '.ready == true and .storage_location == "secondary"' "$result"
result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --storage-location secondary --emit-only)
assert '.created == false and .storage_location == "secondary"' "$result"
export MOCK_BSL_JSON="$DEFAULT_BSL_JSON"

export MOCK_FS_DISABLED=true
if result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --fs-backup); then
  echo 'disabled filesystem backup unexpectedly accepted' >&2; exit 1
fi
assert '.code == "FS_BACKUP_UNAVAILABLE"' "$result"
unset MOCK_FS_DISABLED

export MOCK_DEFAULT_FS=true MOCK_NODE_AGENT_READY=0
result=$(bash "$SKILL_DIR/scripts/preflight.sh")
assert '.ready == true and .default_fs_backup == true and (.checks[] | select(.name == "node_agent") | .status) == "warn"' "$result"
if result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress); then
  echo 'unavailable default filesystem backup unexpectedly accepted' >&2; exit 1
fi
assert '.code == "FS_BACKUP_UNAVAILABLE"' "$result"
result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --snapshot-volumes --emit-only)
assert '.created == false and .storage_location == "primary"' "$result"
unset MOCK_DEFAULT_FS MOCK_NODE_AGENT_READY

result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --name wordpress-backup --fs-backup)
assert '.created == true and .storage_location == "primary"' "$result"
assert '.spec.includedNamespaces == ["wordpress"] and .spec.includeClusterResources == null and .spec.defaultVolumesToFsBackup == true and .spec.snapshotVolumes == false and .spec.storageLocation == "primary"' "$(cat "$MOCK_CREATED_FILE")"

result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress,db --emit-only)
assert '.spec.includedNamespaces == ["wordpress", "db"]' "$(jq -r .manifest <<< "$result")"

result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --snapshot-volumes --emit-only)
assert '.spec.snapshotVolumes == true and .spec.defaultVolumesToFsBackup == false' "$(jq -r .manifest <<< "$result")"

result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --selector app.kubernetes.io/name=wordpress --emit-only)
assert '.created == false and (.create_command | startswith("oc oadp"))' "$result"
assert '.spec.labelSelector.matchLabels["app.kubernetes.io/name"] == "wordpress"' "$(jq -r .manifest <<< "$result")"
if result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --selector $'app=foo"\nmalicious: true' --emit-only); then
  echo 'invalid selector unexpectedly accepted' >&2; exit 1
fi
assert '.code == "INVALID_SELECTOR"' "$result"
if result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces $'wordpress\ndb' --emit-only); then
  echo 'multiline namespace list unexpectedly accepted' >&2; exit 1
fi
assert '.code == "INVALID_NAMESPACE"' "$result"

export MOCK_DENY_CREATE=1
result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --name wordpress-backup)
assert '.created == false and (.rbac | contains("kind: RoleBinding"))' "$result"
unset MOCK_DENY_CREATE

export MOCK_CREATE_FAIL=1
if result=$(bash "$SKILL_DIR/scripts/create-backup.sh" --namespaces wordpress --name wordpress-backup); then
  echo 'existing backup unexpectedly accepted' >&2; exit 1
fi
assert '.code == "CREATE_FAILED"' "$result"
unset MOCK_CREATE_FAIL

if result=$(bash "$SKILL_DIR/scripts/monitor-backup.sh" --name wordpress-backup --interval 0); then
  echo 'zero polling interval unexpectedly accepted' >&2; exit 1
fi
assert '.code == "INVALID_INTERVAL"' "$result"
result=$(bash "$SKILL_DIR/scripts/monitor-backup.sh" --name wordpress-backup --timeout 0)
assert '.terminal == true and .phase == "Completed"' "$result"

export MOCK_DENY_DU=1
result=$(bash "$SKILL_DIR/scripts/verify-backup.sh" --name wordpress-backup)
assert '.succeeded == true and .volume_backups.data_uploads == null and (.inspection_errors | length) == 1 and .volume_snapshots.csi_completed == 1' "$result"
unset MOCK_DENY_DU

export MOCK_DU_PHASE=Failed
result=$(bash "$SKILL_DIR/scripts/verify-backup.sh" --name wordpress-backup)
assert '.succeeded == false and .volume_backups.data_uploads.Failed == 1' "$result"
unset MOCK_DU_PHASE

echo 'create-backup script tests passed'
