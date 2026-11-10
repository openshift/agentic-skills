---
name: argo-app-sync-triage
description: >
  Triage an Argo CD Application by its sync state — OutOfSync, sync status Unknown, a
  sync operation that is stuck, one that Failed or Errored, or Synced while the cluster
  is visibly wrong — and name one root cause backed by cluster evidence. Explains how
  Argo CD computes the diff (desired manifests versus live, after ignoreDifferences and
  the resource tracking method) and why auto-sync declines to run. Routes to one
  workflow per state. Use when the sync status or a sync operation is the symptom, when
  a change was pushed to git and did not reach the cluster, or when an automated
  diagnosis was triggered by a sustained OutOfSync. Read-only. Not for health status,
  which is skills/gitops/argo-app-health-triage.
license: MIT
compatibility: Requires oc or kubectl
---

# Argo CD Application sync triage

Sync status, not health status. An Application can be `Synced` and `Degraded` at the
same time — the live state matches git and the workload is still broken — and it can be
`OutOfSync` and `Healthy`, where everything is running and simply is not what git says.
Reconciling fixes only the second one.

If the symptom is that a workload is broken rather than that it does not match git, stop
and use `skills/gitops/argo-app-health-triage` instead.

This skill is read-only. Diagnose and report. Do not apply changes, and do not run
`argocd app sync`.

## You are probably running non-interactively

This skill is written to be usable by an automated diagnosis run with no human in the
loop. If no one can answer a question, do not ask one. Gather the evidence you can
reach, name the most probable cause, and state your confidence and what you could not
check. An honest `Low` confidence diagnosis is useful. A question is not.

## How Argo CD computes sync status

For each managed resource, the controller compares the **desired** manifest against the
**live** object and normalizes before deciding:

1. Render the source — plain manifests, Helm, Kustomize, or a config management plugin.
   A render failure means there is no desired state, so the status becomes `Unknown`
   with a `ComparisonError` condition. Nothing is compared.
2. Find the live object using the **resource tracking method**. Default is `label`,
   matching `app.kubernetes.io/instance`. If the method is `annotation` the key is
   `argocd.argoproj.io/tracking-id`. A resource the method cannot match is treated as
   not existing, so the app is `OutOfSync` and a second copy may be created on sync.
3. Normalize: drop fields Argo CD knows the API server defaults, then apply
   `spec.ignoreDifferences` on the Application and
   `resource.customizations.ignoreDifferences.<group>_<Kind>` from `argocd-cm`.
4. Anything left is a difference. One differing resource makes the whole Application
   `OutOfSync`.

The three sync statuses are `Synced`, `OutOfSync`, and `Unknown`. They describe the
**diff**, not whether a sync ran. A sync operation has its own separate phase.

### Diff state and operation state are different things

This is the distinction that drives the whole triage, and conflating the two is the most
common way a sync diagnosis goes wrong:

| Field | What it means |
|---|---|
| `.status.sync.status` | The result of the most recent comparison. A fact about the diff right now. |
| `.status.operationState.phase` | The outcome of the last sync **operation**: `Running`, `Terminating`, `Failed`, `Error`, or `Succeeded`. |

An Application can read `Synced` with `.status.operationState.phase: Failed` — the
failed sync was followed by a comparison that found no diff. It can also read
`OutOfSync` with phase `Succeeded`, when the sync worked and something changed the
cluster afterwards. **Read both before routing.** A status alone does not tell you
whether a sync was attempted.

## Before any check

Resolve the CLI. On OpenShift, `oc` is the default.

```bash
if command -v oc >/dev/null 2>&1 && oc api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes; then
  KCTL=oc
elif command -v kubectl >/dev/null 2>&1; then
  KCTL=kubectl
elif command -v oc >/dev/null 2>&1; then
  KCTL=oc
else
  echo "ERROR: no cluster CLI found — install kubectl or oc" >&2; exit 1
fi
```

Always `applications.argoproj.io`, never the short name `application`: on Open Cluster
Management clusters the short name resolves to `applications.app.k8s.io` and a miss
looks like the Application does not exist.

