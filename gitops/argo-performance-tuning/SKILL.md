---
name: argo-performance-tuning
description: >
  Diagnoses and tunes OpenShift GitOps / Argo CD performance and scalability — reducing
  unnecessary reconciliation at the source (resource-update ignore rules, resource exclusions,
  monorepo manifest-cache scoping), repo-server Git and caching behavior, application-controller
  sharding (static and dynamic) and concurrency, Kubernetes client tuning against managed
  clusters, self-heal pacing, API-server timeouts, and reconciliation/webhook tuning. Maps
  symptoms (slow or stuck UI, OOMKilled repo-server, backed-up sync queue, Git provider
  rate-limiting, sluggish drift detection, "context deadline exceeded" errors, high baseline
  CPU from status churn or repeated self-heal) to the specific setting that fixes them, for
  both standalone Argo CD (ConfigMaps + env vars) and the OpenShift GitOps Operator (ArgoCD CR).
  Use when users report Argo CD or OpenShift GitOps running slowly at scale, hitting OOM,
  timing out, or ask how to tune, scale, speed up, or reduce resource usage of GitOps
  reconciliation.
license: MIT
compatibility: Requires kubectl or oc; optionally argocd CLI, yq
---

# Argo Performance Tuning

Diagnose and tune Argo CD / OpenShift GitOps performance and scalability — from a single
sluggish instance to multi-cluster, thousands-of-Applications deployments.

This skill complements `argo-cluster-debug` (diagnoses *broken* resources) and `argo-operations`
(installs/deploys/maintains). It owns the "it works but it's slow / resource-hungry / falling
over at scale" problem space, and reuses the **Generate → Preview → Confirm** safety model from
`argo-operations` for any change that touches a live cluster.

## How This Skill Works

1. **Assess** — gather scale signals and current settings from the live cluster.
2. **Diagnose** — map the reported symptom(s) to the specific bottleneck and setting(s).
3. **Tune** — generate the exact config change for the user's install type, preview it, confirm,
   apply, and state what to monitor afterward.

Load `references/tuning-settings.md` once per session — it is the full settings reference
(defaults, recommended values, standalone vs. OpenShift GitOps Operator locations, and the
common-mistakes list) and the source of truth for every recommendation this skill makes.

## Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| `kubectl` **or** `oc` | Yes | Read current config, apply tuning changes |
| argocd | No | Richer Application/version inspection |
| yq | No | Parsing `argocd-cm`/`argocd-cmd-params-cm` YAML |

**Resolve the CLI first. On OpenShift, `oc` is the default.**

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

Every `kubectl` below means `$KCTL`; `oc` accepts all of them verbatim.

`$PLATFORM` directly determines where tuning settings go. On OpenShift the instance is
almost always an Operator-managed **`ArgoCD` CR** (`argoproj.io/v1beta1`), so settings
belong under its `spec` (`spec.controller.processors`, `spec.repo.env`, …) — **not** in
`argocd-cmd-params-cm`, where the Operator will overwrite them on the next reconcile.
Confirm with `$KCTL get argocd -A` during Phase 1 before generating any patch.

## Phase 1: Assess

Confirm the cluster context and install type first:

```bash
kubectl config current-context
kubectl get argocd -A -o name 2>/dev/null  # Operator-managed (OpenShift GitOps / Argo CD Operator)
# Operator workloads are named <cr-name>-server, so "argocd-server" only matches by
# accident. List what is actually there rather than probing for a fixed name:
# Note deploy AND statefulset — the application-controller is a StatefulSet.
kubectl get deploy,sts -A 2>/dev/null | grep -E '\-server|\-repo-server|\-application-controller'
```

Gather scale signals:

