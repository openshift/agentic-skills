# Progressive Delivery Reference — Promotion, Rollback, and Traffic Management

Step-by-step procedures for promoting, aborting, and managing Rollouts and Application
syncs. Every procedure follows the Generate-Preview-Confirm safety model.

---

## Installing Argo Rollouts

### Controller + CRDs

```bash
# 1. Create namespace
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -

# 2. Install (latest stable)
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

# 3. Verify
kubectl get pods -n argo-rollouts
kubectl get crd rollouts.argoproj.io
```

### Helm Install

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argo-rollouts argo/argo-rollouts \
  --namespace argo-rollouts \
  --create-namespace \
  --set dashboard.enabled=true

# Dashboard access
kubectl argo rollouts dashboard -n argo-rollouts &
```

### OpenShift Install

```bash
# Same as above, but ensure SCC bindings for the controller
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

# The controller runs with restricted-v2 SCC by default.
# If it needs elevated permissions (rare), create a binding:
# oc adm policy add-scc-to-user nonroot-v2 -z argo-rollouts -n argo-rollouts
```

---

## Converting Deployment to Rollout

### Procedure

1. Save the existing Deployment:
   ```bash
   kubectl get deployment <name> -n <namespace> -o yaml > deployment-backup.yaml
   ```

2. Modify the manifest:
   - Change `apiVersion: apps/v1` to `apiVersion: argoproj.io/v1alpha1`
   - Change `kind: Deployment` to `kind: Rollout`
   - Add `spec.strategy.canary` or `spec.strategy.blueGreen`
   - Remove `spec.strategy.rollingUpdate` and `spec.strategy.type`

3. Create the required Services:
   ```yaml
   # Stable service (points to current production pods)
   apiVersion: v1
   kind: Service
   metadata:
     name: my-app-stable
   spec:
     selector:
       app: my-app
     ports:
       - port: 80
         targetPort: 8080
   ---
   # Canary service (points to canary pods)
   apiVersion: v1
   kind: Service
   metadata:
     name: my-app-canary
   spec:
     selector:
       app: my-app
     ports:
       - port: 80
         targetPort: 8080
   ```

4. Preview and apply:
   ```bash
   kubectl apply --dry-run=server -f rollout.yaml
   # After confirmation:
   kubectl apply -f rollout.yaml
   ```

### Alternative: workloadRef (Reference Existing Deployment)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
spec:
  replicas: 5
  selector:
    matchLabels:
      app: my-app
  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
    scaleDown: onsuccess
  strategy:
    canary:
      steps:
        - setWeight: 20
        - pause: {}
```

---

## Syncing Applications

### Manual Sync

```bash
# 1. Check current state
argocd app get <name> 2>/dev/null || \
  kubectl get application <name> -n argocd -o jsonpath='sync={.status.sync.status} health={.status.health.status}'

# 2. Preview diff
argocd app diff <name> 2>/dev/null || \
  echo "argocd CLI not available — check .status.resources for OutOfSync items"

# 3. Sync (after user confirms)
argocd app sync <name> 2>/dev/null || \
  kubectl patch application <name> -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"cli"},"sync":{"revision":"","prune":false}}}'

# 4. Wait for sync to complete
argocd app wait <name> --timeout 300 2>/dev/null || \
  echo "Monitor: kubectl get application <name> -n argocd -o jsonpath='{.status.operationState.phase}'"
```

### Sync with Options

```bash
# Sync specific resources only
argocd app sync <name> --resource 'apps/Deployment/<name>'

# Sync with prune
argocd app sync <name> --prune

# Sync with force (replaces resources — destructive)
# ONLY when user explicitly requests force sync
argocd app sync <name> --force

# Sync to a specific revision
argocd app sync <name> --revision <commit-sha-or-tag>

# Sync with retry
argocd app sync <name> --retry-limit 3 --retry-backoff-duration 5s
```

---

## Canary Rollout Operations

### Check Current Status

```bash
# Preferred (rich output)
kubectl argo rollouts get rollout <name> -n <namespace>

# Fallback
kubectl get rollout <name> -n <namespace> -o jsonpath='{
  "phase": "{.status.phase}",
  "currentStep": {.status.currentStepIndex},
  "stableRS": "{.status.stableRS}",
  "canaryRS": "{.status.currentPodHash}"
}'
```

### Promote (Advance to Next Step)

```bash
# 1. Check what promote will do
kubectl argo rollouts status <name> -n <namespace>

# Show current step
kubectl argo rollouts get rollout <name> -n <namespace> | head -20

# 2. Promote (after user confirms)
kubectl argo rollouts promote <name> -n <namespace>

# 3. Monitor
kubectl argo rollouts get rollout <name> -n <namespace> --watch
```

### Full Promote (Skip All Remaining Steps)

```bash
# WARNING: This skips all remaining canary steps and immediately promotes to 100%
# Only use when user explicitly requests full promotion

# 1. Show remaining steps
kubectl get rollout <name> -n <namespace> -o jsonpath='{.spec.strategy.canary.steps}'
echo "Current step: $(kubectl get rollout <name> -n <namespace> -o jsonpath='{.status.currentStepIndex}')"

# 2. Full promote (after user confirms with resource name)
kubectl argo rollouts promote <name> -n <namespace> --full
```

### Set Weight (Manual Traffic Shift)

```bash
# 1. Show current weight
kubectl argo rollouts get rollout <name> -n <namespace> | grep -i weight

# 2. Set weight (after user confirms)
kubectl argo rollouts set-weight <name> -n <namespace> <percentage>

# Example: shift 50% traffic to canary
kubectl argo rollouts set-weight my-app -n production 50
```

