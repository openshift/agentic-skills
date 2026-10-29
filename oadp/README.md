# OADP skills

This directory contains Phase 1 skills for [OADP (OpenShift API for Data Protection)][oadp], the operator that installs and manages Velero for backup and restore on OpenShift.

- [`health-check`](health-check/SKILL.md) reports Operator, DPA, Velero, node-agent, and storage location readiness.
- [`create-backup`](create-backup/SKILL.md) creates, monitors, and verifies a namespace Backup.
- [`restore-backup`](restore-backup/SKILL.md) restores a Backup into explicitly chosen target namespaces, then monitors and verifies it.
- [`schedule-backup`](schedule-backup/SKILL.md) creates and verifies recurring namespace backups.
- [`diagnose`](diagnose/SKILL.md) investigates failed Backup and Restore operations, including CSI snapshots and data mover resources.

The skills use an authenticated OpenShift session and a configured `DataProtectionApplication` (DPA). Creation uses the `oc-oadp` plugin in admin mode. Read-only checks use `oc` resource JSON. Self-service non-admin workflows are planned separately.

[oadp]: https://docs.redhat.com/en/documentation/openshift_container_platform/latest/html/backup_and_restore/oadp-application-backup-and-restore