```bash
NS=<argocd-namespace>   # argocd or openshift-gitops

# Application and cluster count — the two numbers that matter most for sharding decisions
kubectl get applications.argoproj.io -A --no-headers | wc -l
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster --no-headers | wc -l   # external clusters (+1 for in-cluster)
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=repository --no-headers | wc -l

# Current replica counts
# Do NOT use -l app.kubernetes.io/name=argocd-<component>: the Operator labels workloads
# <cr-name>-<component>, so a hardcoded argocd- prefix matches nothing and every
# component reads as absent. Enumerate and match on suffix instead.
kubectl get deploy,statefulset -n "$NS" -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,WANT:.spec.replicas

# OOM / restart history — strong signal for parallelism-limit tuning
# Label selectors do not work here either — and worse, pods on Operator installs carry
# NO part-of label at all, so a selector-based check silently reports "no OOMs" on a
# cluster that is actively OOMKilling. Scan every pod in the namespace.
kubectl get pods -n "$NS" -o json | python3 -c "
import json,sys
for p in json.load(sys.stdin)['items']:
    for c in p['status'].get('containerStatuses', []):   # .get: pods may have none yet
        reason = c.get('lastState',{}).get('terminated',{}).get('reason')
        if c.get('restartCount') or reason:
            print(f\"{p['metadata']['name']:<55} restarts={c.get('restartCount')} last={reason}\")
"

# Current tuning-relevant settings
kubectl get configmap argocd-cm -n "$NS" -o jsonpath='{.data.timeout\.reconciliation}{"\n"}{.data.timeout\.reconciliation\.jitter}{"\n"}' 2>/dev/null
kubectl get configmap argocd-cmd-params-cm -n "$NS" -o yaml 2>/dev/null
kubectl get argocd -n "$NS" -o yaml 2>/dev/null   # Operator-managed: spec.repo.env / spec.controller.* / spec.extraConfig

# Whether reconciliation-at-the-source reduction is already configured — check before assuming
# timeout.reconciliation is the only lever
kubectl get configmap argocd-cm -n "$NS" -o jsonpath='{.data.resource\.exclusions}{"\n"}{.data.resource\.ignoreResourceUpdatesEnabled}{"\n"}' 2>/dev/null
kubectl get applications.argoproj.io -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.argocd\.argoproj\.io/manifest-generate-paths}{"\n"}{end}' 2>/dev/null | grep -v -P '\t$'
```

Check whether Git webhooks are configured (relevant to `timeout.reconciliation` decisions) —
look for a webhook Route/Ingress/Service in front of `argocd-server`, or ask the user directly.

## Phase 2: Diagnose

Map the reported symptom to the bottleneck using this table, then read the matching section of
`references/tuning-settings.md` for the exact setting, default, recommended value, and placement.

