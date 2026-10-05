---
name: schedule-backup
description: Create and verify recurring OADP namespace backups. Use when a user wants periodic backups or a backup schedule, not a one-time backup.
license: Apache-2.0
compatibility: Requires Python 3, an authenticated OpenShift oc session, and the oc-oadp plugin configured in admin mode.
---

# Schedule an OADP backup

This skill creates a Velero `Schedule` in the OADP namespace (default `openshift-adp`, configurable with `OADP_NAMESPACE`). The schedule template targets the requested application namespaces. Velero's automatic cluster-resource selection can include related persistent volumes. A `BackupStorageLocation` (BSL) must be Available and writable.

1. Confirm the requested application namespaces, UTC cron expression or `@every` interval, retention, storage location, and volume method. Do not invent values. Run the `health-check` skill when the installation state is unknown.
2. Run `python3 scripts/create_schedule.py --name <name> --namespaces <ns1,ns2> --schedule '<UTC cron or @every duration>'` with any explicitly chosen options. The script validates the DPA, Velero, BSL, namespaces, and node-agent when filesystem backup is selected. It previews the resource with the OADP CLI, then creates it if permitted. Use `--emit-only` to return the preview and command without creating it. By default it skips an immediate backup; use `--run-immediately` only when an immediate backup is requested. `--paused` creates a paused schedule. Optional `--storage-location`, `--ttl`, `--fs-backup`, and `--snapshot-volumes` mirror the create-backup skill.
3. If `created` is false, report the missing permission or preview and do not claim the schedule is active. If created, run `python3 scripts/verify_schedule.py --name <name>`. An `Enabled` phase with `ready: true` means the schedule controller accepted it. `FailedValidation`, a timeout, or a paused schedule is not an active recurring backup.
4. Report the schedule expression in UTC, namespaces, BSL, retention, phase, and `last_backup`. A newly enabled schedule may have no backup yet. Verify an actual generated Backup before claiming the application is protected. For backup failures, use the `diagnose` skill.

The scripts return JSON. They do not modify or delete an existing Schedule. Self-service non-admin schedules are outside this Phase 1 admin workflow.
