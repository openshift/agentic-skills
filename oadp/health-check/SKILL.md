---
name: health-check
description: Check whether an OADP installation can run backup and restore workflows. Use for OADP readiness questions and before creating a backup, restore, or schedule on an unfamiliar cluster.
license: Apache-2.0
compatibility: Requires Python 3 and an authenticated OpenShift oc session.
---

# OADP health check

Run `python3 scripts/health_check.py` (or pass `--namespace <oadp-namespace>`). It reads the OADP Operator deployment, DataProtectionApplications, Velero deployment, node-agent DaemonSet, and BackupStorageLocations. It makes no cluster changes.

The JSON result has `ready`, `checks`, `blockers`, and `warnings`. Report each blocker and its affected component. A missing or unready node-agent is a warning unless a DPA defaults to filesystem backups, when it blocks readiness. A healthy result confirms these components are available at the time of inspection; it does not prove a backup or restore will succeed.

Use the installation namespace from the user or `OADP_NAMESPACE`; the default is `openshift-adp`. Do not guess resource names or suppress access errors. If `ready` is false, resolve the reported blocker before starting a backup, restore, or schedule. For a failed operation that already exists, use the `diagnose` skill.
