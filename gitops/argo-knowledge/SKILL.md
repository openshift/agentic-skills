---
name: argo-knowledge
description: >
  Comprehensive knowledge base for the Argo ecosystem including Argo CD, Argo Rollouts,
  Argo Workflows, and Argo Events. Use this skill when generating, reviewing, debugging,
  or explaining Argo CRDs (Application, ApplicationSet, AppProject, Rollout, AnalysisTemplate,
  Workflow, WorkflowTemplate, CronWorkflow, EventSource, Sensor, EventBus), configuring
  notifications, image updater, sync policies, progressive delivery strategies, or
  designing GitOps repository patterns. Also use when the user asks about Argo best practices,
  common mistakes, or needs to choose between Argo approaches (e.g., app-of-apps vs
  ApplicationSet, canary vs blue-green, steps vs DAG workflows).
license: MIT
---

# Argo Knowledge Base

## Rules

1. **Always use correct apiVersion and kind.** Every Argo CRD uses `apiVersion: argoproj.io/v1alpha1`. Never invent CRDs or apiVersions that do not exist.
2. **Load references on-demand.** Only read reference files when the user's question requires detailed field-level knowledge. Do not preload all references.
3. **Max 1-2 reference files per question.** Keep context focused. If a question spans more than two reference areas, answer the primary question first and offer to elaborate.
4. **Validate YAML before presenting.** Every YAML example must be syntactically valid and use real field names from the Argo CRD schemas.
5. **Prefer canonical patterns.** Use the numbered patterns below as starting points. Adapt to the user's specifics rather than inventing from scratch.
6. **State trade-offs.** When recommending an approach, briefly note what you give up.

## What is Argo

The Argo project is a set of Kubernetes-native tools for running and managing jobs and applications on Kubernetes.

- **Argo CD** — Declarative GitOps continuous delivery. Watches Git repos and syncs Kubernetes resources to match the desired state. Supports Helm, Kustomize, plain YAML, Jsonnet, and plugin-based config management tools. Provides a UI, CLI, and API for managing applications across multiple clusters.

- **Argo Rollouts** — Progressive delivery controller. Extends Kubernetes Deployments with canary releases, blue-green deployments, experimentation, and automated analysis-driven promotion/rollback. Integrates with service meshes and ingress controllers for traffic management.

- **Argo Workflows** — Container-native workflow engine for Kubernetes. Runs DAG and step-based workflows where each step is a container. Used for CI/CD pipelines, data processing, ML pipelines, and infrastructure automation.

- **Argo Events** — Event-driven workflow automation. Connects external event sources (webhooks, message queues, cloud events, cron schedules) to triggers that create Argo Workflows or any Kubernetes resource.

**How they relate:** Argo CD deploys your applications via GitOps. Argo Rollouts handles the progressive delivery strategy during those deployments. Argo Workflows orchestrates complex multi-step jobs. Argo Events wires external events to trigger Workflows or other actions. Together they form a complete GitOps + progressive delivery + automation platform.

## CRD Table

| Kind | apiVersion | Project | Purpose |
|------|-----------|---------|---------|
| Application | argoproj.io/v1alpha1 | Argo CD | Defines a single application to sync from Git to a cluster |
| AppProject | argoproj.io/v1alpha1 | Argo CD | RBAC boundary: restricts sources, destinations, and resources |
| ApplicationSet | argoproj.io/v1alpha1 | Argo CD | Generates multiple Applications from templates + generators |
| Rollout | argoproj.io/v1alpha1 | Rollouts | Progressive delivery replacement for Deployment |
| AnalysisTemplate | argoproj.io/v1alpha1 | Rollouts | Defines metric queries for automated rollout analysis |
| ClusterAnalysisTemplate | argoproj.io/v1alpha1 | Rollouts | Cluster-scoped AnalysisTemplate |
| AnalysisRun | argoproj.io/v1alpha1 | Rollouts | Instance of an AnalysisTemplate execution (auto-created) |
| Experiment | argoproj.io/v1alpha1 | Rollouts | Runs multiple ReplicaSet versions simultaneously for comparison |
| Workflow | argoproj.io/v1alpha1 | Workflows | A single workflow execution |
| WorkflowTemplate | argoproj.io/v1alpha1 | Workflows | Reusable workflow definition (namespace-scoped) |
| ClusterWorkflowTemplate | argoproj.io/v1alpha1 | Workflows | Reusable workflow definition (cluster-scoped) |
| CronWorkflow | argoproj.io/v1alpha1 | Workflows | Scheduled workflow execution |
| EventSource | argoproj.io/v1alpha1 | Events | Defines external event sources to consume |
| EventBus | argoproj.io/v1alpha1 | Events | Message transport layer between EventSources and Sensors |
| Sensor | argoproj.io/v1alpha1 | Events | Listens to EventBus, applies filters, fires triggers |