Establish both states and the conditions before routing:

```bash
APP=<application-name>
APP_NS=<namespace-of-the-application-object>

# The Argo CD instance that owns this Application. Needed for controller logs,
# argocd-cm, and cluster secrets. List the instances and pick the owning one.
$KCTL get argocd -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'
NS=<namespace-of-the-ArgoCD-CR>
CR=<name-of-the-ArgoCD-CR>

$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'sync={.status.sync.status}{"\n"}'\
'revision={.status.sync.revision}{"\n"}'\
'health={.status.health.status}{"\n"}'\
'phase={.status.operationState.phase}{"\n"}'\
'opMessage={.status.operationState.message}{"\n"}'\
'startedAt={.status.operationState.startedAt}{"\n"}'\
'finishedAt={.status.operationState.finishedAt}{"\n"}'\
'automated={.spec.syncPolicy.automated}{"\n"}'

# Conditions carry the real error text for most failures.
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'

# Per-resource diff state. The app status is OutOfSync if any one of these is.
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} sync={.status} health={.health.status}{"\n"}{end}'
```

An empty `finishedAt` with a non-empty `startedAt` means an operation is still running.
Compare `startedAt` against now before calling anything stuck.

## Route by state

Check in this order and load exactly one. Do not run a generic workflow first.

| Check | State | Reference |
|---|---|---|
| 1 | Sync status is `Unknown`, or there is a `ComparisonError` or `InvalidSpecError` condition | `references/comparison-error.md` |
| 2 | `operationState.phase` is `Running` or `Terminating` and has been for a while | `references/sync-stuck.md` |
| 3 | `operationState.phase` is `Failed` or `Error` | `references/sync-failed.md` |
| 4 | Sync status is `OutOfSync` and no operation is running | `references/outofsync.md` |
| 5 | Sync status is `Synced` but the cluster does not match what you expect | `references/false-synced.md` |

Order matters. A `ComparisonError` makes every other reading meaningless, because the
diff was never computed — check 1 first even when the louder symptom is `OutOfSync`.

If the Application is `Synced`, the last operation `Succeeded`, and the cluster is
correct, there is nothing to triage. Say so and return.

## Sustained OutOfSync is usually one of four things

An automated trigger firing on a long `OutOfSync` almost always lands on one of these.
Knowing the shape saves a wasted pass through the per-resource diff:

| Shape | Tell |
|---|---|
| Auto-sync is not configured at all | `.spec.syncPolicy.automated` is absent. Manual-sync apps are *expected* to sit `OutOfSync`. Confirm this before diagnosing anything. |
| Auto-sync is configured but declining to run | `automated` is set, no operation is running, and the controller logs say why. |
| Sync runs and the diff comes straight back | `operationState.phase: Succeeded` with a recent `finishedAt`, and still `OutOfSync`. A controller fights something else over the field. |
| Prune is off and an extra resource remains | Per-resource status `PruneSkipped` in the sync result. |

The third is the one to recognize early: if `finishedAt` is recent and the status is
still `OutOfSync`, no amount of syncing will fix it and the cause is a write conflict,
a missing `ignoreDifferences`, or a mutating webhook. `references/outofsync.md` covers
it.

## Operator-managed instances change where the fix goes

On Red Hat OpenShift GitOps, the settings behind several sync causes are reconciled by
the operator. A direct edit to `argocd-cm` is reverted, usually within a minute, so
recommending one produces a fix that appears to work and then regresses.

| Setting | Lives in the `ArgoCD` CR as |
|---|---|
| `resource.customizations.ignoreDifferences.*` | `.spec.resourceIgnoreDifferences` |
| `application.resourceTrackingMethod` | `.spec.resourceTrackingMethod` |
| `resource.exclusions` / `resource.inclusions` | `.spec.resourceExclusions` / `.spec.resourceInclusions` |
| Other `argocd-cm` keys | `.spec.extraConfig` |

Check whether the instance is operator-managed before writing any recommendation that
touches a ConfigMap:

