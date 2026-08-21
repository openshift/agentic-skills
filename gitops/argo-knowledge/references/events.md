# Argo Events Reference

## Architecture

Argo Events has three core components:

1. **EventSource** — Consumes events from external systems and publishes them to the EventBus
2. **EventBus** — Message transport layer (NATS JetStream or Kafka)
3. **Sensor** — Subscribes to EventBus, applies filters/transforms, and fires triggers

Flow: External Event -> EventSource -> EventBus -> Sensor -> Trigger Action

## EventSource

```yaml
apiVersion: argoproj.io/v1alpha1
kind: EventSource
metadata:
  name: <name>
  namespace: <namespace>
spec:
  eventBusName: default                 # EventBus to publish to (default: "default")
  replicas: 1                           # Number of EventSource pods
  service:                              # Service config for webhook-based sources
    ports:
      - port: 12000
        targetPort: 12000
  template:                             # Pod template overrides
    metadata:
      labels: {}
    spec:
      containers:
        - resources: {}
      serviceAccountName: <sa>
      tolerations: []
      nodeSelector: {}

  # Event source type configs (one or more):
  <source-type>:
    <event-name>:
      # source-specific config
```

### EventSource Types

#### Webhook

```yaml
spec:
  webhook:
    deploy-hook:
      endpoint: /deploy
      port: "12000"
      method: POST
```

#### GitHub

```yaml
spec:
  github:
    push-events:
      repositories:
        - owner: my-org
          names:
            - my-repo
      webhook:
        endpoint: /github
        port: "12000"
        method: POST
        url: https://events.example.com  # External URL for webhook registration
      events:
        - push
        - pull_request
        - create
        - delete
      apiToken:
        name: github-token
        key: token
      webhookSecret:
        name: github-token
        key: webhook-secret
      contentType: json
      active: true
      insecure: false
      deleteHookOnFinish: false
```

#### GitLab

```yaml
spec:
  gitlab:
    merge-request:
      gitlab_base_url: https://gitlab.example.com
      projectID: "12345"
      webhook:
        endpoint: /gitlab
        port: "12000"
        method: POST
      events:
        - MergeRequestsEvents
        - PushEvents
        - TagPushEvents
      accessToken:
        name: gitlab-token
        key: token
      secretToken:
        name: gitlab-token
        key: webhook-secret
      enableSSLVerification: true
      deleteHookOnFinish: false
```

#### Kafka

```yaml
spec:
  kafka:
    order-events:
      url: kafka-broker:9092
      topic: orders
      consumerGroup:
        groupName: argo-events
        rebalanceStrategy: range         # range, sticky, roundrobin
      partition: "0"                     # Optional specific partition
      version: "2.0.0"
      tls:
        caCertSecret:
          name: kafka-tls
          key: ca.crt
      sasl:
        mechanism: PLAIN
        userSecret:
          name: kafka-creds
          key: username
        passwordSecret:
          name: kafka-creds
          key: password
      jsonBody: true                     # Parse body as JSON
      connectionBackoff:
        duration: 10s
        factor: 2
        steps: 5
```

#### SNS

```yaml
spec:
  sns:
    notifications:
      topicArn: arn:aws:sns:us-east-1:123456789:my-topic
      webhook:
        endpoint: /sns
        port: "12000"
        method: POST
      accessKey:
        name: aws-creds
        key: access-key
      secretKey:
        name: aws-creds
        key: secret-key
      region: us-east-1
```

#### SQS

```yaml
spec:
  sqs:
    messages:
      region: us-east-1
      queue: my-queue
      waitTimeSeconds: 20
      accessKey:
        name: aws-creds
        key: access-key
      secretKey:
        name: aws-creds
        key: secret-key
      jsonBody: true
```

#### NATS

```yaml
spec:
  nats:
    events:
      url: nats://nats.nats:4222
      subject: my-subject
      jsonBody: true
      auth:
        token:
          name: nats-token
          key: token
```

#### Redis

```yaml
spec:
  redis:
    events:
      hostAddress: redis.redis:6379
      db: 0
      channels:
        - my-channel
      password:
        name: redis-creds
        key: password
      jsonBody: true
```

#### Calendar (Cron)

```yaml
spec:
  calendar:
    hourly:
      schedule: "0 * * * *"             # Cron expression
      interval: 1h                      # OR interval
      timezone: America/New_York
      exclusionDates:
        - 2024-12-25
      persistence:
        catchup:
          enabled: true                  # Fire missed events on restart
        configMap:
          name: calendar-state
          createIfNotExist: true
```

#### Resource (Kubernetes Watch)

```yaml
spec:
  resource:
    pod-changes:
      namespace: default
      group: ""
      version: v1
      resource: pods
      eventTypes:
        - ADD
        - UPDATE
        - DELETE
      filter:
        labels:
          - key: app
            operation: "=="
            value: my-app
        afterAction: true               # Fire after action completes
```

#### Webhook (Generic)

```yaml
spec:
  webhook:
    generic-hook:
      endpoint: /webhook
      port: "12000"
      method: POST
```

