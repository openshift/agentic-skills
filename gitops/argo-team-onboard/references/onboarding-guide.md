# Team Onboarding Reference

Core reference for onboarding a new team to Argo CD. Covers what to create,
templates for every resource, and a post-onboarding validation checklist.

## What Gets Created

### Always

| Resource | Purpose | Notes |
|----------|---------|-------|
| AppProject | Isolates team's Applications with RBAC, source/destination restrictions | One per team. Never use the `default` project for tenant workloads. |
| Application | Deploys team's workload from Git to cluster | One per app per environment. References the team's AppProject. |
| RBAC role | Controls who can view/sync/manage the team's Applications | Project-scoped role bound to SSO group. Lives inside the AppProject spec. |

### Conditional

| Resource | Include When | Skip When |
|----------|-------------|-----------|
| Namespace | Team gets new namespaces not yet on cluster | Namespaces pre-provisioned by platform or another controller |
| ResourceQuota | Platform enforces compute/object limits per team | Cluster uses LimitRange only, or no quota policy exists |
| LimitRange | Platform requires default CPU/memory requests on all pods | Quota policy handles limits at the namespace level |
| RoleBinding | Team needs `kubectl` access to their namespaces (not just Argo CD) | Team interacts only through Argo CD UI/CLI |
| Notification subscriptions | Team wants Slack/Teams/email alerts on sync events | Team monitors via Argo CD UI or external monitoring |
| Sync windows | Production namespaces need change freeze periods | All environments allow continuous deployment |

### Never (Out of Scope)

| Resource | Why Out of Scope | Where to Get Help |
|----------|-----------------|-------------------|
| CI pipelines | Build/test is CI concern, not CD. Argo CD consumes artifacts, doesn't produce them. | Team's CI platform (Jenkins, GitHub Actions, Tekton) |
| Container registry | Registry provisioning is infrastructure, not GitOps onboarding. | Platform team's registry provisioning runbook |
| Secrets backend | External Secrets Operator, Sealed Secrets, or Vault CSI are separate platform services. | `external-secrets` or `sealed-secrets` operator docs |
| Ingress/DNS | Domain provisioning and TLS cert issuance are infrastructure concerns. | Platform team's ingress/DNS runbook |
| NetworkPolicy | Network segmentation is platform-managed, not team-managed. | Platform team's network policy templates |

## AppProject Template

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-{{TEAM_NAME}}                          # Convention: team-<name>
  namespace: argocd                                  # Or openshift-gitops for OpenShift
  labels:
    app.kubernetes.io/part-of: tenant-onboarding
    team: "{{TEAM_NAME}}"
