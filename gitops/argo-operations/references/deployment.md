# Deployment Reference — Creating and Managing Applications

Step-by-step procedures for creating Applications, ApplicationSets, and related
configuration. Every procedure follows the Generate-Preview-Confirm safety model.

---

## Creating Applications

### Helm Source

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://charts.example.com
    chart: my-app
    targetRevision: 1.2.3
    helm:
      releaseName: my-app
      valuesObject:
        replicaCount: 3
        image:
          repository: registry.example.com/my-app
          tag: v1.0.0
      parameters:
        - name: service.type
          value: ClusterIP
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

**OCI Helm source:**
```yaml
source:
  repoURL: oci://registry.example.com/charts
  chart: my-app
  targetRevision: ">=2.0.0 <3.0.0"    # Semver constraint
```

### Kustomize Source

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-prod
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-configs.git
    targetRevision: main
    path: apps/my-app/overlays/production
    kustomize:
      namePrefix: prod-
      commonLabels:
        environment: production
      images:
        - registry.example.com/my-app:v2.1.0
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### Plain Directory Source

```yaml
source:
  repoURL: https://github.com/org/k8s-configs.git
  targetRevision: v1.0.0
  path: manifests/production
  directory:
    recurse: true
    exclude: '*.test.yaml'
```

### Multi-Source Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  sources:
    - repoURL: https://github.com/org/env-config.git
      targetRevision: main
      ref: values                       # Named reference
    - repoURL: https://charts.example.com
      chart: my-app
      targetRevision: 2.x
      helm:
        releaseName: my-app
        valueFiles:
          - $values/envs/production/values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
```

**Key:** The `ref` field on the Git source creates a named reference (`$values`) that
other sources can use in `valueFiles`. The Git source provides the values files; the
Helm source consumes them.

### Dry-Run Procedure

```bash
# 1. Save the manifest
cat > application.yaml << 'EOF'
<generated YAML>
EOF

# 2. Server-side dry-run (validates against API server)
kubectl apply --dry-run=server -f application.yaml

# 3. If CRD not installed, fall back to client-side
kubectl apply --dry-run=client -f application.yaml

# 4. Apply (after user confirms)
kubectl apply -f application.yaml

# 5. Verify
kubectl get application <name> -n argocd -o jsonpath='{.status.sync.status}'
```

### Using argocd CLI

```bash
# Helm source
argocd app create my-app \
  --repo https://charts.example.com \
  --helm-chart my-app \
  --revision 1.2.3 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace my-app \
  --project default \
  --sync-policy automated \
  --self-heal \
  --auto-prune \
  --sync-option CreateNamespace=true

# Verify
argocd app get my-app
```

---

## Creating ApplicationSets

### Git Directory Generator

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: cluster-addons
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  generators:
    - git:
        repoURL: https://github.com/org/cluster-addons.git
        revision: main
        directories:
          - path: addons/*
          - path: addons/experimental-*
            exclude: true
  preserveResourcesOnDeletion: true
  template:
    metadata:
      name: 'addon-{{.path.basename}}'
    spec:
      project: cluster-addons
      source:
        repoURL: https://github.com/org/cluster-addons.git
        targetRevision: main
        path: '{{.path.path}}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{.path.basename}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### List Generator

```yaml
generators:
  - list:
      elements:
        - name: dev
          namespace: app-dev
          cluster: https://kubernetes.default.svc
        - name: staging
          namespace: app-staging
          cluster: https://kubernetes.default.svc
        - name: production
          namespace: app-prod
          cluster: https://api.prod.example.com:6443
```

### Cluster Generator

```yaml
generators:
  - clusters:
      selector:
        matchLabels:
          tier: production
      values:
        revision: main
        helmValues: values-prod.yaml
