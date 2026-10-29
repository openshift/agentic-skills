<!-- Loaded on demand by skills/gitops/argo-cluster-debug/SKILL.md. Load only the workflow(s)
     matching the reported symptom; each is self-contained. -->

# Debugging Workflows

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

Execute the workflow that matches the user's problem. Each workflow is self-contained.
Work through the steps in order — each step builds context for the next.

---

## Workflow 1: Argo CD Installation Check

Use when: user asks if Argo CD is installed, reports general Argo CD failures, or as a prerequisite before Application debugging.

**Steps:**

1. Check for Argo CD CRDs:
   ```bash
   kubectl get crd | grep argoproj.io
   ```
   Expected CRDs: `applications.argoproj.io`, `appprojects.argoproj.io`, `applicationsets.argoproj.io`. If missing, Argo CD is not installed.

2. Identify every Argo CD instance and its namespace. **Do not rely on the
   `part-of=argocd` label alone** — Operator-managed installs (OpenShift GitOps) do not
   set it on pods, so the label selector reports nothing on a cluster running several
   instances, and this step wrongly concludes "Argo CD is not installed":

   ```bash
   # Operator-managed (OpenShift GitOps / argocd-operator): the ArgoCD CR is authoritative
   if kubectl get crd argocds.argoproj.io >/dev/null 2>&1; then
     kubectl get argocd -A --no-headers 2>/dev/null | awk '{print $1"\t"$2"\t(operator)"}'
   fi
   # Helm / plain-manifest installs do carry the label
   kubectl get pods -A -l app.kubernetes.io/part-of=argocd --no-headers 2>/dev/null \
     | awk '{print $1}' | sort -u | sed 's/$/\t-\t(helm)/'
   ```

   Set `NS` to the instance you are debugging and use it for every command below. **There
   is frequently more than one instance** — if so, confirm with the user which one before
   continuing, and note that an ArgoCD CR *named* `argocd` may live in a namespace that is
   not `argocd`.

   ```bash
   NS=<argo-cd-namespace>    # e.g. openshift-gitops, argocd, team-x-gitops
   ```

3. Check all pods in that namespace:
   ```bash
   kubectl get pods -n "$NS" -o wide
   ```
   Operator-managed components are named `<cr-name>-server`, `<cr-name>-repo-server`,
   `<cr-name>-application-controller` — not `argocd-*`. Match on suffix, not prefix.

4. Verify core components are running. All required components must be `Running` with
   `READY` containers:

   | Component | Required |
   |-----------|----------|
   | server | Yes |
   | repo-server | Yes |
   | application-controller | Yes |
   | applicationset-controller | Yes |
   | redis | Yes |
   | dex-server | Yes (when SSO is configured) |
   | notifications-controller | No (optional) |

   **The `app.kubernetes.io/name=argocd-<component>` selectors do not work on
   Operator-managed installs.** The Operator sets `app.kubernetes.io/name=<cr-name>-<component>`,
   so a hardcoded `argocd-` prefix silently matches nothing and every component looks
   absent. Enumerate instead of guessing the label:

   ```bash
   kubectl get deploy,sts -n "$NS" -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,WANT:.spec.replicas
   ```

   Then match components by **suffix** (`-server`, `-repo-server`,
   `-application-controller`, …). To target one component's pods, read its selector off
   the workload rather than assuming a label:

   ```bash
   kubectl get deploy -n "$NS" <cr-name>-repo-server -o jsonpath='{.spec.selector.matchLabels}'
   ```

   **Note:** `notifications-controller` is not deployed in all installations. Its absence
   should not be treated as a failure. On OpenShift you will also see non-Argo-CD
   workloads in the namespace (`gitops-plugin`, `argo-rollouts`) — not components of the
   Argo CD instance itself.