| Symptom | Likely bottleneck | Setting(s) |
|---|---|---|
| High controller CPU with no real drift — frequent status/health flapping on child resources (Pods, ReplicaSets, CRs) | Reconciliation triggered by ignorable field churn | `resource.ignoreResourceUpdatesEnabled` / `resource.customizations.ignoreResourceUpdates` |
| High connection/watch load on managed clusters from non-GitOps-managed, high-churn kinds (Endpoints, EndpointSlice, policy/scan reports) | Watching kinds that should never be reconciled against | `resource.exclusions` |
| One commit to a monorepo triggers mass re-render for every Application in that repo, even untouched paths | Manifest cache invalidated by commit SHA, not by changed paths | `argocd.argoproj.io/manifest-generate-paths` annotation |
| repo-server `OOMKilled` / CrashLoopBackOff during a mass sync or large push | Unbounded concurrent manifest generation | `ARGOCD_REPO_SERVER_PARALLELISM_LIMIT` |
| **argocd-server** `OOMKilled` (exit 137), often while idle | Memory limit too low for the API/UI server — commonly an Operator default (e.g. 256Mi) rather than a concurrency problem | Raise `spec.server.resources.limits.memory` on the ArgoCD CR. Compare against a sibling instance with no limit set before assuming a leak; this is a sizing issue, not a tuning one, so parallelism settings will not help |
| Git provider rate-limiting / 429s / org-wide block | Unbounded concurrent `git ls-remote` | `ARGOCD_GIT_LS_REMOTE_PARALLELISM_LIMIT` |
| `context deadline exceeded` in UI/CLI viewing a complex Application | API server timeout shorter than actual render time | `ARGOCD_SERVER_REPO_SERVER_TIMEOUT_SECONDS` (align with `ARGOCD_EXEC_TIMEOUT`) |
| Sync/comparison errors on large Helm charts or Kustomize overlays | Repo-server child-process timeout too low | `ARGOCD_EXEC_TIMEOUT` |
| Large monorepo is slow to fetch/clone | Full-history clone | Git shallow clone `depth` (repository Secret) |
| Sync failures on flaky/throttled Git connections | No retry | `ARGOCD_GIT_ATTEMPTS_COUNT` |
| CPU spikes when many apps share one commit | Cache stampede — lock timeout too short for a slow chart | `ARGOCD_REVISION_CACHE_LOCK_TIMEOUT` |
| UI/CLI sluggish, slow drift detection at 1,000+ apps | Status comparison concurrency too low | `controller.status.processors` |
| Mass sync leaves apps `Pending`/`Waiting` | Operation concurrency too low | `controller.operation.processors` |
| Raised `operation.processors` but syncs still queue | `kubectl` process-slot limit unchanged | `ARGOCD_APPLICATION_CONTROLLER_KUBECTL_PARALLELISM_LIMIT` |
| Controller `context deadline exceeded` cancelling slow manifest RPCs | Controller→repo-server timeout too low | `ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS` |
| Sustained high baseline CPU/network, no code changes | Aggressive blind polling, no webhooks | `timeout.reconciliation` (+ set up webhooks) |
| Periodic load spikes at a fixed cadence | No jitter spreading polls | `timeout.reconciliation.jitter` |
| Apps repeatedly self-heal / high CPU from constant retry on chronically-drifting apps | No backoff between self-heal attempts | `controller.self.heal.backoff.timeout/factor/cap.seconds` |
| Controller slow calling a *managed cluster's* API server (not the repo-server) at high cluster/app count | K8s client QPS/burst too conservative | `ARGOCD_K8S_CLIENT_QPS` / `ARGOCD_K8S_CLIENT_BURST` |
| High controller→Redis write traffic from one or more Applications with very large resource trees | Entire resource tree rewritten as one Redis key per change | `ARGOCD_APPLICATION_TREE_SHARD_SIZE` |
| One controller maxed out across many registered clusters | No horizontal scaling | Application Controller **sharding** |
| Need to rebalance shards when scaling controller replicas without a restart | Static sharding only rebalances on restart | Dynamic Cluster Distribution (alpha — see Edge Cases) |

If multiple symptoms are present, work through **Tuning order of leverage** in
`references/tuning-settings.md`: reduce unnecessary work first, then align timeouts, then bound
concurrency, then scale out with sharding.

## Phase 3: Tune — Generate, Preview, Blast radius, Confirm

**Almost every tuning change here patches the `ArgoCD` CR, which is operator-managed and
usually shared.** The operator restarts the component you touched, and every Application
on that instance stops reconciling until it is back — a one-field diff hides that
entirely. Compute the affected set and show it before asking to confirm:

```bash
<repo-root>/scripts/blast-radius.sh ArgoCD <name> <namespace>
```

`spec.resourceExclusions` and `resourceTrackingMethod` are the widest of these: they
change what **every** Application on the instance tracks.

**This applies to tuning you only recommend, too.** A suggestion to raise a limit or
enable sharding needs its impact stated even when you are not the one applying it — and
note any ordering dependency, since enabling a setting while a prerequisite is broken can
create the very problem being reported.


Every change that touches the live cluster follows the same 3-step protocol as
`argo-operations`:

1. **Generate** — produce the exact YAML patch or env var change, in a fenced code block. For
   the OpenShift GitOps Operator, show the correct `spec` path (`spec.repo.env`,
   `spec.controller.env`, `spec.controller.processors`, `spec.controller.sharding`, or
   `spec.extraConfig`) — get this wrong and the change silently does nothing. Check the
   **Common mistakes** list in `references/tuning-settings.md` before presenting the patch.
