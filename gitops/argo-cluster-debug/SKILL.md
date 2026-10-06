---
name: argo-cluster-debug
description: >
  Debug and troubleshoot the Argo ecosystem on live Kubernetes clusters — inspects
  Argo CD Application sync status, health checks, and controller logs; diagnoses
  Argo Rollouts canary/blue-green failures and AnalysisRun results; traces Argo
  Workflow step failures and artifact issues; and debugs Argo Events EventSource
  and Sensor connectivity. Prefers argocd/argo CLIs when available, falls back to
  kubectl for CRD inspection. Use when users report failing, stuck, or degraded
  Argo resources on a cluster.
license: MIT
compatibility: Requires kubectl; optionally argocd, argo (workflows CLI), kubectl-argo-rollouts
---

# Argo Cluster Debug

Debug and troubleshoot the full Argo ecosystem on live Kubernetes clusters.

## Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| kubectl | Yes | CRD inspection, pod logs, resource status |
| argocd | No | Richer Application output, diff, sync operations |
| argo | No | Workflow logs, node inspection |
| kubectl-argo-rollouts | No | Rollout status, step details, promotion |

## How This Skill Works

The debug skill provides **systematic workflows** — each is a sequence of checks that
traces the problem from surface symptoms to root cause. The value is in the completeness
of the investigation, not just finding the first error.

**Before starting any workflow:**
1. Check which CLIs are available (argocd, argo, kubectl-argo-rollouts, kubectl)
2. Confirm the current cluster context
3. Load `references/troubleshooting.md` — it maps symptoms to causes and saves time

**General rules:**
- Prefer specialized CLIs when available (richer output), fall back to `kubectl get -o yaml`
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

Execute the workflow that matches the user's problem. Each workflow is self-contained.
Work through the steps in order — each step builds context for the next.

---

### Workflow 1: Argo CD Installation Check

Use when: user asks if Argo CD is installed, reports general Argo CD failures, or as a prerequisite before Application debugging.

**Steps:**

1. Check for Argo CD CRDs:
   ```bash
   kubectl get crd | grep argoproj.io
   ```
   Expected CRDs: `applications.argoproj.io`, `appprojects.argoproj.io`, `applicationsets.argoproj.io`. If missing, Argo CD is not installed.

2. Identify the Argo CD namespace. It defaults to `argocd` but can be customized:
   ```bash
   kubectl get pods --all-namespaces -l app.kubernetes.io/part-of=argocd --no-headers | awk '{print $1}' | sort -u
   ```

3. Check all pods in the Argo CD namespace:
   ```bash
   kubectl get pods -n argocd -o wide
   ```

4. Verify core components are running. All required components must be `Running` with `READY` containers:
   | Component | Label Selector | Required |
   |-----------|---------------|----------|
   | argocd-server | `app.kubernetes.io/name=argocd-server` | Yes |
   | argocd-repo-server | `app.kubernetes.io/name=argocd-repo-server` | Yes |
   | argocd-application-controller | `app.kubernetes.io/name=argocd-application-controller` | Yes |
   | argocd-applicationset-controller | `app.kubernetes.io/name=argocd-applicationset-controller` | Yes |
   | argocd-redis | `app.kubernetes.io/name=argocd-redis` | Yes |
   | argocd-dex-server | `app.kubernetes.io/name=argocd-dex-server` | Yes |
   | argocd-notifications-controller | `app.kubernetes.io/name=argocd-notifications-controller` | No (optional) |

   **Note:** `argocd-notifications-controller` is not deployed in all installations. Its absence should not be treated as a failure.

5. If argocd CLI is available, check version compatibility:
   ```bash
   argocd version
   ```
   Compare client and server versions. Mismatches beyond minor version can cause issues.

6. Check the argocd-cm ConfigMap for server configuration:
   ```bash
   kubectl get configmap argocd-cm -n argocd -o yaml
   ```
   Look for: `url` (server URL), `repositories` (legacy repo config), `resource.customizations` (custom health checks), `kustomize.buildOptions`, `configManagementPlugins`.

7. Check argocd-rbac-cm for RBAC configuration:
   ```bash
   kubectl get configmap argocd-rbac-cm -n argocd -o yaml
   ```
   Look for: `policy.default`, `policy.csv`, `scopes`.

