---
name: restore-backup
description: Restore an application namespace from an OADP Backup, monitor the Restore, and verify its result. Use when a user asks to recover an application or namespace from an existing backup.
license: Apache-2.0
compatibility: Requires Python 3, an authenticated OpenShift oc session, and the oc-oadp plugin configured in admin mode.
---

# Restore an OADP backup

This skill creates a Velero `Restore` in the OADP namespace (default `openshift-adp`, configurable with `OADP_NAMESPACE`). It uses an existing Backup and the admin OADP CLI. It does not perform self-service `NonAdminRestore`.

1. Identify the exact Backup and source application namespaces. Never choose a backup based only on its name. Check its phase and age with `oc oadp backup describe <name> --details`. Run the `health-check` skill when installation state is unknown.
2. Choose target namespaces. Prefer a new namespace mapping such as `source:source-recovered`. The create script refuses an implicit in-place restore. Restoring into an existing target requires explicit `--allow-existing-target`; restoring into the original namespace requires explicit `--allow-in-place`. Explain that restored resources can affect existing workloads before using either option. A partially failed Backup requires explicit `--allow-partially-failed` and must be called out.
3. Run `python3 scripts/create_restore.py --from-backup <backup> --namespace-mappings source:target` with `--include-namespaces <sources>` when selecting a subset or when the Backup includes all namespaces. Use `--emit-only` to review the CLI preview without creating a Restore. The script checks the Backup phase, Velero, BSL, namespaces, targets, and permissions, then uses `oc oadp restore create`.
4. If `created` is true, run `python3 scripts/monitor_restore.py --name <restore>`, then `python3 scripts/verify_restore.py --name <restore>`. Report completion only for phase `Completed` with zero errors and no observed failed volume operations. Surface warnings, item counts, PodVolumeRestore and DataDownload phases, and any incomplete inspection. A completed Velero Restore does not prove application health; verify the recovered workload in its target namespace separately.
5. On `PartiallyFailed`, `Failed`, or `FailedValidation`, use the `diagnose` skill. Do not retry a restore into an existing namespace without understanding its partial effects.

Scripts return JSON. A create result with `created: false` is a preview or permission handoff, not a started Restore.
