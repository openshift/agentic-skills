# Argo Workflows Reference

## Overview

Argo Workflows is a container-native workflow engine for Kubernetes. Each step in a workflow runs as a container in a pod. Workflows support steps (sequential/parallel), DAGs, parameters, artifacts, retries, and scheduling.

## Workflow Spec Structure

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: my-workflow                     # Fixed name (one-shot)
  generateName: my-workflow-            # OR generate unique name (preferred for repeated runs)
  namespace: argo
  labels: {}
  annotations: {}
spec:
  entrypoint: <template-name>          # Required: name of the starting template
  serviceAccountName: <sa>             # ServiceAccount for pod creation
  automountServiceAccountToken: true

  arguments:                            # Workflow-level input parameters and artifacts
    parameters:
      - name: <param-name>
        value: <default-value>
    artifacts: []

  templates: []                         # Template definitions (see below)

  volumes: []                           # Pod-level volumes (available to all templates)
  volumeClaimTemplates: []              # PVC templates (created per workflow)

  ttlStrategy:                          # Auto-delete completed workflows
    secondsAfterCompletion: 3600        # Delete 1h after completion
    secondsAfterSuccess: 1800           # Delete 30m after success
    secondsAfterFailure: 86400          # Keep failures for 24h

  activeDeadlineSeconds: 3600           # Max workflow runtime (ALWAYS SET THIS)
  podGC:                                # Garbage collect completed pods
    strategy: OnPodCompletion           # OnPodCompletion, OnPodSuccess, OnWorkflowCompletion, OnWorkflowSuccess
    deleteDelayDuration: 60s
    labelSelector: {}

  retryStrategy:                        # Global retry strategy
    limit: 3
    retryPolicy: Always                 # Always, OnFailure, OnError, OnTransientError
    backoff:
      duration: 5s
      factor: 2
      maxDuration: 1m

  nodeSelector: {}
  tolerations: []
  affinity: {}
  securityContext: {}
  parallelism: <int>                    # Max parallel pods
  priority: <int>                       # Scheduling priority
  schedulerName: <name>

  onExit: <template-name>              # Exit handler template (runs after workflow completes regardless of status)

  hooks:                                # Lifecycle hooks
    exit:
      template: <template-name>
    running:
      template: <template-name>
      expression: workflow.status == "Running"

  synchronization:                      # Concurrency control
    semaphore:
      configMapKeyRef:
        name: my-semaphore
        key: workflow-limit
    mutex:
      name: my-mutex

  artifactRepositoryRef:
    configMap: artifact-repositories
    key: default

  workflowTemplateRef:                  # Reference a WorkflowTemplate instead of inline templates
    name: <template-name>
    clusterScope: false
```

## Template Types

### Container Template

Runs a single container:

```yaml
templates:
  - name: build
    inputs:
      parameters:
        - name: image-tag
    container:
      image: golang:1.22
      command: [go, build, -o, /output/app, .]
      workingDir: /src
      env:
        - name: GOPROXY
          value: https://proxy.golang.org
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: "2"
          memory: 2Gi
      volumeMounts:
        - name: workdir
          mountPath: /src
    outputs:
      artifacts:
        - name: binary
          path: /output/app
```

### Script Template

Container with an inline script:

```yaml
templates:
  - name: gen-random
    script:
      image: python:3.12-slim
      command: [python]
      source: |
        import random
        result = random.randint(1, 100)
        print(result)
```

The stdout of the script is captured as the template's output result (accessible via `{{steps.<step-name>.outputs.result}}` or `{{tasks.<task-name>.outputs.result}}`).

### Resource Template

Performs CRUD operations on Kubernetes resources:

```yaml
templates:
  - name: create-configmap
    resource:
      action: create                    # create, patch, apply, delete
      manifest: |
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: my-config
          namespace: default
        data:
          key: "{{inputs.parameters.value}}"
      successCondition: status.phase == Succeeded  # For async resources
      failureCondition: status.phase == Failed
```

### Suspend Template

Pauses workflow execution:

```yaml
templates:
  - name: manual-approval
    suspend:
      duration: "0"                     # "0" = indefinite (manual resume)
```

Resume: `argo resume <workflow-name>`

### HTTP Template

Makes HTTP requests:

```yaml
templates:
  - name: call-api
    http:
      url: "https://api.example.com/deploy"
      method: POST
      headers:
        - name: Content-Type
          value: application/json
        - name: Authorization
          value: "Bearer {{inputs.parameters.token}}"
      body: |
        {"version": "{{inputs.parameters.version}}"}
      successCondition: response.statusCode == 200
      timeoutSeconds: 30
```

## Steps-Based Workflows

Sequential steps, with optional parallelism within a step:

```yaml
templates:
  - name: pipeline
    steps:
      - - name: checkout                # Step 1 (sequential)
          template: git-clone
      - - name: test                    # Step 2 (parallel within step)
          template: run-tests
        - name: lint
          template: run-lint
      - - name: build                   # Step 3 (sequential, after step 2 completes)
          template: build-image
          when: "{{steps.test.outputs.result}} == passed"