8. If any component is CrashLoopBackOff or not ready, get its logs:
   ```bash
   kubectl logs -n argocd -l app.kubernetes.io/name=<component-name> --tail=100 --previous
   kubectl logs -n argocd -l app.kubernetes.io/name=<component-name> --tail=100
   ```

9. Check Argo CD events:
   ```bash
   kubectl get events -n argocd --sort-by='.lastTimestamp' | tail -30
   ```

---

### Workflow 2: Application Debugging

Use when: user reports Application sync failure, health degradation, OutOfSync, or unknown status.

**Steps:**

1. Get the Application resource:
   - argocd CLI:
     ```bash
     argocd app get <name> -o yaml
     ```
   - kubectl:
     ```bash
     kubectl get application <name> -n argocd -o yaml
     ```
   If the Application is in a non-default namespace, the user must specify it or check:
   ```bash
   kubectl get applications --all-namespaces | grep <name>
   ```

2. Extract and assess sync status from `.status.sync.status`:
   | Status | Meaning |
   |--------|---------|
   | Synced | Live state matches desired state |
   | OutOfSync | Live state differs from desired state |
   | Unknown | Comparison could not be performed |

3. Extract and assess health status from `.status.health.status`:
   | Status | Meaning |
   |--------|---------|
   | Healthy | All resources healthy |
   | Degraded | One or more resources failed |
   | Progressing | Resources are being rolled out |
   | Suspended | Resource is paused (e.g., suspended CronJob, paused Rollout) |
   | Missing | Resource does not exist in the cluster |
   | Unknown | Health assessment not available |

4. Check `.status.conditions` for error messages. Common conditions:
   - `ComparisonError` — manifest generation failed
   - `SyncError` — sync operation failed
   - `InvalidSpecError` — Application spec is invalid
   - `OrphanedResourceWarning` — resources exist outside the Application's management

5. Check `.status.operationState` for the last sync operation:
   - `.status.operationState.phase` — Succeeded, Failed, Error, Running
   - `.status.operationState.message` — error detail
   - `.status.operationState.syncResult.resources` — per-resource sync results

6. If OutOfSync, analyze the diff:
   - argocd CLI:
     ```bash
     argocd app diff <name>
     ```
   - kubectl: inspect `.status.resources` and compare `status` field per resource. Look for resources with `status: OutOfSync`.

7. Check the source configuration. Applications may use either `spec.source` (single-source) or `spec.sources[]` (multi-source, GA since v2.6). Check both:
   ```bash
   # Check if multi-source
   kubectl get application <name> -n argocd -o jsonpath='{.spec.sources}' 2>/dev/null | grep -q '\[' && echo "multi-source" || echo "single-source"

   # Single-source
   kubectl get application <name> -n argocd -o jsonpath='{.spec.source}' | python3 -m json.tool

   # Multi-source — iterate all sources
   kubectl get application <name> -n argocd -o jsonpath='{range .spec.sources[*]}repoURL={.repoURL} targetRevision={.targetRevision} path={.path} chart={.chart}{"\n"}{end}'
   ```
   For multi-source Applications, each source can fail independently — verify `repoURL`, `targetRevision`, `path`, and Helm `valueFiles` for every entry in `spec.sources[]`.

8. If repo-server is failing to render manifests, check repo-server logs:
   ```bash
   kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=100
   ```

9. Inspect managed resources. List resources from `.status.resources` with non-Healthy or non-Synced status:
   ```bash
   kubectl get application <name> -n argocd -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name}: sync={.status}, health={.health.status}{"\n"}{end}'
   ```

10. For each unhealthy managed resource, inspect it:
    ```bash
    kubectl get <kind> <name> -n <namespace> -o yaml
    kubectl describe <kind> <name> -n <namespace>
    kubectl get events -n <namespace> --field-selector involvedObject.name=<name>
    ```

11. If managed resource is a Deployment/StatefulSet with failing pods:
    ```bash
    kubectl get pods -n <namespace> -l <label-selector> --sort-by='.status.startTime'
    kubectl logs -n <namespace> <pod-name> --tail=100
    kubectl logs -n <namespace> <pod-name> --previous --tail=100
    ```

