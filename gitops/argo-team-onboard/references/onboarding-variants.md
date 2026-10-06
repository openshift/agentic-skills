# Onboarding Variants Reference

Source type variants and optional component add-ons for team onboarding.
Each variant shows the delta from the base templates in `onboarding-guide.md`.

## Source Type Variants

### Helm: Chart Repository

Delta from base: replace `source` block entirely.

```yaml
spec:
  source:
    repoURL: https://charts.example.com              # Helm repo URL
    chart: "{{CHART_NAME}}"                          # Chart name (not a path)
    targetRevision: "1.2.3"                          # Pinned chart version, never '*' or latest
    helm:
      releaseName: "{{APP_NAME}}"
      valuesObject:
        replicaCount: 3
        image:
          repository: registry.example.com/{{TEAM_NAME}}/{{APP_NAME}}
          tag: "v1.0.0"
```

### Helm: OCI Registry

Delta: change `repoURL` prefix to `oci://`.

```yaml
spec:
  source:
    repoURL: oci://registry.example.com/charts       # OCI prefix
    chart: "{{CHART_NAME}}"
    targetRevision: "1.2.3"
    helm:
      releaseName: "{{APP_NAME}}"
      valuesObject:
        replicaCount: 3
```

### Helm: Multi-Source (Chart + Values from Separate Repo)

Delta: replace `source` with `sources` (plural). Requires Argo CD v2.6+.

```yaml
spec:
  sources:
    # Source 1: chart
    - repoURL: https://charts.example.com
      chart: "{{CHART_NAME}}"
      targetRevision: "1.2.3"
      helm:
        releaseName: "{{APP_NAME}}"
        valueFiles:
          - $values/{{ENV}}/values.yaml              # $values references Source 2

    # Source 2: values repo (ref alias)
    - repoURL: https://github.com/{{ORG}}/{{TEAM_NAME}}-config.git
      targetRevision: main
      ref: values                                    # Alias used in $values
```

Values repo structure:

```
{{TEAM_NAME}}-config/
├── dev/
│   └── values.yaml
├── staging/
│   └── values.yaml
└── prod/
    └── values.yaml
```

### Kustomize: Overlays

Delta: none from base Kustomize Application template. Standard path-based source.

```yaml
spec:
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: main
    path: deploy/overlays/{{ENV}}
```

Expected repo layout:

```
deploy/
├── base/
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   └── service.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml
    │   └── patch-replicas.yaml
    ├── staging/
    │   ├── kustomization.yaml
    │   └── patch-resources.yaml
    └── prod/
        ├── kustomization.yaml
        ├── patch-replicas.yaml
        └── patch-resources.yaml
```

### Kustomize: Components

Delta: add `kustomize.components` to source. Requires Kustomize v4.1+.

```yaml
spec:
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: main
    path: deploy/overlays/{{ENV}}
    kustomize:
      components:
        - ../../components/monitoring                # Adds ServiceMonitor
        - ../../components/network-policy            # Adds NetworkPolicy
```

Repo layout with components:

```
deploy/
├── base/
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── components/
│   ├── monitoring/
│   │   ├── kustomization.yaml                       # kind: Component
│   │   └── service-monitor.yaml
│   └── network-policy/
│       ├── kustomization.yaml                       # kind: Component
│       └── network-policy.yaml
└── overlays/
    └── prod/
        ├── kustomization.yaml                       # references components
        └── patch-replicas.yaml
```

### Directory: Plain YAML

Delta: replace `source` with directory config.

```yaml
spec:
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: main
    path: deploy/{{ENV}}
    directory:
      recurse: true                                  # Walk subdirectories
      exclude: '{*.test.yaml,*_test.yaml}'           # Skip test files
      include: '*.yaml'                              # Only YAML files
```

## Optional Component Variants

### With Rollouts

Add Rollout + AnalysisTemplate alongside the Application. Requires the Argo Rollouts
controller installed on the target cluster.

Delta: add Rollout and AnalysisTemplate to team's manifest directory (not to the Application itself).

**Rollout (replaces Deployment):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: "{{APP_NAME}}"
  namespace: "{{TEAM_NAME}}-{{ENV}}"
  labels:
    team: "{{TEAM_NAME}}"
