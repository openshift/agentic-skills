---
name: argo-cluster-debug
description: >
  Debug and troubleshoot Red Hat OpenShift GitOps on live clusters — inspects Argo CD
  Application sync status, health checks, and controller logs; diagnoses Argo Rollouts
  canary/blue-green failures and AnalysisRun results; and handles multi-instance,
  operator-managed installs. Uses oc (OpenShift CLI) for all CRD inspection; falls back
  to kubectl when oc is unavailable. argocd CLI is NOT expected in the sandbox but is
  used when available. Argo Workflows and Argo Events are out of scope. Use when users
  report failing, stuck, or degraded Argo CD or Rollouts resources on a cluster.
license: MIT
compatibility: Requires oc (OpenShift CLI). argocd CLI is NOT expected to be available in the sandbox environment.
---

# Argo Cluster Debug

Debug and troubleshoot the full Argo ecosystem on live Kubernetes clusters.

## Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| `kubectl` **or** `oc` | Yes | CRD inspection, pod logs, resource status |
| argocd | No | Richer Application output, diff, sync operations (NOT available in agentic sandbox; all operations use oc against CRDs) |
| kubectl-argo-rollouts | No | Rollout status, step details, promotion |

**Resolve the CLI before any workflow. On OpenShift, `oc` is the default.**

```bash
# Detect the platform and pick the CLI — on OpenShift, oc is the default.
if command -v oc >/dev/null 2>&1 && oc api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes; then
  KCTL=oc; PLATFORM=OpenShift
elif command -v kubectl >/dev/null 2>&1; then
  KCTL=kubectl
  PLATFORM=$(kubectl api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes && echo OpenShift || echo Kubernetes)
elif command -v oc >/dev/null 2>&1; then
  KCTL=oc; PLATFORM=Kubernetes
else
  echo "ERROR: no cluster CLI found — install kubectl or oc" >&2; exit 1
fi
echo "Platform: $PLATFORM — using '$KCTL'"

# Resolve the Argo CD namespace too — `argocd` is the upstream default and is almost
# never right on OpenShift, where it is `openshift-gitops` (and often several instances).
$KCTL get argocd -A --no-headers 2>/dev/null || \
  $KCTL get pods -A -l app.kubernetes.io/part-of=argocd --no-headers 2>/dev/null | awk '{print $1}' | sort -u
NS=openshift-gitops      # set to the instance you are working on; every command below uses $NS
```

Every `kubectl` in the workflows below means `$KCTL`. `oc` accepts all of them verbatim,
so substituting is always safe. Prefer `oc` on OpenShift — `Route`, `project`,
`SecurityContextConstraints`, and `oc adm` have no `kubectl` equivalent, and they are
exactly what you need when the Argo CD UI is unreachable (Route) or a pod will not start
(SCC). Only report a missing prerequisite when **neither** binary exists.

When `$PLATFORM` is OpenShift, also expect the Argo CD namespace to be
`openshift-gitops` rather than `argocd`, and instances to be Operator-managed `ArgoCD`
CRs (`argoproj.io/v1beta1`) — check `$KCTL get argocd -A`.

## How This Skill Works

The debug skill provides **systematic workflows** — each is a sequence of checks that
traces the problem from surface symptoms to root cause. The value is in the completeness
of the investigation, not just finding the first error.

**Before starting any workflow:**
1. Check which CLIs are available (oc is the default; argocd and kubectl-argo-rollouts are optional and NOT expected in the sandbox)
2. Confirm the current cluster context
3. Pick the matching workflow from the table below and load `references/debug-workflows.md`
4. Load `references/troubleshooting.md` — it maps symptoms to causes and saves time

**General rules:**
- Use `oc` as the primary CLI; fall back to `kubectl get -o yaml` if `oc` is unavailable. Use argocd CLI only when explicitly available (not expected in sandbox)
- Read-only by default — never sync, promote, or delete unless explicitly asked
- Analyze `.status.conditions` as the primary diagnostic signal for every Argo CRD
- Complete the full workflow — don't stop after finding one issue, cascading problems are common

## Cluster Context

- If the user specifies a cluster context, switch to it:
  ```bash
  kubectl config use-context <context-name>
  ```
  If using argocd CLI with a remote server:
  ```bash
  argocd context <context-name>
  ```
- If no cluster is specified, use the current context. Confirm it:
  ```bash
  kubectl config current-context
  ```
- Always verify Argo CD installation before Application/ApplicationSet debugging. Check for the argocd namespace and CRDs.

## Debugging Workflows

Workflows 1–5 live in `references/debug-workflows.md`; Workflow 6 is inline below. Match the reported
symptom to a workflow below, **load that file, and work its steps in order** — each step
builds context for the next. The value is in completing the investigation, not in stopping
at the first error.