12. Produce a root cause analysis report (see Report Format).

---

### Workflow 3: ApplicationSet Debugging

Use when: user reports ApplicationSet not generating Applications, generating wrong Applications, or ApplicationSet errors.

**Steps:**

1. Get the ApplicationSet:
   ```bash
   kubectl get applicationset <name> -n argocd -o yaml
   ```

2. Check `.status.conditions` for errors. Key conditions:
   - `ErrorOccurred` — generator or template rendering failed
   - `ParametersGenerated` — generator output status
   - `ResourcesUpToDate` — template application status

3. Identify the generator type and check its configuration:
   | Generator | Common Issues |
   |-----------|--------------|
   | list | Empty `elements` array |
   | git (directories) | `repoURL` inaccessible, `directories` path pattern wrong |
   | git (files) | File format invalid, path pattern wrong |
   | cluster | No matching clusters, label selector wrong |
   | pull request | API credentials missing/expired, no open PRs matching filter |
   | scmProvider | API credentials missing, org/owner wrong |
   | matrix/merge | Inner generator errors, key conflicts |
   | plugin | Plugin ConfigMap missing, generator RPC error |

4. List generated Applications:
   ```bash
   kubectl get applications -n argocd -l 'app.kubernetes.io/managed-by=applicationset-controller' --show-labels
   ```
   Cross-reference with expected output from the generator.

5. If no Applications generated, check the applicationset-controller logs:
   ```bash
   kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller --tail=200
   ```

6. If some Applications are generated but failing, debug each one using Workflow 2.

7. For progressive sync issues, check `spec.strategy`:
   ```bash
   kubectl get applicationset <name> -n argocd -o jsonpath='{.spec.strategy}' | python3 -m json.tool
   ```
   Check `rollingSync.steps`, `maxUpdate` values, and whether unhealthy apps are blocking progression.

---

### Workflow 4: Rollout Debugging

Use when: user reports canary/blue-green rollout stuck, aborted, or degraded.

**Steps:**

1. Get the Rollout status:
   - kubectl-argo-rollouts:
     ```bash
     kubectl argo rollouts get rollout <name> -n <namespace>
     ```
   - kubectl:
     ```bash
     kubectl get rollout <name> -n <namespace> -o yaml
     ```

2. Check the phase from `.status.phase`:
   | Phase | Meaning |
   |-------|---------|
   | Healthy | Rollout completed successfully |
   | Paused | Waiting for manual promotion or analysis |
   | Progressing | Actively rolling out |
   | Degraded | Rollout encountered errors |
   | Aborting | Rollback in progress |
   | Aborted | Rollback completed |

3. For canary rollouts, check current step and step index:
   ```bash
   kubectl get rollout <name> -n <namespace> -o jsonpath='{.status.currentStepIndex}'
   kubectl get rollout <name> -n <namespace> -o jsonpath='{.spec.strategy.canary.steps}'
   ```
   Identify which step the rollout is paused/stuck at.

4. If paused, determine the reason:
   - `pause` step: manual approval required. Check `.status.pauseConditions`.
   - `analysis` step: AnalysisRun in progress. Proceed to step 5.
   - `setWeight` step: traffic shift issue. Proceed to step 8.

5. Get AnalysisRuns for this Rollout:
   ```bash
   kubectl get analysisrun -n <namespace> --sort-by='.metadata.creationTimestamp'
   ```
   Filter by Rollout ownership:
   ```bash
   kubectl get analysisrun -n <namespace> -o yaml | grep -A5 'ownerReferences' | grep '<rollout-name>'
   ```
   Or use the revision label:
   ```bash
   kubectl get analysisrun -n <namespace> -l rollouts-pod-template-hash=<hash>
   ```

6. Inspect the AnalysisRun:
   ```bash
   kubectl get analysisrun <analysisrun-name> -n <namespace> -o yaml
   ```
   Check:
   - `.status.phase` — Running, Successful, Failed, Error, Inconclusive
   - `.status.metricResults[*].phase` — per-metric status
   - `.status.metricResults[*].measurements` — individual measurement values
   - `.status.metricResults[*].message` — error messages from the provider