```

### Matrix Generator

```yaml
generators:
  - matrix:
      generators:
        - clusters:
            selector:
              matchLabels:
                tier: production
        - git:
            repoURL: https://github.com/org/platform.git
            revision: main
            directories:
              - path: services/*
```

### Merge Generator

```yaml
generators:
  - merge:
      mergeKeys:
        - name
      generators:
        - clusters:
            selector:
              matchLabels:
                tier: production
            values:
              helmValues: values-default.yaml
        - clusters:
            selector:
              matchLabels:
                region: us-east-1
            values:
              helmValues: values-us-east.yaml
```

### Pull Request Generator

```yaml
generators:
  - pullRequest:
      github:
        owner: org
        repo: my-app
        tokenRef:
          secretName: github-token
          key: token
        labels:
          - preview
      requeueAfterSeconds: 60
```

### Progressive Sync (RollingSync)

```yaml
spec:
  strategy:
    type: RollingSync
    rollingSync:
      steps:
        - matchExpressions:
            - key: envLabel
              operator: In
              values:
                - staging
          maxUpdate: 100%
        - matchExpressions:
            - key: envLabel
              operator: In
              values:
                - production
          maxUpdate: 25%
```

### ApplicationSet with ignoreApplicationDifferences

```yaml
spec:
  ignoreApplicationDifferences:
    - jsonPointers:
        - /spec/source/targetRevision
    - jqPathExpressions:
        - .spec.source.helm.valuesObject
```

---

## Sync Policies

### Automated Sync

```yaml
syncPolicy:
  automated:
    prune: true         # Delete resources not in Git
    selfHeal: true      # Re-sync on live drift
    allowEmpty: false   # Fail if source produces no manifests
```

### Sync Options

| Option | Effect |
|--------|--------|
| `CreateNamespace=true` | Create target namespace if missing |
| `ServerSideApply=true` | Use server-side apply (handles large CRDs, conflicts) |
| `Replace=true` | Use `kubectl replace` instead of apply (destructive) |
| `PruneLast=true` | Prune resources after all other syncs complete |
| `PrunePropagationPolicy=foreground` | Wait for dependent resources before pruning |
| `ApplyOutOfSyncOnly=true` | Only apply resources that are OutOfSync |
| `Validate=false` | Skip schema validation (use for CRDs with unknown fields) |
| `FailOnSharedResource=true` | Fail if another Application manages the same resource |
| `RespectIgnoreDifferences=true` | Use ignoreDifferences during sync |

### Retry Policy

```yaml
syncPolicy:
  retry:
    limit: 5            # Max retries (-1 for infinite)
    backoff:
      duration: 5s      # Initial retry interval
      factor: 2         # Exponential backoff factor
      maxDuration: 3m   # Max retry interval
```

---

## Notifications Setup

### ConfigMap + Secret

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.slack: |
    token: $slack-token
  template.app-sync-succeeded: |
    message: |
      Application {{.app.metadata.name}} synced successfully.
      Revision: {{.app.status.sync.revision | trunc 7}}
    slack:
      attachments: |
        [{
          "color": "#18be52",
          "title": "{{.app.metadata.name}} synced",
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"
        }]
  template.app-sync-failed: |
    message: |
      Application {{.app.metadata.name}} sync failed.
      Error: {{.app.status.operationState.message}}
    slack:
      attachments: |
        [{
          "color": "#E96D76",
          "title": "{{.app.metadata.name}} sync failed",
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"
        }]
  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [app-sync-succeeded]
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send: [app-sync-failed]
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: argocd
type: Opaque
stringData:
  slack-token: xoxb-PLACEHOLDER
```

### Application Annotations

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.slack: platform-alerts
    notifications.argoproj.io/subscribe.on-sync-succeeded.slack: deployments
```

---

## Image Updater Setup

### Application Annotations

```yaml
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: myapp=registry.example.com/my-app
    argocd-image-updater.argoproj.io/myapp.update-strategy: semver
    argocd-image-updater.argoproj.io/myapp.allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"
    argocd-image-updater.argoproj.io/myapp.ignore-tags: "latest,dev-*"
    argocd-image-updater.argoproj.io/write-back-method: git
    argocd-image-updater.argoproj.io/write-back-target: kustomization
    argocd-image-updater.argoproj.io/git-branch: main
```

### Helm Image Mapping

```yaml
argocd-image-updater.argoproj.io/myapp.helm.image-name: image.repository
argocd-image-updater.argoproj.io/myapp.helm.image-tag: image.tag
```

### Pull Secret

```yaml
argocd-image-updater.argoproj.io/myapp.pull-secret: pullsecret:argocd/registry-creds
```

### Update Strategies

| Strategy | Behavior |
|----------|----------|
| `semver` | Latest semver tag matching constraint |
| `latest` | Most recently built image (by build date) |
| `name` | Alphabetically last tag matching pattern |
| `digest` | Update when digest changes for a given tag |

---

## Sync Waves and Hooks

### Sync Wave Ordering

Resources sync in wave order (lowest first). Default wave is 0.

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"   # Before default
    argocd.argoproj.io/sync-wave: "0"    # Default
    argocd.argoproj.io/sync-wave: "1"    # After default
```

**Typical ordering:**
- Wave -5: Namespaces, CRDs
- Wave -3: RBAC (ServiceAccounts, Roles, Bindings)
- Wave -1: ConfigMaps, Secrets
- Wave 0: Deployments, Services (default)
- Wave 1: Ingress, Routes
- Wave 3: Post-deploy Jobs (smoke tests)

### Hooks

```yaml
metadata:
  annotations:
    argocd.argoproj.io/hook: PreSync      # Run before sync
    argocd.argoproj.io/hook: PostSync     # Run after sync
    argocd.argoproj.io/hook: SyncFail     # Run on sync failure
    argocd.argoproj.io/hook: Skip         # Never sync this resource
    argocd.argoproj.io/hook-delete-policy: HookSucceeded  # Delete after success
```

**Hook delete policies:**
| Policy | Behavior |
|--------|----------|
| `HookSucceeded` | Delete when hook succeeds |
| `HookFailed` | Delete when hook fails |
| `BeforeHookCreation` | Delete existing hook before creating new one |

### Example: Database Migration Hook

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
    argocd.argoproj.io/sync-wave: "-1"
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: registry.example.com/my-app:v2.0.0
          command: ["./migrate", "--apply"]
      restartPolicy: Never
  backoffLimit: 3
```
