# Day-2 Operations Reference — Upgrades, Scaling, Backup, and Maintenance

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

Step-by-step procedures for day-2 operational tasks. Every procedure follows the
Generate-Preview-Confirm safety model.

---

## Upgrading Argo CD

### Pre-Upgrade Checklist

Before any upgrade:

1. **Check current version:**
   ```bash
   argocd version 2>/dev/null || \
     kubectl get pods -n "$NS" -o jsonpath='{.items[0].spec.containers[0].image}' | cut -d: -f2
   ```

2. **Read the release notes** for the target version. Check for:
   - Breaking changes
   - Deprecated features
   - CRD schema changes
   - Required migrations

3. **Backup all resources** (see Backup section below).

4. **Check CRD compatibility:**
   ```bash
   kubectl get crd applications.argoproj.io -o jsonpath='{.spec.versions[*].name}'
   ```

### Helm Upgrade

```bash
# 1. Update repo
helm repo update argo

# 2. Check available versions
helm search repo argo/argo-cd --versions | head -10

# 3. Preview changes
helm diff upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version <new-version> \
  -f values.yaml 2>/dev/null || \
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version <new-version> \
  -f values.yaml \
  --dry-run

# 4. Upgrade CRDs first (Helm does not upgrade CRDs automatically)
kubectl apply --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v<new-version>/manifests/crds/application-crd.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v<new-version>/manifests/crds/appproject-crd.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v<new-version>/manifests/crds/applicationset-crd.yaml

# 5. Upgrade (after user confirms)
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version <new-version> \
  -f values.yaml \
  --wait --timeout 5m

# 6. Verify
kubectl rollout status deployment/argocd-server -n "$NS"
argocd version 2>/dev/null
```

### OpenShift GitOps Operator Upgrade

The operator upgrades are managed by OLM. For automatic upgrades:

```bash
# Check current CSV
kubectl get csv -n openshift-gitops-operator | grep gitops

# Check install plan approval
kubectl get subscriptions.operators.coreos.com openshift-gitops-operator -n openshift-gitops-operator -o jsonpath='{.spec.installPlanApproval}'
```

For manual approval:

```bash
# 1. List pending install plans
kubectl get installplan -n openshift-gitops-operator | grep openshift-gitops

# 2. Review the install plan
kubectl get installplan <plan-name> -n openshift-gitops-operator -o yaml

# 3. Approve (after user confirms)
kubectl patch installplan <plan-name> -n openshift-gitops-operator --type merge -p '{"spec":{"approved":true}}'

# 4. Verify
kubectl get csv -n openshift-gitops-operator | grep gitops
kubectl get pods -n openshift-gitops
```

### In-Place Image Bump (Emergency)

For quick version bumps without Helm/operator (emergency patches only):

```bash
# 1. Show current images
kubectl get deployment -n "$NS" -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.template.spec.containers[0].image}{"\n"}{end}'

# 2. Preview
echo "Will update all Argo CD components to v<new-version>"

# 3. Update images (after user confirms)
ARGOCD_VERSION=v2.14.2
for deploy in argocd-server argocd-repo-server argocd-applicationset-controller argocd-notifications-controller; do
  kubectl set image deployment/$deploy \
    -n "$NS" \
    ${deploy##argocd-}=quay.io/argoproj/argocd:$ARGOCD_VERSION 2>/dev/null
done

# StatefulSet (controller in some installs)
kubectl set image statefulset/argocd-application-controller \
  -n "$NS" \
  argocd-application-controller=quay.io/argoproj/argocd:$ARGOCD_VERSION 2>/dev/null || \
kubectl set image deployment/argocd-application-controller \
  -n "$NS" \
  argocd-application-controller=quay.io/argoproj/argocd:$ARGOCD_VERSION 2>/dev/null

# 4. Verify
kubectl rollout status deployment/argocd-server -n "$NS"
```

---

## API Migration

### Deprecated API Check

```bash
# Check for deprecated APIs in managed Applications
argocd admin settings resource-overrides list   # NOTE: there is no 'list-deprecated' subcommand (checked on argocd v3.5.5) 2>/dev/null || \
  echo "argocd admin not available — check manually"

# Scan for deprecated apiVersions in Git repos
grep -rn 'apiVersion: extensions/v1beta1\|apiVersion: networking.k8s.io/v1beta1\|apiVersion: policy/v1beta1' .
```