7. If analysis failed, check the AnalysisTemplate:
   ```bash
   kubectl get analysistemplate <template-name> -n <namespace> -o yaml
   ```
   Verify:
   - `successCondition` / `failureCondition` expressions
   - `provider` configuration (Prometheus URL, Datadog API key, web query, etc.)
   - `interval`, `count`, `failureLimit`, `inconclusiveLimit`

8. Check traffic management configuration:
   - Istio:
     ```bash
     kubectl get virtualservice -n <namespace> -o yaml
     kubectl get destinationrule -n <namespace> -o yaml
     ```
   - NGINX Ingress:
     ```bash
     kubectl get ingress -n <namespace> -o yaml
     ```
     Check `canary-*` annotations.
   - ALB:
     ```bash
     kubectl get ingress -n <namespace> -o yaml
     ```
     Check `alb.ingress.kubernetes.io/*` annotations.
   - Traefik:
     ```bash
     kubectl get traefikservice -n <namespace> -o yaml
     ```

9. Check ReplicaSets — compare stable vs canary:
   ```bash
   kubectl get replicaset -n <namespace> -l app=<app-label> -o wide
   ```
   The stable RS has the `rollouts-pod-template-hash` matching `.status.stableRS`, canary RS matches `.status.currentPodHash`.

10. Check pod status for the canary ReplicaSet:
    ```bash
    kubectl get pods -n <namespace> -l rollouts-pod-template-hash=<canary-hash>
    kubectl describe pods -n <namespace> -l rollouts-pod-template-hash=<canary-hash>
    ```

11. Produce a root cause analysis report.

---

### Workflow 5: Workflow Debugging

Use when: user reports Workflow failure, stuck steps, or errors.

**Steps:**

1. Get the Workflow:
   - argo CLI:
     ```bash
     argo get <name> -n <namespace>
     ```
   - kubectl:
     ```bash
     kubectl get workflow <name> -n <namespace> -o yaml
     ```

2. Check the phase from `.status.phase`:
   | Phase | Meaning |
   |-------|---------|
   | Pending | Not yet scheduled |
   | Running | Actively executing |
   | Succeeded | All steps completed |
   | Failed | One or more steps failed |
   | Error | System error (not step failure) |
   | Omitted | Step skipped by when condition |
   | Skipped | Node skipped because `when` expression evaluated to false or a dependency failed |

3. If the Workflow is Failed or Error, identify the failed node(s) from `.status.nodes`:
   ```bash
   kubectl get workflow <name> -n <namespace> -o jsonpath='{range .status.nodes[*]}{.displayName}: {.phase} - {.message}{"\n"}{end}' | grep -E 'Failed|Error'
   ```

4. Get logs for the failed node:
   - argo CLI:
     ```bash
     argo logs <name> -n <namespace> --node-id <node-id>
     ```
   - kubectl (the pod name is the node ID):
     ```bash
     kubectl logs <pod-name> -n <namespace> -c main --tail=200
     ```
   Also check the `wait` container for artifact/sidecar issues:
   ```bash
   kubectl logs <pod-name> -n <namespace> -c wait --tail=100
   ```

5. Check for common failure patterns:
   | Pattern | Indicator |
   |---------|-----------|
   | ImagePullBackOff | Pod event shows image pull failure |
   | OOMKilled | Container `lastState.terminated.reason=OOMKilled` |
   | Deadline exceeded | `.status.message` contains "exceeded its deadline" |
   | Artifact error | `wait` container logs show S3/GCS/Artifactory errors |
   | Resource quota | Pod event shows "exceeded quota" |
   | Pod security | Pod event shows SecurityContext violation |
   | Node selector | Pod event shows "didn't match Pod's node affinity" |

6. If using a DAG template, trace the dependency chain:
   ```bash
   kubectl get workflow <name> -n <namespace> -o jsonpath='{.spec.templates[?(@.dag)].dag.tasks[*]}' | python3 -m json.tool
   ```
   Identify which upstream task's failure caused downstream omissions.

7. If using `templateRef` or `workflowTemplateRef`, check the referenced template:
   ```bash
   kubectl get workflowtemplate <template-name> -n <namespace> -o yaml
   ```
   Or for cluster-scoped:
   ```bash
   kubectl get clusterworkflowtemplate <template-name> -o yaml
   ```