| # | Workflow | Use when |
|---|----------|----------|
| 1 | Argo CD Installation Check | User asks if Argo CD is installed, reports general Argo CD failures — **or as a prerequisite before any Application/ApplicationSet debugging** |
| 2 | Application Debugging | Application sync failure, health degradation, `OutOfSync`, or `Unknown` status |
| 3 | ApplicationSet Debugging | ApplicationSet not generating Applications, generating the wrong ones, or reporting errors |
| 4 | Rollout Debugging | Canary or blue-green Rollout stuck, aborted, or degraded |
| 5 | Log Analysis | Cross-component log correlation when the failing component is not yet known |
| 6 | Operator / OLM triage | Argo CD itself is misbehaving and the instance looks healthy — upgrade wedged, operator pod crash-looping, CRD conversion webhook failing. See below; this is often upstream of everything else |

### Workflow 6: Operator / OLM triage (OpenShift GitOps)

Not an Argo CD problem but an *operator* problem, and it masquerades as one. Symptoms:
CR edits revert, a new setting never takes effect, components run an old version, or
everything is "Available" while nothing you change sticks.

```bash
# 1. Is the operator itself healthy? Restart count is the tell.
oc get pods -n openshift-gitops-operator

# 2. CSV phase is authoritative. The Subscription's `state` is NOT — it reports
#    AtLatestKnown while the CSV behind it is stuck Pending or Replacing.
oc get csv -n openshift-gitops-operator -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
oc get subscriptions.operators.coreos.com -n openshift-gitops-operator \
  -o jsonpath='installedCSV={.items[0].status.installedCSV} state={.items[0].status.state}{"\n"}'

# 3. A failed InstallPlan is the usual blocker
oc get installplan -n openshift-gitops-operator \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
oc describe installplan -n openshift-gitops-operator | grep -A5 -i 'message\|condition'

# 4. Conversion webhook — an empty caBundle or a crash-looping operator pod makes every
#    ArgoCD CR write fail admission, which looks like "my edits revert"
oc get crd argocds.argoproj.io \
  -o jsonpath='{.spec.conversion.webhook.clientConfig.caBundle}{"\n"}' | wc -c
```

**A zero-length `caBundle`, or an operator pod with hundreds of restarts, means the
operator cannot reconcile anything.** Fix that before investigating any Argo CD symptom
downstream of it — otherwise you are debugging the shadow.

Run **Workflow 1 first** whenever Argo CD's own health is unverified — a broken controller
or repo-server explains most Application-level symptoms, and skipping it leads to
misdiagnosing a healthy Application as broken.

If a workflow is inconclusive, `references/troubleshooting.md` maps symptoms to causes.

## Report Format

Every debugging session must conclude with a structured report.

### 1. Summary

| Field | Value |
|-------|-------|
| Cluster Context | `<context-name>` |
| Argo Component | Argo CD / Rollouts |
| Component Versions | Operator CSV + Argo CD version, e.g. `openshift-gitops-operator.v1.21.3` / Argo CD v3.4.5 |
| Resource | `<kind>/<namespace>/<name>` |
| Current Status | Sync/Health/Phase status |

**When more than one Argo CD instance is in scope**, repeat sections 1–4 per instance
under an `## Instance: <namespace>` heading, then give one combined section 5. A single
flat report across instances hides which instance owns which fault — and on OpenShift,
`openshift-gitops` plus one or more tenant instances is the normal case, not an edge case.

### 2. Resource Analysis

- **Spec**: key configuration details (source, strategy, template)
- **Status Conditions**: each condition with type, status, message, timestamp
- **Events**: relevant Kubernetes events

### 3. Dependency Chain

Map the full dependency chain relevant to the problem:
- Argo CD: `Git Repo -> Repo Server -> Application -> Managed Resources -> Pods`
- Rollouts: `Rollout -> ReplicaSets -> Pods`, `Rollout -> AnalysisRun -> Metric Provider`

### 4. Root Cause

State the identified root cause with supporting evidence:
- The specific error message or condition
- The resource and field where the failure originates
- The chain of causation from root cause to observed symptom

### 5. Recommendations

Prioritized list of actions:
- **BLOCKER** — must fix to restore functionality
- **HIGH** — significant risk if not addressed
- **MEDIUM** — best practice violation contributing to the issue
- **LOW** — improvement for reliability or observability

**Every recommendation must state its impact, not just its urgency.** Priority says how
soon; impact says what else moves when someone acts on it. A reader deciding whether to
do this now or in a maintenance window needs the second one, and it is the part they
cannot work out from the recommendation itself.

```
BLOCKER — Delete Rollout/openshift-gitops/example (no containers; hot-loops the controller)
  Impact: argo-rollouts controller only. The Rollout is invalid so nothing runs from
          it; no workload is affected. Controller restarts once.

HIGH    — Raise argocd-server memory to 1Gi (OOMKilling at the 256Mi default)
  Impact: restarts argocd-server on the openshift-gitops instance. UI and API
          unavailable for ~30s for everyone using it. Reconciliation is unaffected.
```