### Pause / Resume

```bash
# Pause at current step
kubectl argo rollouts pause <name> -n <namespace>

# Resume from pause
kubectl argo rollouts promote <name> -n <namespace>
```

---

## Blue-Green Rollout Operations

### Check Current Status

```bash
kubectl argo rollouts get rollout <name> -n <namespace>

# Show which ReplicaSet is active vs preview
kubectl get rollout <name> -n <namespace> -o jsonpath='{
  "activeRS": "{.status.blueGreen.activeSelector}",
  "previewRS": "{.status.blueGreen.previewSelector}"
}'
```

### Promote Preview to Active

```bash
# 1. Verify preview is healthy
kubectl get pods -n <namespace> -l rollouts-pod-template-hash=$(kubectl get rollout <name> -n <namespace> -o jsonpath='{.status.currentPodHash}')

# 2. Show what promote will do
echo "This will switch active traffic from the current stable ReplicaSet to the preview ReplicaSet."

# 3. Promote (after user confirms)
kubectl argo rollouts promote <name> -n <namespace>

# 4. Monitor
kubectl argo rollouts get rollout <name> -n <namespace> --watch
```

---

## Abort Rollout

Aborting stops the rollout and scales down the canary/preview ReplicaSet. Traffic
returns to the stable ReplicaSet.

```bash
# 1. Show current state
kubectl argo rollouts get rollout <name> -n <namespace>

# 2. Abort (after user confirms — destructive, requires resource name confirmation)
kubectl argo rollouts abort <name> -n <namespace>

# 3. Verify stable is serving
kubectl argo rollouts get rollout <name> -n <namespace>
```

**After abort:** The Rollout enters `Aborted` phase. To re-deploy, update the Rollout
spec (e.g., image tag) and it will start a new rollout. Or use `retry`:

```bash
kubectl argo rollouts retry rollout <name> -n <namespace>
```

---

## Retry Rollout

Retries a failed or aborted rollout with the same spec:

```bash
# 1. Check current state (should be Degraded or Aborted)
kubectl argo rollouts get rollout <name> -n <namespace>

# 2. Retry (after user confirms)
kubectl argo rollouts retry rollout <name> -n <namespace>

# 3. Monitor
kubectl argo rollouts get rollout <name> -n <namespace> --watch
```

---

## Manual AnalysisRun

Run an AnalysisTemplate manually (outside of a Rollout) for pre-flight checks:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisRun
metadata:
  name: preflight-check
  namespace: production
spec:
  metrics:
    - name: smoke-test
      count: 1
      provider:
        job:
          spec:
            template:
              spec:
                containers:
                  - name: test
                    image: registry.example.com/smoke-tests:latest
                    command: ["./run-tests.sh"]
                    args: ["--url", "http://my-app-preview.production.svc"]
                restartPolicy: Never
            backoffLimit: 0
```

```bash
# Preview
kubectl apply --dry-run=server -f analysisrun.yaml

# Apply (after user confirms)
kubectl apply -f analysisrun.yaml

# Monitor
kubectl get analysisrun preflight-check -n production -w
```

---

## Rollback

### Application Rollback (Argo CD)

```bash
# 1. List revision history
argocd app history <name>

# 2. Show what the target revision contained
argocd app manifests <name> --revision <revision-number>

# 3. Rollback (after user confirms — destructive, requires resource name confirmation)
argocd app rollback <name> <revision-number>

# 4. Verify
argocd app get <name>
```

**Note:** Rollback sets the Application to the target revision but auto-sync (if
enabled) will immediately re-sync to HEAD. Disable auto-sync first if you need the
rollback to persist:

```bash
argocd app set <name> --sync-policy none
argocd app rollback <name> <revision-number>
```

### Rollout Undo

```bash
# 1. Show revision history
kubectl argo rollouts get rollout <name> -n <namespace>

# 2. Undo to previous revision (after user confirms)
kubectl argo rollouts undo <name> -n <namespace>

# 3. Undo to specific revision
kubectl argo rollouts undo <name> -n <namespace> --to-revision=2

# 4. Monitor
kubectl argo rollouts get rollout <name> -n <namespace> --watch
```

---

## Traffic Management Setup

### Istio

```yaml
strategy:
  canary:
    canaryService: my-app-canary
    stableService: my-app-stable
    trafficRouting:
      istio:
        virtualServices:
          - name: my-app-vsvc
            routes:
              - primary
        destinationRule:
          name: my-app-destrule
          canarySubsetName: canary
          stableSubsetName: stable
```

### NGINX Ingress

```yaml
strategy:
  canary:
    canaryService: my-app-canary
    stableService: my-app-stable
    trafficRouting:
      nginx:
        stableIngress: my-app-ingress
        annotationPrefix: nginx.ingress.kubernetes.io
        additionalIngressAnnotations:
          canary-by-header: X-Canary
```

### AWS ALB

```yaml
strategy:
  canary:
    canaryService: my-app-canary
    stableService: my-app-stable
    trafficRouting:
      alb:
        ingress: my-app-ingress
        servicePort: 80
        rootService: my-app-root
        annotationPrefix: alb.ingress.kubernetes.io
```

### No Traffic Management (Replica-Based)

Without traffic routing configuration, canary weight is approximated by replica ratio.
For example, with 10 replicas and `setWeight: 20`, 2 pods run the canary image and 8
run stable. Traffic distribution depends on the load balancer (not precise percentage).