8. Check the ServiceAccount and its permissions:
   ```bash
   kubectl get workflow <name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}'
   kubectl get rolebinding,clusterrolebinding -n <namespace> -o yaml | grep -A5 <service-account-name>
   ```

9. If Pending, check the Workflow controller logs:
   ```bash
   kubectl logs -n argo -l app=workflow-controller --tail=100
   ```
   The controller namespace may differ — check:
   ```bash
   kubectl get pods --all-namespaces -l app=workflow-controller
   ```

10. For CronWorkflow issues:
    ```bash
    kubectl get cronworkflow <name> -n <namespace> -o yaml
    ```
    Check `.status.lastScheduledTime`, `.status.active`, `spec.concurrencyPolicy`, `spec.timezone`.

11. Produce a root cause analysis report.

---

### Workflow 6: EventSource / Sensor Debugging

Use when: user reports events not flowing, Sensor not triggering, or EventSource failures.

**Steps:**

1. Check the EventBus first — it is the backbone:
   ```bash
   kubectl get eventbus -n <namespace> -o yaml
   ```
   Verify the EventBus pods are running:
   ```bash
   kubectl get pods -n <namespace> -l controller=eventbus
   ```
   For NATS-based EventBus:
   ```bash
   kubectl get statefulset -n <namespace> -l eventbus-name=<eventbus-name>
   ```

2. Get the EventSource:
   ```bash
   kubectl get eventsource <name> -n <namespace> -o yaml
   ```

3. Check EventSource `.status.conditions`:
   | Condition | Healthy State |
   |-----------|--------------|
   | Deployed | True |
   | DependenciesProvided | True |
   | SourceReady | True |

4. If EventSource is not ready, check its pods:
   ```bash
   kubectl get pods -n <namespace> -l eventsource-name=<name>
   kubectl logs -n <namespace> -l eventsource-name=<name> --tail=100
   ```

5. For webhook EventSources, verify network connectivity:
   ```bash
   kubectl get svc -n <namespace> -l eventsource-name=<name>
   kubectl get ingress -n <namespace> | grep <eventsource-name>
   ```

6. Get the Sensor:
   ```bash
   kubectl get sensor <name> -n <namespace> -o yaml
   ```

7. Check Sensor `.status.conditions`:
   | Condition | Healthy State |
   |-----------|--------------|
   | Deployed | True |
   | DependenciesProvided | True |
   | SensorReady | True |
   | TriggersProvided | True |

8. If Sensor is deployed but not triggering, check:
   - Dependencies: each dependency must reference a valid EventSource and event name
   - Filters: `filters.data`, `filters.context`, `filters.time` may be excluding events
   - Event dependency expression: `spec.dependencies[*].eventSourceName` and `spec.dependencies[*].eventName` must match the EventSource's event keys

9. Check Sensor pod logs for event receipt and trigger execution:
   ```bash
   kubectl logs -n <namespace> -l sensor-name=<name> --tail=200
   ```

10. If triggers are failing, check the trigger template:
    - For `k8s` triggers: verify the RBAC for the Sensor ServiceAccount to create the target resource
      ```bash
      kubectl get sa -n <namespace> -l sensor-name=<name>
      # Note: -n <target-namespace> is the namespace where the resource will be created,
      # not necessarily the ServiceAccount's namespace. The --as flag uses the SA's namespace.
      kubectl auth can-i create workflows --as=system:serviceaccount:<sa-namespace>:<sa-name> -n <target-namespace>
      ```
    - For `http` triggers: verify the URL, TLS, and payload
    - For `aws-lambda`, `slack`, etc.: check credentials in referenced Secrets

11. Trace the full pipeline:
    ```
    EventSource (ingests) -> EventBus (transports) -> Sensor (filters & triggers) -> Target Resource
    ```
    Check each component in order. The break is usually at the first unhealthy component.

12. Produce a root cause analysis report.

---

### Workflow 7: Log Analysis

Use for any Argo component when logs are needed.

**Steps:**

1. Identify the Deployment managing the target pods:
   ```bash
   kubectl get deployment -n <namespace> -l <label-selector>
   ```