Where a cluster is reachable, compute it rather than guess:

```bash
<repo-root>/scripts/blast-radius.sh <kind> <name> [namespace]
```

It resolves the fan-out for `ArgoCD`, `AppProject`, `ApplicationSet`, `Application`,
`RolloutManager` and the shared ConfigMaps, and is strictly read-only. With no cluster,
reason it out from the manifests and **say it was not verified** — an unverified impact
is still far more useful than none.

"Impact: this Application only, nothing else references it" is a good answer. Say it
rather than omitting the line; silence reads as "unknown", which is a different claim.

Three cases worth stating explicitly whenever they apply:
- **Operator-managed objects restart on edit.** The restart is itself the impact and it
  is invisible in a diff.
- **Shared instances.** On OpenShift the default `openshift-gitops` instance is usually
  shared; the person asking typically owns one tenant and is not thinking about the others.
- **Ordering.** If one recommendation must land before another is safe, say so. Enabling
  a gate while a dependency is broken can create the very failure being reported.

---

## Edge Cases

Handle these scenarios explicitly:

| Scenario | Behavior |
|----------|----------|
| Argo CD not installed (no argocd namespace or CRDs) | Report "Argo CD is not installed on this cluster" and stop Application/AppSet workflows |
| argocd CLI not logged in | Detect `{"level":"fatal","msg":"Argo CD server address unspecified",...}` (JSON, not a literal `FATAL:` prefix — grep for `\"level\":\"fatal\"` or just `fatal`) and suggest `argocd login <server>` |
| **The named resource does not exist** | Do not invent findings and do not silently debug a different object. Run the not-found procedure below, report what you searched, then either ask for the right name or clearly label any substitute as a method demonstration only |
| Multiple Argo CD instances | Report **per instance** (see Report Format) rather than asking the user to choose — multiple instances are the norm on OpenShift. Ask only if a *write* is required and the target is ambiguous |
| Application in Progressing state | Note that the resource is actively reconciling — wait 60s and re-check before diagnosing |
| Suspended Application or Rollout | Report as intentional suspension, do not treat as error unless user says otherwise |
| Unknown health status | Check for custom health check Lua scripts in `argocd-cm` under `resource.customizations.health.<group_kind>` |
| Rollout without traffic management | Note that canary is replica-based only — weight percentages are approximated by replica ratio |
| Helm source with missing values files | Check `spec.source.helm.valueFiles` paths relative to the chart, not the repo root |
| Multi-source Application | Iterate all entries in `spec.sources[]` — each source can fail independently |

## When the named resource does not exist

The most common real debugging session does not start from a broken resource — it starts
from a name that does not resolve. Typo, wrong namespace, wrong cluster context, wrong
Argo CD instance, or already deleted. **Establish this before running any workflow**, or
you will produce a confident analysis of nothing.

```bash
# 1. Search cluster-wide. Always the FULL resource name — see the gotcha below.
$KCTL get applications.argoproj.io -A | grep -i <name>

# 2. Not there? It may have been deleted recently.
$KCTL get events -A --field-selector involvedObject.name=<name> \
  --sort-by=.lastTimestamp 2>/dev/null | tail -5

# 3. Confirm you are on the cluster the user means.
$KCTL config current-context

# 4. Confirm which Argo CD instance should own it.
$KCTL get argocd -A
```

**Gotcha — the short form can resolve to the wrong CRD.** On clusters running Open
Cluster Management (common on OpenShift), `kubectl get application <name>` resolves to
`applications.app.k8s.io`, not Argo CD, and returns a `NotFound` for the *wrong kind*:

```
Error from server (NotFound): applications.app.k8s.io "<name>" not found
```

That reads as "your Application is gone" when it may exist perfectly well. Always write
`applications.argoproj.io` explicitly.

**This is not limited to `application`.** Any short name served by more than one API
group resolves to whichever group sorts first, and a miss is reported as `NotFound` for
that *other* kind — which reads as "it does not exist" rather than "you asked the wrong
API". On a cluster running ACM/MCE, `subscription` is the other common one:

```bash
# Two groups serve `subscriptions` on an ACM cluster:
#   apps.open-cluster-management.io/v1   <- the bare name hits this
#   operators.coreos.com/v1alpha1        <- OLM's, the one you almost always want
$KCTL get subscription -A                        # "No resources found"  (WRONG kind)
$KCTL get subscriptions.operators.coreos.com -A  # the operator Subscriptions
```

Observed: a bare `get subscription -A` returned "No resources found" on a cluster whose
OLM Subscription was present and healthy, which led to a confident — and wrong — root
cause of "the Subscription was deleted".

