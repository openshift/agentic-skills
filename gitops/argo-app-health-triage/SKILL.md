---
name: argo-app-health-triage
description: >
  Triage an Argo CD Application by its health status — Degraded, Progressing, Missing,
  or Unknown — and name one root cause backed by cluster evidence. Explains how Argo CD
  computes health (custom Lua first, then built-in per-kind checks) and how child health
  rolls up to the Application, including the resources that are excluded from the rollup
  and never affect it. Routes to one workflow per status. Use when an Application's
  health status is the symptom, when an automated diagnosis has been triggered by a
  sustained unhealthy status, or when the reported status does not match what the
  workloads look like. Read-only. Not for sync status, drift, or ApplicationSet and
  Rollout health.
license: MIT
compatibility: Requires oc or kubectl
---

# Argo CD Application health triage

Health status, not sync status. An Application can be `Synced` and `Degraded` at the
same time: the live state matches git and the workload is still broken. When that is
what you see, drift is not the cause and reconciling again will not help.

This skill is read-only. Diagnose and report. Do not apply changes.

## You are probably running non-interactively

This skill is written to be usable by an automated diagnosis run with no human in the
loop. If no one can answer a question, do not ask one. Gather the evidence you can
reach, name the most probable cause, and state your confidence and what you could not
check. An honest `Low` confidence diagnosis is useful. A question is not.

## How Argo CD computes health

Resolution order for a single resource:

1. If the object has a `deletionTimestamp` and no hook finalizer — `Progressing`,
   message `Pending deletion`. Nothing else is evaluated.
2. A custom Lua script from `resource.customizations.health.<group>_<Kind>` in
   `argocd-cm`, if one exists for the GVK. **A script that errors makes the resource
   `Unknown`, and the Lua error becomes the health message.**
3. The built-in check for the GVK — Deployment, StatefulSet, DaemonSet, ReplicaSet,
   Pod, Job, Service, Ingress, PVC, HPA, APIService, and Argo CD's own kinds.
4. No check for the GVK — no health status at all. The resource is skipped. A CRD that
   Argo CD does not know how to assess never makes an Application unhealthy.

### Rollup to the Application

Application health starts at `Healthy` and becomes the **worst** health among the
resources that count. Worst is this order, best to worst:

`Healthy` → `Suspended` → `Progressing` → `Missing` → `Degraded` → `Unknown`

Two consequences that drive triage:

- **`Unknown` is the worst status, not a mild one.** One resource with a broken health
  check makes the whole Application `Unknown` and hides every other problem in it.
- **`Degraded` outranks `Missing`.** An Application with one missing resource and one
  degraded resource reports `Degraded`. The missing one is invisible at app level.

### What is excluded from the rollup

These never affect Application health. Finding one of them broken does not explain the
status, and you must keep looking:

| Excluded | Rule |
|---|---|
| Resources annotated `argocd.argoproj.io/ignore-healthcheck: "true"` | Skipped outright. Note the exact spelling — `ignore-healthcheck`, one word. |
| Hooks, and resources in the `Skip` sync phase | Skipped. A failed `PreSync` hook Job does not show as Degraded here; it shows as a failed sync operation. |
| An Application that manages itself | Excluded so app-of-apps does not self-reference. |
| A **missing** resource whose kind has no built-in check and no custom override | Skipped. A deleted ConfigMap or Secret does **not** make an Application `Missing`. |
| A child `Application` that is `Missing` or `Unknown` | Excluded from the parent in an app-of-apps. |

The fourth row is the one that misleads most often. If an Application is `Missing`, the
absent resource is a kind Argo CD can health-check, or one with a custom Lua override.

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

Establish the status and the responsible resource before routing:

```bash
APP=<application-name>
APP_NS=<namespace-of-the-application-object>

# The Argo CD instance that owns this Application. Needed for controller logs,
# argocd-cm, and cluster secrets. List the instances and pick the owning one.
$KCTL get argocd -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'
NS=<namespace-of-the-ArgoCD-CR>
CR=<name-of-the-ArgoCD-CR>

$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='health={.status.health.status}{"\n"}message={.status.health.message}{"\n"}sync={.status.sync.status}{"\n"}'

# The resources carrying the status. The app status is the worst of these.
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} health={.health.status} msg={.health.message} sync={.status}{"\n"}{end}'
```