## How Argo CD Works

### Sync Loop

1. **Desired state:** Argo CD reads manifests from a Git repo (source). The source can be Helm charts, Kustomize overlays, plain YAML directories, Jsonnet, or custom config management plugins.
2. **Live state:** Argo CD queries the target Kubernetes cluster (destination) for the current state of resources it manages.
3. **Diff:** Argo CD compares desired vs live state. Resources that differ are marked `OutOfSync`.
4. **Sync:** When triggered (manually or via automated sync policy), Argo CD applies the desired state to the cluster using `kubectl apply`, server-side apply, or `kubectl create/replace` depending on sync options.
5. **Health assessment:** After sync, Argo CD evaluates resource health using built-in health checks (Deployments, StatefulSets, Services, Ingresses, etc.) and custom health checks (Lua scripts in `argocd-cm`). Resources are marked Healthy, Progressing, Degraded, Suspended, or Missing.

### Resource Tracking

Argo CD tracks which resources belong to an Application using one of three methods:

- **`label`** — Adds `app.kubernetes.io/instance: <app-name>` label. Simple but can conflict with other tools using this label.
- **`annotation`** — Adds `argocd.argoproj.io/tracking-id` annotation. Avoids label conflicts. Default in modern Argo CD.
- **`annotation+label`** — Uses both. Maximum compatibility.

Configured via `resource.trackingMethod` in `argocd-cm` ConfigMap.

### Multi-Cluster

Argo CD manages applications across multiple clusters from a single control plane:

- The cluster running Argo CD is the **in-cluster** target (referenced as `https://kubernetes.default.svc`).
- External clusters are added via `argocd cluster add <context-name>`, which creates a ServiceAccount + ClusterRoleBinding on the target cluster and stores credentials as a Secret in the Argo CD namespace.
- Cluster Secrets have label `argocd.argoproj.io/secret-type: cluster` and contain `server`, `name`, `config` (with `bearerToken`, `tlsClientConfig`).

## Decision Trees

### Application vs ApplicationSet

Use **Application** when:
- You have a single application or a small, fixed number of applications
- Each application has unique configuration that doesn't follow a pattern
- You want direct, explicit control over each application

Use **ApplicationSet** when:
- You need to generate many Applications from a pattern (e.g., per-directory, per-cluster, per-team)
- Applications share a common template with parameterized differences
- You want Applications auto-created/deleted when directories or clusters appear/disappear
- You need progressive rollout across environments (rollingSync)

### Rollout vs Deployment

Use **Deployment** when:
- You want simple rolling updates
- You don't need traffic shaping, analysis, or manual promotion gates
- The application is non-critical or internal-only

Use **Rollout** when:
- You need canary or blue-green deployment strategies
- You want automated analysis (metrics-based promotion/rollback)
- You need traffic percentage control via service mesh or ingress
- You need manual approval gates between rollout steps
- You want experiment-based A/B testing

### Which ApplicationSet Generator

- **Git directory** — One Application per directory in a monorepo. Best for: environments or services organized as directories.
- **Git file** — One Application per JSON/YAML config file in a repo. Best for: externalized app configs with arbitrary fields.
- **List** — Explicitly enumerated Applications. Best for: small, fixed sets with no dynamic discovery.
- **Cluster** — One Application per registered Argo CD cluster. Best for: deploying the same app to all clusters matching a selector.
- **Matrix** — Cartesian product of two generators. Best for: deploy N apps to M clusters.
- **Merge** — Combine generator outputs, overriding fields from a secondary generator. Best for: cluster-specific overrides on top of a base config.
- **Pull request** — One Application per open PR. Best for: PR preview environments.
- **SCM provider** — One Application per repo in a GitHub org or GitLab group. Best for: auto-onboarding repos.

## Canonical YAML Patterns

### Pattern 1: Application with Helm Source

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

### Pattern 2: Application with Kustomize Source

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

### Pattern 3: ApplicationSet with Git Directory Generator

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

### Pattern 4: ApplicationSet with Cluster Generator + Matrix

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
  preserveResourcesOnDeletion: true
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

### Pattern 5: Rollout with Canary Strategy + AnalysisTemplate

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

### Pattern 6: Rollout with Blue-Green Strategy

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