```bash
$KCTL get cm argocd-cm -n "$NS" \
  -o jsonpath='{range .metadata.ownerReferences[*]}{.kind}/{.name}{"\n"}{end}'
```

An `ArgoCD/<name>` owner means report the CR field, never the ConfigMap key.

## Output

Report these, in this order. A cause with no supporting output is not a diagnosis.

1. **State and source.** Both the sync status and the operation phase, plus the specific
   resource or condition message that produced them. Quote the message.
2. **Root cause.** One causal chain, ending at something observed. If the evidence does
   not reach a cause, say which check was inconclusive rather than naming a plausible
   cause.
3. **Confidence.** `High` only when the condition message and the underlying resource
   agree and you verified the cause directly. `Medium` when the cause is strongly
   implied but a step was unverifiable. `Low` when you are reasoning from the status
   alone, or could not reach the repo or a resource.
4. **Whether action is required.** Several sustained-`OutOfSync` states are not
   actionable: a manual-sync Application awaiting a human, a sync window that is closed
   by design, a deliberately unpruned resource. If nothing should be changed, say so
   explicitly and give the diagnosis alone.

### If the run writes a structured result

When the output is an `AnalysisResult`, the four items above are its fields:

| Item | Field |
|---|---|
| 1 and 2 | `diagnosis.summary` and `diagnosis.rootCause` |
| 3 | `diagnosis.confidence` — the enum is exactly `Low`, `Medium`, `High` |
| 4 | `actionRequired` |

`actionRequired: "False"` ends the run as Completed with no remediation, so use it
deliberately for the not-actionable states above rather than inventing an option to
fill the field. A manual-sync Application is the common case.

When `actionRequired` is `"True"`, each option's `remediationPlan.actions[].command`
must be an exact executable command — so the rule is not "never produce a command", it
is **produce the right one**. For anything in the operator-managed table above, that is
a patch to the `ArgoCD` CR, never an edit to `argocd-cm`:

```bash
oc patch argocd <cr> -n <ns> --type merge -p '{"spec":{"resourceTrackingMethod":"annotation"}}'
```

Set `risk` and `reversible` from what the action actually does, not from how routine it
feels. Enabling `prune` is `Critical` and `Irreversible` — it deletes every live
resource no longer in git. A CR patch restarts Argo CD components, so it is at least
`Medium`. Put the read-back that proves the fix worked in a `post-check` action.

Declare every namespace the commands touch in the option's RBAC, with a
`justification`. That declaration is the only source of execution permissions, and an
Application's own namespace is usually not its destination namespace — enumerate from
the objects you named in the diagnosis, not from where the Application object lives.

Whatever the output shape, never propose a manual `kubectl` edit to a managed resource
without first checking `spec.syncPolicy.automated.selfHeal`. With self-heal on, Argo CD
reverts it within seconds — the action reports success, the `post-check` fails, and the
Application is unchanged.

## Reference

| Topic | File | When to load |
|---|---|---|
| Comparison failed, so there is no diff | `references/comparison-error.md` | Sync status `Unknown`, `ComparisonError`, or `InvalidSpecError` |
| A sync operation that will not finish | `references/sync-stuck.md` | Phase `Running` or `Terminating` |
| A sync operation that failed | `references/sync-failed.md` | Phase `Failed` or `Error` |
| OutOfSync: drift, auto-sync declining, perpetual diff | `references/outofsync.md` | `OutOfSync` with no operation running |
| Synced but wrong | `references/false-synced.md` | Status is `Synced` and the cluster still does not match |
| Application **health** status triage | `skills/gitops/argo-app-health-triage` | The symptom is `Degraded`, `Progressing`, `Missing`, or health `Unknown` |
| Operator-owned behavior — destination RBAC, apps-in-any-namespace | `skills/gitops/argo-operator` | A sync is `forbidden`, or the Application is ignored entirely with no status |
| ApplicationSet, Rollout, and controller-level debugging | `skills/gitops/argo-cluster-debug` | The symptom is not an Application sync state |