### Common Migrations

| From | To | Resources |
|------|----|-----------|
| `extensions/v1beta1` | `networking.k8s.io/v1` | Ingress |
| `policy/v1beta1` | `policy/v1` | PodDisruptionBudget |
| `rbac.authorization.k8s.io/v1beta1` | `rbac.authorization.k8s.io/v1` | Role, ClusterRole, Bindings |
| `argoproj.io/v1alpha1` ArgoCD | `argoproj.io/v1beta1` ArgoCD | ArgoCD CR (operator) |

### ArgoCD CR Migration (v1alpha1 to v1beta1)

Key field changes in the OpenShift GitOps operator:

```yaml
# v1alpha1 (old)
spec:
  dex:
    openShiftOAuth: true

# v1beta1 (current)
spec:
  sso:
    provider: dex
    dex:
      openShiftOAuth: true
```

```bash
# 1. Export current CR
kubectl get argocd -n openshift-gitops -o yaml > argocd-backup.yaml

# 2. Update apiVersion and fields
# (manual edit or use sed/yq)

# 3. Preview
kubectl diff -f argocd-v1beta1.yaml

# 4. Apply (after user confirms)
kubectl apply -f argocd-v1beta1.yaml
```

---

## Scaling Components

### Application Controller

The controller uses sharding to distribute Application reconciliation. For large
installations (500+ Applications):

```bash
# Check current replicas
kubectl get deployment argocd-application-controller -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null || \
  kubectl get statefulset argocd-application-controller -n "$NS" -o jsonpath='{.spec.replicas}'

# Scale (after user confirms)
kubectl scale statefulset/argocd-application-controller --replicas=2 -n "$NS" 2>/dev/null || \
  kubectl scale deployment/argocd-application-controller --replicas=2 -n "$NS"

# Set the environment variable for shard count
kubectl set env statefulset/argocd-application-controller ARGOCD_CONTROLLER_REPLICAS=2 -n "$NS" 2>/dev/null || \
  kubectl set env deployment/argocd-application-controller ARGOCD_CONTROLLER_REPLICAS=2 -n "$NS"
```

### Repo Server

```bash
# Scale repo-server for parallel manifest generation
kubectl scale deployment/argocd-repo-server --replicas=3 -n "$NS"

# Increase resource limits for large repos
kubectl set resources deployment/argocd-repo-server -n "$NS" \
  --limits=cpu=2,memory=2Gi \
  --requests=cpu=500m,memory=512Mi
```

### Helm Values (Preferred)

```yaml
# values.yaml updates for scaling
controller:
  replicas: 2
  env:
    - name: ARGOCD_CONTROLLER_REPLICAS
      value: "2"
  resources:
    requests:
      cpu: "1"
      memory: 2Gi
    limits:
      cpu: "2"
      memory: 4Gi
repoServer:
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: "2"
      memory: 2Gi
server:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 80
```

---

## HA Setup

### Redis Sentinel

```yaml
# Helm values for Redis HA
redis-ha:
  enabled: true
  haproxy:
    enabled: true
    replicas: 3
  redis:
    replicas: 3
  sentinel:
    replicas: 3
  persistentVolume:
    enabled: true
    size: 10Gi
```

### Controller Sharding

With multiple controller replicas, each replica manages a subset of Applications.
Sharding is automatic when `ARGOCD_CONTROLLER_REPLICAS` matches the replica count.

```bash
# Verify sharding
kubectl get pods -n "$NS" -l app.kubernetes.io/name=$CR-application-controller
for pod in $(kubectl get pods -n "$NS" -l app.kubernetes.io/name=$CR-application-controller -o name); do
  echo "=== $pod ==="
  kubectl logs $pod -n "$NS" --tail=5 | grep "shard"
done
```

---

## Backup and Restore

### Export All Applications