spec:
  replicas: 3
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: "{{APP_NAME}}"
  template:
    metadata:
      labels:
        app: "{{APP_NAME}}"
    spec:
      containers:
        - name: "{{APP_NAME}}"
          image: registry.example.com/{{TEAM_NAME}}/{{APP_NAME}}:v1.0.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
  strategy:
    canary:
      maxSurge: "25%"
      maxUnavailable: 0
      steps:
        - setWeight: 20
        - pause: { duration: 60s }                   # Wait, observe metrics
        - setWeight: 50
        - pause: { duration: 60s }
        - setWeight: 80
        - pause: { duration: 60s }
      analysis:
        templates:
          - templateName: "{{APP_NAME}}-success-rate"
        startingStep: 1                              # Start analysis at first pause
        args:
          - name: service-name
            value: "{{APP_NAME}}"
      # Traffic management (Istio / NGINX / ALB)
      # trafficRouting:
      #   istio:
      #     virtualService:
      #       name: "{{APP_NAME}}-vsvc"
      #       routes:
      #         - primary
```

**AnalysisTemplate:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: "{{APP_NAME}}-success-rate"
  namespace: "{{TEAM_NAME}}-{{ENV}}"
spec:
  args:
    - name: service-name
  metrics:
    - name: success-rate
      interval: 30s
      count: 5                                       # Run 5 measurements
      successCondition: result[0] >= 0.95            # 95% success rate
      failureLimit: 2                                # Max 2 failures before abort
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(http_requests_total{
              service="{{args.service-name}}",
              status=~"2.."
            }[2m]))
            /
            sum(rate(http_requests_total{
              service="{{args.service-name}}"
            }[2m]))
```

**Application ignoreDifferences addition for Rollouts:**

```yaml
  ignoreDifferences:
    - group: argoproj.io
      kind: Rollout
      jsonPointers:
        - /spec/replicas                             # HPA-managed
    - group: apps
      kind: Deployment                               # Keep if Deployment also exists
      jsonPointers:
        - /spec/replicas
```

### With Notifications

Delta: add annotations to the Application metadata.

```yaml
metadata:
  annotations:
    # Sync events
    notifications.argoproj.io/subscribe.on-sync-succeeded.slack: "{{SLACK_CHANNEL}}"
    notifications.argoproj.io/subscribe.on-sync-failed.slack: "{{SLACK_CHANNEL}}"
    notifications.argoproj.io/subscribe.on-sync-status-unknown.slack: "{{SLACK_CHANNEL}}"

    # Health events
    notifications.argoproj.io/subscribe.on-health-degraded.slack: "{{SLACK_CHANNEL}}"

    # Deployment events (for tracking rollout completion)
    notifications.argoproj.io/subscribe.on-deployed.slack: "{{SLACK_CHANNEL}}"
```

For Microsoft Teams:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.teams: "{{TEAMS_WEBHOOK_NAME}}"
    notifications.argoproj.io/subscribe.on-health-degraded.teams: "{{TEAMS_WEBHOOK_NAME}}"
```

For email:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.email: "{{TEAM_EMAIL}}"
    notifications.argoproj.io/subscribe.on-health-degraded.email: "{{TEAM_EMAIL}}"
```

### With Sync Windows

Delta: add `syncWindows` to the AppProject spec.

**Business hours only (production):**

```yaml
spec:
  syncWindows:
    - kind: allow
      schedule: '0 8 * * 1-5'                       # Mon-Fri 8am UTC
      duration: 10h                                  # Until 6pm UTC
      applications: ['*']
      namespaces: ['{{TEAM_NAME}}-prod']
      manualSync: true                               # Also block manual syncs outside window
```

**Deny weekends:**

```yaml
spec:
  syncWindows:
    - kind: deny
      schedule: '0 18 * * 5'                         # Friday 6pm UTC
      duration: 62h                                  # Until Monday 8am UTC
      applications: ['*']
      namespaces: ['{{TEAM_NAME}}-prod']
      manualSync: false                              # Allow emergency manual syncs
```

**Combined (business hours + deny weekends):**

```yaml
spec:
  syncWindows:
    - kind: allow
      schedule: '0 8 * * 1-5'
      duration: 10h
      applications: ['*']
      namespaces: ['{{TEAM_NAME}}-prod']
      manualSync: true
    - kind: deny
      schedule: '0 18 * * 5'
      duration: 62h
      applications: ['*']
      namespaces: ['{{TEAM_NAME}}-prod']
      manualSync: false
```

**Maintenance window (specific time for planned changes):**

