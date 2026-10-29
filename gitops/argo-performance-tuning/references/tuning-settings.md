# Performance & Scale Tuning Settings Reference

Source: [Tuning OpenShift GitOps for performance at scale](https://blog.stderr.at/gitopscollection/2026-03-27-openshift-gitops-performance-tuning/) (Thomas Jungbauer).
Defaults and recommendations below are indicative — always validate in your own environment and
change one setting at a time.

**Standalone Argo CD** reads `argocd-cm` / `argocd-cmd-params-cm` ConfigMaps and env vars on the
upstream Deployments/StatefulSet. **OpenShift GitOps** maps the same settings into the `ArgoCD`
custom resource (`metadata.name`/`namespace` typically `openshift-gitops`); the same `spec`
fragments work for a community **Argo CD Operator** install under `metadata.name`/`namespace`
`argocd`. Repository shallow-clone depth is always a repository `Secret`, never a CR field.

## Quick lookup table

| Setting | Default | Recommended | Standalone location | Operator (ArgoCD CR) location |
|---|---|---|---|---|
| Git shallow clone `depth` | full history | `1` | Repository `Secret` `stringData.depth` | Same — always a Secret, not the CR |
| `ARGOCD_REPO_SERVER_PARALLELISM_LIMIT` | `0` (unlimited) | `20`, then tune | env on `argocd-repo-server` or `argocd-cmd-params-cm` `reposerver.parallelism.limit` | `spec.repo.env` |
| `ARGOCD_GIT_LS_REMOTE_PARALLELISM_LIMIT` | `0` (unlimited) | `20` when Git rate-limits | env on `argocd-repo-server` | `spec.repo.env` |
| `ARGOCD_EXEC_TIMEOUT` | `90s` | `180s`+ for heavy Helm/Kustomize | env on `argocd-repo-server` | **`spec.repo.execTimeout`** (dedicated) |
| `ARGOCD_EXEC_FATAL_TIMEOUT` | `10s` | leave default unless you know why | env on `argocd-repo-server` | `spec.repo.env` |
| `ARGOCD_GIT_ATTEMPTS_COUNT` | `1` | `3`–`5` on flaky networks | env on `argocd-repo-server` | `spec.repo.env` |
| `ARGOCD_REPO_CACHE_EXPIRATION` | `24h` | keep `24h` unless you know why | env on `argocd-repo-server` | `spec.repo.env` |
| `ARGOCD_REVISION_CACHE_LOCK_TIMEOUT` | `10s` | raise (e.g. `30s`) for large charts | env on `argocd-repo-server` | `spec.repo.env` |
| `ARGOCD_SERVER_REPO_SERVER_TIMEOUT_SECONDS` | `60` | match repo render time (e.g. `180`) | env on `argocd-server` | `spec.server.env` |
| Application Controller sharding | disabled / 1 replica | enabled; algorithm + replicas | HA StatefulSet, `argocd-cmd-params-cm` `controller.sharding.algorithm`, `ARGOCD_CONTROLLER_REPLICAS`/`ARGOCD_CONTROLLER_SHARD` | `spec.controller.sharding` + `spec.controller.env` (algorithm) |
| `timeout.reconciliation` | `3m` | `600s`–`3600s` **with webhooks** | `argocd-cm` key | **`spec.controller.appSync`** (dedicated) |
| `timeout.reconciliation.jitter` | `60s` | non-zero fraction of the interval | `argocd-cm` key | `spec.extraConfig` |
| `controller.status.processors` | `20` | `50`–`100` at large scale | `argocd-cmd-params-cm` | `spec.controller.processors.status` |
| `controller.operation.processors` | `10` | raise when sync queue backs up | `argocd-cmd-params-cm` | `spec.controller.processors.operation` |
| `ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS` | `60` | `120`–`300` for slow manifest RPCs | `argocd-cmd-params-cm` `controller.repo.server.timeout.seconds` | `spec.controller.env` (**not** `extraConfig`) |
| `ARGOCD_APPLICATION_CONTROLLER_KUBECTL_PARALLELISM_LIMIT` | upstream `20`; **OpenShift GitOps operator passes `--kubectl-parallelism-limit 10`** | match or sit slightly below `operation.processors` — and measure from 10, not 20, on OpenShift | `argocd-cmd-params-cm` `controller.kubectl.parallelism.limit` | **`spec.controller.parallelismLimit`** (dedicated) |
| `resource.ignoreResourceUpdatesEnabled` | `true` | keep `true`; tune the ignore rules, don't disable it | `argocd-cm` key | `spec.extraConfig` |
| `resource.exclusions` | ships with defaults (v3.0+) | keep enabled; **extend, never replace** | `argocd-cm` key | **`spec.resourceExclusions`** (dedicated field — NOT `spec.extraConfig`) |
| `argocd.argoproj.io/manifest-generate-paths` | unset | set on each Application sharing a monorepo | Application annotation | Application annotation (same on both) |
| `controller.app.state.cache.expiration` | `1h` | raise only with evidence of churn; distinct from `ARGOCD_REPO_CACHE_EXPIRATION` | `argocd-cmd-params-cm` | `spec.controller.env` |
| `ARGOCD_K8S_CLIENT_QPS` / `ARGOCD_K8S_CLIENT_BURST` | `50` / `100` | `100`-`200` / `200`-`400`, watch managed-cluster API server | `argocd-cmd-params-cm` `controller.k8s.client.qps`/`.burst` | `spec.controller.env` |
| `controller.self.heal.timeout.seconds` + backoff (`timeout`/`factor`/`cap`) | `0` / `2s` / `3x` / `300s` | raise backoff cap on chronically-drifting apps | `argocd-cmd-params-cm` | `spec.controller.env` |
| `controller.sync.timeout.seconds` | `0` (no timeout) | set only if a specific hung sync needs a hard stop | `argocd-cmd-params-cm` | `spec.controller.env` |
| `controller.sync.wave.delay.seconds` | `2s` | raise for multi-wave apps where downstream controllers need more reaction time | `argocd-cmd-params-cm` | `spec.controller.env` |
| `ARGOCD_APPLICATION_TREE_SHARD_SIZE` | `0` (single Redis key) | `100` for apps with very large resource trees | env on `argocd-application-controller` | `spec.controller.env` |
| `controller.resource.health.persist` | upstream `false` (3.0+); **OpenShift GitOps operator ships `true`** | on OpenShift you are already paying the in-CR health write cost — setting it `false` is a *reduction*, not a no-op | `argocd-cmd-params-cm` | **`spec.cmdParams`** (dedicated — not `spec.extraConfig`) |
| Dynamic Cluster Distribution | disabled (alpha) | only for non-production / with restart-based fallback ready | `ARGOCD_ENABLE_DYNAMIC_CLUSTER_DISTRIBUTION` + Deployment (not StatefulSet) | same env var under `spec.controller.env` |

## Controller: Reduce reconciliation at the source

**Fixes:** the root cause behind "sustained high baseline CPU/memory" — before reaching for
`timeout.reconciliation`, check whether the controller is reconciling at all for the right
reasons. These settings stop unnecessary reconciliation from being triggered in the first
place, rather than bounding or parallelizing work that's already happening. Apply before
`timeout.reconciliation` tuning — it is the first step in the **tuning order of leverage**
below.

### `resource.ignoreResourceUpdatesEnabled` (default `true`)

**Fixes:** continuous reconciliation triggered by Kubernetes controllers that periodically
rewrite fields on resources Argo CD watches (most commonly `.status`), causing high
`argocd-application-controller` CPU with no actual drift.

Enabled by default since Argo CD ~2.8. The shipped default rule ignores `.status` changes for
all resources — an Application only re-reconciles if the change also flips the resource's
*health*, not on every status write:

```yaml
# argocd-cm (Operator: spec.extraConfig)
resource.customizations.ignoreResourceUpdates.all: |
  jsonPointers:
    - /status
```

**Applies only to tracked resources** (resources the Application directly manages). Dependent/
child resources (a `ReplicaSet` or `Pod` created by a `Deployment`) are not covered by default —
add the annotation `argocd.argoproj.io/ignore-resource-updates: "true"` directly on the churny
child resource's manifest if it's a known offender. Evaluating this annotation costs some CPU
per watch event, so only opt in resources you've confirmed are high-churn (check controller logs
for `"Ignoring change of object because none of the watched resource fields have changed"` to see
it working, or the absence of that line to find what still isn't covered).

**Do not disable this setting** to "fix" a missed status change — find the specific field
causing the problem and add it to the ignore rule instead; disabling it re-enables reconciling
on every periodic status rewrite cluster-wide.

### One instance's answer does not transfer to its siblings

**Read every setting per instance.** A cluster commonly runs several ArgoCD CRs, and they
diverge in ways that matter: on the cluster this reference was verified against, one
instance has `clusters: ['*']` in its exclusions and the others do not, and one has no
resource limits at all while its siblings OOMKill at the 256Mi operator default. A
finding on `openshift-gitops` tells you nothing about `team-b`.

```bash
for NS in $(kubectl get argocd -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\n"}{end}'); do
  echo "== $NS"; kubectl get argocd -n "$NS" -o yaml | grep -E 'resourceExclusions|extraConfig|cmdParams|processors' 
done
```

### Dedicated `ArgoCD` CR fields — prefer these over env vars

Several settings in the table above have a **first-class field on the `ArgoCD` CR**.
Where one exists, use it: a dedicated field is schema-validated (so a typo is rejected
rather than silently ignored), and it will not be clobbered the way a raw env entry can
be. Verified present on `argoproj.io/v1beta1`:

| Setting | Dedicated CR field | Instead of |
|---------|-------------------|-----------|
| kubectl parallelism | `spec.controller.parallelismLimit` | `ARGOCD_APPLICATION_CONTROLLER_KUBECTL_PARALLELISM_LIMIT` env |
| reconciliation interval | `spec.controller.appSync` | `timeout.reconciliation` in `argocd-cm` |
| repo-server exec timeout | `spec.repo.execTimeout` | `ARGOCD_EXEC_TIMEOUT` env |
| sharding algorithm | `spec.controller.sharding.algorithm` | `ARGOCD_CONTROLLER_SHARDING_ALGORITHM` env |
| resource exclusions/inclusions | `spec.resourceExclusions` / `spec.resourceInclusions` | `argocd-cm` keys via `extraConfig` |
| `controller.resource.health.persist` | `spec.cmdParams` | `spec.extraConfig` |

`spec.controller.sharding` also exposes `enabled`, `replicas`, `minShards`, `maxShards`,
`clustersPerShard` and `dynamicScalingEnabled`.

Check what the installed operator version supports before assuming:

```bash
kubectl explain argocd.spec.controller.sharding
kubectl explain argocd.spec.cmdParams
```

Use `spec.*.env` only for settings with **no** dedicated field — and remember
`spec.extraConfig` takes precedence over the CRD, so a stray entry there silently
overrides a dedicated field you set correctly.

### `resource.exclusions` (ships with defaults since v3.0)

**Fixes:** API server connection/watch load on *managed* clusters from kinds that are never
declared in Git and never child resources of anything Argo CD tracks.

The shipped default excludes high-volume, high-churn, control-plane-owned kinds — `Endpoints`,
`EndpointSlice`, and (if Kyverno is installed) its `PolicyReport`/`ClusterPolicyReport`/
`*AdmissionReport`/`*BackgroundScanReport` kinds:

```yaml
# Standalone Argo CD — argocd-cm key
resource.exclusions: |
  - apiGroups: ['', 'discovery.k8s.io']
    kinds: ['Endpoints', 'EndpointSlice']
    clusters: ['*']
```

```yaml
# OpenShift GitOps — the ArgoCD CR has a DEDICATED field for this.
# It is spec.resourceExclusions, not spec.extraConfig.
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: openshift-gitops
  namespace: openshift-gitops
spec:
  resourceExclusions: |
    - apiGroups: ['', 'discovery.k8s.io']
      kinds: ['Endpoints', 'EndpointSlice']
      clusters: ['*']
    - apiGroups: ['wgpolicyk8s.io']          # your additions go here too
      kinds: ['PolicyReport', 'ClusterPolicyReport']
      clusters: ['*']
```

> **`spec.resourceExclusions` is a single YAML string, and a merge patch replaces it
> wholesale.** The operator ships a populated default — on a live cluster it already excludes
> `Endpoints`, `EndpointSlice` and the Kyverno report kinds. Patching it with only your own
> entries silently deletes the shipped ones and *increases* watch load, which is the opposite of
> the intent. Always read the current value, append, and write the whole string back:
>
> ```bash
> # Read BOTH. An instance can have an EMPTY spec.resourceExclusions while its argocd-cm
> # carries a fully populated resource.exclusions — observed on a real cluster, where one
> # instance had the CR field set and a sibling had only the ConfigMap. Reading just the
> # CR field returns empty, you "append" to nothing, and you wipe the shipped defaults —
> # exactly the failure this warning exists to prevent.
> kubectl get argocd <name> -n "$NS" -o jsonpath='{.spec.resourceExclusions}'
> kubectl get cm argocd-cm -n "$NS" -o jsonpath='{.data.resource\.exclusions}'
> ```
>
> If only the ConfigMap is populated, the operator is managing it from its own defaults
> rather than from the CR. Seed `spec.resourceExclusions` with the *current ConfigMap
> contents plus your additions*, not with your additions alone.
>
> The same applies to `spec.resourceInclusions`.
>
> **Why not `spec.extraConfig`?** It is not that it fails — it is that it *wins*. Per the
> CRD: *"ExtraConfig can be used to add fields to Argo CD configmap that are not supported
> by Argo CD CRD. Note: ExtraConfig takes precedence over Argo CD CRD."* Put
> `resource.exclusions` there and it silently overrides `spec.resourceExclusions`, so the
> dedicated field appears to be ignored and you end up debugging the wrong layer. Use
> `extraConfig` only for keys with no dedicated CR field.

Extend this list for your own cluster's high-churn, non-GitOps-managed CRDs (admission/scan
report objects from other controllers are the most common candidates) rather than leaving them
to be caught by `ignoreResourceUpdates` evaluation — excluding is cheaper than ignoring, since an
excluded kind is never watched at all.