```bash
# Export all Applications
kubectl get applications.argoproj.io -n "$NS" -o yaml > applications-backup.yaml

# Export individual Applications
for app in $(kubectl get applications.argoproj.io -n "$NS" -o name); do
  name=$(basename $app)
  kubectl get applications.argoproj.io $name -n "$NS" -o yaml > "backup/application-${name}.yaml"
done

# Count exported
echo "Exported: $(ls backup/application-*.yaml 2>/dev/null | wc -l) Applications"
```

### Export All AppProjects

```bash
# Export all AppProjects
kubectl get appprojects -n "$NS" -o yaml > appprojects-backup.yaml

# Export individual AppProjects
for proj in $(kubectl get appprojects -n "$NS" -o name); do
  name=$(basename $proj)
  kubectl get appproject $name -n "$NS" -o yaml > "backup/appproject-${name}.yaml"
done

echo "Exported: $(ls backup/appproject-*.yaml 2>/dev/null | wc -l) AppProjects"
```

### Export Secrets (Cluster and Repo Credentials)

```bash
# Export repo credentials (encrypted — contains tokens)
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=repository -o yaml > backup/repo-secrets.yaml

# Export cluster credentials (encrypted — contains tokens)
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster -o yaml > backup/cluster-secrets.yaml

# WARNING: These contain sensitive data. Encrypt or restrict access to the backup files.
echo "WARNING: Backup files contain sensitive credentials. Secure appropriately."
```

### Export ConfigMaps

```bash
kubectl get configmap argocd-cm argocd-rbac-cm argocd-cmd-params-cm argocd-notifications-cm -n "$NS" -o yaml > backup/configmaps.yaml 2>/dev/null
```

### Full Backup Script

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="argocd-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up Argo CD resources to $BACKUP_DIR..."

# NS must be the real Argo CD namespace — 'argocd' does not exist on operator installs.
# On OpenShift GitOps it is openshift-gitops, and there may be several instances.
NS="${NS:-openshift-gitops}"   # 'argocd' is the upstream default and usually wrong on OpenShift
# There is often MORE THAN ONE instance. Back up each:
#   for NS in $(kubectl get argocd -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\n"}{end}'); do ... done

# `kubectl get ... -o yaml` exits 0 and writes an empty "items: []" list when nothing
# matched, so `cmd && echo "[OK]"` reports success for an EMPTY backup. Count instead.
backup() {            # backup <kind> <outfile> <label>
  local kind="$1" out="$2" label="$3" n
  n=$(kubectl get "$kind" -n "$NS" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -gt 0 ]; then
    kubectl get "$kind" -n "$NS" -o yaml > "$out" && echo "[OK] $label ($n)"
  else
    echo "[SKIP] No $label found in namespace $NS"
  fi
}

backup applications.argoproj.io "$BACKUP_DIR/applications.yaml"    "Applications"
backup applicationsets          "$BACKUP_DIR/applicationsets.yaml" "ApplicationSets"
backup appprojects              "$BACKUP_DIR/appprojects.yaml"     "AppProjects"

# On operator-managed clusters the ArgoCD CR is the most important object to back up
# and is easy to forget — it holds all instance configuration.
backup argocd                   "$BACKUP_DIR/argocd-cr.yaml"       "ArgoCD CR"

# ConfigMaps
for cm in argocd-cm argocd-rbac-cm argocd-cmd-params-cm argocd-notifications-cm argocd-tls-certs-cm argocd-ssh-known-hosts-cm; do
  kubectl get configmap "$cm" -n "$NS" -o yaml > "$BACKUP_DIR/${cm}.yaml" 2>/dev/null && \
    echo "[OK] $cm" || echo "[SKIP] $cm not found"
done

# Secrets (sensitive)
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=repository -o yaml > "$BACKUP_DIR/repo-secrets.yaml" 2>/dev/null && \
  echo "[OK] Repository secrets" || echo "[SKIP] No repo secrets"
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster -o yaml > "$BACKUP_DIR/cluster-secrets.yaml" 2>/dev/null && \
  echo "[OK] Cluster secrets" || echo "[SKIP] No cluster secrets"

echo ""
echo "Backup complete: $BACKUP_DIR"
echo "Files: $(ls "$BACKUP_DIR" | wc -l)"
echo "WARNING: Secret files contain sensitive credentials. Encrypt before storing."
```

### Restore

```bash
# 1. Ensure Argo CD is installed on the target cluster