spec:
  description: "Project for {{TEAM_NAME}} team"

  # --- Source restrictions ---
  # List ONLY team's repos. Never use '*'.
  sourceRepos:
    - https://github.com/{{ORG}}/{{TEAM_NAME}}-*.git  # Wildcard for team's repos
    # - https://charts.example.com                    # Add Helm repos if needed
    # - oci://registry.example.com/charts             # OCI Helm registry

  # --- Destination restrictions ---
  # List ONLY team's namespaces. Never use server: '*' or namespace: '*'.
  destinations:
    - server: https://kubernetes.default.svc
      namespace: "{{TEAM_NAME}}-dev"
    - server: https://kubernetes.default.svc
      namespace: "{{TEAM_NAME}}-staging"
    - server: https://kubernetes.default.svc
      namespace: "{{TEAM_NAME}}-prod"
    # Multi-cluster: add remote cluster entries
    # - server: https://prod-cluster.example.com
    #   namespace: "{{TEAM_NAME}}-prod"

  # --- Cluster-scoped resources ---
  # Empty = no cluster-scoped resources allowed (safest default).
  # Add Namespace only if team creates their own namespaces via GitOps.
  clusterResourceWhitelist: []
  # clusterResourceWhitelist:
  #   - group: ''
  #     kind: Namespace

  # --- Namespace resource deny list ---
  # Block resources managed by the platform team.
  namespaceResourceBlacklist:
    - group: ''
      kind: ResourceQuota                            # Platform-managed
    - group: ''
      kind: LimitRange                               # Platform-managed
    - group: networking.k8s.io
      kind: NetworkPolicy                            # Platform-managed

  # --- Orphaned resource detection ---
  orphanedResources:
    warn: true                                       # Alert on unmanaged resources
    ignore:
      - group: ""
        kind: ConfigMap
        name: kube-root-ca.crt                       # Auto-created by K8s
      - group: ""
        kind: ServiceAccount
        name: default                                # Auto-created by K8s

  # --- Project-scoped RBAC ---
  roles:
    - name: developer
      description: "{{TEAM_NAME}} developer — view and sync"
      policies:
        # get: view Application status, logs, manifests
        - p, proj:team-{{TEAM_NAME}}:developer, applications, get, team-{{TEAM_NAME}}/*, allow
        # sync: trigger manual syncs
        - p, proj:team-{{TEAM_NAME}}:developer, applications, sync, team-{{TEAM_NAME}}/*, allow
        # action: allow resource actions (restart, resume rollout)
        - p, proj:team-{{TEAM_NAME}}:developer, applications, action/*, team-{{TEAM_NAME}}/*, allow
      groups:
        - "{{SSO_GROUP}}"                            # Maps to IdP/SSO group

    - name: viewer
      description: "{{TEAM_NAME}} viewer — read-only"
      policies:
        - p, proj:team-{{TEAM_NAME}}:viewer, applications, get, team-{{TEAM_NAME}}/*, allow
      groups:
        - "{{SSO_GROUP_READONLY}}"

  # --- Sync windows (optional, add for production) ---
  # syncWindows:
  #   - kind: deny
  #     schedule: '0 18 * * 5'                       # Friday 6pm UTC
  #     duration: 62h                                # Until Monday 8am UTC
  #     applications: ['*']
  #     namespaces: ['{{TEAM_NAME}}-prod']
  #     manualSync: false                            # Allow manual syncs during deny
```

## Application Templates

### Kustomize Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: "{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}}"        # e.g. payments-api-prod
  namespace: argocd
  labels:
    team: "{{TEAM_NAME}}"
    env: "{{ENV}}"
  annotations:
    # Notification subscriptions (if notifications enabled)
    notifications.argoproj.io/subscribe.on-sync-failed.slack: "{{SLACK_CHANNEL}}"
    notifications.argoproj.io/subscribe.on-health-degraded.slack: "{{SLACK_CHANNEL}}"
  finalizers:
    - resources-finalizer.argocd.argoproj.io          # Clean up on Application delete
spec:
  project: team-{{TEAM_NAME}}                        # Must match AppProject name

  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: main                              # Pin to branch or tag, never HEAD
    path: deploy/overlays/{{ENV}}                     # Kustomize overlay path

  destination:
    server: https://kubernetes.default.svc
    namespace: "{{TEAM_NAME}}-{{ENV}}"

  syncPolicy:
    automated:
      prune: true                                    # Remove resources deleted from Git
      selfHeal: true                                 # Revert manual cluster changes
    syncOptions:
      - CreateNamespace=false                        # Namespace managed separately
      - ServerSideApply=true                         # Avoid field ownership conflicts
      - RespectIgnoreDifferences=true                # Honor ignoreDifferences during sync
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  # Ignore fields managed by controllers, not Git
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas                             # HPA manages replicas
    - group: autoscaling
      kind: HorizontalPodAutoscaler
      jqPathExpressions:
        - .status                                    # Status is runtime-only
```

### Helm Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: "{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}}"
  namespace: argocd
  labels:
    team: "{{TEAM_NAME}}"
    env: "{{ENV}}"
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.slack: "{{SLACK_CHANNEL}}"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: team-{{TEAM_NAME}}

  source:
    # Option A: Helm repo
    repoURL: https://charts.example.com
    chart: "{{CHART_NAME}}"
    targetRevision: "1.2.3"                          # Pin chart version, never '*'

    # Option B: OCI registry
    # repoURL: oci://registry.example.com/charts
    # chart: "{{CHART_NAME}}"
    # targetRevision: "1.2.3"

    helm:
      releaseName: "{{APP_NAME}}"
      valuesObject:                                  # Inline values (v2.6+)
        replicaCount: 3
        image:
          repository: registry.example.com/{{TEAM_NAME}}/{{APP_NAME}}
          tag: "v1.0.0"                              # Updated by image-updater or CI
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
      # valueFiles:                                  # Alternative: values from Git
      #   - values-{{ENV}}.yaml

  destination:
    server: https://kubernetes.default.svc
    namespace: "{{TEAM_NAME}}-{{ENV}}"

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=false
      - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```

### Multi-Source Helm Application (Chart + Values from Separate Repo)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: "{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}}"
  namespace: argocd
  labels:
    team: "{{TEAM_NAME}}"
    env: "{{ENV}}"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: team-{{TEAM_NAME}}

  sources:                                           # Multi-source (v2.6+)
    - repoURL: https://charts.example.com
      chart: "{{CHART_NAME}}"
      targetRevision: "1.2.3"
      helm:
        releaseName: "{{APP_NAME}}"
        valueFiles:
          - $values/{{ENV}}/values.yaml              # Reference values repo via alias

    - repoURL: https://github.com/{{ORG}}/{{TEAM_NAME}}-config.git
      targetRevision: main
      ref: values                                    # Alias used in $values above

  destination:
    server: https://kubernetes.default.svc
    namespace: "{{TEAM_NAME}}-{{ENV}}"

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Directory Application (Plain YAML)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: "{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}}"
  namespace: argocd
  labels:
    team: "{{TEAM_NAME}}"
    env: "{{ENV}}"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: team-{{TEAM_NAME}}

  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: main
    path: deploy/{{ENV}}                             # Directory with raw YAML
    directory:
      recurse: true                                  # Include subdirectories
      exclude: '{*.test.yaml,*_test.yaml}'           # Exclude test files

  destination:
    server: https://kubernetes.default.svc
    namespace: "{{TEAM_NAME}}-{{ENV}}"

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=false
      - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

## RBAC Template

### Project-Scoped Roles

Roles defined in the AppProject spec (see AppProject Template above) provide fine-grained access.
For cases where centralized RBAC is preferred, add entries to `argocd-rbac-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  # Global RBAC policy (supplements project-level roles)
  policy.csv: |
    # Team developers — get + sync within their project
    p, role:team-{{TEAM_NAME}}-dev, applications, get, team-{{TEAM_NAME}}/*, allow
    p, role:team-{{TEAM_NAME}}-dev, applications, sync, team-{{TEAM_NAME}}/*, allow
    p, role:team-{{TEAM_NAME}}-dev, applications, action/*, team-{{TEAM_NAME}}/*, allow
    p, role:team-{{TEAM_NAME}}-dev, logs, get, team-{{TEAM_NAME}}/*, allow

    # Bind SSO group to role
    g, {{SSO_GROUP}}, role:team-{{TEAM_NAME}}-dev

  # Default policy for authenticated users with no matching role
  policy.default: role:readonly
```

### Permission Matrix

| Action | developer | viewer | admin (platform) |
|--------|-----------|--------|-------------------|
| `applications/get` | Yes | Yes | Yes |
| `applications/sync` | Yes | No | Yes |
| `applications/action/*` | Yes | No | Yes |
| `applications/create` | No | No | Yes |
| `applications/delete` | No | No | Yes |
| `applications/override` | No | No | Yes |
| `logs/get` | Yes | No | Yes |
| `exec/create` | No | No | No (enable explicitly) |

### Apps-in-Any-Namespace RBAC

When using apps-in-any-namespace, RBAC syntax includes the Application namespace:

```
# Format: p, <role>, <resource>, <action>, <project>/<app-namespace>/<app-name>, <effect>
p, role:team-{{TEAM_NAME}}-dev, applications, get, team-{{TEAM_NAME}}/{{TEAM_NAME}}-apps/*, allow
p, role:team-{{TEAM_NAME}}-dev, applications, sync, team-{{TEAM_NAME}}/{{TEAM_NAME}}-apps/*, allow
```

## Conditional Resources

### Namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: "{{TEAM_NAME}}-{{ENV}}"
  labels:
    app.kubernetes.io/part-of: tenant-onboarding
    team: "{{TEAM_NAME}}"
    env: "{{ENV}}"
  annotations:
    openshift.io/description: "{{TEAM_NAME}} {{ENV}} namespace"
    # openshift.io/requester: "{{SSO_GROUP}}"       # OpenShift-specific
```

### ResourceQuota (3 Tiers)

#### Small (dev/test)

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: "{{TEAM_NAME}}-dev"
spec:
  hard:
    requests.cpu: "2"
    requests.memory: 4Gi
    limits.cpu: "4"
    limits.memory: 8Gi
    pods: "20"
    services: "10"
    persistentvolumeclaims: "5"
    configmaps: "20"
    secrets: "20"
```

#### Medium (staging)

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: "{{TEAM_NAME}}-staging"
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    limits.cpu: "16"
    limits.memory: 32Gi
    pods: "50"
    services: "20"
    persistentvolumeclaims: "10"
    configmaps: "40"
    secrets: "40"
```

#### Large (production)

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: "{{TEAM_NAME}}-prod"
spec:
  hard:
    requests.cpu: "32"
    requests.memory: 64Gi
    limits.cpu: "64"
    limits.memory: 128Gi
    pods: "200"
    services: "50"
    persistentvolumeclaims: "30"
    configmaps: "100"
    secrets: "100"
```

### LimitRange

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: "{{TEAM_NAME}}-{{ENV}}"
spec:
  limits:
    - type: Container
      default:                                       # Default limits if not specified
        cpu: 500m
        memory: 512Mi
      defaultRequest:                                # Default requests if not specified
        cpu: 100m
        memory: 128Mi
      max:                                           # Max any single container can request
        cpu: "4"
        memory: 8Gi
      min:                                           # Min any single container must request
        cpu: 50m
        memory: 64Mi
    - type: Pod
      max:
        cpu: "8"
        memory: 16Gi
```

### RoleBinding (kubectl Access)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: "{{TEAM_NAME}}-developers"
  namespace: "{{TEAM_NAME}}-{{ENV}}"
subjects:
  - kind: Group
    name: "{{SSO_GROUP}}"                            # Must match IdP group name
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: edit                                         # K8s built-in: CRUD on most resources
  apiGroup: rbac.authorization.k8s.io
```

Use `view` instead of `edit` for read-only `kubectl` access.

### Notification Subscriptions

Per-Application annotations (see Application templates above) or project-level default:

```yaml
# In argocd-notifications-cm
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  # Define trigger
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send: [app-sync-failed]
  trigger.on-health-degraded: |
    - when: app.status.health.status == 'Degraded'
      send: [app-health-degraded]

  # Define template
  template.app-sync-failed: |
    message: |
      Application {{.app.metadata.name}} sync failed.
      Sync Status: {{.app.status.sync.status}}
      Health: {{.app.status.health.status}}
      {{if .app.status.operationState}}Error: {{.app.status.operationState.message}}{{end}}
  template.app-health-degraded: |
    message: |
      Application {{.app.metadata.name}} health is Degraded.
      Health: {{.app.status.health.status}}

  # Slack service config (reference argocd-notifications-secret for token)
  service.slack: |
    token: $slack-token
```

### Sync Windows

```yaml
# Add to AppProject spec.syncWindows (see AppProject Template)
syncWindows:
  # Business hours only for production
  - kind: allow
    schedule: '0 8 * * 1-5'                          # Mon-Fri 8am UTC
    duration: 10h                                    # Until 6pm UTC
    applications: ['*']
    namespaces: ['{{TEAM_NAME}}-prod']
    manualSync: true                                 # Block manual syncs outside window too

  # Deny weekends for production
  - kind: deny
    schedule: '0 18 * * 5'                           # Friday 6pm UTC
    duration: 62h                                    # Until Monday 8am UTC
    applications: ['*']
    namespaces: ['{{TEAM_NAME}}-prod']
    manualSync: false                                # Allow manual syncs for emergencies
```

## Validation Checklist

Run after every onboarding to verify isolation and access controls.

### Sync and Health

- [ ] Application syncs successfully (status: Synced, Healthy)
- [ ] `argocd app get team-{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}}` shows correct project, repo, destination
- [ ] Automated sync triggers on Git push (if `automated` is enabled)
- [ ] Retry backoff is configured and tested (break a manifest, observe retries)

### AppProject Isolation

- [ ] Team's Application references the correct AppProject (not `default`)
- [ ] `sourceRepos` contains only team's repos — verify: `argocd proj get team-{{TEAM_NAME}} -o yaml | grep sourceRepos`
- [ ] No wildcard `*` in `sourceRepos` or `destinations`
- [ ] Team cannot create Applications targeting other teams' namespaces
- [ ] Team cannot create Applications sourcing from other teams' repos

### RBAC Verification

- [ ] Team member can sync their own apps: `argocd app sync team-{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}} --auth-token $TEAM_TOKEN`
- [ ] Team member cannot sync other teams' apps (expect "permission denied")
- [ ] Team member cannot delete Applications (expect "permission denied")
- [ ] Team member cannot create new Applications (expect "permission denied" — platform team creates)
- [ ] Team member cannot access `exec` or `override` actions

### Namespace Isolation

- [ ] Team cannot deploy to namespaces outside their `destinations` list
- [ ] Team cannot create cluster-scoped resources (unless explicitly whitelisted)
- [ ] Team cannot modify ResourceQuota, LimitRange, or NetworkPolicy (`namespaceResourceBlacklist` enforced)
- [ ] ResourceQuota limits are applied and visible: `kubectl describe quota -n {{TEAM_NAME}}-{{ENV}}`

### Notification Verification (If Configured)

- [ ] Sync failure notification fires to correct channel
- [ ] Health degradation notification fires to correct channel
- [ ] No cross-team notification leakage

### Sync Window Verification (If Configured)

- [ ] Sync blocked outside allow window: `argocd app sync` returns window error
- [ ] Manual sync permitted during deny window (if `manualSync: false`)
- [ ] Dev/staging environments not affected by production sync windows
