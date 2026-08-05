# Argo Rollouts Reference

## Overview

Argo Rollouts extends Kubernetes with advanced deployment strategies: canary, blue-green, experimentation, and automated analysis. A Rollout replaces a Deployment and manages ReplicaSets with traffic shaping and metric-based promotion.

## Rollout Spec Structure

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: <name>
  namespace: <namespace>
spec:
  replicas: <int>
  revisionHistoryLimit: <int>           # Default: 10
  selector:
    matchLabels: {}
  template:                             # Pod template (identical to Deployment)
    metadata:
      labels: {}
    spec:
      containers: []
  workloadRef:                          # Alternative: reference an existing Deployment
    apiVersion: apps/v1
    kind: Deployment
    name: <deployment-name>
    scaleDown: onsuccess                # When to scale down the Deployment: never, onsuccess, progressively
  strategy:
    canary: {}                          # OR
    blueGreen: {}
  minReadySeconds: <int>
  progressDeadlineSeconds: <int>        # Default: 600
  progressDeadlineAbort: false          # Abort instead of error on deadline
  restartAt: <timestamp>               # Schedule a restart
  analysis: {}                         # Background analysis (runs entire lifecycle)
```

## Canary Strategy

```yaml
strategy:
  canary:
    maxSurge: 1                         # Max pods above desired during update (int or %)
    maxUnavailable: 0                   # Max unavailable pods during update (int or %)
    canaryService: <svc-name>           # Service routing to canary pods
    stableService: <svc-name>           # Service routing to stable pods
    scaleDownDelaySeconds: 30           # Delay before scaling down old RS
    scaleDownDelayRevisionLimit: 2      # Max old RS to keep before delay
    abortScaleDownDelaySeconds: 30      # Delay before scaling down after abort
    dynamicStableScale: false           # Scale stable RS based on traffic weight
    canaryMetadata:                     # Extra metadata for canary pods
      labels: {}
      annotations: {}
    stableMetadata:                     # Extra metadata for stable pods
      labels: {}
      annotations: {}
    steps: []                           # Rollout steps (see below)
    trafficRouting: {}                  # Traffic management (see below)
    analysis: {}                        # Inline analysis (see below)
    antiAffinity: {}                    # Anti-affinity between canary and stable
    pingPong:                           # Ping-pong deployment pattern
      pingService: <svc>
      pongService: <svc>
```

### Canary Steps

```yaml
steps:
  # Set traffic weight
  - setWeight: 10

  # Pause (timed or indefinite)
  - pause: { duration: 5m }            # Timed pause
  - pause: {}                          # Indefinite (manual promote required)

  # Scale canary independently of weight
  - setCanaryScale:
      replicas: 2                      # Exact replica count
      # OR
      weight: 20                       # Percentage of spec.replicas
      matchTrafficWeight: true         # Scale canary to match current traffic weight

  # Run analysis
  - analysis:
      templates:
        - templateName: success-rate
        - templateName: latency-check
          clusterScope: true            # Use ClusterAnalysisTemplate
      args:
        - name: service-name
          value: my-app
        - name: threshold
          value: "0.95"
      dryRun:                           # Run analysis but don't fail rollout
        - metricName: experimental-metric

  # Run experiment
  - experiment:
      duration: 30m
      templates:
        - name: baseline
          specRef: stable
          replicas: 1
        - name: canary
          specRef: canary
          replicas: 1
      analyses:
        - name: compare
          templateName: compare-metrics
          args:
            - name: baseline-hash
              value: '{{templates.baseline.podTemplateHash}}'
            - name: canary-hash
              value: '{{templates.canary.podTemplateHash}}'

  # Set header-based routing (for traffic management that supports it)
  - setHeaderRoute:
      name: smoke-test-header
      match:
        - headerName: X-Canary
          headerValue:
            exact: "true"

  # Set mirror traffic
  - setMirrorRoute:
      name: mirror-traffic
      percentage: 50
      match:
        - method:
            exact: GET
```

## Blue-Green Strategy

```yaml
strategy:
  blueGreen:
    activeService: <active-svc>         # Service pointing to active (live) version
    previewService: <preview-svc>       # Service pointing to preview (new) version
    autoPromotionEnabled: true          # Auto-promote after analysis (default: true)
    autoPromotionSeconds: 60            # Wait N seconds before auto-promotion
    scaleDownDelaySeconds: 30           # Wait before scaling down old version
    scaleDownDelayRevisionLimit: 1      # Max old RS to keep during delay
    abortScaleDownDelaySeconds: 30      # Scale-down delay after abort
    antiAffinity: {}
    activeMetadata:                     # Extra metadata for active pods
      labels: {}
    previewMetadata:                    # Extra metadata for preview pods
      labels: {}

    prePromotionAnalysis:               # Analysis before promoting preview to active
      templates:
        - templateName: smoke-test
      args:
        - name: preview-url
          value: http://preview-svc.ns.svc.cluster.local

    postPromotionAnalysis:              # Analysis after promotion
      templates:
        - templateName: success-rate
      args:
        - name: service-name
          value: my-app