**Before trusting any empty result, check whether the short name is ambiguous:**

```bash
$KCTL api-resources | awk '$1=="<shortname>"'   # more than one row == ambiguous
```

An empty result from a bare short name is not evidence of absence.

**Then report it as a finding, not a failure.** State what you searched and what exists.
If you demonstrate the method on a different resource, say so in the heading — never let
a substitute read as the user's resource.

## Remediation Actions

> **Important:** All write operations require explicit user approval before execution.
> Follow the pattern: diagnose → show evidence → propose fix → get user approval → apply → verify.

### Retry Failed Sync

**When:** SyncError identified as transient (network timeout, temporary API unavailability)
**Evidence required:** `.status.conditions` shows SyncError with transient message

**Action (after user approval):**
```bash
$KCTL -n $NS patch applications.argoproj.io $APP --type=merge \
  -p '{"operation":{"sync":{"revision":"HEAD","prune":false}}}'
```

**Verify:**
```bash
$KCTL -n $NS get applications.argoproj.io $APP -o jsonpath='{.status.sync.status}'
# Expected: Synced
```

### Force Hard Refresh

**When:** Application stuck in Progressing >10 minutes with no pod failures, or stale cache suspected
**Evidence required:** `.status.sync.status` is not progressing, pods are healthy

**Action (after user approval):**
```bash
$KCTL -n $NS annotate applications.argoproj.io $APP argocd.argoproj.io/refresh=hard --overwrite
```

**Verify:**
```bash
$KCTL -n $NS get applications.argoproj.io $APP -o jsonpath='{.status.sync.status}'
```

### Restart Argo CD Controller

**When:** Controller logs show repeated OOM kills, rpc errors, stale cache, or excessive resource consumption
**Evidence required:** Pod logs or events showing OOM/CrashLoopBackOff, or controller not reconciling

**Action (after user approval):**
```bash
# For operator-managed installs:
$KCTL -n $NS rollout restart statefulset/${CR_NAME}-application-controller
# Verify:
$KCTL -n $NS rollout status statefulset/${CR_NAME}-application-controller --timeout=120s
```

### Fix Missing RBAC

**When:** SyncError contains "is forbidden" or "cannot create/patch/delete resource"
**Evidence required:** Specific error message identifying the missing permission

**Action (after user approval):**
```bash
# 1. Identify the service account
SA=$($KCTL -n $NS get applications.argoproj.io $APP -o jsonpath='{.spec.syncPolicy.syncOptions}' | grep -o 'ServiceAccount=[^ ]*' | cut -d= -f2)
SA=${SA:-"${CR_NAME}-argocd-application-controller"}

# 2. Show what's missing
echo "Missing permission: <verb> <resource> in <namespace>"
echo "Service account: $SA"
echo "Suggested fix: Create a RoleBinding granting the needed permission"

# 3. Generate the RoleBinding (user reviews before applying)
cat <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-${APP}-fix
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: <appropriate-role>
subjects:
- kind: ServiceAccount
  name: $SA
  namespace: $NS
EOF
```

### Terminate Stuck Sync Operation

**When:** Application has a stuck in-progress sync operation that won't complete
**Evidence required:** `.status.operationState.phase` is "Running" for extended period

**Action (after user approval):**
```bash
$KCTL -n $NS patch applications.argoproj.io $APP --type=json \
  -p '[{"op":"remove","path":"/status/operationState"}]' --subresource=status
```

**Verify:** Check that a fresh sync can be triggered.

## Argo CRD Reference

All CRDs use `apiVersion: argoproj.io/v1alpha1` unless noted:

| Kind | Project | Description |
|------|---------|-------------|
| Application | Argo CD | Defines a deployed application |
| AppProject | Argo CD | Groups applications with RBAC and restrictions |
| ApplicationSet | Argo CD | Templated multi-cluster/multi-env application generation |
| Rollout | Argo Rollouts | Advanced deployment with canary/blue-green |
| AnalysisTemplate | Argo Rollouts | Metrics-based promotion criteria |
| ClusterAnalysisTemplate | Argo Rollouts | Cluster-scoped AnalysisTemplate |
| AnalysisRun | Argo Rollouts | Instance of an analysis execution |
| Experiment | Argo Rollouts | Temporary ReplicaSet for A/B testing |

## Reference Index

| Topic | Reference File | When to Load |
|-------|---------------|-------------|
| The seven step-by-step debugging workflows (installation, Application, ApplicationSet, Rollout, Workflow, Events, log analysis) | `references/debug-workflows.md` | **Every debugging session** — load the workflow matching the symptom |
| Symptom → cause → fix tables for Argo CD and Argo Rollouts | `references/troubleshooting.md` | Alongside a workflow, or when a workflow is inconclusive |