5. If argocd CLI is available, check version compatibility:
   ```bash
   argocd version
   ```
   **In `--core` mode this is vacuous** — the CLI *is* the server, so client and server
   always match. Three fallbacks, in order, because the obvious ones fail on OpenShift:

   ```bash
   # 1. The CR's status — usually EMPTY on operator-managed instances. Try it, don't rely on it.
   kubectl get argocd -n "$NS" -o jsonpath='{.items[0].status.version}{"\n"}'

   # 2. The image — on OpenShift this is DIGEST-PINNED, so it gives you a sha256 and no
   #    version. Useful for pinning down an exact build, useless for "what version is this".
   kubectl get deploy -n "$NS" "$CR"-server -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'

   # 3. The operator CSV — the ONLY reliable source of a human-readable version on an
   #    operator-managed cluster. Use the CSV's phase too: it is authoritative where the
   #    Subscription's `state` is not.
   oc get csv -n openshift-gitops-operator -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
   ```

   Report which source you used. "Version unknown" is a legitimate answer on a
   digest-pinned install and is better than quoting a sha256 as if it were a version.
   Compare client and server versions. Mismatches beyond minor version can cause issues.

6. Check the argocd-cm ConfigMap for server configuration:
   ```bash
   kubectl get configmap argocd-cm -n "$NS" -o yaml
   ```
   Look for: `url` (server URL), `repositories` (legacy repo config), `resource.customizations` (custom health checks), `kustomize.buildOptions`, `configManagementPlugins`.

7. Check argocd-rbac-cm for RBAC configuration:
   ```bash
   kubectl get configmap argocd-rbac-cm -n "$NS" -o yaml
   ```
   Look for: `policy.default`, `policy.csv`, `scopes`.

8. If any component is CrashLoopBackOff or not ready, get its logs:
   ```bash
   kubectl logs -n "$NS" -l app.kubernetes.io/name=<component-name> --tail=100 --previous
   kubectl logs -n "$NS" -l app.kubernetes.io/name=<component-name> --tail=100
   ```

9. Check Argo CD events:
   ```bash
   kubectl get events -n "$NS" --sort-by='.lastTimestamp' | tail -30
   ```

---

## Workflow 2: Application Debugging

Use when: user reports Application sync failure, health degradation, OutOfSync, or unknown status.

**Steps:**

1. Get the Application resource:
   - argocd CLI:
     ```bash
     argocd app get <name> -o yaml
     ```
   - kubectl:
     ```bash
     kubectl get applications.argoproj.io <name> -n "$NS" -o yaml
     ```
   If the Application is in a non-default namespace, the user must specify it or check:
   ```bash
   kubectl get applications.argoproj.io --all-namespaces | grep <name>
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
   kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.spec.sources}' 2>/dev/null | grep -q '\[' && echo "multi-source" || echo "single-source"

   # Single-source
   kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.spec.source}' | python3 -m json.tool

   # Multi-source — iterate all sources
   kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{range .spec.sources[*]}repoURL={.repoURL} targetRevision={.targetRevision} path={.path} chart={.chart}{"\n"}{end}'
   ```
   For multi-source Applications, each source can fail independently — verify `repoURL`, `targetRevision`, `path`, and Helm `valueFiles` for every entry in `spec.sources[]`.

8. If repo-server is failing to render manifests, check repo-server logs:
   ```bash
   kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-repo-server --tail=100
   ```

