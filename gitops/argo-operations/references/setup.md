# Setup Reference — Installing and Configuring Argo CD

Step-by-step procedures for installing Argo CD. Each procedure follows the
Generate-Preview-Confirm safety model.

---

## Helm Install (Vanilla Kubernetes)

### Non-HA Install

```bash
# 1. Add the Argo CD Helm repo
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# 2. Create the namespace
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

# 3. Preview — render templates without installing
helm template argocd argo/argo-cd \
  --namespace argocd \
  --version <chart-version> \
  -f values.yaml

# 4. Install (after user confirms)
helm install argocd argo/argo-cd \
  --namespace argocd \
  --version <chart-version> \
  -f values.yaml \
  --wait --timeout 5m

# 5. Verify
kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd
```

**Key values for non-HA:**

```yaml
# values.yaml — non-HA
global:
  image:
    tag: "v2.14.2"  # Pin to specific version
redis-ha:
  enabled: false
controller:
  replicas: 1
server:
  replicas: 1
  service:
    type: ClusterIP
repoServer:
  replicas: 1
applicationSet:
  replicas: 1
notifications:
  enabled: true
configs:
  params:
    server.insecure: false
    application.namespaces: ""  # Restrict to argocd namespace by default
  cm:
    url: https://argocd.example.com
    resource.trackingMethod: annotation
```

### HA Install

```yaml
# values.yaml — HA
redis-ha:
  enabled: true
  haproxy:
    enabled: true
controller:
  replicas: 2
  env:
    - name: ARGOCD_CONTROLLER_REPLICAS
      value: "2"
server:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 5
repoServer:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 5
applicationSet:
  replicas: 2
```

### Helm Upgrade (Existing Install)

```bash
# 1. Preview changes
helm diff upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version <new-version> \
  -f values.yaml 2>/dev/null || \
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version <new-version> \
  -f values.yaml \
  --dry-run

# 2. Apply (after user confirms)
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version <new-version> \
  -f values.yaml \
  --wait --timeout 5m

# 3. Verify
kubectl rollout status deployment/argocd-server -n argocd
kubectl rollout status deployment/argocd-repo-server -n argocd
kubectl rollout status statefulset/argocd-application-controller -n argocd 2>/dev/null || \
  kubectl rollout status deployment/argocd-application-controller -n argocd
```

---

## OpenShift GitOps Operator Install

### Step 1: Create Subscription

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: openshift-gitops-operator
  namespace: openshift-operators
spec:
  channel: latest
  installPlanApproval: Automatic    # Or Manual for controlled upgrades
  name: openshift-gitops-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
```

```bash
# Preview
kubectl apply --dry-run=server -f subscription.yaml

# Apply (after user confirms)
kubectl apply -f subscription.yaml

# Wait for operator to be ready
kubectl wait --for=condition=CatalogSourcesUnhealthy=False \
  subscription/openshift-gitops-operator -n openshift-operators --timeout=120s
```

### Step 2: Configure the ArgoCD CR

The operator creates a default ArgoCD instance in `openshift-gitops`. To customize:

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: openshift-gitops
  namespace: openshift-gitops
spec:
  server:
    autoscale:
      enabled: false
    route:
      enabled: true
      tls:
        termination: reencrypt
  controller:
    resources:
      limits:
        cpu: "2"
        memory: 4Gi
      requests:
        cpu: 500m
        memory: 1Gi
  repo:
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
      requests:
        cpu: 250m
        memory: 256Mi
  redis:
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
  ha:
    enabled: false
  dex:
    openShiftOAuth: true
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
  rbac:
    defaultPolicy: role:readonly
    policy: |
      g, cluster-admins, role:admin
    scopes: '[groups]'
  resourceExclusions: |
    - apiGroups:
      - tekton.dev
      kinds:
      - TaskRun
      - PipelineRun
    - apiGroups:
      - operators.coreos.com
      kinds:
      - InstallPlan
  notifications:
    enabled: true
```

```bash
# Preview
kubectl diff -f argocd-cr.yaml 2>/dev/null || kubectl apply --dry-run=server -f argocd-cr.yaml

# Apply (after user confirms)
kubectl apply -f argocd-cr.yaml

# Verify
kubectl get pods -n openshift-gitops -l app.kubernetes.io/part-of=argocd
kubectl get route -n openshift-gitops
```

### Step 3: Namespace-Scoped Instance (Team Instance)

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: team-argocd
  namespace: team-frontend
spec:
  server:
    route:
      enabled: true
  sourceNamespaces:
    - team-frontend
    - team-frontend-staging
    - team-frontend-prod
```

Label target namespaces:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-frontend-staging
  labels:
    argocd.argoproj.io/managed-by: team-frontend
```

---

## Autopilot Bootstrap

```bash
# 1. Set the repo URL
export GIT_REPO=https://github.com/org/gitops-repo.git
export GIT_TOKEN=<token>

# 2. Bootstrap (creates repo structure + installs Argo CD)
argocd-autopilot repo bootstrap \
  --repo "$GIT_REPO" \
  --git-token "$GIT_TOKEN"

# 3. Create a project
argocd-autopilot project create production \
  --repo "$GIT_REPO" \
  --git-token "$GIT_TOKEN"

# 4. Create an application
argocd-autopilot app create my-app \
  --repo "$GIT_REPO" \
  --git-token "$GIT_TOKEN" \
  --project production \
  --app "https://github.com/org/my-app.git" \
  --type kustomize
```

