---
name: create-backup
description: Trigger, monitor, and verify an OADP/Velero backup of one or more OpenShift namespaces. Use when a user wants to back up a namespace or application, or protect workloads before an upgrade or risky change. Not for restoring (use restore-backup), recurring backups (use schedule-backup), or diagnosing an already-failed backup (use diagnose).
license: Apache-2.0
compatibility: Requires an authenticated OpenShift oc session, the oc-oadp plugin configured in admin mode, bash, and jq.
---

# Environment

- Platform: OpenShift Container Platform (OCP) with OADP installed. OADP manages Velero and its resources.
- OADP is installed in a namespace (default `openshift-adp`, override with the `OADP_NAMESPACE` env var). A `DataProtectionApplication` (DPA) configures Velero and one or more `BackupStorageLocation` (BSL) objects.
- A backup is a `Backup` custom resource (`velero.io/v1`) created in the OADP namespace. Velero reconciles it and reports progress in `.status`.
- The skill leaves `includeClusterResources` unset. With selected namespaces, Velero may include related cluster-scoped resources such as PersistentVolumes needed by backed-up PVCs.
- You run commands against the live cluster. This skill uses the admin `Backup` API in the OADP namespace. Self-service `NonAdminBackup` uses a separate `oc oadp nonadmin backup` flow.
- Required CLIs: `oc`, the `oc-oadp` plugin in admin mode, and `jq`.

# Rules

- Always run `preflight.sh` before creating a backup. Do not create a backup against a broken install; surface the blockers instead.
- Use the `health-check` skill for a broader installation report when OADP readiness is unknown.
- Never invent namespace names, label selectors, or storage location names. The create script confirms namespaces exist.
- Creating a backup is a mutation. `create-backup.sh` previews the resource with `oc oadp backup create -o json` and submits it with `oc oadp backup create` only if the current identity can create and read Backup CRs. Otherwise it returns the preview, a create command, and RBAC for an admin to review. Report `created: false` clearly.
- Choose the volume backup method deliberately:
  - Filesystem backup (`--fs-backup`) needs a ready `node-agent` DaemonSet and eligible pod volumes.
  - Volume snapshots (`--snapshot-volumes`) need a CSI driver with snapshot support or a native snapshot plugin.
  - The flags are mutually exclusive in this skill. If neither is requested, Velero uses its configured defaults. Preflight reports `default_fs_backup`; the create script checks node-agent when that default is enabled. State the requested setting and the volume results observed after verification. A flag alone does not prove that volume data was captured.
- After creating a backup, monitor it to a terminal phase, then verify. Do not report success from `create-backup.sh` alone; success requires phase `Completed`, zero Backup errors, and no observed failed volume operations or missing snapshots.
- On `PartiallyFailed` or `Failed`, do not retry blindly. Surface the errors and use the diagnose skill if it is available.
- All scripts output JSON to stdout and return a structured error object on failure. Use `jq` for further filtering.
- Do not ask the user to run a command; gather the information yourself where you have access.
- Be concise. Evidence-backed statements, no filler.

# Tools

All scripts live under `scripts/` and output JSON. They resolve the OADP namespace from `OADP_NAMESPACE` (default `openshift-adp`) and auto-detect the DPA when only one exists. Preflight needs read access to the DPA, Velero deployment, node-agent, and BSLs. Full verification also needs list access to PodVolumeBackups and DataUploads.

- `bash scripts/preflight.sh [--dpa <name>] [--storage-location <name>]`: Check the DPA, Velero, node-agent, and selected BSL. The BSL must be Available and writable. Returns `ready`, `storage_location`, `default_fs_backup`, `available_bsls`, checks, and blockers.
- `bash scripts/create-backup.sh --namespaces <ns1,ns2> [options]`: Validate inputs and namespaces, repeat preflight, then create a new `Backup` through the OADP CLI. If permissions are insufficient or `--emit-only` is passed, return the CLI's JSON preview, `create_command`, and, when needed, RBAC. Returns `created`, `backup_name`, and `manifest`.
- `bash scripts/monitor-backup.sh --name <backup> [--timeout <s>] [--interval <s>]`: Poll until the backup reaches a terminal phase (`Completed`, `PartiallyFailed`, `Failed`, `FailedValidation`) or times out. Returns `phase`, `terminal`, `timed_out`, `progress`, `warnings`, `errors`.
- `bash scripts/verify-backup.sh --name <backup>`: Summarize phase, `succeeded`, warnings/errors, items, snapshot counts, PodVolumeBackup and DataUpload phases, and guidance. `inspection_errors` records volume resources that could not be listed; their counts are `null`, not zero.

## `create-backup.sh` options

- `--namespaces <list>`: Comma-separated namespaces to back up (required).
- `--name <name>`: Backup name (default: `<first-ns>-backup-<timestamp>`).
- `--selector <k=v,k=v>`: Label selector to limit backed-up resources. Use valid Kubernetes label keys and values.
- `--storage-location <name>`: BSL name. If omitted, use the single default BSL or the sole BSL. Specify one when selection is ambiguous.
- `--ttl <duration>`: Retention, e.g. `720h` (default: Velero default).
- `--fs-backup`: Filesystem backup for volumes (`defaultVolumesToFsBackup: true`).
- `--snapshot-volumes`: Volume snapshots (`snapshotVolumes: true`).
- `--dpa <name>`: DPA name when more than one exists in the namespace.
- `--emit-only`: Return the manifest and create command without creating the Backup. It still checks cluster readiness.

# Protocol

Follow these steps in order. Do not skip preflight, and do not claim success before verification.

## Step 1: Preflight

```bash
bash scripts/preflight.sh [--dpa <name>] [--storage-location <name>]
```

If `ready` is `false`, stop. Report the blockers. Common blockers: DPA not reconciled, no Velero deployment, no unique default BSL, or a selected BSL that is unavailable or read only. If `node_agent` is a warning, do not use `--fs-backup`.

## Step 2: Create the backup

Choose the volume option from the workload and cluster configuration. For persistent data, inspect PVCs and the configured backup path before choosing a flag. If you cannot establish which method protects the data, explain the uncertainty before creating the backup. `create-backup.sh` repeats preflight and refuses to create against a blocked install.

```bash
bash scripts/create-backup.sh --namespaces <ns> [--fs-backup|--snapshot-volumes] [--selector k=v]
```

Read the result:
- `created: true`: the Backup CR was created. Note the `backup_name`.
- `created: false` with `rbac` present: the identity lacks permission. Report the preview, `create_command`, and RBAC for admin review. Do not claim the backup started.
- `created: false` from `--emit-only`: hand back the manifest and create command.

## Step 3: Monitor to a terminal phase

```bash
bash scripts/monitor-backup.sh --name <backup_name>
```

If `timed_out` is `true`, the backup is still running. Report the current phase and progress; the user can re-run monitor with a longer `--timeout`.

## Step 4: Verify and report

```bash
bash scripts/verify-backup.sh --name <backup_name>
```

Report the final outcome:
- `succeeded: true`: phase `Completed`, zero Backup errors, and no observed failed volume operations or missing snapshots. State the namespaces, items, and observed volume results. If `inspection_errors` is nonempty, say that volume evidence is incomplete.
- Warnings present: completed but call out the warnings and how to inspect them.
- `PartiallyFailed` / `Failed` / `FailedValidation`: report the errors and guidance. Use the diagnose skill for volume failures when it is available.