9. Inspect managed resources. List resources from `.status.resources` with non-Healthy or non-Synced status:
   ```bash
   kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name}: sync={.status}, health={.health.status}{"\n"}{end}'
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

## Workflow 3: ApplicationSet Debugging

Use when: user reports ApplicationSet not generating Applications, generating wrong Applications, or ApplicationSet errors.

**Steps:**

1. Get the ApplicationSet:
   ```bash
   kubectl get applicationset <name> -n "$NS" -o yaml
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
   kubectl get applications.argoproj.io -n "$NS" -l 'app.kubernetes.io/managed-by=applicationset-controller' --show-labels
   ```
   Cross-reference with expected output from the generator.

5. If no Applications generated, check the applicationset-controller logs:
   ```bash
   kubectl logs -n "$NS" -l app.kubernetes.io/name=$CR-applicationset-controller --tail=200
   ```

6. If some Applications are generated but failing, debug each one using Workflow 2.

7. For progressive sync issues, check `spec.strategy`:
   ```bash
   kubectl get applicationset <name> -n "$NS" -o jsonpath='{.spec.strategy}' | { read -r s || true; [ -n "$s" ] \
     && printf '%s' "$s" | python3 -m json.tool \
     || echo 'no spec.strategy set — this ApplicationSet syncs AllAtOnce'; }
   ```
   Check `rollingSync.steps`, `maxUpdate` values, and whether unhealthy apps are blocking progression.

   **First, check that progressive syncs are switched on at all — on OpenShift GitOps
   they are not by default.** `RollingSync` is a no-op unless the applicationset
   controller runs with `--enable-progressive-syncs`. Without it the strategy block is
   accepted, stored, and **completely ignored**: every Application syncs AllAtOnce while
   the ApplicationSet still shows `ResourcesUpToDate=True` and reports no error anywhere.

   ```bash
   # The flag (operator installs do NOT set it by default). Note the label is NOT
   # prefixed with the CR name, and `range` is used so an empty result prints nothing
   # instead of crashing with "array index out of bounds" the way .items[0] does.
   $KCTL get deploy -n "$NS" -l app.kubernetes.io/name=argocd-applicationset-controller \
     -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.template.spec.containers[0].command}{"\n"}{end}'

   # The tell: RollingSync populates .status.applicationStatus. An empty value or `[]`
   # alongside a declared rollingSync strategy means the strategy is not running.
   $KCTL get applicationset <name> -n "$NS" -o jsonpath='{.status.applicationStatus}{"\n"}'
   ```

   Verified on OpenShift GitOps 1.21.3: an ApplicationSet declaring two `rollingSync`
   steps had an empty `.status.applicationStatus`, and both generated Applications
   reached `Synced` at the **same revision** — the production app was never gated behind
   a staging app that never became Healthy.

   To enable it, set `spec.applicationSet.extraCommandArgs: ["--enable-progressive-syncs"]`
   on the **`ArgoCD` CR**, not on the Deployment — the operator reverts direct Deployment
   edits. Expect the controller to restart.

   Only once the flag is on do the usual causes apply: a step whose `matchExpressions`
   match no Application (that step completes vacuously), `maxUpdate` saturated by apps
   that never converge, or an earlier step whose apps never reach Healthy.

---

## Workflow 4: Rollout Debugging

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

   **Resolve the numbering before you answer.** `.status.currentStepIndex` is a
   **0-based index into `spec.strategy.canary.steps`**, while users almost always count
   steps from 1 — so "stuck at step 2" usually means `currentStepIndex: 1`, and an index
   of 2 is the user's "step 3". The two readings point at different steps and therefore
   different root causes. State the mapping explicitly, e.g.:

   > `currentStepIndex: 1` → `steps[1]` = `pause: {duration: 30s}` — your "step 2".

   If the user's wording is ambiguous, print the whole list with both numberings and say
   which one you diagnosed. An index equal to `len(steps)` means every step completed.

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

8b. **Blue-green: there are no steps, so "stuck" means something different.** A
    blue-green Rollout has no `steps` array and no `currentStepIndex`, and it never
    progresses on its own the way canary does between `setWeight`/`pause` entries. It
    moves preview → active on exactly one trigger:

    | | canary | blue-green |
    |---|---|---|
    | progression | automatic through `steps[]`, pausing only where told | single promotion event, no intermediate steps |
    | what "stuck" means | sitting at one `steps[]` entry | preview is up and promotion never fired |
    | usual cause | a `pause` with no duration, or a failing `analysis` step | `autoPromotionEnabled: false` was set explicitly and nobody promoted, a failing/running `prePromotionAnalysis`, or the new ReplicaSet never became Healthy |

    So do not look for a step index on a blue-green Rollout — check, in order:
    ```bash
    kubectl get rollout <name> -n <namespace> \
      -o jsonpath='{.spec.strategy.blueGreen.autoPromotionEnabled}{"\n"}{.status.pauseConditions}{"\n"}'
    ```
    **`autoPromotionEnabled` defaults to `true`** — an unset field means the rollout
    *should* self-promote as soon as the new ReplicaSet is Healthy. So an unset field is
    a red flag pointing at the ReplicaSet or at analysis, whereas an explicit
    `autoPromotionEnabled: false` is **intended behaviour**: the rollout is waiting for
    `kubectl argo rollouts promote <name>`, and you should report it as such rather than
    as a fault. (`autoPromotionSeconds` only applies in that paused state — it promotes
    automatically once that many seconds have elapsed; it defaults to nil, meaning never.)

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

## Workflow 5: Log Analysis

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