```

**Blue-green flow:**
1. New ReplicaSet created with preview pods
2. `previewService` updated to point to preview pods
3. `prePromotionAnalysis` runs against preview
4. If analysis passes (or `autoPromotionEnabled: true` + `autoPromotionSeconds` elapsed), promote
5. `activeService` switches to new pods
6. `postPromotionAnalysis` runs
7. Old ReplicaSet scales down after `scaleDownDelaySeconds`

## Traffic Management Integrations

### Istio

```yaml
trafficRouting:
  istio:
    virtualServices:
      - name: my-app-vsvc
        routes:
          - primary                     # Route name within VirtualService
    destinationRule:
      name: my-app-destrule
      canarySubsetName: canary
      stableSubsetName: stable
```

Argo Rollouts automatically modifies the VirtualService weight split and DestinationRule subsets.

### AWS ALB Ingress

```yaml
trafficRouting:
  alb:
    ingress: my-app-ingress             # Ingress resource name
    rootService: my-app-root            # Root service (optional)
    servicePort: 443                    # Service port
    annotationPrefix: alb.ingress.kubernetes.io  # Custom prefix (optional)
    stickinessConfig:
      enabled: true
      durationSeconds: 3600
```

### Nginx Ingress

```yaml
trafficRouting:
  nginx:
    stableIngress: my-app-ingress       # Existing Ingress for stable
    additionalIngressAnnotations:       # Annotations for canary Ingress
      canary-by-header: X-Canary
      canary-by-header-value: "true"
    annotationPrefix: nginx.ingress.kubernetes.io
```

### Traefik

```yaml
trafficRouting:
  traefik:
    weightedTraefikServiceName: my-app-traefik  # TraefikService name
```

### SMI (Service Mesh Interface)

```yaml
trafficRouting:
  smi:
    rootService: my-app                 # Root service
    trafficSplitName: my-app-split      # TrafficSplit name
```

## AnalysisTemplate

Defines metrics to evaluate during rollouts:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: <name>
  namespace: <namespace>
spec:
  args:
    - name: <arg-name>
      value: <default-value>            # Optional default
    - name: <arg-name>                  # Required arg (must be provided at runtime)

  metrics:
    - name: <metric-name>
      interval: 60s                     # How often to run the measurement
      count: 10                         # Total measurements to make
      initialDelay: 60s                 # Wait before first measurement
      successCondition: result[0] >= 0.95  # CEL or Go template expression
      failureCondition: result[0] < 0.8
      failureLimit: 3                   # Max failures before analysis fails
      inconclusiveLimit: 3              # Max inconclusive before failing
      consecutiveErrorLimit: 4          # Max consecutive errors
      provider: {}                      # Metric provider (see below)

  dryRun:                               # Run but don't affect rollout decision
    - metricName: <name>

  measurementRetention:                 # How many measurements to keep
    - metricName: <name>
      limit: 10
```

### Metric Providers

#### Prometheus

```yaml
provider:
  prometheus:
    address: http://prometheus.monitoring:9090
    query: |
      sum(rate(http_requests_total{service="{{args.service-name}}", status=~"2.."}[5m]))
      /
      sum(rate(http_requests_total{service="{{args.service-name}}"}[5m]))
    timeout: 30                         # Query timeout in seconds
    insecure: false
    headers:
      - key: Authorization
        value: "Bearer {{args.api-token}}"
```

#### Datadog

```yaml
provider:
  datadog:
    interval: 5m
    query: |
      avg:app.request.error_rate{service:{{args.service-name}}}
    apiVersion: v2
```

#### New Relic

```yaml
provider:
  newRelic:
    profile: default
    query: |
      SELECT percentage(count(*), WHERE httpResponseCode < 500)
      FROM Transaction WHERE appName = '{{args.service-name}}'
```

#### Web (HTTP)

```yaml
provider:
  web:
    url: "https://api.example.com/health/{{args.service-name}}"
    method: GET
    headers:
      - key: Authorization
        value: "Bearer {{args.api-token}}"
    timeoutSeconds: 30
    jsonPath: "{$.healthy}"
    insecure: false
```