**Note:** Autopilot modifies the Git repository. Preview the commits it will create
by running with `--dry-run` first (if supported by your version), or by reviewing the
generated directory structure before pushing.

---

## SSO / Dex Configuration

### OpenShift OAuth (OpenShift GitOps Operator)

Enabled by default when `dex.openShiftOAuth: true` in the ArgoCD CR. No additional
config needed — the operator configures Dex automatically.

### Generic OIDC (Keycloak, Okta, Azure AD)

```yaml
# In argocd-cm ConfigMap (Helm) or ArgoCD CR spec.oidcConfig (operator)
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  url: https://argocd.example.com
  oidc.config: |
    name: Keycloak
    issuer: https://keycloak.example.com/realms/argocd
    clientID: argocd
    clientSecret: $oidc.keycloak.clientSecret
    requestedScopes:
      - openid
      - profile
      - email
      - groups
```

The `clientSecret` is referenced from `argocd-secret`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-secret
  namespace: argocd
type: Opaque
stringData:
  oidc.keycloak.clientSecret: <secret-value>
```

### SAML

```yaml
data:
  dex.config: |
    connectors:
      - type: saml
        id: saml
        name: SAML SSO
        config:
          ssoURL: https://idp.example.com/sso
          caData: <base64-ca-cert>
          redirectURI: https://argocd.example.com/api/dex/callback
          entityIssuer: https://argocd.example.com/api/dex/callback
          usernameAttr: name
          emailAttr: email
          groupsAttr: groups
```

---

## RBAC Configuration

### argocd-rbac-cm

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  # Default policy for authenticated users without explicit role mapping
  policy.default: role:readonly

  # CSV-format policy rules
  policy.csv: |
    # Roles
    p, role:dev, applications, get, */*, allow
    p, role:dev, applications, sync, */*, allow
    p, role:dev, logs, get, */*, allow

    # Group mappings (SSO groups -> roles)
    g, platform-admins, role:admin
    g, dev-team, role:dev
    g, readonly-users, role:readonly

  # Which OIDC claim to use for group matching
  scopes: '[groups]'
```

### AppProject RBAC Roles

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-frontend
  namespace: argocd
spec:
  sourceRepos:
    - 'https://github.com/org/frontend-*'
  destinations:
    - namespace: 'frontend-*'
      server: https://kubernetes.default.svc
  clusterResourceWhitelist: []   # No cluster-scoped resources
  namespaceResourceWhitelist:
    - group: ''
      kind: ConfigMap
    - group: ''
      kind: Service
    - group: apps
      kind: Deployment
    - group: networking.k8s.io
      kind: Ingress
  roles:
    - name: deployer
      description: Can sync frontend apps
      policies:
        - p, proj:team-frontend:deployer, applications, sync, team-frontend/*, allow
        - p, proj:team-frontend:deployer, applications, get, team-frontend/*, allow
      groups:
        - frontend-devs
```

---

## Adding External Clusters

### Using argocd CLI

```bash
# 1. List available contexts
kubectl config get-contexts -o name

# 2. Add cluster (creates ServiceAccount + ClusterRoleBinding on target)
argocd cluster add <context-name> \
  --name <display-name> \
  --label tier=production \
  --label region=us-east-1

# 3. Verify
argocd cluster list
```

### Using Cluster Secret (Declarative)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-prod-east
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  name: prod-east
  server: https://api.prod-east.example.com:6443
  config: |
    {
      "bearerToken": "<service-account-token>",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "<base64-ca-cert>"
      }
    }
```

```bash
# Preview
kubectl apply --dry-run=server -f cluster-secret.yaml

# Apply (after user confirms)
kubectl apply -f cluster-secret.yaml

# Verify
argocd cluster list 2>/dev/null || kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster
```

**Note:** Never commit cluster Secrets to Git in plain text. Use sealed-secrets,
external-secrets, or SOPS encryption.

### Workload Identity / IRSA (Cloud Providers)

For EKS with IRSA or GKE with Workload Identity, use the service account annotation
pattern instead of bearer tokens:

```yaml
stringData:
  config: |
    {
      "awsAuthConfig": {
        "clusterName": "prod-east",
        "roleARN": "arn:aws:iam::123456789:role/argocd-manager"
      }
    }
```

---

## AppProject Creation

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: Production workloads
  sourceRepos:
    - 'https://github.com/org/k8s-configs.git'
    - 'https://charts.example.com'
  destinations:
    - namespace: 'prod-*'
      server: https://kubernetes.default.svc
    - namespace: 'prod-*'
      server: https://api.prod-east.example.com:6443
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
  namespaceResourceBlacklist:
    - group: ''
      kind: ResourceQuota
    - group: ''
      kind: LimitRange
  orphanedResources:
    warn: true
  syncWindows:
    - kind: allow
      schedule: '0 8-18 * * 1-5'    # Weekdays 8am-6pm
      duration: 10h
      applications:
        - '*'
      namespaces:
        - '*'
      timeZone: America/New_York
    - kind: deny
      schedule: '0 0 * * 0'          # Sundays
      duration: 24h
      applications:
        - '*'
```

```bash
# Preview
kubectl apply --dry-run=server -f appproject.yaml

# Apply (after user confirms)
kubectl apply -f appproject.yaml

# Verify
argocd proj get production 2>/dev/null || kubectl get appproject production -n argocd -o yaml
```
