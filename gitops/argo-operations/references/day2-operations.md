# Day-2 Operations Reference — Upgrades, Scaling, Backup, and Maintenance

Step-by-step procedures for day-2 operational tasks. Every procedure follows the
Generate-Preview-Confirm safety model.

---

## Upgrading Argo CD

### Pre-Upgrade Checklist

Before any upgrade:

1. **Check current version:**
   ```bash
   argocd version 2>/dev/null || \
     kubectl get pods -n argocd -o jsonpath='{.items[0].spec.containers[0].image}' | cut -d: -f2
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
kubectl rollout status deployment/argocd-server -n argocd
argocd version 2>/dev/null
```

### OpenShift GitOps Operator Upgrade

The operator upgrades are managed by OLM. For automatic upgrades:

```bash
# Check current CSV
kubectl get csv -n openshift-operators | grep gitops

# Check install plan approval
kubectl get subscription openshift-gitops-operator -n openshift-operators -o jsonpath='{.spec.installPlanApproval}'
```

For manual approval:

```bash
# 1. List pending install plans
kubectl get installplan -n openshift-operators | grep openshift-gitops

# 2. Review the install plan
kubectl get installplan <plan-name> -n openshift-operators -o yaml

# 3. Approve (after user confirms)
kubectl patch installplan <plan-name> -n openshift-operators --type merge -p '{"spec":{"approved":true}}'

# 4. Verify
kubectl get csv -n openshift-operators | grep gitops
kubectl get pods -n openshift-gitops
```

### In-Place Image Bump (Emergency)

For quick version bumps without Helm/operator (emergency patches only):

```bash
# 1. Show current images
kubectl get deployment -n argocd -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.template.spec.containers[0].image}{"\n"}{end}'

# 2. Preview
echo "Will update all Argo CD components to v<new-version>"

# 3. Update images (after user confirms)
ARGOCD_VERSION=v2.14.2
for deploy in argocd-server argocd-repo-server argocd-applicationset-controller argocd-notifications-controller; do
  kubectl set image deployment/$deploy \
    -n argocd \
    ${deploy##argocd-}=quay.io/argoproj/argocd:$ARGOCD_VERSION 2>/dev/null
done

# StatefulSet (controller in some installs)
kubectl set image statefulset/argocd-application-controller \
  -n argocd \
  argocd-application-controller=quay.io/argoproj/argocd:$ARGOCD_VERSION 2>/dev/null || \
kubectl set image deployment/argocd-application-controller \
  -n argocd \
  argocd-application-controller=quay.io/argoproj/argocd:$ARGOCD_VERSION 2>/dev/null

# 4. Verify
kubectl rollout status deployment/argocd-server -n argocd
```

---

## API Migration

### Deprecated API Check

```bash
# Check for deprecated APIs in managed Applications
argocd admin settings resource-overrides list-deprecated 2>/dev/null || \
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
kubectl get deployment argocd-application-controller -n argocd -o jsonpath='{.spec.replicas}' 2>/dev/null || \
  kubectl get statefulset argocd-application-controller -n argocd -o jsonpath='{.spec.replicas}'

# Scale (after user confirms)
kubectl scale statefulset/argocd-application-controller --replicas=2 -n argocd 2>/dev/null || \
  kubectl scale deployment/argocd-application-controller --replicas=2 -n argocd

# Set the environment variable for shard count
kubectl set env statefulset/argocd-application-controller ARGOCD_CONTROLLER_REPLICAS=2 -n argocd 2>/dev/null || \
  kubectl set env deployment/argocd-application-controller ARGOCD_CONTROLLER_REPLICAS=2 -n argocd
```

### Repo Server

```bash
# Scale repo-server for parallel manifest generation
kubectl scale deployment/argocd-repo-server --replicas=3 -n argocd

# Increase resource limits for large repos
kubectl set resources deployment/argocd-repo-server -n argocd \
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
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller
for pod in $(kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller -o name); do
  echo "=== $pod ==="
  kubectl logs $pod -n argocd --tail=5 | grep "shard"
done
```

---

## Backup and Restore

### Export All Applications

```bash
# Export all Applications
kubectl get applications -n argocd -o yaml > applications-backup.yaml

# Export individual Applications
for app in $(kubectl get applications -n argocd -o name); do
  name=$(basename $app)
  kubectl get application $name -n argocd -o yaml > "backup/application-${name}.yaml"
done

# Count exported
echo "Exported: $(ls backup/application-*.yaml 2>/dev/null | wc -l) Applications"
```

### Export All AppProjects

