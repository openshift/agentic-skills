# Argo CD Notifications Reference

## Overview

Argo CD Notifications is built into Argo CD (since v2.6). It monitors Application resources and sends notifications based on configurable triggers and templates. Configuration lives in two resources in the Argo CD namespace:

- **`argocd-notifications-cm`** ConfigMap — Services, templates, triggers
- **`argocd-notifications-secret`** Secret — Tokens, passwords, API keys

## ConfigMap Structure

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  # Service configurations
  service.<service-type>: |
    <service-config>

  # Templates
  template.<template-name>: |
    <template-config>

  # Triggers
  trigger.<trigger-name>: |
    <trigger-config>

  # Default triggers (applied to all subscribed apps)
  defaultTriggers: |
    - on-sync-succeeded
    - on-health-degraded

  # Global context variables
  context: |
    argocdUrl: https://argocd.example.com
    environmentName: production
```

## Service Configuration

### Slack

```yaml
data:
  service.slack: |
    token: $slack-token
    signingSecret: $slack-signing-secret
    icon: ":argocd:"
    username: ArgoCD
```

Secret:
```yaml
stringData:
  slack-token: xoxb-XXXXXXXXX
  slack-signing-secret: XXXXXXXXX
```

### Microsoft Teams

```yaml
data:
  service.teams: |
    recipientUrls:
      my-channel: https://outlook.office.com/webhook/XXXXXXX
```

### GitHub (Commit Status)

```yaml
data:
  service.github: |
    appID: 12345
    installationID: 67890
    privateKey: $github-private-key
```

### Webhook

```yaml
data:
  service.webhook.<webhook-name>: |
    url: https://api.example.com/argocd-events
    headers:
      - name: Content-Type
        value: application/json
      - name: Authorization
        value: "Bearer $webhook-token"
    insecureSkipVerify: false
```

### Email (SMTP)

```yaml
data:
  service.email: |
    host: smtp.example.com
    port: 587
    from: argocd@example.com
    username: $email-username
    password: $email-password
    html: true
```

### Grafana

```yaml
data:
  service.grafana: |
    apiUrl: https://grafana.example.com/api
    apiKey: $grafana-api-key
```

### Opsgenie

```yaml
data:
  service.opsgenie: |
    apiUrl: https://api.opsgenie.com
    apiKeys:
      default: $opsgenie-api-key
```

### PagerDuty

```yaml
data:
  service.pagerduty: |
    token: $pagerduty-token
    from: argocd@example.com
```

### Rocket.Chat

```yaml
data:
  service.rocketchat: |
    serverUrl: https://rocketchat.example.com
    token: $rocketchat-token
    userId: $rocketchat-user-id
```

### Google Chat

```yaml
data:
  service.googlechat: |
    webhooks:
      my-space: https://chat.googleapis.com/v1/spaces/XXXXXX/messages?key=XXXXX&token=XXXXX
```

### Matrix

```yaml
data:
  service.matrix: |
    homeserverUrl: https://matrix.example.com
    accessToken: $matrix-access-token
    roomId: "!XXXXXXXXX:example.com"
```

### Telegram

```yaml
data:
  service.telegram: |
    token: $telegram-bot-token
```

## Template Configuration

### Basic Template

```yaml
data:
  template.app-sync-succeeded: |
    message: |
      Application {{.app.metadata.name}} has been successfully synced.
      Revision: {{.app.status.sync.revision}}
```

### Slack Template with Blocks

```yaml
data:
  template.app-deployed: |
    message: "{{.app.metadata.name}} deployed to {{.app.spec.destination.namespace}}"
    slack:
      attachments: |
        [{
          "color": "#18be52",
          "title": "{{.app.metadata.name}}",
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}",
          "fields": [
            {"title": "Project", "value": "{{.app.spec.project}}", "short": true},
            {"title": "Namespace", "value": "{{.app.spec.destination.namespace}}", "short": true},
            {"title": "Revision", "value": "{{.app.status.sync.revision | trunc 7}}", "short": true},
            {"title": "Status", "value": "{{.app.status.health.status}}", "short": true}
          ]
        }]
      blocks: |
        [{
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": "{{.app.metadata.name}} Deployed"
          }
        },
        {
          "type": "section",
          "fields": [
            {"type": "mrkdwn", "text": "*Project:* {{.app.spec.project}}"},
            {"type": "mrkdwn", "text": "*Status:* {{.app.status.health.status}}"}
          ]
        }]
      groupingKey: "{{.app.metadata.name}}"
      notifyBroadcast: false
      deliveryPolicy: Post              # Post, PostAndUpdate