```

- Each outer list item is a sequential step.
- Each inner list item runs in parallel within that step.
- `when` conditionals control step execution.

## DAG-Based Workflows

Directed acyclic graph with explicit dependencies:

```yaml
templates:
  - name: pipeline
    dag:
      tasks:
        - name: checkout
          template: git-clone
        - name: unit-test
          template: run-tests
          dependencies: [checkout]
        - name: integration-test
          template: run-integration
          dependencies: [checkout]
        - name: lint
          template: run-lint
          dependencies: [checkout]
        - name: build
          template: build-image
          dependencies: [unit-test, lint]
          arguments:
            parameters:
              - name: test-result
                value: "{{tasks.unit-test.outputs.result}}"
        - name: deploy
          template: deploy-app
          dependencies: [build, integration-test]
```

Tasks run as soon as all their dependencies are satisfied. No explicit dependency = runs immediately.

## Parameters

### Workflow-Level Parameters

```yaml
spec:
  arguments:
    parameters:
      - name: environment
        value: staging                   # Default value
      - name: image-tag                  # No default = required at submit time
  entrypoint: main
  templates:
    - name: main
      container:
        image: my-app:{{workflow.parameters.image-tag}}
        env:
          - name: ENV
            value: "{{workflow.parameters.environment}}"
```

Submit with parameters: `argo submit workflow.yaml -p environment=production -p image-tag=v2.0`

### Template-Level Parameters

```yaml
templates:
  - name: deploy
    inputs:
      parameters:
        - name: env
        - name: replicas
          default: "3"
    container:
      image: kubectl:latest
      command: [sh, -c]
      args:
        - kubectl scale deployment my-app --replicas={{inputs.parameters.replicas}} -n {{inputs.parameters.env}}
```

### Output Parameters

```yaml
templates:
  - name: get-version
    container:
      image: alpine:latest
      command: [sh, -c]
      args:
        - echo "v2.1.0" > /tmp/version.txt
    outputs:
      parameters:
        - name: version
          valueFrom:
            path: /tmp/version.txt
            default: "unknown"
```

Access: `{{steps.get-version.outputs.parameters.version}}` or `{{tasks.get-version.outputs.parameters.version}}`

## Artifacts

### S3

```yaml
templates:
  - name: produce-artifact
    outputs:
      artifacts:
        - name: report
          path: /tmp/report.html
          s3:
            endpoint: s3.amazonaws.com
            bucket: my-bucket
            key: reports/{{workflow.uid}}/report.html
            accessKeySecret:
              name: s3-credentials
              key: accessKey
            secretKeySecret:
              name: s3-credentials
              key: secretKey
```

### GCS

```yaml
artifacts:
  - name: data
    path: /data/output
    gcs:
      bucket: my-bucket
      key: data/{{workflow.uid}}/output
      serviceAccountKeySecret:
        name: gcs-credentials
        key: serviceAccountKey
```

### Git

```yaml
artifacts:
  - name: source
    path: /src
    git:
      repo: https://github.com/org/repo.git
      revision: main
      usernameSecret:
        name: git-creds
        key: username
      passwordSecret:
        name: git-creds
        key: password
```

### Raw

```yaml
artifacts:
  - name: config
    path: /config/app.yaml
    raw:
      data: |
        server:
          port: 8080
          host: 0.0.0.0
```

## Volume-Based Workflows

### PVC Template

```yaml
spec:
  volumeClaimTemplates:
    - metadata:
        name: workdir
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 5Gi
        storageClassName: standard

  templates:
    - name: step1
      container:
        image: alpine
        command: [sh, -c]
        args: ["echo 'data' > /mnt/data.txt"]
        volumeMounts:
          - name: workdir
            mountPath: /mnt
    - name: step2
      container:
        image: alpine
        command: [cat, /mnt/data.txt]
        volumeMounts:
          - name: workdir
            mountPath: /mnt
```

### EmptyDir

```yaml
spec:
  volumes:
    - name: shared
      emptyDir: {}
  templates:
    - name: step
      container:
        volumeMounts:
          - name: shared
            mountPath: /shared
```

## Resource Limits and Lifecycle

```yaml
spec:
  activeDeadlineSeconds: 7200           # Max 2 hours for entire workflow
  templates:
    - name: step
      activeDeadlineSeconds: 600        # Max 10 min for this template
      retryStrategy:
        limit: 3
        retryPolicy: OnFailure          # Always, OnFailure, OnError, OnTransientError
        backoff:
          duration: 10s
          factor: 2
          maxDuration: 5m
        affinity:
          nodeAntiAffinity: {}          # Retry on different node
      timeout: 300s                     # Template timeout
      container:
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: "1"
            memory: 1Gi
```

## WorkflowTemplate References

### Namespace-Scoped

```yaml
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
metadata:
  name: ci-template
  namespace: argo
