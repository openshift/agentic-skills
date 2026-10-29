<!-- Loaded on demand by skills/gitops/argo-knowledge/SKILL.md. Each pattern is a validated
     starting point — adapt to the user's specifics rather than pasting verbatim. -->

# Canonical YAML Patterns

Nine validated starting points covering Argo CD and Argo Rollouts as shipped by
OpenShift GitOps. Every manifest uses
`apiVersion: argoproj.io/v1alpha1` and real field names from the Argo CRD schemas.

| # | Pattern | Project |
|---|---------|---------|
| 1 | Application with Helm source | Argo CD |
| 2 | Application with Kustomize source | Argo CD |
| 3 | ApplicationSet with git directory generator | Argo CD |
| 4 | ApplicationSet with cluster generator + matrix | Argo CD |
| 5 | Rollout with canary strategy + AnalysisTemplate | Rollouts |
| 6 | Rollout with blue-green strategy | Rollouts |
| 7 | Notifications config (`argocd-notifications-cm`) | Argo CD |
| 8 | Image updater annotations | Argo CD |
| 9 | Multi-source Application (chart + external values) | Argo CD |

## Pattern 1: Application with Helm Source

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
          tag: latest
        ingress:
          enabled: true
          hosts:
            - my-app.example.com
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

## Pattern 2: Application with Kustomize Source

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

## Pattern 3: ApplicationSet with Git Directory Generator

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
  syncPolicy:
    # NOTE: preserveResourcesOnDeletion lives under spec.syncPolicy, NOT at spec level.
    # At spec level the API server silently prunes it and you lose the protection.
    preserveResourcesOnDeletion: true
  template:
    metadata:
      name: 'addon-{{.path.basename}}'
      labels:
        envLabel: staging
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

## Pattern 4: ApplicationSet with Cluster Generator + Matrix

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: platform-services
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  syncPolicy:
    preserveResourcesOnDeletion: true   # under syncPolicy — not at spec level
  generators:
    - matrix:
        generators:
          - clusters:
              selector:
                matchLabels:
                  tier: production
              values:
                revision: main
          - list:
              elements:
                - app: ingress-nginx
                  namespace: ingress-nginx
                  path: platform/ingress-nginx
                - app: cert-manager
                  namespace: cert-manager
                  path: platform/cert-manager
                - app: monitoring
                  namespace: monitoring
                  path: platform/monitoring
  template:
    metadata:
      name: '{{.name}}-{{.app}}'
    spec:
      project: platform
      source:
        repoURL: https://github.com/org/platform-config.git
        targetRevision: '{{.values.revision}}'
        path: '{{.path}}'
      destination:
        server: '{{.server}}'
        namespace: '{{.namespace}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - ServerSideApply=true
```

## Pattern 5: Rollout with Canary Strategy + AnalysisTemplate

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
  namespace: my-app
spec:
  replicas: 5
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
        - name: my-app
          image: registry.example.com/my-app:v2.0.0
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
      maxSurge: 1
      maxUnavailable: 0
      steps:
        - setWeight: 10
        - pause: { duration: 2m }
        - setWeight: 30
        - analysis:
            templates:
              - templateName: success-rate
            args:
              - name: service-name
                value: my-app
        - setWeight: 60
        - pause: { duration: 5m }
        - setWeight: 100
      canaryService: my-app-canary
      stableService: my-app-stable
      trafficRouting:
        istio:
          virtualServices:
            - name: my-app-vsvc
              routes:
                - primary
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
  namespace: my-app
spec:
  args:
    - name: service-name
  metrics:
    - name: success-rate
      interval: 60s
      count: 5
      successCondition: result[0] >= 0.95
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(http_requests_total{service="{{args.service-name}}", status=~"2.."}[5m]))
            /
            sum(rate(http_requests_total{service="{{args.service-name}}"}[5m]))
```

## Pattern 6: Rollout with Blue-Green Strategy

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
  namespace: my-app
spec:
  replicas: 3
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
        - name: my-app
          image: registry.example.com/my-app:v2.0.0
          ports:
            - containerPort: 8080
  strategy:
    blueGreen:
      activeService: my-app-active
      previewService: my-app-preview
      autoPromotionEnabled: false
      scaleDownDelaySeconds: 30
      prePromotionAnalysis:
        templates:
          - templateName: smoke-test
        args:
          - name: preview-url
            value: http://my-app-preview.my-app.svc.cluster.local
      postPromotionAnalysis:
        templates:
          - templateName: success-rate
        args:
          - name: service-name
            value: my-app