```

### Email Template

```yaml
data:
  template.app-sync-failed-email: |
    email:
      subject: "ArgoCD: {{.app.metadata.name}} sync failed"
    message: |
      <h2>Application {{.app.metadata.name}} sync failed</h2>
      <p><b>Project:</b> {{.app.spec.project}}</p>
      <p><b>Error:</b> {{.app.status.operationState.message}}</p>
      <p><a href="{{.context.argocdUrl}}/applications/{{.app.metadata.name}}">View in ArgoCD</a></p>
```

### Teams Template

```yaml
data:
  template.app-sync-failed-teams: |
    teams:
      themeColor: "#FF0000"
      title: "{{.app.metadata.name}} Sync Failed"
      summary: "ArgoCD application {{.app.metadata.name}} sync has failed"
      sections: |
        [{
          "facts": [
            {"name": "Application", "value": "{{.app.metadata.name}}"},
            {"name": "Project", "value": "{{.app.spec.project}}"},
            {"name": "Error", "value": "{{.app.status.operationState.message}}"}
          ]
        }]
      potentialAction: |
        [{
          "@type": "OpenUri",
          "name": "Open in ArgoCD",
          "targets": [{"os": "default", "uri": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"}]
        }]
```

### GitHub Commit Status Template

```yaml
data:
  template.app-deployed-github: |
    message: "ArgoCD deployed {{.app.metadata.name}}"
    github:
      repoURLPath: "{{.app.spec.source.repoURL}}"
      revisionPath: "{{.app.status.operationState.syncResult.revision}}"
      status:
        state: success                  # error, failure, pending, success
        label: "argocd/{{.app.metadata.name}}"
        targetURL: "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"
```

### Webhook Template

```yaml
data:
  template.webhook-notification: |
    webhook:
      my-webhook:
        method: POST
        path: /argocd/events
        body: |
          {
            "app": "{{.app.metadata.name}}",
            "project": "{{.app.spec.project}}",
            "status": "{{.app.status.health.status}}",
            "sync": "{{.app.status.sync.status}}",
            "revision": "{{.app.status.sync.revision}}"
          }
```

## Template Functions

Available in Go templates:

| Function | Description | Example |
|----------|-------------|---------|
| `trunc N` | Truncate string | `{{.app.status.sync.revision \| trunc 7}}` |
| `now` | Current time | `{{now}}` |
| `toUpper` | Uppercase | `{{.app.metadata.name \| toUpper}}` |
| `toLower` | Lowercase | `{{.app.metadata.name \| toLower}}` |
| `replace` | String replace | `{{.app.metadata.name \| replace "-" "_"}}` |
| `default` | Default value | `{{.app.spec.project \| default "default"}}` |

## Template Variables

| Variable | Description |
|----------|-------------|
| `.app.metadata.name` | Application name |
| `.app.metadata.namespace` | Application namespace |
| `.app.metadata.annotations` | Application annotations |
| `.app.metadata.labels` | Application labels |
| `.app.spec.project` | Project name |
| `.app.spec.source.repoURL` | Source repository URL |
| `.app.spec.source.path` | Source path |
| `.app.spec.source.targetRevision` | Target revision |
| `.app.spec.destination.server` | Destination cluster |
| `.app.spec.destination.namespace` | Destination namespace |
| `.app.status.sync.status` | Sync status (Synced, OutOfSync) |
| `.app.status.sync.revision` | Current synced revision |
| `.app.status.health.status` | Health status (Healthy, Degraded, Progressing, etc.) |
| `.app.status.health.message` | Health message |
| `.app.status.operationState.phase` | Operation phase (Succeeded, Failed, Error, Running) |
| `.app.status.operationState.message` | Operation message (error details) |
| `.app.status.operationState.syncResult.revision` | Synced revision |
| `.context.argocdUrl` | ArgoCD server URL (from context config) |
| `.serviceType` | Notification service type |
| `.recipient` | Notification recipient |

## Trigger Configuration

### Basic Trigger

```yaml
data:
  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      oncePer: app.status.sync.revision
      send:
        - app-sync-succeeded

  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send:
        - app-sync-failed

  trigger.on-health-degraded: |
    - when: app.status.health.status == 'Degraded'
      send:
        - app-health-degraded

  trigger.on-sync-status-unknown: |
    - when: app.status.sync.status == 'Unknown'
      send:
        - app-sync-status-unknown
```

### Trigger Fields

| Field | Description |
|-------|-------------|
| `when` | Condition expression (see below) |
| `send` | List of template names to send |
| `oncePer` | Dedup key expression — only trigger once per unique value of this expression |

### Trigger Condition Expressions

Conditions use [expr](https://expr.medv.io/) syntax:

```
# Phase checks
app.status.operationState.phase in ['Succeeded']
app.status.operationState.phase in ['Error', 'Failed']

# Health checks
app.status.health.status == 'Degraded'
app.status.health.status == 'Healthy'
app.status.health.status != 'Healthy'

# Sync status
app.status.sync.status == 'OutOfSync'
app.status.sync.status == 'Synced'

# Combined conditions
app.status.operationState.phase in ['Succeeded'] && app.status.health.status == 'Healthy'

# Time-based
time.Now().Sub(time.Parse(app.status.operationState.startedAt)).Minutes() > 10

# Resource count
len(app.status.resources.filter(r, r.health.status == 'Degraded')) > 0
```

### Default Triggers

Applied automatically to any Application that subscribes to a service without specifying triggers:

```yaml
data:
  defaultTriggers: |
    - on-sync-succeeded
    - on-sync-failed
    - on-health-degraded
```

## Subscription via Annotations

Subscribe an Application to notifications by adding annotations:

```yaml
metadata:
  annotations:
    # Format: notifications.argoproj.io/subscribe.<trigger>.<service>: <recipients>
    notifications.argoproj.io/subscribe.on-sync-failed.slack: my-channel
    notifications.argoproj.io/subscribe.on-sync-succeeded.slack: deployments
    notifications.argoproj.io/subscribe.on-health-degraded.slack: alerts
    notifications.argoproj.io/subscribe.on-sync-failed.email: team@example.com
    notifications.argoproj.io/subscribe.on-sync-failed.teams: my-channel
    notifications.argoproj.io/subscribe.on-sync-succeeded.webhook.my-webhook: ""
    notifications.argoproj.io/subscribe.on-deployed.googlechat: my-space
    notifications.argoproj.io/subscribe.on-sync-failed.telegram: "-1234567890"
```

Multiple recipients: comma-separated values.

```yaml
notifications.argoproj.io/subscribe.on-sync-failed.slack: alerts,team-channel
```

## Built-in Default Triggers and Templates

Argo CD ships with these commonly used defaults:

| Trigger | Condition | Template |
|---------|-----------|----------|
| `on-created` | New Application created | `app-created` |
| `on-deleted` | Application deleted | `app-deleted` |
| `on-deployed` | App synced and healthy | `app-deployed` |
| `on-health-degraded` | Health degraded | `app-health-degraded` |
| `on-sync-failed` | Sync operation failed | `app-sync-failed` |
| `on-sync-running` | Sync in progress | `app-sync-running` |
| `on-sync-status-unknown` | Sync status unknown | `app-sync-status-unknown` |
| `on-sync-succeeded` | Sync succeeded | `app-sync-succeeded` |

These are available out of the box. Custom triggers/templates in `argocd-notifications-cm` override or extend them.

## Complete Example: Slack Notifications for Sync Failures

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: argocd
type: Opaque
stringData:
  slack-token: xoxb-YOUR-BOT-TOKEN
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  context: |
    argocdUrl: https://argocd.example.com

  service.slack: |
    token: $slack-token

  template.app-sync-failed: |
    message: |
      :x: Application {{.app.metadata.name}} sync failed!
      Project: {{.app.spec.project}}
      Error: {{.app.status.operationState.message}}
    slack:
      attachments: |
        [{
          "color": "#E96D76",
          "title": "{{.app.metadata.name}}",
          "title_link": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}",
          "fields": [
            {"title": "Project", "value": "{{.app.spec.project}}", "short": true},
            {"title": "Revision", "value": "{{.app.status.sync.revision | trunc 7}}", "short": true},
            {"title": "Error", "value": "{{.app.status.operationState.message}}", "short": false}
          ]
        }]

  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send:
        - app-sync-failed
```

Application annotation:
```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.slack: alerts-channel
```