2. **Preview**:
   ```bash
   # NOTE: --validate is an `apply`-only flag. `kubectl/oc patch` rejects it with
   # "error: unknown flag: --validate", so the preview fails outright. Server dry-run
   # on a patch still validates against the CRD schema; it just does not take that flag.
   kubectl patch argocd <name> -n <ns> --type merge -p '<patch>' --dry-run=server -o yaml
   # or, for standalone ConfigMap/env changes:
   kubectl diff -f <file>.yaml
   ```
3. **Confirm** — ask "Apply this? (yes/no)" and wait for explicit approval before applying.
   Read-only assessment (Phase 1) never requires confirmation.

After applying, state what to watch to confirm the fix worked and catch regressions:
controller/repo-server CPU & memory, reconcile duration, kube-apiserver request rate/latency,
and Git provider rate-limit headers. Recommend changing **one** major setting at a time.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Only one cluster registered | Sharding will not help — say so explicitly and point to repo-server/controller concurrency settings instead |
| No Git webhook configured | Do not recommend lowering `timeout.reconciliation` much, and caution that raising it delays commit detection by up to the full interval; recommend configuring a webhook first |
| OpenShift GitOps Operator in use | `processors` go under `spec.controller.processors`, **not** `spec.extraConfig`; controller repo-server timeout goes under `spec.controller.env`, **not** `spec.extraConfig` |
| Floating tags / mutable Helm chart versions in use | Do not recommend lowering `ARGOCD_REPO_CACHE_EXPIRATION` to chase freshness — recommend webhooks or version pinning instead |
| Public repository with no Repository Secret yet | Must create the Secret object first — shallow-clone `depth` cannot be set without it |
| User asks for `consistent-hashing` sharding on OpenShift GitOps | The API accepts it — `spec.controller.sharding.algorithm` is enum-validated to `legacy\|round-robin\|consistent-hashing` (verified on operator 1.21.3). The caveat is Red Hat's **support posture**, not API availability, so do not claim the field will reject it. Check the installed operator version and flag the support question before production use |
| User asks about `round-robin` as a "safe" default | Note it is also still experimental — removing the rank-0 cluster reshuffles every cluster across every shard |
| User asks for Dynamic Cluster Distribution, or to rebalance shards without a restart | It is alpha; cite the known 2025 scale-down (clusters left unassigned) and scale-up (double-assigned) bugs and recommend the static sharding model with a planned restart for production until resolved |
| User has a monorepo and asks to fix cache invalidation on every commit | Recommend `argocd.argoproj.io/manifest-generate-paths` (works without webhooks since v2.11) over lowering `ARGOCD_REPO_CACHE_EXPIRATION`; note it requires full-history clone (no shallow `depth`) and has had real cache-coherency bugs — pair with `resource.ignoreResourceUpdatesEnabled` as defense in depth |
| User reports high controller CPU with no actual drift, especially from child resources (Pods/ReplicaSets) | Check `resource.ignoreResourceUpdatesEnabled` (default `true`) and whether the specific churny field is covered before reaching for `timeout.reconciliation` |
| Repo-server/controller already restarting with `OOMKilled` | Treat as urgent — recommend the relevant parallelism/processor limit immediately, not just resource-limit increases that mask the root cause |
| Cluster not reachable | Report the error and stop; do not generate apply commands for a cluster you cannot validate against |

## Reference Index

| Topic | Reference File | When to Load |
|-------|---------------|-------------|
| Full settings table, per-setting Problem→Fix detail, sharding algorithms, standalone vs. Operator YAML, common mistakes, tuning order of leverage | `references/tuning-settings.md` | Every request — this is the primary source of truth for this skill |

## Related Skills

- **Resource broken, not just slow?** → `argo-cluster-debug`
- **Installing, deploying, or general day-2 ops?** → `argo-operations` (its `day2-operations.md`
  covers basic replica/resource scaling; this skill covers the deeper env-var/ConfigMap tuning)
- **"What is X" / generate manifests?** → `argo-knowledge`