spec:
  arguments:
    parameters:
      - name: repo
  entrypoint: main
  templates:
    - name: main
      dag:
        tasks:
          - name: build
            template: build-step
    - name: build-step
      container:
        image: golang:1.22
        command: [go, build]
```

Reference from a Workflow:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: ci-run-
spec:
  workflowTemplateRef:
    name: ci-template
  arguments:
    parameters:
      - name: repo
        value: https://github.com/org/app.git
```

Or reference individual templates:

```yaml
templates:
  - name: main
    steps:
      - - name: build
          templateRef:
            name: ci-template
            template: build-step
            clusterScope: false
```

### Cluster-Scoped

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ClusterWorkflowTemplate
metadata:
  name: shared-ci-template
spec:
  templates:
    - name: build
      # ...
```

Reference with `clusterScope: true`.

## CronWorkflow

```yaml
apiVersion: argoproj.io/v1alpha1
kind: CronWorkflow
metadata:
  name: nightly-cleanup
  namespace: argo
spec:
  schedule: "0 2 * * *"                 # Cron expression (daily at 2am)
  timezone: America/New_York            # Optional timezone
  concurrencyPolicy: Replace            # Allow, Forbid, Replace
  startingDeadlineSeconds: 60           # Max seconds after missed schedule
  successfulJobsHistoryLimit: 3         # Completed workflows to keep
  failedJobsHistoryLimit: 3             # Failed workflows to keep
  suspend: false                        # Pause scheduling

  workflowSpec:                         # Inline workflow spec
    entrypoint: cleanup
    activeDeadlineSeconds: 3600
    templates:
      - name: cleanup
        container:
          image: my-cleanup:latest
          command: [/cleanup.sh]

  # OR reference a WorkflowTemplate
  workflowSpec:
    workflowTemplateRef:
      name: cleanup-template
```

## Suspend/Resume, Stop/Terminate

```bash
# Suspend a running workflow (pauses at next node boundary)
argo suspend my-workflow

# Resume a suspended workflow
argo resume my-workflow

# Stop a workflow (finish running nodes, then mark Failed)
argo stop my-workflow --message "stopping for maintenance"

# Terminate a workflow (kill running nodes immediately)
argo terminate my-workflow
```

## Archive and Garbage Collection

### Workflow Archive (PostgreSQL/MySQL)

Configured in the Workflow Controller ConfigMap:

```yaml
persistence:
  archive: true
  postgresql:
    host: postgres.argo
    port: 5432
    database: argo
    tableName: argo_workflows
    userNameSecret:
      name: argo-postgres
      key: username
    passwordSecret:
      name: argo-postgres
      key: password
```

### Garbage Collection

```yaml
# Per-workflow TTL
spec:
  ttlStrategy:
    secondsAfterCompletion: 3600
    secondsAfterSuccess: 600
    secondsAfterFailure: 86400

# Controller-level default
workflowDefaults:
  spec:
    ttlStrategy:
      secondsAfterCompletion: 86400
    podGC:
      strategy: OnPodSuccess
```

## Workflow-of-Workflows Pattern

A parent workflow creates child workflows using the resource template:

```yaml
templates:
  - name: orchestrator
    dag:
      tasks:
        - name: run-etl
          template: submit-workflow
          arguments:
            parameters:
              - name: workflow-template
                value: etl-workflow
        - name: run-ml
          template: submit-workflow
          dependencies: [run-etl]
          arguments:
            parameters:
              - name: workflow-template
                value: ml-workflow

  - name: submit-workflow
    inputs:
      parameters:
        - name: workflow-template
    resource:
      action: create
      manifest: |
        apiVersion: argoproj.io/v1alpha1
        kind: Workflow
        metadata:
          generateName: child-
        spec:
          workflowTemplateRef:
            name: {{inputs.parameters.workflow-template}}
      successCondition: status.phase == Succeeded
      failureCondition: status.phase in (Failed, Error)
```

The parent workflow waits for each child workflow to complete before continuing.

## Common Variables

| Variable | Description |
|----------|-------------|
| `{{workflow.name}}` | Workflow name |
| `{{workflow.namespace}}` | Workflow namespace |
| `{{workflow.uid}}` | Workflow UID |
| `{{workflow.parameters.<name>}}` | Workflow-level parameter |
| `{{workflow.status}}` | Workflow status |
| `{{steps.<step>.outputs.result}}` | Step output (script stdout) |
| `{{steps.<step>.outputs.parameters.<name>}}` | Step output parameter |
| `{{tasks.<task>.outputs.result}}` | DAG task output |
| `{{tasks.<task>.outputs.parameters.<name>}}` | DAG task output parameter |
| `{{inputs.parameters.<name>}}` | Template input parameter |
| `{{inputs.artifacts.<name>.path}}` | Input artifact mount path |
| `{{pod.name}}` | Current pod name |
| `{{retries}}` | Current retry count |