# 2. Apply ConfigMaps first
kubectl apply -f backup/configmaps.yaml

# 3. Apply AppProjects
kubectl apply -f backup/appprojects.yaml

# 4. Apply Secrets (repo + cluster credentials)
kubectl apply -f backup/repo-secrets.yaml
kubectl apply -f backup/cluster-secrets.yaml

# 5. Apply Applications last
kubectl apply -f backup/applications.yaml

# 6. Verify
argocd app list 2>/dev/null || kubectl get applications.argoproj.io -n "$NS"
```

---

## Credential Rotation

> **These recipes end in `| kubectl apply -f -`, which skips Generate → Preview →
> Confirm and violates Safety Rules 1 and 8.** Split them: render to a file, show it to
> the user (redacting the credential), get explicit confirmation, then apply. Credentials
> are the single worst thing to apply unreviewed — a typo'd rotation locks Argo CD out of
> every repo at once.
>
> ```bash
> kubectl create secret ... --dry-run=client -o yaml > /tmp/cred.yaml   # 1. generate
> kubectl diff -f /tmp/cred.yaml                                        # 2. preview
> #    -> ask "Apply this? (yes/no)"                                    # 3. confirm
> kubectl apply -f /tmp/cred.yaml && shred -u /tmp/cred.yaml            # 4. apply + shred
> ```

### Git SSH Keys

```bash
# 1. Generate new key
ssh-keygen -t ed25519 -f argocd-repo-key -N "" -C "argocd@cluster"

# 2. Update the repo secret
kubectl create secret generic repo-<name> \
  --namespace argocd \
  --from-file=sshPrivateKey=argocd-repo-key \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Add the public key to the Git provider
cat argocd-repo-key.pub

# 4. VERIFY — a credential that applies cleanly and cannot authenticate is the whole
#    failure mode. Confirm Argo CD can actually reach the repo with the new credential.
argocd repo get <repo-url> 2>/dev/null || \
  kubectl get secret repo-<name> -n "$NS" -o jsonpath='{.metadata.labels}{"\n"}'
# Force a fresh fetch rather than trusting the repo-server cache:
argocd app get <app-using-that-repo> --refresh 2>/dev/null || \
  kubectl annotate applications.argoproj.io <app> -n "$NS" \
    argocd.argoproj.io/refresh=hard --overwrite
# Then confirm the Application is not in ComparisonError:
kubectl get applications.argoproj.io <app> -n "$NS" \
  -o jsonpath='sync={.status.sync.status} cond={.status.conditions[*].type}{"\n"}'

# 4. Test connectivity
argocd repo get <repo-url> 2>/dev/null || \
  kubectl get secret repo-<name> -n "$NS" -o jsonpath='{.data.sshPrivateKey}' | base64 -d | head -1
```

### Verifying an upgrade

> **Always qualify `subscriptions.operators.coreos.com`.** On a cluster with Red Hat ACM,
> `subscriptions.apps.open-cluster-management.io` shadows the OLM kind, and a bare
> `kubectl get subscription` returns `No resources found` while the OLM Subscription
> exists — the same failure class as bare `applications`. Verified on a live cluster.

**An upgrade is not done when the command returns.** Check all four, and report the output:

```bash
# 1. The CSV must be Succeeded. Do NOT trust the Subscription's `state` — it reports
#    AtLatestKnown while the CSV behind it is stuck Pending or Failed.
kubectl get csv -n <operator-ns> -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
kubectl get subscriptions.operators.coreos.com -n <operator-ns> -o jsonpath='{.items[*].status.installedCSV}{"\n"}'

# 2. No failed InstallPlan left behind
kubectl get installplan -n <operator-ns> -o custom-columns=NAME:.metadata.name,PHASE:.status.phase

# 3. Components actually rolled to the new version
kubectl get pods -n "$NS" -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount
kubectl get deploy,sts -n "$NS" -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'

