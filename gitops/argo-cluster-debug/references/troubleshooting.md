# Argo Cluster Debug — Troubleshooting Reference

> **Component selectors:** `$CR` is the ArgoCD instance's name — `openshift-gitops`,
> `team-b`, etc. Operator-managed workloads are labelled `<cr-name>-<component>`, so a
> hardcoded `app.kubernetes.io/name=argocd-server` matches **nothing** and the component
> reads as absent. Resolve it alongside `$NS`:
>
> ```bash
> CR=$(kubectl get argocd -n "$NS" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
> CR=${CR:-argocd}   # falls back to the Helm/standalone naming
> ```
>
> On a Helm or plain-manifest install the components really are `argocd-*`, so the
> fallback makes the same commands work on both.

> **Namespace:** `$NS` below is the Argo CD instance's namespace. It is **`openshift-gitops`
> on OpenShift GitOps**, `argocd` on a standalone install, and something else entirely for a
> second instance. There is frequently more than one — resolve it once and reuse it:
>
> ```bash
> kubectl get argocd -A    # operator-managed instances and their namespaces
> NS=openshift-gitops      # set to the instance you are working on
> ```
>
> The same applies to `namespace: argocd` inside the YAML below — it is a placeholder for
> the Argo CD instance's namespace. An Application created in `argocd` on a cluster whose
> instance lives in `openshift-gitops` is never picked up, with no error anywhere.
> (`namespace:` on an Application's **destination** is a different field — that one is the
> workload's namespace and is unrelated.)

Symptom-to-cause mappings organized by Argo component. Read this in full before starting any debugging workflow.

---

## Application Sync Failures

### ComparisonError: invalid manifests

**Symptoms:** Application status shows `ComparisonError` condition. `.status.conditions[].message` contains schema validation or parsing errors.

**Causes:**
- Invalid YAML in the source repo (indentation, missing fields)
- CRD not installed on the cluster — manifests reference a Kind the API server doesn't know about
- Helm template rendering failure — missing values, incompatible chart version
- Kustomize build failure — missing bases, invalid strategic merge patch
- jsonnet compilation error

**Debug:**
```bash
# Check the condition message
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.status.conditions[*].message}'

# Check repo-server logs for manifest generation errors
kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-repo-server --tail=200 | grep -i error

# For Helm: try rendering locally
helm template <chart-path> -f <values-file>

# For Kustomize: try building locally
kustomize build <path>
```

### SyncError: permission denied (RBAC)

**Symptoms:** Sync fails with `Unauthorized` or `forbidden` in the operation state message.

**Causes:**
- The Argo CD application controller ServiceAccount lacks RBAC to create/update the target resource
- AppProject `clusterResourceWhitelist` or `namespaceResourceBlacklist` blocks the resource
- Destination namespace not allowed by the AppProject

**Debug:**
```bash
# Check the operation state
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.status.operationState.syncResult.resources[*]}' | python3 -m json.tool

# Check AppProject restrictions
kubectl get appproject <project-name> -n "$NS" -o yaml

# Verify the controller can create the resource
# The controller SA is <cr-name>-argocd-application-controller in the INSTANCE namespace.
# Getting this wrong is worse than useless: auth can-i answers "no" for a service account
# that does not exist, which reads as "RBAC is broken" when nothing is broken.
# Verified: the wrong SA returns "no", the real one returns "yes" on the same cluster.
kubectl auth can-i create <resource> \
  --as=system:serviceaccount:"$NS":"$CR"-argocd-application-controller -n <target-namespace>
```

### OutOfSync but auto-sync not triggering

**Symptoms:** Application shows OutOfSync, but `syncPolicy.automated` is configured and no sync operation starts.

**Causes:**
- `syncPolicy.automated` is missing entirely — check for typos (`automated` not `automatic`)
- Application has a `SyncError` condition from a previous failed sync — auto-sync backs off on repeated failures
- Application is in a `Progressing` health state — auto-sync waits for health before re-syncing
- `spec.syncPolicy.automated.selfHeal` is false — changes to live resources won't trigger sync
- AppProject sync windows are blocking the sync

**Debug:**
```bash
# Check syncPolicy
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.spec.syncPolicy}'

# Check for sync error backoff
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.status.operationState.retryCount}'

# Check sync windows on the AppProject
kubectl get appproject <project> -n "$NS" -o jsonpath='{.spec.syncWindows}'

# Check application-controller logs for sync decisions
kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-application-controller --tail=200 | grep <app-name>
```

### Sync stuck in Progressing

**Symptoms:** Sync operation shows as `Running` indefinitely. Resources never reach `Healthy` state.

**Causes:**
- A resource has a finalizer preventing deletion during sync (common with replaced resources)
- A webhook (mutating or validating) is blocking resource creation
- A Deployment rollout is stuck (image pull failure, crashloop, resource limits)
- PersistentVolumeClaim is stuck in `Pending` (no StorageClass, no available PV)
- A Job never completes (infinite loop, waiting for resource that doesn't exist)

**Debug:**
```bash
# Check which resources are not synced/healthy
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{range .status.resources[*]}{.kind}/{.name}: sync={.status}, health={.health.status}{"\n"}{end}' | grep -v 'Synced.*Healthy'

# Check for stuck deletions (finalizers)
kubectl get <kind> <name> -n <namespace> -o jsonpath='{.metadata.finalizers}'

# Check for webhook rejections
kubectl get events -n <namespace> --field-selector reason=FailedCreate
```

### "rpc error: code = Unknown" on Application

**Symptoms:** Application shows `rpc error: code = Unknown desc = ...` in conditions or operation state.

**Causes:**
- Repo-server crashed or is overloaded — manifest generation timed out
- Git repository is unreachable (network, authentication)
- Manifest generation exceeds `reposerver.timeout.seconds` (default: 60s in argocd-cm)
- Large repositories with many files causing OOM in repo-server

**Debug:**
```bash
# Check repo-server health
kubectl get pods -n "$NS" -l app.kubernetes.io/name=$CR-repo-server

# Check repo-server resource usage
kubectl top pods -n "$NS" -l app.kubernetes.io/name=$CR-repo-server

# Check repo connectivity (repo-server no longer ships git binary since v2.5+)
# Option 1: Use argocd CLI if available
argocd repo list
# Option 2: Check repo-server logs for fetch errors
kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-repo-server --tail=200 | grep -i -E 'repo|fetch|clone|error'

# Check timeout config
kubectl get configmap argocd-cm -n "$NS" -o jsonpath='{.data.reposerver\.timeout\.seconds}'
```

### Helm rendering failures

**Symptoms:** ComparisonError with Helm template errors.

**Causes:**
- `valueFiles` paths are relative to the chart root, not the repo root
- Chart dependency not built (`helm dependency build` needed)
- Values file has wrong schema for the chart version
- `helm.parameters` override syntax is wrong
- Chart version pinned in `spec.source.chart` doesn't exist in the Helm repo

**Debug:**
```bash
# Check the source config
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.spec.source.helm}' | python3 -m json.tool

# Try rendering locally with the same values
helm template <release-name> <chart> -f <values.yaml> --version <version>
```

### Kustomize build failures

**Symptoms:** ComparisonError with Kustomize build errors.

**Causes:**
- Missing `resources` or `bases` entries in kustomization.yaml
- Invalid strategic merge patch (patch target not found)
- Remote base URL is unreachable
- `namePrefix`/`nameSuffix` conflicts with label selectors
- Kustomize version mismatch (v4 vs v5 syntax differences)

**Debug:**
```bash
# Check Kustomize version Argo CD is using
kubectl get configmap argocd-cm -n "$NS" -o jsonpath='{.data.kustomize\.buildOptions}'

# Try building locally
kustomize build <path>
```

---

## Health Check Issues

### Degraded

**Symptoms:** Application health is `Degraded`. One or more managed resources are unhealthy.

**Common causes by resource kind:**

| Kind | Degraded Cause |
|------|---------------|
| Deployment | ReplicaSet has unavailable replicas — pod CrashLoopBackOff, ImagePullBackOff |
| StatefulSet | Pod stuck in Pending or CrashLoopBackOff |
| DaemonSet | Pods not scheduled on expected nodes |
| Service | Endpoint has no ready addresses (no pods matching selector) |
| Ingress | Backend Service not found |
| PersistentVolumeClaim | Stuck in Pending (no matching PV, StorageClass missing) |
| Job | Failed (backoffLimit reached) |

**Debug:**
```bash
# Find the degraded resource
kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{range .status.resources[?(@.health.status=="Degraded")]}{.kind}/{.namespace}/{.name}{"\n"}{end}'

# Get events for the degraded resource
kubectl describe <kind> <name> -n <namespace>
```

### Progressing

**Symptoms:** Application health stays `Progressing` indefinitely.

**Causes:**
- Deployment rollout waiting for new pods to become ready
- StatefulSet rolling update in progress
- Argo Rollout in canary/blue-green progression
- New pod stuck in `Init:0/1` (init container not completing)

**Debug:**
```bash
# Check rollout status
kubectl rollout status deployment/<name> -n <namespace> --timeout=10s

# Check pod status
kubectl get pods -n <namespace> -l <selector> --sort-by='.status.startTime'
```

### Missing

**Symptoms:** Application health shows `Missing` for one or more resources.

**Causes:**
- Resource was deleted from the cluster but exists in the desired state
- Namespace doesn't exist yet (sync wave ordering issue)
- CRD not installed — the resource Kind is unknown to the API server
- RBAC prevents Argo CD from reading the resource

**Debug:**
```bash
# Verify the resource doesn't exist
kubectl get <kind> <name> -n <namespace>

# Check if the CRD exists
kubectl get crd <crd-name>

# Check RBAC
kubectl auth can-i get <resource> \
  --as=system:serviceaccount:"$NS":"$CR"-argocd-application-controller -n <namespace>
# (a nonexistent SA answers "no" — confirm the SA exists before believing a denial:
#  kubectl get sa -n "$NS" | grep application-controller)
```

### Unknown

**Symptoms:** Application health shows `Unknown` for a custom resource.

**Causes:**
- No built-in health check for the CRD's Kind
- Custom health check Lua script has a syntax error
- Custom health check returns `nil` or an unexpected status

**Debug:**
```bash
# Check for custom health checks in argocd-cm
kubectl get configmap argocd-cm -n "$NS" -o yaml | grep -A20 'resource.customizations.health'

# Check in argocd-cm data for the specific Kind
kubectl get configmap argocd-cm -n "$NS" -o jsonpath='{.data}' | python3 -c "
import sys, json
data = json.load(sys.stdin)
for k,v in data.items():
    if 'health' in k:
        print(f'{k}:\n{v}\n')
"
```

**Custom health check location (v2.x):**
- `argocd-cm` ConfigMap with separate keys per resource kind: `data["resource.customizations.health.<group>_<kind>"]`
- Example: `resource.customizations.health.certmanager.io_Certificate` or `resource.customizations.health.argoproj.io_Rollout`
- The old `data["resource.customizations"]` YAML block format is deprecated in v2.x — each customization type (health, actions, ignoreDifferences) uses its own dot-separated key

---

## ApplicationSet Issues

### No Applications generated

**Symptoms:** ApplicationSet exists but `kubectl get applications.argoproj.io -n "$NS"` shows none owned by it.

**Causes:**
- Generator returns an empty parameter set
- For `git` generators: repository path doesn't match any directories/files
- For `cluster` generators: no clusters match the label selector
- For `scmProvider`/`pullRequest` generators: API credentials are missing or expired
- Template has invalid syntax — applicationset-controller silently drops errors in some versions
- RBAC: applicationset-controller ServiceAccount can't list clusters or access SCM API

**Debug:**
```bash
# Check applicationset-controller logs
kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-applicationset-controller --tail=200

# Check ApplicationSet status
kubectl get applicationset <name> -n "$NS" -o jsonpath='{.status}' | python3 -m json.tool

# For cluster generator: list known clusters
argocd cluster list
# or
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster
```

### Duplicate Applications

**Symptoms:** Multiple Applications with the same name or targeting the same destination.

**Causes:**
- Overlapping generators (e.g., two `list` generators producing the same parameters)
- Missing `goTemplate: true` with incorrect `name` template producing duplicates
- Matrix generator with non-unique key combinations

**Debug:**
```bash
# List applications and their owning ApplicationSet
kubectl get applications.argoproj.io -n "$NS" -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.ownerReferences[0].name}{"\n"}{end}'
```

### Applications not updating after generator source changes

**Symptoms:** Changes to the generator source (e.g., new directory in git repo, new cluster) are not reflected.

**Causes:**
- Generator caching — SCM/PR generators cache API responses (default varies)
- `requeueAfterSeconds` not set or set too high
- applicationset-controller not reconciling — check its logs for errors

**Debug:**
```bash
# Check requeueAfterSeconds
kubectl get applicationset <name> -n "$NS" -o jsonpath='{.spec.generators[*].scmProvider.requeueAfterSeconds}'

# Force reconciliation by touching the ApplicationSet
kubectl annotate applicationset <name> -n "$NS" refreshed-at="$(date +%s)" --overwrite
```

### Progressive sync stuck

**Symptoms:** ApplicationSet with `spec.strategy.type: RollingSync` is not progressing through steps.

**Causes:**
- `maxUpdate` value is blocking — all allowed slots are occupied by unhealthy apps
- An Application in an earlier step is Degraded, blocking progression
- `matchExpressions` in step selectors don't match any Applications

**Debug:**
```bash
# Check strategy configuration
kubectl get applicationset <name> -n "$NS" -o jsonpath='{.spec.strategy}' | python3 -m json.tool

# Check Application health per step
kubectl get applications.argoproj.io -n "$NS" -l 'app.kubernetes.io/managed-by=applicationset-controller' -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'
```

---

## Rollout Issues

### Canary stuck at a step

**Symptoms:** Rollout shows `Paused` phase with a step index that doesn't advance.

**Causes:**
- Current step is a `pause` step with `duration: {}` (indefinite) — requires manual promotion
- Current step is `analysis` — AnalysisRun is still running or has failed
- Current step is `setWeight` — traffic management configuration is incorrect
- `setCanaryScale` step specifying explicit replicas but not enough nodes/resources

**Debug:**
```bash
# Get current step index and steps
kubectl get rollout <name> -n <namespace> -o jsonpath='Step {.status.currentStepIndex}: {.spec.strategy.canary.steps[*]}'

# Check pause conditions
kubectl get rollout <name> -n <namespace> -o jsonpath='{.status.pauseConditions}'

# For manual promotion (if requested by user):
kubectl argo rollouts promote <name> -n <namespace>
```

### Blue-green not promoting

**Symptoms:** Rollout shows `Paused` in blue-green mode. Preview stack is running but active is not updated.

**Causes:**
- `autoPromotionEnabled: false` — requires manual promotion
- `prePromotionAnalysis` is failing — AnalysisRun for pre-promotion metrics has failed
- `autoPromotionSeconds` not elapsed yet
- `scaleDownDelaySeconds` causing old ReplicaSet to linger (not a failure, just slow cleanup)

**Debug:**
```bash
# Check blue-green configuration
kubectl get rollout <name> -n <namespace> -o jsonpath='{.spec.strategy.blueGreen}' | python3 -m json.tool

# Check active vs preview services
kubectl get rollout <name> -n <namespace> -o jsonpath='active={.status.blueGreen.activeSelector}, preview={.status.blueGreen.previewSelector}'

# Check preview service endpoints
kubectl get endpoints <preview-service> -n <namespace>
```

### AnalysisRun inconclusive

**Symptoms:** AnalysisRun phase is `Inconclusive`. Rollout may be paused or aborted depending on `inconclusiveLimit`.

**Causes:**
- Metrics provider returned no data (query returned empty result set)
- Prometheus query returns `NaN` or no timeseries
- `successCondition` and `failureCondition` both evaluate to false
- Measurement `startedAt` was before canary pods were ready (no metrics to scrape)

**Debug:**
```bash
# Check metric results
kubectl get analysisrun <name> -n <namespace> -o jsonpath='{range .status.metricResults[*]}metric={.name}, phase={.phase}, measurements={.count}{"\n"}{end}'

# Get the actual measurement values
kubectl get analysisrun <name> -n <namespace> -o jsonpath='{.status.metricResults[0].measurements}' | python3 -m json.tool

# Check the AnalysisTemplate provider config
kubectl get analysistemplate <template> -n <namespace> -o yaml
```

### Traffic split not working

**Symptoms:** Canary weight is set but traffic is not actually shifting. All traffic goes to stable.

**Causes:**
- Istio VirtualService not found or not owned by the Rollout
- Istio VirtualService `host` doesn't match the Rollout's canary/stable services
- NGINX Ingress: `nginx.ingress.kubernetes.io/canary: "true"` annotation missing on canary Ingress
- ALB: target group binding not configured
- Rollout's `spec.strategy.canary.trafficRouting` references a service that doesn't exist

**Debug:**
```bash
# Check traffic routing config on Rollout
kubectl get rollout <name> -n <namespace> -o jsonpath='{.spec.strategy.canary.trafficRouting}' | python3 -m json.tool

# For Istio: check VirtualService weights
kubectl get virtualservice <vs-name> -n <namespace> -o jsonpath='{.spec.http[0].route}'

# Verify services exist
kubectl get svc <stable-service> <canary-service> -n <namespace>
```

### ScaleDown delay — preview/canary pods lingering

**Symptoms:** After promotion, old ReplicaSet pods remain running.

**Causes:**
- `scaleDownDelaySeconds` is set (default: 30 for canary, 30 for blue-green) — this is intentional to drain connections
- `abortScaleDownDelaySeconds` for aborted rollouts
- Finalizer on the ReplicaSet preventing scale-down

**Debug:**
```bash
# Check scale-down delay config
kubectl get rollout <name> -n <namespace> -o jsonpath='{.spec.strategy.canary.scaleDownDelaySeconds}'
kubectl get rollout <name> -n <namespace> -o jsonpath='{.spec.strategy.blueGreen.scaleDownDelaySeconds}'

# Check ReplicaSet status
kubectl get replicaset -n <namespace> -l app=<app-label> -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,HASH:.metadata.labels.rollouts-pod-template-hash'
```

---



## Common kubectl Commands

Quick reference for the most-used debug commands across all Argo components.

### Argo CD

| Command | Purpose |
|---------|---------|
| `kubectl get applications.argoproj.io -n "$NS"` | List all Applications |
| `kubectl get applications.argoproj.io -n "$NS" -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'` | Application status summary |
| `kubectl get applicationsets -n "$NS"` | List all ApplicationSets |
| `kubectl get appprojects -n "$NS"` | List all AppProjects |
| `kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-application-controller --tail=100` | Controller logs |
| `kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-repo-server --tail=100` | Repo server logs |
| `kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-server --tail=100` | API server logs |
| `kubectl get configmap argocd-cm -n "$NS" -o yaml` | Server configuration |
| `kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=repository` | Configured repositories |
| `kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster` | Configured clusters |
| `argocd app list` | List apps (CLI) |
| `argocd app get <name>` | App detail (CLI) |
| `argocd app diff <name>` | Show diff (CLI). **Often unusable on OpenShift GitOps**: in `--core` mode it looks for `app.kubernetes.io/name=argocd-redis`, which the operator names `<cr-name>-redis`; `--redis-name "$CR"-redis` gets one step further and then fails `NOAUTH Authentication required`. It also exits 0 despite printing `FATAL`, so check output not exit code. Fall back to `kubectl get application <name> -o jsonpath='{.status.resources}'` |
| `argocd app history <name>` | Sync history (CLI) |

### Argo Rollouts

| Command | Purpose |
|---------|---------|
| `kubectl get rollouts -n <ns>` | List Rollouts |
| `kubectl get analysisrun -n <ns> --sort-by='.metadata.creationTimestamp'` | List AnalysisRuns |
| `kubectl get analysistemplate -n <ns>` | List AnalysisTemplates |
| `kubectl get experiments -n <ns>` | List Experiments |
| `kubectl argo rollouts get rollout <name> -n <ns>` | Rollout detail (plugin CLI) |
| `kubectl argo rollouts status <name> -n <ns>` | Rollout status (plugin CLI) |
| `kubectl argo rollouts list rollouts -n <ns>` | List rollouts (plugin CLI) |
| `kubectl get replicaset -n <ns> -l app=<label> -o wide` | ReplicaSets for a Rollout |
| `kubectl logs -n "$NS" -l app.kubernetes.io/name=argo-rollouts` | Rollouts controller logs. **On OpenShift GitOps the controller runs in the Argo CD instance namespace, not `argo-rollouts`** — it is reconciled from a `RolloutManager` CR. Find it with `kubectl get deploy -A \| grep argo-rollouts` |



## Version-Specific Notes

### Argo CD v2.14+
- ApplicationSets are first-class (no separate controller install since v2.6, but v2.14 adds progressive sync improvements)
- `argocd.argoproj.io/tracking-method` annotation supports `annotation+label` hybrid
- Multi-source Applications GA — `spec.sources[]` replaces `spec.source`
- Notification triggers moved to `argocd-notifications-cm` ConfigMap
- Application-in-any-namespace feature — Applications can live outside `argocd` namespace when enabled

### Argo Rollouts v1.8+
- `spec.strategy.canary.plugins` for traffic router plugins
- Header-based routing for canary
- Improved Istio multi-cluster support
- `spec.strategy.canary.dynamicStableScale` for optimized replica management
- `spec.analysis.measurementRetention` for keeping measurement history