### Pattern 7: Workflow DAG Pattern

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: ci-pipeline-
  namespace: argo
spec:
  entrypoint: ci-pipeline
  serviceAccountName: argo-workflow
  arguments:
    parameters:
      - name: repo-url
        value: https://github.com/org/my-app.git
      - name: revision
        value: main
      - name: image
        value: registry.example.com/my-app
  templates:
    - name: ci-pipeline
      dag:
        tasks:
          - name: checkout
            template: git-clone
            arguments:
              parameters:
                - name: repo-url
                  value: '{{workflow.parameters.repo-url}}'
                - name: revision
                  value: '{{workflow.parameters.revision}}'
          - name: unit-test
            template: run-tests
            dependencies:
              - checkout
          - name: lint
            template: run-lint
            dependencies:
              - checkout
          - name: build-image
            template: build-push
            dependencies:
              - unit-test
              - lint
            arguments:
              parameters:
                - name: image
                  value: '{{workflow.parameters.image}}'
    - name: git-clone
      inputs:
        parameters:
          - name: repo-url
          - name: revision
      container:
        image: alpine/git:latest
        command: [sh, -c]
        args:
          - git clone --branch {{inputs.parameters.revision}} {{inputs.parameters.repo-url}} /work
        volumeMounts:
          - name: work
            mountPath: /work
    - name: run-tests
      container:
        image: golang:1.22
        command: [sh, -c]
        args:
          - cd /work && go test ./...
        volumeMounts:
          - name: work
            mountPath: /work
    - name: run-lint
      container:
        image: golangci/golangci-lint:latest
        command: [sh, -c]
        args:
          - cd /work && golangci-lint run
        volumeMounts:
          - name: work
            mountPath: /work
    - name: build-push
      inputs:
        parameters:
          - name: image
      container:
        image: gcr.io/kaniko-project/executor:latest
        args:
          - --context=/work
          - --destination={{inputs.parameters.image}}:{{workflow.uid}}
        volumeMounts:
          - name: work
            mountPath: /work
  volumeClaimTemplates:
    - metadata:
        name: work
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 1Gi
```

### Pattern 8: EventSource + Sensor Triggering a Workflow

```yaml
apiVersion: argoproj.io/v1alpha1
kind: EventSource
metadata:
  name: github-webhook
  namespace: argo-events
spec:
  service:
    ports:
      - port: 12000
        targetPort: 12000
  github:
    push-events:
      repositories:
        - owner: my-org
          names:
            - my-app
      webhook:
        endpoint: /push
        port: "12000"
        method: POST
      events:
        - push
      apiToken:
        name: github-token
        key: token
      webhookSecret:
        name: github-token
        key: webhook-secret
      contentType: json
      active: true
---
apiVersion: argoproj.io/v1alpha1
kind: EventBus
metadata:
  name: default
  namespace: argo-events
spec:
  jetstream:
    version: latest
    replicas: 3
    persistence:
      storageClassName: standard
      accessMode: ReadWriteOnce
      volumeSize: 20Gi
---
apiVersion: argoproj.io/v1alpha1
kind: Sensor
metadata:
  name: github-sensor
  namespace: argo-events
spec:
  dependencies:
    - name: github-push
      eventSourceName: github-webhook
      eventName: push-events
      filters:
        data:
          - path: body.ref
            type: string
            value:
              - refs/heads/main
  triggers:
    - template:
        name: trigger-ci
        argoWorkflow:
          operation: submit
          source:
            resource:
              apiVersion: argoproj.io/v1alpha1
              kind: Workflow
              metadata:
                generateName: ci-triggered-
                namespace: argo
              spec:
                entrypoint: build
                arguments:
                  parameters:
                    - name: repo-url
                    - name: revision
                templates:
                  - name: build
                    container:
                      image: golang:1.22
                      command: [sh, -c]
                      args:
                        - |
                          echo "Building {{workflow.parameters.repo-url}} at {{workflow.parameters.revision}}"
          parameters:
            - src:
                dependencyName: github-push
                dataKey: body.repository.clone_url
              dest: spec.arguments.parameters.0.value
            - src:
                dependencyName: github-push
                dataKey: body.after
              dest: spec.arguments.parameters.1.value
