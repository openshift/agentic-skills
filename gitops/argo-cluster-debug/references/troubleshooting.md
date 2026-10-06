# Argo Cluster Debug — Troubleshooting Reference

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
kubectl get application <name> -n argocd -o jsonpath='{.status.conditions[*].message}'

# Check repo-server logs for manifest generation errors
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=200 | grep -i error

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
kubectl get application <name> -n argocd -o jsonpath='{.status.operationState.syncResult.resources[*]}' | python3 -m json.tool

# Check AppProject restrictions
kubectl get appproject <project-name> -n argocd -o yaml

# Verify the controller can create the resource
kubectl auth can-i create <resource> --as=system:serviceaccount:argocd:argocd-application-controller -n <target-namespace>
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
kubectl get application <name> -n argocd -o jsonpath='{.spec.syncPolicy}'

# Check for sync error backoff
kubectl get application <name> -n argocd -o jsonpath='{.status.operationState.retryCount}'

# Check sync windows on the AppProject
kubectl get appproject <project> -n argocd -o jsonpath='{.spec.syncWindows}'

# Check application-controller logs for sync decisions
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=200 | grep <app-name>
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
kubectl get application <name> -n argocd -o jsonpath='{range .status.resources[*]}{.kind}/{.name}: sync={.status}, health={.health.status}{"\n"}{end}' | grep -v 'Synced.*Healthy'

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
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-repo-server

# Check repo-server resource usage
kubectl top pods -n argocd -l app.kubernetes.io/name=argocd-repo-server

# Check repo connectivity (repo-server no longer ships git binary since v2.5+)
# Option 1: Use argocd CLI if available
argocd repo list
# Option 2: Check repo-server logs for fetch errors
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=200 | grep -i -E 'repo|fetch|clone|error'

# Check timeout config
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.reposerver\.timeout\.seconds}'
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
kubectl get application <name> -n argocd -o jsonpath='{.spec.source.helm}' | python3 -m json.tool

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
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.kustomize\.buildOptions}'

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
kubectl get application <name> -n argocd -o jsonpath='{range .status.resources[?(@.health.status=="Degraded")]}{.kind}/{.namespace}/{.name}{"\n"}{end}'

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
kubectl auth can-i get <resource> --as=system:serviceaccount:argocd:argocd-application-controller -n <namespace>
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
kubectl get configmap argocd-cm -n argocd -o yaml | grep -A20 'resource.customizations.health'

# Check in argocd-cm data for the specific Kind
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data}' | python3 -c "
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

**Symptoms:** ApplicationSet exists but `kubectl get applications -n argocd` shows none owned by it.

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
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller --tail=200

# Check ApplicationSet status
kubectl get applicationset <name> -n argocd -o jsonpath='{.status}' | python3 -m json.tool

# For cluster generator: list known clusters
argocd cluster list
# or
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster
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
kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.ownerReferences[0].name}{"\n"}{end}'
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
kubectl get applicationset <name> -n argocd -o jsonpath='{.spec.generators[*].scmProvider.requeueAfterSeconds}'

# Force reconciliation by touching the ApplicationSet
kubectl annotate applicationset <name> -n argocd refreshed-at="$(date +%s)" --overwrite
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
kubectl get applicationset <name> -n argocd -o jsonpath='{.spec.strategy}' | python3 -m json.tool

# Check Application health per step
kubectl get applications -n argocd -l 'app.kubernetes.io/managed-by=applicationset-controller' -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'
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

## Workflow Issues

### Workflow Pending

**Symptoms:** Workflow phase is `Pending`. No pods are created.

**Causes:**
- No workflow-controller running in the cluster
- ResourceQuota exceeded in the namespace
- PodSecurityPolicy/PodSecurityAdmission blocking pod creation
- ServiceAccount doesn't exist
- PriorityClass not found
- Node affinity/tolerations preventing scheduling
- `synchronization` semaphore or mutex is held by another Workflow

**Debug:**
```bash
# Check workflow controller
kubectl get pods --all-namespaces -l app=workflow-controller

# Check resource quotas
kubectl get resourcequota -n <namespace>
kubectl describe resourcequota -n <namespace>

# Check ServiceAccount
kubectl get sa <sa-name> -n <namespace>

# Check synchronization (use the specific sub-field, the parent returns empty)
kubectl get workflow <name> -n <namespace> -o jsonpath='{.status.synchronization.semaphore}'
kubectl get workflow <name> -n <namespace> -o jsonpath='{.status.synchronization.mutex}'
```