```bash
# Export all AppProjects
kubectl get appprojects -n argocd -o yaml > appprojects-backup.yaml

# Export individual AppProjects
for proj in $(kubectl get appprojects -n argocd -o name); do
  name=$(basename $proj)
  kubectl get appproject $name -n argocd -o yaml > "backup/appproject-${name}.yaml"
done

echo "Exported: $(ls backup/appproject-*.yaml 2>/dev/null | wc -l) AppProjects"
```

### Export Secrets (Cluster and Repo Credentials)

```bash
# Export repo credentials (encrypted — contains tokens)
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository -o yaml > backup/repo-secrets.yaml

# Export cluster credentials (encrypted — contains tokens)
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster -o yaml > backup/cluster-secrets.yaml

# WARNING: These contain sensitive data. Encrypt or restrict access to the backup files.
echo "WARNING: Backup files contain sensitive credentials. Secure appropriately."
```

### Export ConfigMaps

```bash
kubectl get configmap argocd-cm argocd-rbac-cm argocd-cmd-params-cm argocd-notifications-cm -n argocd -o yaml > backup/configmaps.yaml 2>/dev/null
```

### Full Backup Script

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="argocd-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up Argo CD resources to $BACKUP_DIR..."

# Applications
kubectl get applications -n argocd -o yaml > "$BACKUP_DIR/applications.yaml" 2>/dev/null && \
  echo "[OK] Applications" || echo "[SKIP] No Applications found"

# ApplicationSets
kubectl get applicationsets -n argocd -o yaml > "$BACKUP_DIR/applicationsets.yaml" 2>/dev/null && \
  echo "[OK] ApplicationSets" || echo "[SKIP] No ApplicationSets found"

# AppProjects
kubectl get appprojects -n argocd -o yaml > "$BACKUP_DIR/appprojects.yaml" 2>/dev/null && \
  echo "[OK] AppProjects" || echo "[SKIP] No AppProjects found"

# ConfigMaps
for cm in argocd-cm argocd-rbac-cm argocd-cmd-params-cm argocd-notifications-cm argocd-tls-certs-cm argocd-ssh-known-hosts-cm; do
  kubectl get configmap "$cm" -n argocd -o yaml > "$BACKUP_DIR/${cm}.yaml" 2>/dev/null && \
    echo "[OK] $cm" || echo "[SKIP] $cm not found"
done

# Secrets (sensitive)
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository -o yaml > "$BACKUP_DIR/repo-secrets.yaml" 2>/dev/null && \
  echo "[OK] Repository secrets" || echo "[SKIP] No repo secrets"
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster -o yaml > "$BACKUP_DIR/cluster-secrets.yaml" 2>/dev/null && \
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
argocd app list 2>/dev/null || kubectl get applications -n argocd
```

---

## Credential Rotation

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

# 4. Test connectivity
argocd repo get <repo-url> 2>/dev/null || \
  kubectl get secret repo-<name> -n argocd -o jsonpath='{.data.sshPrivateKey}' | base64 -d | head -1
```

### Git PAT (Personal Access Token)

```bash
# 1. Create/update repo credential secret
kubectl create secret generic repo-creds-<name> \
  --namespace argocd \
  --from-literal=url=https://github.com/org \
  --from-literal=username=argocd \
  --from-literal=password=<new-pat> \
  --dry-run=client -o yaml | \
  kubectl label --local -f - argocd.argoproj.io/secret-type=repo-creds -o yaml | \
  kubectl apply -f -

# 2. Verify
argocd repo list 2>/dev/null || kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repo-creds
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
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster

# 2. Get the target cluster's ServiceAccount token
# (requires access to the target cluster)
kubectl --context <target-context> create token argocd-manager -n kube-system --duration=8760h

# 3. Update the cluster secret with the new token
kubectl patch secret <cluster-secret-name> -n argocd --type json -p "[
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
  watch kubectl get applications -n argocd
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
helm upgrade argocd argo/argo-cd --set notifications.enabled=true -n argocd --reuse-values

# Operator
kubectl patch argocd openshift-gitops -n openshift-gitops --type merge -p '{"spec":{"notifications":{"enabled":true}}}'
```

### Enable/Disable Image Updater

```bash
# Install image updater
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/manifests/install.yaml

# Verify
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

### Enable Applications in Any Namespace

```bash
# Helm
helm upgrade argocd argo/argo-cd \
  --set configs.params.application.namespaces="team-*" \
  -n argocd --reuse-values

# ConfigMap (direct)
kubectl patch configmap argocd-cmd-params-cm -n argocd --type merge -p '{"data":{"application.namespaces":"team-*"}}'

# Restart server to pick up changes
kubectl rollout restart deployment/argocd-server -n argocd
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
