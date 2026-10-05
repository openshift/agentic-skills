---
name: diagnose
description: Investigate a failed or stalled OADP Backup or Restore, including CSI snapshots, filesystem volumes, and data-mover operations. Use for backup or restore errors and partial failures.
license: Apache-2.0
compatibility: Requires Python 3 and an authenticated OpenShift oc session; the oc-oadp plugin provides detailed logs.
---

# Diagnose an OADP operation

Run `python3 scripts/diagnose.py --kind backup --name <name>` or use `--kind restore`. Set `OADP_NAMESPACE` or pass `--namespace` when OADP is not in `openshift-adp`. The script only reads cluster resources. It returns the operation phase, findings with evidence and next steps, child volume operations, inspection errors, and OADP CLI commands for details and logs.

For backups, inspect the Backup's validation and error status, CSI and native snapshot counts, Backup-labeled VolumeSnapshots and VolumeSnapshotContents, PodVolumeBackups, DataUploads, BackupStorageLocation, Velero, and node-agent. For restores, inspect the Restore, its source Backup, Restore-labeled CSI snapshot objects when the source Backup used CSI snapshots, PodVolumeRestores, DataDownloads, storage location, Velero, and node-agent. Failed child operation messages are stronger evidence than top-level counts. Snapshot objects may have been cleaned up, so an empty list is not proof that no CSI snapshots were used.

Run the returned `oc oadp` describe and logs commands when the counts or child status do not explain the failure. Inspect Kubernetes events and relevant CSI or data-mover components as indicated by findings. Do not retry or delete an operation automatically. Separate observed failure states from hypotheses and identify missing permissions or incomplete inspection. Redact credentials and sensitive data before sharing logs outside the cluster team.