#### Job

```yaml
provider:
  job:
    metadata:
      labels:
        app: analysis
    spec:
      backoffLimit: 1
      template:
        spec:
          containers:
            - name: test
              image: curlimages/curl:latest
              command: [sh, -c]
              args:
                - |
                  curl -sf http://{{args.service-name}}/health
          restartPolicy: Never
```

#### Kayenta (Automated Canary Analysis)

```yaml
provider:
  kayenta:
    address: https://kayenta.example.com
    application: my-app
    canaryConfigName: my-canary-config
    metricsAccountName: prometheus
    storageAccountName: s3
    threshold:
      pass: 90
      marginal: 75
    scopes:
      - name: default
        controlScope:
          scope: baseline
        experimentScope:
          scope: canary
```

#### CloudWatch

```yaml
provider:
  cloudWatch:
    interval: 5m
    metricDataQueries:
      - id: error_rate
        metricStat:
          metric:
            namespace: MyApp
            metricName: ErrorRate
            dimensions:
              - name: ServiceName
                value: "{{args.service-name}}"
          period: 300
          stat: Average
```

#### Graphite

```yaml
provider:
  graphite:
    address: http://graphite.monitoring:80
    query: "summarize(stats.my-app.errors, '5min', 'sum')"
```

#### InfluxDB

```yaml
provider:
  influxdb:
    profile: default
    query: |
      from(bucket: "metrics")
        |> range(start: -5m)
        |> filter(fn: (r) => r._measurement == "http_requests" and r.service == "{{args.service-name}}")
```

## ClusterAnalysisTemplate

Cluster-scoped version of AnalysisTemplate. Referenced with `clusterScope: true`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ClusterAnalysisTemplate
metadata:
  name: global-success-rate
spec:
  args:
    - name: service-name
  metrics:
    - name: success-rate
      # ... same as AnalysisTemplate
```

## AnalysisRun

Auto-created by the Rollouts controller when an analysis step executes. Not user-created.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisRun
metadata:
  name: my-app-6cf78b4d5-2-success-rate
  namespace: my-app
  ownerReferences:
    - apiVersion: argoproj.io/v1alpha1
      kind: Rollout
      name: my-app
status:
  phase: Successful                     # Running, Successful, Failed, Error, Inconclusive
  metricResults:
    - name: success-rate
      phase: Successful
      measurements:
        - phase: Successful
          value: "0.98"
          startedAt: "2024-01-01T00:00:00Z"
          finishedAt: "2024-01-01T00:01:00Z"
```

## Experiments

Run side-by-side comparison of versions:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Experiment
metadata:
  name: my-experiment
spec:
  duration: 1h                          # How long to run
  progressDeadlineSeconds: 300
  templates:
    - name: baseline
      specRef: stable                   # Use stable RS template
      replicas: 1
      selector:
        matchLabels:
          app: my-app
          experiment: baseline
      metadata:
        labels:
          app: my-app
          experiment: baseline
    - name: canary
      specRef: canary                   # Use canary RS template
      replicas: 1
      selector:
        matchLabels:
          app: my-app
          experiment: canary
      metadata:
        labels:
          app: my-app
          experiment: canary
  analyses:
    - name: compare
      templateName: compare-latencies
      args:
        - name: baseline-hash
          value: '{{templates.baseline.podTemplateHash}}'
        - name: canary-hash
          value: '{{templates.canary.podTemplateHash}}'
```

## Rollout Commands

```bash
# Promote a paused rollout to next step
kubectl argo rollouts promote my-app

# Full promote (skip all remaining steps)
kubectl argo rollouts promote --full my-app

# Abort a rollout (revert to stable)
kubectl argo rollouts abort my-app

# Retry an aborted rollout
kubectl argo rollouts retry rollout my-app

# Restart (trigger a new rollout with same image)
kubectl argo rollouts restart my-app

# Set image (trigger a new rollout)
kubectl argo rollouts set image my-app my-app=registry.example.com/my-app:v2

# Undo (rollback to previous revision)
kubectl argo rollouts undo my-app

# Watch status
kubectl argo rollouts status my-app --watch

# Get detailed info
kubectl argo rollouts get rollout my-app
```

## Background Analysis

Run analysis for the entire lifecycle of a rollout (not just a single step):

```yaml
spec:
  strategy:
    canary:
      analysis:
        templates:
          - templateName: continuous-success-rate
        args:
          - name: service-name
            value: my-app
        startingStep: 1                 # Start after first step
```

The background analysis runs from `startingStep` until the rollout completes or analysis fails. If it fails, the rollout is aborted.