```

## Pattern 7: Notifications Config (argocd-notifications-cm)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.slack: |
    token: $slack-token
    signingSecret: $slack-signing-secret
  template.app-sync-succeeded: |
    message: |
      Application {{.app.metadata.name}} has been successfully synced.
      Revision: {{.app.status.sync.revision}}
      Project: {{.app.spec.project}}
    slack:
      attachments: |
        [{
          "color": "#18be52",
          "title": "{{.app.metadata.name}} synced",
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}",
          "fields": [
            {"title": "Project", "value": "{{.app.spec.project}}", "short": true},
            {"title": "Revision", "value": "{{.app.status.sync.revision | trunc 7}}", "short": true}
          ]
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
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}",
          "fields": [
            {"title": "Project", "value": "{{.app.spec.project}}", "short": true},
            {"title": "Error", "value": "{{.app.status.operationState.message}}", "short": false}
          ]
        }]
  template.app-health-degraded: |
    message: |
      Application {{.app.metadata.name}} is degraded.
    slack:
      attachments: |
        [{
          "color": "#f4c030",
          "title": "{{.app.metadata.name}} degraded",
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"
        }]
  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [app-sync-succeeded]
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send: [app-sync-failed]
  trigger.on-health-degraded: |
    - when: app.status.health.status == 'Degraded'
      send: [app-health-degraded]
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: argocd
type: Opaque
stringData:
  slack-token: xoxb-XXXXXXXXX
  slack-signing-secret: XXXXXXXXX
```

**Application annotation to subscribe:**

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.slack: my-channel
    notifications.argoproj.io/subscribe.on-health-degraded.slack: my-channel
    notifications.argoproj.io/subscribe.on-sync-succeeded.slack: deployments
```

## Pattern 8: Image Updater Annotations

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
  annotations:
    argocd-image-updater.argoproj.io/image-list: myapp=registry.example.com/my-app
    argocd-image-updater.argoproj.io/myapp.update-strategy: semver
    argocd-image-updater.argoproj.io/myapp.allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"
    argocd-image-updater.argoproj.io/myapp.ignore-tags: "latest,dev-*"
    argocd-image-updater.argoproj.io/myapp.pull-secret: pullsecret:argocd/registry-creds
    argocd-image-updater.argoproj.io/write-back-method: git
    argocd-image-updater.argoproj.io/write-back-target: kustomization
    argocd-image-updater.argoproj.io/git-branch: main
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-configs.git
    targetRevision: main
    path: apps/my-app/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Match the write-back target to the source type.** The example above is a Kustomize
overlay, so it uses `write-back-target: kustomization`. For a **Helm** source, drop that
annotation and point the updater at the chart's value keys instead:

```yaml
    argocd-image-updater.argoproj.io/myapp.helm.image-name: image.repository
    argocd-image-updater.argoproj.io/myapp.helm.image-tag: image.tag
    argocd-image-updater.argoproj.io/write-back-method: git
    argocd-image-updater.argoproj.io/write-back-target: helmvalues:./values.yaml
```

The `helm.image-name`/`helm.image-tag` annotations are silently ignored on a Kustomize
source, and `write-back-target: kustomization` is ignored on a Helm source — mixing them
produces an updater that appears configured but never writes anything back.

## Pattern 9: Multi-Source Application (Helm chart + external values)

GA since v2.6. Use `spec.sources[]` (plural) — **not** `spec.source` — when a chart lives
in one repo and its values live in another. This is the canonical shape for "chart from a
registry, config from our GitOps repo".

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: webapp
  namespace: argocd
spec:
  project: default
  sources:
    # 1. The chart. For an OCI registry the oci:// scheme is OMITTED from repoURL —
    #    it is implied by enableOCI: "true" on the repository Secret.
    - repoURL: registry.example.com/charts
      chart: webapp
      targetRevision: 2.*                 # semver constraint
      helm:
        releaseName: webapp
        valueFiles:
          - $values/envs/production/values.yaml   # $values resolves to the ref below
    # 2. The values repo, exposed to the chart source as $values
    - repoURL: https://github.com/org/config.git
      targetRevision: main
      ref: values                         # defines $values; no `path` needed for a pure ref
  destination:
    server: https://kubernetes.default.svc
    namespace: webapp-prod
  syncPolicy:
    automated:
      selfHeal: true
      prune: false
    syncOptions:
      - ServerSideApply=true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas                  # HPA owns replica count
```

**The three things that go wrong here:**

1. **Using `spec.source` (singular) with a list.** Multi-source requires the `sources`
   array. The singular field silently takes only one source.
2. **Putting `oci://` in `repoURL`.** Per the Argo CD docs, *"the `oci://` syntax is not
   included"* — register the repo with `enableOCI: "true"` instead.
3. **Referencing `$values` without a `ref` on the other source.** The `ref` name is what
   `$values` resolves to; without it the path is treated as literal and the chart renders
   with defaults rather than failing loudly.

A source used purely as a `ref` target does not need a `path` — it is mounted so other
sources can read files out of it.