```

### Pattern 9: Notifications Config (argocd-notifications-cm)

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

### Pattern 10: Image Updater Annotations

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
    argocd-image-updater.argoproj.io/myapp.helm.image-name: image.repository
    argocd-image-updater.argoproj.io/myapp.helm.image-tag: image.tag
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

## Common Mistakes

1. **Missing `namespace: argocd` on Application metadata.** Applications must live in the Argo CD namespace (or a namespace explicitly allowed via `--application-namespaces`). Omitting this causes Argo CD to never see the Application.

2. **Using `helm.values` (string) instead of `helm.valuesObject` (map).** `helm.values` is a multiline YAML string which is error-prone. `helm.valuesObject` is a structured map and should be preferred.

3. **Setting `automated.prune: true` without understanding consequences.** This deletes resources from the cluster that are no longer in Git. If you accidentally remove a manifest from Git, prune will delete the live resource. Use `prune: false` until you trust the workflow, or use `preserveResourcesOnDeletion` on ApplicationSets.

4. **Forgetting `CreateNamespace=true` sync option.** Argo CD does not create namespaces by default. Without this option, syncing to a non-existent namespace fails.

5. **Using `targetRevision: HEAD` in production.** This follows the default branch and makes deployments unpredictable. Pin to a specific tag, commit SHA, or semver range.

6. **Rollout without matching Services.** Canary and blue-green strategies require correctly configured `stableService` and `canaryService`/`previewService`. Forgetting these Services causes traffic routing failures.

7. **AnalysisTemplate with no `count` or `interval`.** Without these, the analysis runs once and completes immediately, which is rarely useful. Set `count` and `interval` for continuous monitoring during rollout.

8. **ApplicationSet with `goTemplate: true` but using `{{name}}` syntax.** Go templates use `{{.name}}`, not `{{name}}` (which is fasttemplate syntax). Mixing them produces empty strings silently.

9. **EventSource and Sensor in different namespaces without cross-namespace EventBus config.** They must reference the same EventBus. By default, they look for an EventBus named `default` in their own namespace.

10. **Workflow `activeDeadlineSeconds` not set.** Without a deadline, stuck workflows run forever, consuming cluster resources. Always set a reasonable deadline.

11. **Notification trigger `when` expression referencing wrong fields.** Common mistake: `app.status.sync.status` vs `app.status.operationState.phase`. Sync status is Synced/OutOfSync. Operation phase is Succeeded/Failed/Error/Running.

12. **Image updater `write-back-method: git` without write access.** The image updater needs push access to the Git repo. Without it, updates silently fail. Check the image updater logs.

## Reference Index

| Topic | Reference File | When to Load |
|-------|---------------|-------------|
| Application spec, sync policies, sync waves, health checks, ignore differences, multi-cluster | `references/applications.md` | Questions about Application configuration, sync behavior, health, or multi-cluster |
| ApplicationSet generators, templates, progressive syncs | `references/applicationsets.md` | Questions about ApplicationSet generators, templating, or progressive rollout |
| AppProject RBAC, source/destination restrictions, sync windows | `references/app-projects.md` | Questions about RBAC, project policies, sync windows |
| Rollout canary/blue-green, traffic management, AnalysisTemplate, experiments | `references/rollouts.md` | Questions about progressive delivery, canary/blue-green, analysis metrics |
| Workflow DAG/steps, parameters, artifacts, CronWorkflow | `references/workflows.md` | Questions about workflow orchestration, scheduling, parameters |
| EventSource types, EventBus, Sensor triggers, filters | `references/events.md` | Questions about event-driven automation |
| Notification services, templates, triggers, subscriptions | `references/notifications.md` | Questions about alerting and notifications |
| Image updater annotations, strategies, write-back | `references/image-updater.md` | Questions about automated image updates |
| App-of-apps, monorepo, multi-repo patterns | `references/repo-patterns.md` | Questions about repository structure and GitOps patterns |
| Sync policy, RBAC, health checks, secret management | `references/best-practices.md` | General architecture and operational best practices |
| Agent mode, principal/agent architecture, managed/autonomous modes, hub-and-spoke | `references/agent-mode.md` | Questions about argocd-agent, multi-cluster at scale, air-gapped, edge deployments |
| Applications in any namespace, multi-instance, multi-tenancy, Autopilot | `references/multi-tenancy.md` | Questions about multi-tenancy, team isolation, --application-namespaces, Autopilot bootstrap |
| OpenShift GitOps Operator, ArgoCD CRD, Routes, SCCs, OAuth, managed namespaces | `references/openshift.md` | Questions about running Argo on OpenShift, operator-managed instances, OpenShift-specific patterns |
| GitOps Promoter, PromotionStrategy, environment promotion, commit status gating | `references/gitops-promoter.md` | Questions about environment promotion, PR-based gating, branch-per-environment, gitops-promoter CRDs |