2. Extract the label selector and container name:
   ```bash
   kubectl get deployment <deployment-name> -n <namespace> -o jsonpath='{.spec.selector.matchLabels}' | python3 -m json.tool
   kubectl get deployment <deployment-name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[*].name}'
   ```

3. List pods with matching labels:
   ```bash
   kubectl get pods -n <namespace> -l <key=value> --sort-by='.status.startTime'
   ```

4. Get logs — prefer `--tail` to limit output:
   ```bash
   kubectl logs <pod-name> -n <namespace> -c <container> --tail=200
   ```
   For previous instance (after crash):
   ```bash
   kubectl logs <pod-name> -n <namespace> -c <container> --previous --tail=200
   ```

5. Analyze logs for:
   - `level=error` or `"error"` entries
   - Stack traces
   - Connection refused / timeout patterns
   - RBAC denied messages
   - OOM or resource pressure signals
   - Repeated restart patterns (check timestamps)

---

## Report Format

Every debugging session must conclude with a structured report.

### 1. Summary

| Field | Value |
|-------|-------|
| Cluster Context | `<context-name>` |
| Argo Component | CD / Rollouts / Workflows / Events |
| Component Versions | e.g., Argo CD v2.14.2 |
| Resource | `<kind>/<namespace>/<name>` |
| Current Status | Sync/Health/Phase status |

### 2. Resource Analysis

- **Spec**: key configuration details (source, strategy, template)
- **Status Conditions**: each condition with type, status, message, timestamp
- **Events**: relevant Kubernetes events

### 3. Dependency Chain

Map the full dependency chain relevant to the problem:
- Argo CD: `Git Repo -> Repo Server -> Application -> Managed Resources -> Pods`
- Rollouts: `Rollout -> ReplicaSets -> Pods`, `Rollout -> AnalysisRun -> Metric Provider`
- Workflows: `Workflow -> DAG/Steps -> Pods -> Artifacts`
- Events: `EventSource -> EventBus -> Sensor -> Trigger Target`

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

---

## Edge Cases

Handle these scenarios explicitly:

| Scenario | Behavior |
|----------|----------|
| Argo CD not installed (no argocd namespace or CRDs) | Report "Argo CD is not installed on this cluster" and stop Application/AppSet workflows |
| argocd CLI not logged in | Detect `FATAL: Argo CD server address unspecified` and suggest `argocd login <server>` |
| Multiple Argo CD instances | If multiple namespaces found, list them and ask user to specify |
| Application in Progressing state | Note that the resource is actively reconciling — wait 60s and re-check before diagnosing |
| Suspended Application or Rollout | Report as intentional suspension, do not treat as error unless user says otherwise |
| Unknown health status | Check for custom health check Lua scripts in `argocd-cm` under `resource.customizations.health.<group_kind>` |
| Rollout without traffic management | Note that canary is replica-based only — weight percentages are approximated by replica ratio |
| Workflow pods cleaned up by GC | Report that logs are unavailable due to pod GC — suggest increasing `spec.podGC.strategy` or checking archived workflows |
| CronWorkflow not firing | Check `spec.timezone`, `spec.concurrencyPolicy`, `spec.startingDeadlineSeconds`, and whether previous run is still active |
| Argo Events NATS cluster split | Check NATS pod logs for cluster connectivity, check PDB and pod anti-affinity |
| Helm source with missing values files | Check `spec.source.helm.valueFiles` paths relative to the chart, not the repo root |
| Multi-source Application | Iterate all entries in `spec.sources[]` — each source can fail independently |

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
| Workflow | Argo Workflows | DAG/step-based job execution (`argoproj.io/v1alpha1`) |
| WorkflowTemplate | Argo Workflows | Reusable workflow definition |
| ClusterWorkflowTemplate | Argo Workflows | Cluster-scoped WorkflowTemplate |
| CronWorkflow | Argo Workflows | Scheduled workflow execution |
| EventSource | Argo Events | Event ingestion (webhooks, SNS, SQS, etc.) |
| EventBus | Argo Events | Event transport (NATS, JetStream, Kafka) |
| Sensor | Argo Events | Event-driven trigger execution |