If `.status.resources[*].health` is empty, the instance stores resource health in the
app tree rather than inline (`.status.resourceHealthSource: appTree`). Read it with
`argocd app resources "$APP"` or from the API, and say so if you cannot reach it.

## Route by status

Load exactly one. Do not run a generic workflow first.

| Status | Reference | What it is |
|---|---|---|
| `Degraded` | `references/degraded.md` | A health check ran and reported failure |
| `Progressing` | `references/progressing.md` | Not healthy yet, still allowed to become healthy. Sustained is the symptom |
| `Missing` | `references/missing.md` | A resource in the desired state has no live object |
| `Unknown` | `references/unknown.md` | Health could not be computed. Usually a broken check, not a broken workload |

If the Application is `Healthy` or `Suspended`, there is nothing to triage. Say so and
return — both are recovery states.

When more than one resource is unhealthy, the Application status comes from the worst.
Diagnose that one, and list the others as additional findings rather than merging them
into one cause.

## Grace periods lie about Deployments

An automated trigger that fires after a few minutes of sustained unhealthy status will
catch a failing Deployment while it is still `Progressing`, not `Degraded`. A
Deployment only becomes `Degraded` when its `Progressing` condition reaches
`ProgressDeadlineExceeded`, and `progressDeadlineSeconds` defaults to 600 — ten
minutes. So for the first ten minutes, a Deployment whose pods cannot start and a
Deployment that is rolling out normally report the same health status.

Never read `Progressing` as "it is still working." Go to `references/progressing.md`
and check the pods.

## Output

Report these, in this order. A cause with no supporting output is not a diagnosis.

1. **Status and source.** The Application health status, and the specific resource and
   health message that produced it. Quote the message.
2. **Root cause.** One causal chain, ending at something observed. If the evidence does
   not reach a cause, say which check was inconclusive rather than naming a plausible
   cause.
3. **Confidence.** `High` only when the health message and the underlying resource
   agree and you verified the cause directly. `Medium` when the cause is strongly
   implied but a step was unverifiable. `Low` when you are reasoning from the status
   alone, or could not reach a resource.
4. **Whether action is required.** Several sustained-unhealthy states are not
   actionable: a resource waiting on something external, a long-running Job, a workload
   inside its progress deadline, a node drain. If nothing should be changed, say so
   explicitly and give the diagnosis alone. Proposing a remediation for a condition
   that resolves itself is worse than proposing nothing.

Shaping a remediation plan — exact commands, risk, reversibility, rollback — is a
separate concern from triage. Do not invent `kubectl` fixes here, and in particular do
not propose one without first checking `spec.syncPolicy.automated.selfHeal`: with
self-heal on, Argo CD reverts a manual cluster change within seconds.

## Reference

| Topic | File | When to load |
|---|---|---|
| Degraded: a check reported failure | `references/degraded.md` | Status is `Degraded` |
| Progressing: stuck versus still working | `references/progressing.md` | Status is `Progressing` |
| Missing: desired but not live | `references/missing.md` | Status is `Missing` |
| Unknown: health could not be computed | `references/unknown.md` | Status is `Unknown` |
| Application **sync state** triage | `skills/gitops/argo-app-sync-triage` | The symptom is `OutOfSync`, a stuck or failed sync, or `Synced` while the cluster is wrong. Health and sync are independent — an app can be `Synced` and `Degraded` |
| Operator-owned behavior — destination RBAC, apps-in-any-namespace, and UI RBAC | `skills/gitops/argo-operator` | A sync is `forbidden` and resources never appeared, or the Application is ignored entirely |
| Generic Application, ApplicationSet, and Rollout debugging | `skills/gitops/argo-cluster-debug` | The symptom is not an Application health status |
