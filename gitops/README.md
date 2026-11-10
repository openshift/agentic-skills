# GitOps skills

This directory contains skills that help AI agents design, generate, review,
and troubleshoot GitOps-based application delivery.

The skills may cover:

- General GitOps concepts and repository patterns
- Argo CD
- OpenShift GitOps Operator
- Argo Rollouts
- Argo Workflows
- Argo Events
- Multi-cluster and multi-tenant delivery

## Available skills

### argo-knowledge

Provides knowledge and guidance for the Argo ecosystem and OpenShift GitOps,
including manifest generation, architecture guidance, resource explanations,
best practices, and common configuration mistakes.

### argo-operator

Read-only diagnosis of behavior the OpenShift GitOps operator owns, where the fix is
an operator input — a label, a CR field, an operator environment variable — and never
the reconciled object itself.

Three topics:

| Topic | Symptom |
|---|---|
| Destination-namespace RBAC | Sync fails `forbidden` or `Unauthorized` |
| Apps in any namespace | An `Application` outside the Argo CD namespace is ignored, with no status at all |
| UI and CLI RBAC | A human sees no Applications, or gets `permission denied` |

Each is a different "permission denied" with an unrelated fix, so the skill routes on
cheap discriminating evidence before loading a reference.

Every topic is written for an automated run with no human available: it never asks a
question, and it reports the `ArgoCD` CR field rather than emitting a Role,
RoleBinding, or ConfigMap edit that the operator would revert.

This skill is the home for further operator-owned topics. Add each as a
`## Topic: <name>` section in `SKILL.md` with its own `references/` file and a row in
the reference table. Keep the split that already exists across the other skills:

| Belongs in | Content |
|------------|---------|
| `argo-operator` | Live diagnosis where the operator owns the object |
| `argo-knowledge/references/openshift-gitops-operator.md` | Operator CRD field reference |
| `argo-operations` | Installing or changing an operator-managed instance |
| `argo-cluster-debug` | Debugging that is not operator-owned |

### argo-app-sync-triage

Triages an Argo CD Application by its sync state — `OutOfSync`, sync status `Unknown`,
a sync that is stuck, one that failed, or `Synced` while the cluster is visibly wrong —
with one workflow per state. Covers how the diff is computed, why auto-sync declines to
run, and the distinction between diff state (`.status.sync.status`) and operation state
(`.status.operationState.phase`) that most sync misdiagnoses come from. The sibling of
`argo-app-health-triage`; read-only.

### argo-app-health-triage

Triages an Argo CD Application by its health status — `Degraded`, `Progressing`,
`Missing`, or `Unknown` — with one workflow per status. Covers how Argo CD computes
health (custom Lua first, then built-in per-kind checks) and how child health rolls up,
including the resources that are excluded and never affect it. Written to be usable by
an automated diagnosis run with no human in the loop.

### argo-cluster-debug

Debugs OpenShift GitOps on live clusters — Application and ApplicationSet inspection,
Argo Rollouts canary and blue-green failures, AnalysisRun results, controller logs, and
operator or OLM triage. Routes health and sync symptoms to `argo-app-health-triage` and
`argo-app-sync-triage` rather than handling them itself.

### argo-operations

Sets up, deploys, promotes, and manages OpenShift GitOps resources on live clusters —
installation, Application and ApplicationSet lifecycle, Rollout promotion and rollback,
and day-2 operations. Every write runs dry-run first and requires explicit confirmation
before applying. This is the write-capable skill; the triage skills are read-only.

### argo-performance-tuning

Diagnoses and tunes Argo CD performance at scale — reconciliation load, repo-server Git
and caching behavior, application-controller sharding and concurrency, self-heal pacing,
and API-server timeouts. Maps a symptom such as OOMKilled repo-server or a backed-up sync
queue to the specific setting that fixes it, for both standalone Argo CD and the operator.

### argo-repo-audit

Audits GitOps repositories by scanning local files rather than a live cluster — AppProject
RBAC and security restrictions, sync policies, optional schema validation, and a
prioritized report.

### argo-team-onboard

Onboards application teams the GitOps way, generating tenant config (AppProject,
Application, RBAC, Namespace, quotas, NetworkPolicies) and committing it to the GitOps
repo for Argo CD to reconcile rather than applying it imperatively.