## Repo-Server: Git shallow cloning

**Fixes:** slow fetch/clone on large or long-lived monorepos.

By default the repo-server clones full history. Set `depth` on the repository `Secret` to fetch
only the last N commits:

```yaml
kind: Secret
apiVersion: v1
metadata:
  name: repo-2960947011
  namespace: openshift-gitops
  labels:
    argocd.argoproj.io/secret-type: repository
  annotations:
    managed-by: argocd.argoproj.io
stringData:
  depth: "1"
  type: git
  url: https://github.com/org/repo.git
type: Opaque
```

For public repositories you may need to create this Secret manually — it does not exist by
default. Verify in repo-server logs: `git fetch origin <rev> --depth 1 --force --prune` should
replace a full `git fetch origin --tags --force --prune`.

## Repo-Server: env vars

Set under `spec.repo.env` on the `ArgoCD` CR (OpenShift GitOps / Argo CD Operator):

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: openshift-gitops
  namespace: openshift-gitops
spec:
  repo:
    env:
      - name: ARGOCD_REPO_SERVER_PARALLELISM_LIMIT
        value: "20"
```

### `ARGOCD_REPO_SERVER_PARALLELISM_LIMIT` (default `0`)

**Fixes:** repo-server `OOMKilled` / crash-looping during mass manifest generation.

Unbounded concurrent `helm template`/`kustomize build` runs (e.g. a push that touches 500
Applications at once) spike CPU and memory. Setting a value > 0 (e.g. `20`) creates a worker-pool
semaphore — the rest queue instead of running concurrently. Trade-off: large bursts take a little
longer to sync, but the repo-server stays up. Start at `20` and watch memory.

### `ARGOCD_GIT_LS_REMOTE_PARALLELISM_LIMIT` (default `0`)

**Fixes:** Git provider rate-limiting / 429s / org-wide blocks when many Applications share one
repo+branch — each reconciliation runs `git ls-remote` per Application concurrently.

Set > 0 (e.g. `20`) to cap concurrent connections to the Git provider. Don't set it too low (e.g.
`2`) — that can itself cause controller-side timeouts while requests wait in queue.

### `ARGOCD_EXEC_TIMEOUT` (default `90s`)

**Fixes:** timeouts/render errors for large or slow Helm charts and Kustomize overlays.

Max time for a repo-server child process (helm/kustomize/plugin). Raise to `180s`+ for heavy
charts. Don't set excessively high — that delays failing fast on a truly hung process.

### `ARGOCD_EXEC_FATAL_TIMEOUT` (default `10s`)

**Fixes:** zombie child processes after `ARGOCD_EXEC_TIMEOUT` fires (SIGTERM ignored).

Hard SIGKILL deadline after `ARGOCD_EXEC_TIMEOUT` sends SIGTERM. Leave at default unless you have
evidence of hung processes surviving SIGTERM.

### `ARGOCD_GIT_ATTEMPTS_COUNT` (default `1`)

**Fixes:** sync/reconciliation failing outright on transient Git network blips (connection reset,
SSH handshake failures, provider throttling).

Raise to `3`–`5` for resilience. Avoid very high values (e.g. `50`) — a genuinely down provider or
expired credentials will tie up the repo-server retrying for minutes, and you'll still hit
`ARGOCD_EXEC_TIMEOUT` eventually.

## Repo-Server: caching

### `ARGOCD_REPO_CACHE_EXPIRATION` (default `24h`)

**Fixes/protects against:** redundant re-clone + re-render of unchanged commits (expensive).

TTL for cached repo state and generated manifests in Redis. `24h` is a good default for most
environments. **Do not lower this** (e.g. to `5m`) just to pick up floating tags (`latest`, `main`)
or mutable Helm chart versions sooner — that forces constant re-rendering and tanks performance.
If you need faster propagation for floating tags, use webhooks or pin versions instead.

### `ARGOCD_REVISION_CACHE_LOCK_TIMEOUT` (default `10s`)

**Fixes:** "cache stampede" — many Applications on the same commit all render independently and
spike CPU when the first renderer doesn't finish within the lock timeout.

One worker locks the cache key for a revision while rendering; others wait instead of duplicating
work. Raise (e.g. `30s`) if your slowest chart/overlay takes longer than the default to render.
Trade-off: if the first worker hangs without releasing the lock, others wait the full timeout.

### `argocd.argoproj.io/manifest-generate-paths` (unset by default)

**Fixes:** the actual root cause behind "one commit to a monorepo invalidates the manifest
cache for every Application in that repo, even ones whose paths weren't touched" — this is the
official, documented fix for the scenario `ARGOCD_REPO_CACHE_EXPIRATION` and shallow-clone
`depth` only work around indirectly.

A semicolon-separated list of in-repo paths, set on each Application:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/manifest-generate-paths: ".;charts/shared"
```