### Workflow Failed — OOMKilled

**Symptoms:** Workflow node shows `Failed` with `OOMKilled` reason.

**Causes:**
- Container `resources.limits.memory` too low for the workload
- Memory leak in the user's script/binary
- Large file processing in memory

**Debug:**
```bash
# Get the failed pod's termination status
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'

# Check the resource limits in the template
kubectl get workflow <name> -n <namespace> -o jsonpath='{.spec.templates[*].container.resources}'
```

**Fix:** Increase `resources.limits.memory` in the Workflow template. Or add `resources` to the specific step that failed.

### Workflow Failed — deadline exceeded

**Symptoms:** Workflow message contains "exceeded its deadline" or "activeDeadlineSeconds".

**Causes:**
- `activeDeadlineSeconds` set on the Workflow or template and exceeded
- Long-running step blocked on I/O or external dependency
- Retry loop consuming time budget

**Debug:**
```bash
# Check deadline
kubectl get workflow <name> -n <namespace> -o jsonpath='{.spec.activeDeadlineSeconds}'

# Check which node was running when deadline hit
kubectl get workflow <name> -n <namespace> -o jsonpath='{range .status.nodes[*]}{.displayName}: {.phase} started={.startedAt} finished={.finishedAt}{"\n"}{end}'
```

### Workflow Failed — artifact error

**Symptoms:** `wait` container logs show S3/GCS/Artifactory connectivity or permission errors.

**Causes:**
- Artifact repository not configured — check `default-artifact-repository` in workflow-controller ConfigMap
- S3 bucket credentials expired or wrong
- S3 endpoint URL incorrect (especially for MinIO)
- Artifact key collision (two steps writing to the same path)
- GCS service account JSON key invalid

**Debug:**
```bash
# Check artifact repository config
kubectl get configmap workflow-controller-configmap -n argo -o yaml | grep -A20 artifactRepository

# Check wait container logs for the failed pod
kubectl logs <pod-name> -n <namespace> -c wait --tail=100

# Check the Secret referenced for artifact credentials
kubectl get secret <artifact-secret> -n argo -o yaml
```

### DAG steps stuck — dependency cycle

**Symptoms:** Workflow is `Running` but no progress. Nodes are in `Pending` phase indefinitely.

**Causes:**
- Circular dependency in DAG `dependencies` field (A -> B -> C -> A)
- Dependency references a task name that doesn't exist (typo)
- `when` condition on a task depends on a task that is itself waiting

**Debug:**
```bash
# Get the DAG definition
kubectl get workflow <name> -n <namespace> -o jsonpath='{.spec.templates[?(@.dag)].dag.tasks}' | python3 -m json.tool

# Check node states
kubectl get workflow <name> -n <namespace> -o jsonpath='{range .status.nodes[*]}{.displayName}: {.phase} type={.type}{"\n"}{end}'
```

### CronWorkflow not firing

**Symptoms:** CronWorkflow exists but no new Workflows are created at the expected schedule.