# 4. The instance reconciled cleanly afterwards
kubectl get argocd -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,PHASE:.status.phase
```

If the CSV sits in `Pending` or `Replacing` for more than a few minutes, the upgrade is
**stuck, not slow** — read `.status.conditions` on the CSV and the InstallPlan before
retrying anything.

### Git PAT (Personal Access Token)

```bash
# 1. Create/update repo credential secret
kubectl create secret generic repo-creds-<name> \
  --namespace argocd \
  --from-literal=url=https://github.com/org \
  --from-literal=username=argocd \
  --from-literal=password=<new-pat> \
  --from-literal=type=git \
  --dry-run=client -o yaml | \
  kubectl label --local -f - argocd.argoproj.io/secret-type=repo-creds -o yaml | \
  kubectl apply -f -

# 2. Verify
argocd repo list 2>/dev/null || kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=repo-creds
```

### GitHub App Credentials

```bash
kubectl create secret generic repo-creds-github-app \
  --namespace argocd \
  --from-literal=url=https://github.com/org \
  --from-literal=githubAppID=<app-id> \
  --from-literal=githubAppInstallationID=<installation-id> \
  --from-file=githubAppPrivateKey=private-key.pem \
  --dry-run=client -o yaml | \
  kubectl label --local -f - argocd.argoproj.io/secret-type=repo-creds -o yaml | \
  kubectl apply -f -
```

### Cluster Token Rotation

```bash
# 1. Identify the cluster secret
kubectl get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster

# 2. Get the target cluster's ServiceAccount token
# (requires access to the target cluster)
kubectl --context <target-context> create token argocd-manager -n kube-system --duration=8760h

# 3. Update the cluster secret with the new token
kubectl patch secret <cluster-secret-name> -n "$NS" --type json -p "[
  {\"op\": \"replace\", \"path\": \"/data/config\", \"value\": \"$(echo -n '{\"bearerToken\":\"<new-token>\",\"tlsClientConfig\":{\"insecure\":false}}' | base64)\"}
]"

# 4. Verify
argocd cluster list 2>/dev/null
```

---

## Disaster Recovery

### Re-bootstrap from Git

If Argo CD is destroyed but the GitOps repo is intact:

1. **Reinstall Argo CD** (Helm or operator).
2. **Restore ConfigMaps and Secrets** from backup or Git.
3. **Apply the root Application or ApplicationSet** that generates all other Applications.
4. Argo CD will reconcile all Applications from the Git source.

```bash
# 1. Install Argo CD
helm install argocd argo/argo-cd --namespace argocd --create-namespace --wait

# 2. Restore config
kubectl apply -f backup/configmaps.yaml
kubectl apply -f backup/repo-secrets.yaml
kubectl apply -f backup/cluster-secrets.yaml

# 3. Apply root Application (app-of-apps or root ApplicationSet)
kubectl apply -f root-application.yaml

# 4. Wait for reconciliation
argocd app list --watch 2>/dev/null || \
  watch kubectl get applications.argoproj.io -n "$NS"
```

### Autopilot Recovery

If using Autopilot, the entire state is in Git:

```bash
argocd-autopilot repo bootstrap \
  --repo <repo-url> \
  --git-token <token> \
  --recover
```

---

## Feature Toggles

### Enable/Disable Notifications

```bash
# Helm
helm upgrade argocd argo/argo-cd --set notifications.enabled=true -n "$NS" --reuse-values

# Operator
kubectl patch argocd openshift-gitops -n openshift-gitops --type merge -p '{"spec":{"notifications":{"enabled":true}}}'
```

### Enable/Disable Image Updater

```bash
# Install image updater
kubectl apply -n "$NS" -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/manifests/install.yaml

# Verify
kubectl get pods -n "$NS" -l app.kubernetes.io/name=$CR-image-updater
```

### Enable Applications in Any Namespace

```bash
# Helm
helm upgrade argocd argo/argo-cd \
  --set configs.params.application.namespaces="team-*" \
  -n "$NS" --reuse-values

# ConfigMap (direct)
kubectl patch configmap argocd-cmd-params-cm -n "$NS" --type merge -p '{"data":{"application.namespaces":"team-*"}}'

# Restart server to pick up changes
kubectl rollout restart deployment/argocd-server -n "$NS"
```

### Enable Server-Side Apply

```yaml
# Per-Application (syncOptions)
syncOptions:
  - ServerSideApply=true

# Global default (argocd-cm)
data:
  server.side.apply: "true"
```