#### Slack

```yaml
spec:
  slack:
    slash-commands:
      token:
        name: slack-token
        key: token
      signingSecret:
        name: slack-token
        key: signing-secret
      webhook:
        endpoint: /slack
        port: "12000"
        method: POST
```

#### AMQP (RabbitMQ)

```yaml
spec:
  amqp:
    events:
      url: amqp://guest:guest@rabbitmq:5672/
      exchangeName: my-exchange
      exchangeType: topic
      routingKey: "events.#"
      jsonBody: true
      connectionBackoff:
        duration: 10s
        factor: 2
        steps: 5
```

#### Pub/Sub (GCP)

```yaml
spec:
  pubsub:
    events:
      projectID: my-gcp-project
      topicProjectID: my-gcp-project
      topic: my-topic
      subscriptionID: argo-events-sub
      credentialSecret:
        name: gcp-creds
        key: serviceAccountKey
      jsonBody: true
```

#### Minio / S3-compatible

```yaml
spec:
  minio:
    file-upload:
      endpoint: minio.minio:9000
      bucket:
        name: my-bucket
      events:
        - s3:ObjectCreated:*
        - s3:ObjectRemoved:*
      filter:
        prefix: uploads/
        suffix: .csv
      accessKey:
        name: minio-creds
        key: accessKey
      secretKey:
        name: minio-creds
        key: secretKey
      insecure: true
```

#### Pulsar

```yaml
spec:
  pulsar:
    events:
      url: pulsar://pulsar:6650
      topics:
        - persistent://public/default/my-topic
      type: exclusive
      jsonBody: true
```

All supported EventSource types: webhook, github, gitlab, bitbucket, bitbucketserver, slack, sns, sqs, kafka, amqp, nats, redis, pubsub, emitter, calendar, file, resource, stripe, azure-events-hub, azure-service-bus, azure-queue-storage, minio, pulsar, generic, gerrit, sftp.

## EventBus

### NATS JetStream (recommended)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: EventBus
metadata:
  name: default
  namespace: argo-events
spec:
  jetstream:
    version: latest                     # NATS version
    replicas: 3                         # 3 for HA
    persistence:
      storageClassName: standard
      accessMode: ReadWriteOnce
      volumeSize: 20Gi
    streamConfig: |
      maxAge: 72h                       # Message retention
      maxBytes: 1073741824              # 1GB
      replicas: 3
    settings: |
      max_payload: 1048576              # 1MB max message
    containerTemplate:
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
    metadata:
      labels: {}
      annotations: {}
```

### Kafka

```yaml
apiVersion: argoproj.io/v1alpha1
kind: EventBus
metadata:
  name: default
  namespace: argo-events
spec:
  kafka:
    url: kafka-broker:9092
    topic: argo-events
    version: "2.6.0"
    tls:
      caCertSecret:
        name: kafka-tls
        key: ca.crt
    sasl:
      mechanism: PLAIN
      userSecret:
        name: kafka-creds
        key: username
      passwordSecret:
        name: kafka-creds
        key: password
    consumerGroup:
      groupName: argo-events
      rebalanceStrategy: sticky
```

### NATS (native — legacy)

```yaml
spec:
  nats:
    native:
      replicas: 3
      auth: token
```

### NATS (exotic — external)

```yaml
spec:
  nats:
    exotic:
      url: nats://external-nats:4222
      clusterID: argo-events
      auth:
        token:
          name: nats-token
          key: token
```

## Sensor

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Sensor
metadata:
  name: <name>
  namespace: <namespace>
spec:
  eventBusName: default
  replicas: 1
  template:
    metadata:
      labels: {}
    spec:
      containers:
        - resources: {}
      serviceAccountName: <sa>

  dependencies:                         # Events to subscribe to
    - name: <dependency-name>
      eventSourceName: <eventsource-name>
      eventName: <event-name>
      filters: {}                       # Optional filters (see below)
      transform: {}                     # Optional transformation (see below)
      filtersLogicalOperator: and       # "and" or "or" for combining filters

  triggers:                             # Actions to perform
    - template:
        name: <trigger-name>
        conditions: <condition-expr>    # Optional: which dependencies activate this trigger
        <trigger-type>: {}              # Trigger config (see below)
      retryStrategy:
        steps: 3
        duration: 10s
        factor: 2
      rateLimit:
        unit: minute
        requestsPerUnit: 5
```

## Sensor Dependency Filters

### Data Filter

Filter based on event payload fields:

```yaml
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
            - refs/heads/release-*
        - path: body.commits.#.modified.#
          type: string
          value:
            - "src/**"
          comparator: ">="              # >=, >, =, !=, <, <=
```

### Time Filter

```yaml
filters:
  time:
    start: "08:00:00"
    stop: "18:00:00"
```

### Context Filter

Filter on CloudEvents context attributes:

```yaml
filters:
  context:
    type: github.push
    source: my-org/my-repo
    subject: main
```

### Expression Filter (CEL)