**Causes:**
- `spec.timezone` is wrong or missing (defaults to controller's timezone, usually UTC)
- `spec.concurrencyPolicy: Forbid` and a previous Workflow is still running
- `spec.startingDeadlineSeconds` is too short — the controller missed the window
- `spec.suspend: true` — CronWorkflow is explicitly suspended
- Workflow controller is not running or not watching the namespace

**Debug:**
```bash
# Check CronWorkflow config
kubectl get cronworkflow <name> -n <namespace> -o yaml

# Check last scheduled time
kubectl get cronworkflow <name> -n <namespace> -o jsonpath='last={.status.lastScheduledTime}, active={.status.active}'

# Check for active workflows from this CronWorkflow
kubectl get workflows -n <namespace> -l workflows.argoproj.io/cron-workflow=<name>

# Check controller logs
kubectl logs -n argo -l app=workflow-controller --tail=100 | grep <name>
```

---

## Events Issues

### EventSource not receiving events

**Symptoms:** EventSource status is `Ready` but no events flow to the Sensor. Sensor logs show no incoming events.

**Causes (by EventSource type):**

| Type | Common Cause |
|------|-------------|
| webhook | URL not reachable — firewall, no Ingress/Service, wrong port |
| github/gitlab | Webhook secret mismatch, webhook not configured on the repo |
| sns/sqs | IAM permissions, wrong region, queue/topic ARN incorrect |
| kafka | Broker unreachable, topic doesn't exist, consumer group conflict |
| resource | RBAC — EventSource ServiceAccount can't watch the resource |
| calendar | Timezone issue, cron expression syntax |
| file | Volume mount missing, file path doesn't exist in the pod |

**Debug:**
```bash
# Check EventSource pods
kubectl get pods -n <namespace> -l eventsource-name=<name>
kubectl logs -n <namespace> -l eventsource-name=<name> --tail=200

# For webhook: check Service and Ingress
kubectl get svc -n <namespace> | grep <eventsource-name>
kubectl get ingress -n <namespace> | grep <eventsource-name>

# For webhook: test connectivity from inside the cluster
kubectl run curl-test --rm -i --restart=Never --image=curlimages/curl -- curl -v http://<service>.<namespace>.svc:<port>/<endpoint>
```

### EventBus pods crashing

**Symptoms:** EventBus pods in CrashLoopBackOff or restarting frequently. Events not flowing.

**Causes:**
- NATS cluster can't form quorum — pod anti-affinity with insufficient nodes
- Disk pressure — NATS JetStream storage full
- TLS certificate issues between NATS nodes
- Resource limits too low for the event volume
- PersistentVolume issues for JetStream storage

**Debug:**
```bash
# Check EventBus pods
kubectl get pods -n <namespace> -l controller=eventbus
kubectl describe pods -n <namespace> -l controller=eventbus

# Check NATS logs
kubectl logs -n <namespace> <eventbus-pod> --tail=200

# Check PVCs for JetStream
kubectl get pvc -n <namespace> -l controller=eventbus

# Check EventBus status
kubectl get eventbus -n <namespace> -o yaml
```

### Sensor not triggering

**Symptoms:** Events are reaching the EventBus (EventSource logs confirm publishing), but the Sensor does not fire triggers.

**Causes:**
- `spec.dependencies[].eventSourceName` or `spec.dependencies[].eventName` doesn't match the EventSource event key
- `spec.dependencies[].filters` are excluding all events:
  - `filters.data` — JSONPath filter doesn't match the event payload
  - `filters.context` — CloudEvents context attributes don't match
  - `filters.time` — time window filter excluding current time
  - `filters.exprFilters` — CEL/expression evaluating to false
- Dependency expression (`spec.dependencies[].filtersLogicalOperator`) using `and` when `or` is needed
- EventBus subscription issue — Sensor pod restarted and lost its subscription position

**Debug:**
```bash
# Check Sensor status
kubectl get sensor <name> -n <namespace> -o yaml

# Check Sensor pod logs — look for "event received" and "trigger executed" messages
kubectl logs -n <namespace> -l sensor-name=<name> --tail=200

# Verify dependency names match EventSource event keys
kubectl get eventsource <es-name> -n <namespace> -o jsonpath='{.spec}' | python3 -c "
import sys, json
spec = json.load(sys.stdin)
for event_type, events in spec.items():
    if isinstance(events, dict):
        for name in events:
            print(f'{event_type}/{name}')
"
```

### Trigger failing — target resource not created

**Symptoms:** Sensor logs show "event received" and "executing trigger" but the target resource (e.g., Workflow) is not created.

**Causes:**
- RBAC: Sensor ServiceAccount doesn't have permission to create the target resource
- Trigger template has invalid YAML (rendering error with parameter substitution)
- `spec.triggers[].template.k8s.operation` is wrong (e.g., `update` for a resource that doesn't exist yet)
- `spec.triggers[].template.k8s.source.resource` has an invalid manifest
- Parameter dependency references a non-existent path in the event payload

**Debug:**
```bash
# Check Sensor ServiceAccount RBAC
SA=$(kubectl get sensor <name> -n <namespace> -o jsonpath='{.spec.template.serviceAccountName}')
echo "ServiceAccount: $SA"
kubectl auth can-i create workflows --as=system:serviceaccount:<namespace>:$SA -n <namespace>
kubectl auth can-i create pods --as=system:serviceaccount:<namespace>:$SA -n <namespace>

# Check Sensor logs for trigger errors
kubectl logs -n <namespace> -l sensor-name=<name> --tail=200 | grep -i -E 'error|fail|trigger'

# Check the trigger template
kubectl get sensor <name> -n <namespace> -o jsonpath='{.spec.triggers[0].template}' | python3 -m json.tool
```

### Full pipeline debug: EventSource -> EventBus -> Sensor -> Trigger

When the break point is unclear, trace the full pipeline:

```bash
# 1. EventBus health
kubectl get eventbus -n <namespace>
kubectl get pods -n <namespace> -l controller=eventbus

# 2. EventSource health and event publishing
kubectl get eventsource -n <namespace>
kubectl logs -n <namespace> -l eventsource-name=<name> --tail=50 | grep -i publish

# 3. Sensor health and event receipt
kubectl get sensor -n <namespace>
kubectl logs -n <namespace> -l sensor-name=<name> --tail=50 | grep -i -E 'event|trigger'

# 4. Target resource creation
kubectl get <target-kind> -n <namespace> --sort-by='.metadata.creationTimestamp' | tail -5
```

---

## Common kubectl Commands

Quick reference for the most-used debug commands across all Argo components.

### Argo CD

| Command | Purpose |
|---------|---------|
| `kubectl get applications -n argocd` | List all Applications |
| `kubectl get applications -n argocd -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'` | Application status summary |
| `kubectl get applicationsets -n argocd` | List all ApplicationSets |
| `kubectl get appprojects -n argocd` | List all AppProjects |
| `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100` | Controller logs |
| `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=100` | Repo server logs |
| `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=100` | API server logs |
| `kubectl get configmap argocd-cm -n argocd -o yaml` | Server configuration |
| `kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository` | Configured repositories |
| `kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster` | Configured clusters |
| `argocd app list` | List apps (CLI) |
| `argocd app get <name>` | App detail (CLI) |
| `argocd app diff <name>` | Show diff (CLI) |
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
| `kubectl logs -n argo-rollouts -l app.kubernetes.io/name=argo-rollouts` | Rollouts controller logs |

### Argo Workflows

| Command | Purpose |
|---------|---------|
| `kubectl get workflows -n <ns>` | List Workflows |
| `kubectl get workflowtemplates -n <ns>` | List WorkflowTemplates |
| `kubectl get clusterworkflowtemplates` | List ClusterWorkflowTemplates |
| `kubectl get cronworkflows -n <ns>` | List CronWorkflows |
| `argo list -n <ns>` | List workflows (CLI) |
| `argo get <name> -n <ns>` | Workflow detail (CLI) |
| `argo logs <name> -n <ns>` | Workflow logs (CLI) |
| `argo logs <name> -n <ns> --node-id <id>` | Node-specific logs (CLI) |
| `kubectl logs -n argo -l app=workflow-controller --tail=100` | Controller logs |
| `kubectl get configmap workflow-controller-configmap -n argo -o yaml` | Controller config |

### Argo Events

| Command | Purpose |
|---------|---------|
| `kubectl get eventsources -n <ns>` | List EventSources |
| `kubectl get sensors -n <ns>` | List Sensors |
| `kubectl get eventbus -n <ns>` | List EventBus |
| `kubectl logs -n <ns> -l eventsource-name=<name> --tail=100` | EventSource logs |
| `kubectl logs -n <ns> -l sensor-name=<name> --tail=100` | Sensor logs |
| `kubectl get pods -n <ns> -l controller=eventbus` | EventBus pods |
| `kubectl logs -n <ns> -l controller=eventsource-controller --tail=100` | EventSource controller logs |
| `kubectl logs -n <ns> -l controller=sensor-controller --tail=100` | Sensor controller logs |

---

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

### Argo Workflows v3.6+
- Artifact GC — `spec.artifactGC.strategy` controls cleanup
- `spec.hooks` for lifecycle hooks (exit, on-error)
- HTTP template for API calls without pods
- Plugin templates for custom executors
- `spec.synchronization.mutex` and `spec.synchronization.semaphore` for concurrency control

### Argo Events v1.10+
- JetStream as default EventBus (replacing NATS Streaming)
- `spec.eventBusName` to reference specific EventBus instances
- Rate limiting on Sensors
- Event dependency filtering with CEL expressions
- `spec.triggers[].atLeastOnce` for delivery guarantees