Argo CD compares the changed files between the last cached revision and the new commit; if none
of the changed files fall under the annotated paths, the existing cache is kept valid for the
new commit and the Application is **not** re-rendered. Available **without configuring
webhooks** since Argo CD v2.11 — webhooks are not a precondition, though configuring them in
addition (and, for large plain-YAML monorepos, setting `ARGOCD_DISABLE_WEBHOOK_ROOT_PATH_CACHE`
or disabling the webhook's Redis cache warm-up) further reduces load by skipping reconciliation
entirely for unaffected apps rather than just reusing a cache.

**Correctness caveat:** this feature has had real cache-coherency bugs — a webhook-triggered
cache rename that doesn't persist `app.Status.Sync.Revision`, and a sibling-path false-positive
in `UpdateRevisionForPaths` — fixed as recently as mid-2026. Verify your Argo CD patch version
addresses known issues before relying on this as the *only* safeguard against a mass-reconcile
storm on a large monorepo; pair it with `resource.ignoreResourceUpdatesEnabled` (above) as
defense in depth.

**Requires a full-history clone** (no `depth` set, or `depth: 0`) to compare revisions — a
shallow clone doesn't have enough history for the path-diff comparison, so Argo CD falls back to
treating every commit as a full change. Don't combine shallow-clone `depth` with
`manifest-generate-paths` on the same repository.

### `ARGOCD_SERVER_REPO_SERVER_TIMEOUT_SECONDS` (default `60`, on `argocd-server`)

**Fixes:** UI/CLI showing `context deadline exceeded` for a complex Application even though the
repo-server is still successfully rendering it in the background.

This is the API server's client-side timeout waiting on the repo-server's manifest-generation RPC.
**Align it with `ARGOCD_EXEC_TIMEOUT`** — if the repo-server may legitimately take 180s to render a
chart but this stays at 60s, the UI fails even on success.

## Application Controller: Sharding

**Fixes:** a single controller reconciling too many Applications across too many clusters —
high CPU/memory, long reconcile queues, API-server throttling, repo-server pressure.

Only useful with **more than one registered cluster** — sharding distributes *clusters* (not
individual apps) across controller replicas; each replica only reconciles Applications whose
destination cluster maps to its shard.

**Distribution algorithms** (`ARGOCD_CONTROLLER_SHARDING_ALGORITHM` / `controller.sharding.algorithm`):

| Algorithm | Behavior |
|---|---|
| `legacy` | Stable hash from cluster ID. Simple, can be unbalanced. Default for compatibility. |
| `round-robin` | Spreads clusters more evenly in the common case, but is itself still **experimental**: removing the rank-0 cluster reshuffles every cluster across every shard, with a temporary performance hit. |
| `consistent-hashing` | Consistent hashing with bounded loads. Reduces reshuffling on shard-count changes — benchmarked by CNOE/Red Hat at 10→9 shards: **10-15 cluster reassignments vs. 37-48 under round-robin**, at the cost of somewhat less even CPU balance across shards than round-robin's best case. **Not documented for OpenShift GitOps** — verify support against your installed operator version before relying on it in production. Still marked experimental upstream; see the [CNOE sharding benchmark](https://cnoe.io/blog/argo-cd-application-scalability) for full methodology. |

OpenShift GitOps (`ArgoCD` CR):

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: openshift-gitops
  namespace: openshift-gitops
spec:
  controller:
    env:
      - name: ARGOCD_CONTROLLER_SHARDING_ALGORITHM
        value: round-robin
    sharding:
      enabled: true
      replicas: 3
      minShards: 2
      maxShards: 5
```

Standalone Argo CD: run the application controller as an HA StatefulSet, set `replicas` = shard
count, set `controller.sharding.algorithm` in `argocd-cmd-params-cm`, and ensure each pod gets
`ARGOCD_CONTROLLER_REPLICAS` (total shards) and `ARGOCD_CONTROLLER_SHARD` (this pod's index).

Sharding applies **only** to the application controller — repo-server, Redis, and argocd-server
scale and are sized independently.

### Dynamic Cluster Distribution (alpha — shard rebalancing without restarts)

**Fixes:** the static sharding model above requires a full controller restart to redistribute
clusters whenever replica count changes; at large scale that's a real availability/reconciliation
gap during every scale event. Available since Argo CD v2.9.

Requires running the controller as a **Deployment, not a StatefulSet** (apply the
`manifests/ha/base/controller-deployment/` Kustomize overlay) plus:

```yaml
env:
  - name: ARGOCD_ENABLE_DYNAMIC_CLUSTER_DISTRIBUTION
    value: "true"
```

The controller tracks replica count via the Deployment itself (not `ARGOCD_CONTROLLER_REPLICAS`)
and coordinates shard assignment through the `argocd-app-controller-shard-cm` ConfigMap, using a
heartbeat (`ARGOCD_CONTROLLER_HEARTBEAT_TIME`, default `10s`) to detect dead/unresponsive
controller pods — if a pod hasn't updated its heartbeat for `3 * HeartbeatTime`, its readiness
probe is marked unhealthy.

**Known production risk (2025, still open as of this writing):** scaling replicas **down** can
leave some clusters/apps assigned to no shard at all, and scaling **up** can double-assign a
cluster to two shards simultaneously — see
[argoproj/argo-cd#24147](https://github.com/argoproj/argo-cd/issues/24147) and
[#24520](https://github.com/argoproj/argo-cd/issues/24520). The current workaround for both is a
full controller restart after a replica-count change. **Do not rely on this feature for
production scale-down events yet** — recommend the static sharding model (with a planned
restart) until these are resolved, and flag this explicitly if a user asks for it.

## Controller: Kubernetes client tuning (managed-cluster API calls)

**Fixes:** a different bottleneck than everything above — how fast the controller is *allowed*
to call each **managed cluster's own API server**, separate from the controller→repo-server RPC
timeouts and separate from the kube-apiserver the controller itself runs against.

```yaml
# argocd-cmd-params-cm (Operator: spec.controller.env)
controller.k8s.client.qps: "100"
controller.k8s.client.burst: "200"
```

### `ARGOCD_K8S_CLIENT_QPS` / `ARGOCD_K8S_CLIENT_BURST` (default `50` / `100`)

**Fixes:** slow sync/reconcile fan-out across many managed clusters when the controller is
throttling its own requests well below what the managed API server could actually handle.

AWS's 97-cluster/10,000-application benchmark found this one of the highest-leverage single
changes at that scale: raising from the 50/100 default to 100/200 cut sync time from 42 minutes
to 17; 150/300 to 12 minutes; 200/400 to 11 minutes. Raise in the same steps and watch each
managed cluster's own kube-apiserver request rate/latency as you go — this setting's whole
purpose is to protect those clusters, so don't raise it past what they can actually absorb.

Related, lower-leverage settings in the same family (raise only if QPS/burst alone isn't the
bottleneck): `ARGOCD_K8S_CLIENT_MAX_IDLE_CONNECTIONS` (default `500`), `ARGOCD_K8S_TCP_TIMEOUT`
(default `30s`), `ARGOCD_K8S_TCP_KEEPALIVE` (default `30s`), `ARGOCD_K8S_TLS_HANDSHAKE_TIMEOUT`
(default `10s`).

## Controller: Self-heal pacing

**Fixes:** the same class of "sustained high baseline CPU" symptom as `timeout.reconciliation`,
but caused by an Application that keeps drifting and getting self-healed over and over, rather
than by polling cadence.

```yaml
# argocd-cmd-params-cm (Operator: spec.controller.env)
controller.self.heal.timeout.seconds: "0"
controller.self.heal.backoff.timeout.seconds: "2"
controller.self.heal.backoff.factor: "3"
controller.self.heal.backoff.cap.seconds: "300"
```

`controller.self.heal.timeout.seconds` (default `0`) is a flat delay between self-heal attempts
when set; the exponential backoff triplet (`backoff.timeout.seconds` default `2`, `backoff.factor`
default `3`, `backoff.cap.seconds` default `300`) is what actually paces repeated attempts on a
chronically out-of-sync Application — each retry waits longer, up to the cap, instead of
hammering the same self-heal attempt every reconcile loop. Raise the backoff cap if a specific
app is known to be a repeat offender rather than lowering `timeout.reconciliation` globally to
compensate.

## Controller: Resource-tree sharding in Redis

**Fixes:** high controller→Redis traffic specifically from Applications with very large
resource trees (many managed resources) — unrelated to **cluster sharding** above; this shards
one Application's own cached data across multiple Redis keys, not clusters across replicas.

```yaml
env:
  - name: ARGOCD_APPLICATION_TREE_SHARD_SIZE
    value: "100"
```

Default `0` stores an Application's entire resource tree in a single Redis key — every change to
any one resource rewrites the whole tree. A value > `0` (docs suggest `100`) splits the tree into
shards of that many resources each; only the shard containing the changed resource is rewritten,
cutting Redis write traffic substantially for apps with large resource counts. No effect on apps
with small trees — only tune this if a specific Application's resource count is in the hundreds+.

## Controller: ConfigMap settings (`argocd-cm` / `spec.extraConfig`)

```yaml
# Operator — merges into argocd-cm
spec:
  extraConfig:
    timeout.reconciliation: 600s
    timeout.reconciliation.jitter: 60s
```

### `timeout.reconciliation` (default `3m`)

**Fixes:** sustained baseline CPU/memory/network load from blind polling at scale (thousands of
Applications checking Git every 3 minutes even when nothing changed).

Raise to `600s`–`3600s` — but **only if Git webhooks are configured**. Without webhooks, new
commits are detected up to one full interval later; with webhooks the controller doesn't need to
poll aggressively, so a longer interval is safe. This is one of the single highest-leverage
settings when combined with webhooks.

### `timeout.reconciliation.jitter` (default `60s`)

**Fixes:** periodic load spikes when thousands of Applications' polls align to the same instant.

Random delay (0 to this max) added per-Application poll so refreshes spread out instead of
synchronizing. Keep **non-zero** — a reasonable fraction of `timeout.reconciliation`. If you raise
the base interval for performance, raise jitter proportionally too.

## Controller: command-line parameters (`argocd-cmd-params-cm` / `spec.controller.*`)

These are passed as container command-line flags by the Operator, **not** read from
`argocd-cm`/`extraConfig` — a common source of misconfiguration.

```yaml
# Operator
spec:
  controller:
    processors:
      status: 50
      operation: 25
    env:
      - name: ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS
        value: "180"
      - name: ARGOCD_APPLICATION_CONTROLLER_KUBECTL_PARALLELISM_LIMIT
        value: "50"
```

### `controller.status.processors` (default `20`)

**Fixes:** slow drift detection / sluggish status refresh in the UI at scale.

Number of concurrent status comparisons (desired vs. live state). With 500+ Applications and only
20 processors, most queue during a mass reconciliation. Raise to `50`–`100` above ~1,000
Applications. Trade-off: more controller CPU/memory.

### `controller.operation.processors` (default `10`)

**Fixes:** mass syncs leaving many Applications `Pending`/`Waiting` while only 10 run at a time.

Number of concurrent sync/operation runs. Independent of `status.processors` — tune separately
based on refresh load vs. sync load.

### `ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS` (default `60`)

**Fixes:** controller-side `context deadline exceeded` cancelling a legitimately slow
`GenerateManifests` RPC before the repo-server finishes.

**Must go under `spec.controller.env` on the Operator CR, not `spec.extraConfig`.** Raise (e.g.
`180`) so it's at least as long as the worst-case repo-server render time you expect. This is the
controller→repo-server gRPC client timeout — it does not replace `ARGOCD_EXEC_TIMEOUT` (child
process timeout) or `ARGOCD_REPO_SERVER_PARALLELISM_LIMIT` (concurrency cap).

### `ARGOCD_APPLICATION_CONTROLLER_KUBECTL_PARALLELISM_LIMIT` (upstream `20`, OpenShift GitOps `10`)

**Fixes:** raising `operation.processors` without raising this just moves the bottleneck — extra
operation processors wait on a `kubectl` process slot.

> **The effective default on OpenShift GitOps is `10`, not the upstream `20`.** The operator
> passes `--kubectl-parallelism-limit 10` on the application-controller. Verified on a live
> cluster. Any "match or sit slightly below `operation.processors`" reasoning that starts from
> 20 is starting from the wrong baseline and will under-provision by half. Read the real value
> before recommending a change:
>
> ```bash
> kubectl get sts -n "$NS" -o json | python3 -c "
> import json,sys
> for it in json.load(sys.stdin)['items']:
>     for c in it['spec']['template']['spec']['containers']:
>         a=c.get('command',[])+c.get('args',[])
>         for i,x in enumerate(a):
>             if 'parallelism' in x: print(it['metadata']['name'], x, a[i+1] if i+1<len(a) else '')
> "
> ```

Max concurrent `kubectl` child processes the controller may spawn. Raise to match or sit slightly
below `operation.processors` (e.g. `50`). Raise in steps and watch kube-apiserver request
rate/latency, etcd, and controller CPU/memory after each change — don't set it far above
`operation.processors`, extra headroom wastes memory without raising throughput.

### `controller.sync.timeout.seconds` (default `0`, no timeout)

**Fixes:** a specific Application's sync hanging indefinitely with no automatic failure. Leave at
`0` unless you've identified a particular sync (e.g. a hung hook) that needs a hard ceiling — this
is a blunter, Application-wide timeout, not a substitute for `ARGOCD_EXEC_TIMEOUT` or the
repo-server/controller RPC timeouts above.

### `controller.sync.wave.delay.seconds` (default `2s`)

**Fixes:** sync waves advancing before a downstream controller (an Operator, a webhook, an
admission controller) has had a chance to react to the previous wave's changes. Raise for
Applications with many waves where later waves depend on slower-reacting controllers; leave at
default otherwise — raising it globally slows every multi-wave Application's total sync time.

### `controller.resource.health.persist` (default `false` since Argo CD 3.0)

**Fixes:** `Application` CR update churn from writing resource health status into the
Application's own `/status` on every health change — 3.0 changed the default to store health
externally instead. Setting this to `true` restores the pre-3.0 behavior of persisting health in
the CR (useful if something reads health via `kubectl get applications.argoproj.io -o yaml`) at the cost of
reintroducing that update load.

> **On OpenShift GitOps this is `true`, not `false`.** Verified on a live cluster:
> `argocd-cmd-params-cm` carries `controller.resource.health.persist: "true"` and the
> application-controller runs with `--persist-resource-health`. So the advice inverts: you are
> *already* paying the Application-CR update churn, and setting it to `false` is an available
> reduction rather than a default to leave alone. Check before assuming:
>
> ```bash
> kubectl get cm argocd-cmd-params-cm -n "$NS" -o jsonpath='{.data.controller\.resource\.health\.persist}'
> ```
>
> **Set it via `spec.cmdParams`, not `spec.extraConfig`.** Per `kubectl explain
> argocd.spec.cmdParams`, this is one of only *two* keys that field supports:
>
> ```yaml
> spec:
>   cmdParams:
>     controller.resource.health.persist: "false"
> ```

## Common mistakes (OpenShift GitOps Operator)

1. **Putting `controller.status.processors` / `controller.operation.processors` under
   `spec.extraConfig`.** They belong under `spec.controller.processors.status` /
   `spec.controller.processors.operation` — the Operator sets these as container command-line
   flags, not ConfigMap data.
2. **Putting `ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS` under
   `spec.extraConfig`.** It's an env var — belongs under `spec.controller.env`.
3. **Lowering `timeout.reconciliation` without webhooks**, or raising it far without webhooks —
   either hurts. Pair a longer interval with a configured Git webhook.
4. **Relying on `consistent-hashing` sharding on OpenShift GitOps** — the operator still passes
   through whatever value you set. **Note the API does accept it**: on operator 1.21.3
   `spec.controller.sharding.algorithm` is enum-validated to
   `legacy | round-robin | consistent-hashing`, so "undocumented on OpenShift GitOps" is a
   statement about Red Hat's *support posture*, not about API availability — do not tell
   users the field will reject it. Verify
   against your installed version before depending on it in production.
5. **Lowering `ARGOCD_REPO_CACHE_EXPIRATION`** to chase floating tags — use webhooks or pin
   versions instead; a short TTL forces constant re-rendering.
6. **Raising `ARGOCD_EXEC_TIMEOUT` without raising `ARGOCD_SERVER_REPO_SERVER_TIMEOUT_SECONDS` and
   `ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS` to match.** The repo-server will
   keep working past the point the server/controller already gave up and surfaced an error.
7. **Relying on Dynamic Cluster Distribution for production scale-down.** It's alpha and has
   open 2025 bugs (argoproj/argo-cd#24147, #24520) where scaling down can leave clusters
   unassigned to any shard. Use the static sharding model with a planned restart instead until
   these are resolved.
8. **Treating `argocd.argoproj.io/manifest-generate-paths` as a complete fix without checking
   your patch version.** It has had real cache-coherency bugs; pair it with
   `resource.ignoreResourceUpdatesEnabled` as defense in depth rather than relying on it alone.
9. **Combining shallow-clone `depth` with `manifest-generate-paths` on the same repository.**
   The path-diff comparison needs full history; a shallow clone defeats it silently.

## Tuning order of leverage

1. **Stop unnecessary reconciliation at the source** — `resource.ignoreResourceUpdatesEnabled`
   (keep the default `/status` rule, extend it for your own churny fields),
   `resource.exclusions` for known high-churn non-GitOps kinds, and
   `argocd.argoproj.io/manifest-generate-paths` for monorepos. This is cheaper than anything
   below it because the work never happens at all.
2. **Reduce unnecessary Git/render work** — shallow clone depth, sane cache TTLs, Git webhooks
   instead of blind polling.
3. **Align related timeouts** — `ARGOCD_EXEC_TIMEOUT`, controller repo-server timeout, API server
   repo-server timeout should all be consistent with the slowest chart you expect to render.
4. **Bound concurrency** — repo-server parallelism limit, `git ls-remote` parallelism limit,
   status/operation processors, kubectl parallelism, `ARGOCD_K8S_CLIENT_QPS`/`BURST` against
   managed clusters, self-heal backoff for chronically-drifting apps.
5. **Scale out** — sharding and replicas (static, or Dynamic Cluster Distribution with the
   scale-down caveat above), once the above no longer helps. `ARGOCD_APPLICATION_TREE_SHARD_SIZE`
   if a specific Application's own resource tree is the Redis bottleneck.

Treat tuning as evidence-led: change one major setting at a time and watch controller/repo-server
memory, reconcile duration, API rate, and Git rate-limit headers before changing the next.

## References

- [Tuning OpenShift GitOps for performance at scale](https://blog.stderr.at/gitopscollection/2026-03-27-openshift-gitops-performance-tuning/)
- Argo CD: [Reconcile Optimization](https://argo-cd.readthedocs.io/en/stable/operator-manual/reconcile/), [High Availability](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/), [Dynamic Cluster Distribution](https://argo-cd.readthedocs.io/en/stable/operator-manual/dynamic-cluster-distribution/), [argocd-cmd-params-cm.yaml reference](https://argo-cd.readthedocs.io/en/latest/operator-manual/argocd-cmd-params-cm-yaml/), [2.14→3.0 upgrade notes](https://argo-cd.readthedocs.io/en/stable/operator-manual/upgrading/2.14-3.0/)
- Red Hat OpenShift GitOps — Managing resource use, Argo CD instance / CR properties
- [AWS: Argo CD Application Controller Scalability Testing on Amazon EKS](https://aws.amazon.com/blogs/opensource/argo-cd-application-controller-scalability-testing-on-amazon-eks/) — real QPS/burst and sharding benchmark numbers
- [CNOE: Argo CD Benchmarking — Pushing the Limits and Sharding Deep Dive](https://cnoe.io/blog/argo-cd-application-scalability) — consistent-hashing vs. round-robin reshuffling/CPU-balance data
- [argoproj/argo-cd#24147](https://github.com/argoproj/argo-cd/issues/24147), [#24520](https://github.com/argoproj/argo-cd/issues/24520) — open Dynamic Cluster Distribution scale-down/scale-up bugs
- [argoproj/argo-cd#27971](https://github.com/argoproj/argo-cd/issues/27971), [#27194](https://github.com/argoproj/argo-cd/issues/27194) — `manifest-generate-paths` cache-coherency issues