```yaml
filters:
  exprs:
    - expr: body.action in ["opened", "synchronize"]
      fields:
        - name: body.action
          path: body.action
    - expr: int(body.pull_request.number) > 0
      fields:
        - name: body.pull_request.number
          path: body.pull_request.number
```

### Combining Filters

```yaml
dependencies:
  - name: filtered-event
    eventSourceName: my-source
    eventName: my-event
    filtersLogicalOperator: and         # All filters must match
    filters:
      data:
        - path: body.action
          type: string
          value: ["push"]
      time:
        start: "08:00:00"
        stop: "18:00:00"
      context:
        type: github.push
```

## Event Transformation

### Data Transformation

Transform event data before passing to trigger:

```yaml
dependencies:
  - name: github-push
    eventSourceName: github-webhook
    eventName: push-events
    transform:
      jq: ".body | {repo: .repository.full_name, branch: .ref, sha: .after}"
```

Or using Lua:

```yaml
transform:
  script: |
    event = obj.body
    return {
      repo = event.repository.full_name,
      branch = event.ref,
      sha = event.after
    }
```

## Sensor Triggers

### Argo Workflow Trigger

```yaml
triggers:
  - template:
      name: run-ci
      argoWorkflow:
        operation: submit               # submit, resubmit, retry, resume, suspend, stop, terminate
        source:
          resource:
            apiVersion: argoproj.io/v1alpha1
            kind: Workflow
            metadata:
              generateName: ci-
              namespace: argo
            spec:
              entrypoint: main
              arguments:
                parameters:
                  - name: repo
                  - name: sha
              templates:
                - name: main
                  container:
                    image: alpine
                    command: [echo]
                    args: ["Building {{workflow.parameters.repo}} at {{workflow.parameters.sha}}"]
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

### HTTP Trigger

```yaml
triggers:
  - template:
      name: call-webhook
      http:
        url: https://api.example.com/deploy
        method: POST
        headers:
          Content-Type: application/json
          Authorization: "Bearer ${secret:my-secret:token}"
        payload:
          - src:
              dependencyName: my-dep
              dataKey: body
            dest: body
        secureHeaders:
          - name: Authorization
            valueFrom:
              secretKeyRef:
                name: api-token
                key: token
        timeout: 30
```

### Kubernetes Resource Trigger

```yaml
triggers:
  - template:
      name: create-job
      k8s:
        operation: create               # create, update, patch
        source:
          resource:
            apiVersion: batch/v1
            kind: Job
            metadata:
              generateName: process-
              namespace: default
            spec:
              template:
                spec:
                  containers:
                    - name: worker
                      image: worker:latest
                  restartPolicy: Never
        parameters:
          - src:
              dependencyName: my-dep
              dataKey: body.data
            dest: spec.template.spec.containers.0.env.0.value
            operation: append
```

### Slack Trigger

```yaml
triggers:
  - template:
      name: notify-slack
      slack:
        channel: deployments
        message: "New deployment triggered for {{.Input.body.repository.name}}"
        slackToken:
          name: slack-token
          key: token
        parameters:
          - src:
              dependencyName: github-push
              dataKey: body.repository.name
            dest: message
```

### AWS Lambda Trigger

```yaml
triggers:
  - template:
      name: invoke-lambda
      awsLambda:
        functionName: process-event
        region: us-east-1
        accessKey:
          name: aws-creds
          key: access-key
        secretKey:
          name: aws-creds
          key: secret-key
        payload:
          - src:
              dependencyName: my-dep
              dataKey: body
            dest: event
```

### Log Trigger

```yaml
triggers:
  - template:
      name: log-event
      log:
        intervalSeconds: 0              # Log every event
```

### NATS Trigger

```yaml
triggers:
  - template:
      name: publish-nats
      nats:
        url: nats://nats:4222
        subject: processed-events
        payload:
          - src:
              dependencyName: my-dep
              dataKey: body
            dest: data
```

### Kafka Trigger

```yaml
triggers:
  - template:
      name: publish-kafka
      kafka:
        url: kafka:9092
        topic: processed-events
        partition: 0
        payload:
          - src:
              dependencyName: my-dep
              dataKey: body
            dest: data
```

## Trigger Conditions

Control which dependencies activate a trigger using boolean logic:

```yaml
triggers:
  - template:
      name: deploy-production
      conditions: "github-push && approval"   # Both must fire
      argoWorkflow:
        # ...

  - template:
      name: deploy-staging
      conditions: "github-push"               # Only github-push needed
      argoWorkflow:
        # ...
```

Operators: `&&` (AND), `||` (OR), `!` (NOT), parentheses for grouping.

## Trigger Policies

```yaml
triggers:
  - template:
      name: my-trigger
    policy:
      k8s:
        backoff:
          steps: 3
          duration: 5s
          factor: 2
        errorOnBackoffTimeout: true
      status:
        allow:
          - 200
          - 201
```

## Cross-Namespace Event Delivery

EventSource and Sensor must be in the same namespace, or you must configure the EventBus to allow cross-namespace subscriptions. The simplest approach: deploy EventSource, EventBus, and Sensor in the same namespace.