```yaml
spec:
  syncWindows:
    - kind: allow
      schedule: '0 2 * * 3'                          # Wednesday 2am UTC
      duration: 4h                                   # Until 6am UTC
      applications: ['*']
      namespaces: ['{{TEAM_NAME}}-prod']
      manualSync: true
```

### With Promotion (gitops-promoter)

Uses branch-per-environment with the gitops-promoter controller for automated promotion.

Delta: add PromotionStrategy CR and change Application `targetRevision` to environment branches.

**Application (per environment branch):**

```yaml
# Dev — tracks main branch
spec:
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: environments/dev                 # Environment branch
    path: deploy

---
# Staging — promoted from dev
spec:
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: environments/staging
    path: deploy

---
# Prod — promoted from staging
spec:
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: environments/prod
    path: deploy
```

**PromotionStrategy:**

```yaml
apiVersion: promoter.argoproj.io/v1alpha1
kind: PromotionStrategy
metadata:
  name: "{{APP_NAME}}"
  namespace: argocd
spec:
  repositoryReference:
    owner: "{{ORG}}"
    name: "{{REPO}}"
    scmProviderRef:
      name: github                                   # References SCMProvider CR
  environments:
    - branch: environments/dev
      autoMerge: true                                # Auto-merge PRs to dev
    - branch: environments/staging
      autoMerge: true                                # Auto-merge PRs to staging
    - branch: environments/prod
      autoMerge: false                               # Require manual merge to prod
  activeCommitStatuses:
    - key: health-check
      # Waits for commit status from Argo CD before promoting
```

**SCMProvider (one per Git provider):**

```yaml
apiVersion: promoter.argoproj.io/v1alpha1
kind: SCMProvider
metadata:
  name: github
  namespace: argocd
spec:
  github:
    domain: github.com
  secretRef:
    name: github-token                               # Secret with PAT or GitHub App creds
```

### Minimal (AppProject + Application Only)

The absolute minimum for onboarding. No quota, no notifications, no sync windows.

**AppProject:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-{{TEAM_NAME}}
  namespace: argocd
spec:
  sourceRepos:
    - https://github.com/{{ORG}}/{{REPO}}.git
  destinations:
    - server: https://kubernetes.default.svc
      namespace: "{{TEAM_NAME}}-{{ENV}}"
  clusterResourceWhitelist: []
  namespaceResourceBlacklist:
    - group: ''
      kind: ResourceQuota
    - group: ''
      kind: LimitRange
    - group: networking.k8s.io
      kind: NetworkPolicy
  orphanedResources:
    warn: true
  roles:
    - name: developer
      policies:
        - p, proj:team-{{TEAM_NAME}}:developer, applications, get, team-{{TEAM_NAME}}/*, allow
        - p, proj:team-{{TEAM_NAME}}:developer, applications, sync, team-{{TEAM_NAME}}/*, allow
      groups:
        - "{{SSO_GROUP}}"
```

**Application:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: "{{TEAM_NAME}}-{{APP_NAME}}-{{ENV}}"
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: team-{{TEAM_NAME}}
  source:
    repoURL: https://github.com/{{ORG}}/{{REPO}}.git
    targetRevision: main
    path: deploy/{{ENV}}
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

Total resources: 2. No conditional resources, no optional components.

## Variant Selection Matrix

| Variant | Add When | Skip When |
|---------|----------|-----------|
| Helm (repo) | Team uses public/private Helm chart repo | Team uses Kustomize or raw YAML |
| Helm (OCI) | Team publishes charts to OCI registry | Team uses non-OCI Helm repo |
| Helm (multi-source) | Chart and values live in different repos | Chart + values co-located |
| Kustomize (overlays) | Team has base + per-env patches | Single environment, no variance |
| Kustomize (components) | Shared optional features (monitoring, netpol) across teams | Features are always-on, bake into base |
| Directory | Team has plain YAML, no templating | Team needs templating (use Kustomize or Helm) |
| Rollouts | Team needs canary/blue-green with automated analysis | Team is fine with Deployment rolling updates |
| Notifications | Team wants push alerts on sync/health events | Team uses external monitoring (Datadog, Grafana) |
| Sync windows | Production change freeze required | All envs allow continuous deployment |
| Promotion | Multi-env pipeline with gated promotion | Single env, or manual promotion via UI/CLI is sufficient |
| Minimal | Fast onboarding, team will iterate on config later | Production workload needing full guard rails from day one |
