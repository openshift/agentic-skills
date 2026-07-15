# Argo CD Applications Reference

## Application Spec Structure

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app-name>
  namespace: argocd                    # Must be the Argo CD namespace
  labels: {}
  annotations: {}
  finalizers:
    - resources-finalizer.argocd.argoproj.io  # Cascade-delete managed resources
spec:
  project: <project-name>             # AppProject reference (default: "default")

  source:                              # Single source (use sources[] for multi-source)
    repoURL: <repo-url>               # Git URL or Helm chart repo URL
    targetRevision: <revision>         # Branch, tag, commit SHA, or semver range
    path: <path>                       # For Git repos: path to manifests directory
    chart: <chart-name>                # For Helm repos: chart name (mutually exclusive with path)
    helm:                              # Helm-specific options
      releaseName: <name>
      valuesObject: {}                 # Structured values (preferred over values string)
      values: |                        # Multi-line YAML string values (use valuesObject instead)
      valueFiles:                      # List of values files relative to path
        - values-prod.yaml
      parameters:                      # Individual parameter overrides
        - name: <param.path>
          value: <value>
          forceString: false           # Force value to be treated as string
      fileParameters:                  # File-based parameters
        - name: <param>
          path: <file-path>
      ignoreMissingValueFiles: false   # Don't error on missing values files
      skipCrds: false                  # Skip CRD installation
      passCredentials: false           # Pass credentials to all domains
      version: v3                      # Helm version (v3 default)
    kustomize:                         # Kustomize-specific options
      namePrefix: <prefix>
      nameSuffix: <suffix>
      commonLabels: {}
      commonAnnotations: {}
      images:                          # Override kustomize images
        - <image>:<tag>
      forceCommonLabels: false
      forceCommonAnnotations: false
      version: <kustomize-version>
    directory:                         # Plain directory options
      recurse: false                   # Recurse into subdirectories
      jsonnet:                         # Jsonnet-specific options
        extVars: []
        tlas: []
        libs: []
      exclude: <glob>                  # Exclude files matching glob
      include: <glob>                  # Only include files matching glob
    plugin:                            # Config management plugin
      name: <plugin-name>
      env:
        - name: <key>
          value: <value>
      parameters:
        - name: <key>
          string: <value>

  sources: []                          # Multi-source (list of source objects)

  destination:
    server: <cluster-url>              # Cluster API server URL
    name: <cluster-name>               # OR cluster name (mutually exclusive with server)
    namespace: <namespace>             # Target namespace

  syncPolicy:
    automated:                         # Automated sync settings
      prune: false                     # Delete resources not in Git
      selfHeal: false                  # Re-sync when live state drifts
      allowEmpty: false                # Allow syncing when source produces zero manifests
    syncOptions: []                    # List of sync options (see below)
    managedNamespaceMetadata:          # Metadata for auto-created namespaces
      labels: {}
      annotations: {}
    retry:
      limit: <int>                     # Max retry attempts (0 = no retry, -1 = infinite)
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  ignoreDifferences: []                # Ignore specific field diffs (see below)

  info:                                # Informational metadata (displayed in UI)
    - name: <key>
      value: <value>

  revisionHistoryLimit: 10             # Number of sync history entries to keep
```

## Sync Policies

### Automated Sync

```yaml
syncPolicy:
  automated:
    prune: true       # DELETE resources from cluster that are no longer in Git
    selfHeal: true    # Re-sync when someone manually modifies a resource in the cluster
    allowEmpty: false  # If true, allows sync when Git source produces zero resources
```

- **prune** — When a manifest is removed from Git, the corresponding resource is deleted from the cluster. Without this, removed manifests leave orphaned resources.
- **selfHeal** — When a resource is manually modified in the cluster (kubectl edit, etc.), Argo CD reverts it to match Git. Polling interval is configurable via `timeout.reconciliation` in `argocd-cm` (default: 180s).
- **allowEmpty** — Safety guard. If your source suddenly produces zero manifests (broken Helm chart, empty directory), this prevents deleting everything. Keep `false` in production.

### Manual Sync

Omit `syncPolicy.automated` entirely. Users must click "Sync" in the UI or run `argocd app sync <app>`.

## Sync Options

Applied as a list of `Key=Value` strings under `syncPolicy.syncOptions`:

| Option | Default | Description |
|--------|---------|-------------|
| `CreateNamespace=true` | false | Create the destination namespace if it doesn't exist |
| `ServerSideApply=true` | false | Use server-side apply instead of client-side. Avoids annotation size limits. Required for CRDs >256KB |
| `Replace=true` | false | Use `kubectl replace` instead of `kubectl apply`. Destructive — replaces entire resource |
| `PruneLast=true` | false | Delete removed resources after all other resources are synced and healthy |
| `PrunePropagationPolicy=foreground` | background | Deletion propagation: `foreground`, `background`, or `orphan` |
| `ApplyOutOfSyncOnly=true` | false | Only apply resources that are out of sync (optimization for large apps) |
| `RespectIgnoreDifferences=true` | false | Use ignoreDifferences during sync (not just diff display). Prevents reverting ignored fields |
| `Validate=false` | true | Skip schema validation during apply |
| `SkipDryRunOnMissingResource=true` | false | Skip dry-run for resource types not installed on the cluster |
| `FailOnSharedResource=true` | false | Fail sync if a resource is managed by another Application |

Sync options can also be set per-resource via annotation:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-options: ServerSideApply=true,PruneLast=true
```

## Sync Waves and Hooks

### Sync Waves

Control the order resources are applied within a sync operation:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "5"
```

- Waves are integers (negative allowed). Lower numbers sync first.
- Default wave is 0. Resources within the same wave sync in parallel.
- Argo CD waits for all resources in a wave to be healthy before moving to the next wave.
- Typical pattern: `-1` for namespaces/CRDs, `0` for core resources, `1` for dependent resources, `5` for post-deploy jobs.

### Sync Hooks

Run Jobs or Pods at specific phases of the sync lifecycle:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
```

**Hook phases:**
- `PreSync` — Before the sync (e.g., database migrations, schema changes)
- `Sync` — During the sync (applied alongside manifests in the same wave)
- `PostSync` — After all resources are synced and healthy (e.g., smoke tests, notifications)
- `SyncFail` — When sync fails (e.g., cleanup, alerting)
- `Skip` — Skip this resource during sync entirely

**Delete policies:**
- `HookSucceeded` — Delete hook resource after it succeeds
- `HookFailed` — Delete hook resource after it fails
- `BeforeHookCreation` — Delete existing hook resource before creating a new one (default)

## Health Checks

### Built-in Health Checks

Argo CD has built-in health assessments for standard Kubernetes resources:

| Resource | Healthy When |
|----------|-------------|
| Deployment | All replicas updated and available |
| StatefulSet | All replicas updated and ready |
| DaemonSet | All desired pods scheduled and available |
| ReplicaSet | All replicas available |
| Pod | Running and ready |
| Service | Exists (always healthy) |
| Ingress | Has at least one address assigned |
| PVC | Bound |
| Job | Succeeded |
| PDB | CurrentHealthy >= DesiredHealthy |

**Health statuses:**
- `Healthy` — Resource is operating normally
- `Progressing` — Resource is not yet healthy but is making progress (e.g., Deployment rolling out)
- `Degraded` — Resource has failed or errored
- `Suspended` — Resource is paused (e.g., suspended CronJob, Rollout paused)
- `Missing` — Resource does not exist in the cluster

### Custom Health Checks (Lua)

Add custom health checks for CRDs or override built-in checks in `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resource.customizations.health.argoproj.io_Rollout: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.phase == "Healthy" then
        hs.status = "Healthy"
        hs.message = "Rollout is healthy"
      elseif obj.status.phase == "Paused" then
        hs.status = "Suspended"
        hs.message = obj.status.message
      elseif obj.status.phase == "Degraded" then
        hs.status = "Degraded"
        hs.message = obj.status.message
      else
        hs.status = "Progressing"
        hs.message = "Rollout in progress"
      end
    end
    return hs
```

## Resource Tracking Methods

Configured in `argocd-cm` via `resource.trackingMethod`:

| Method | Label Added | Annotation Added | Pros | Cons |
|--------|------------|-----------------|------|------|
| `label` | `app.kubernetes.io/instance` | — | Simple, visible via `kubectl` | Conflicts with Helm/other tools using same label |
| `annotation` | — | `argocd.argoproj.io/tracking-id` | No label conflicts | Not visible via label selectors |
| `annotation+label` | Both | Both | Maximum compatibility | Two tracking markers |

Default is `annotation` in Argo CD 2.6+.

## Ignore Differences

Prevent specific fields from showing as OutOfSync:

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas                      # Ignore HPA-managed replicas
    - group: "*"
      kind: "*"
      managedFieldsManagers:
        - kube-controller-manager             # Ignore fields managed by controller
    - group: admissionregistration.k8s.io
      kind: MutatingWebhookConfiguration
      jqPathExpressions:
        - .webhooks[]?.clientConfig.caBundle   # Ignore injected CA bundles
```

**Methods:**
- `jsonPointers` — RFC 6901 JSON pointers. Exact field paths. E.g., `/spec/replicas`.
- `jqPathExpressions` — jq expressions for more complex matching. E.g., `.spec.template.spec.containers[]?.resources`.
- `managedFieldsManagers` — Ignore all fields managed by a specific field manager. Useful for controller-managed fields.

To make ignored differences also ignored during sync (not just display), add `RespectIgnoreDifferences=true` to sync options.

System-level ignore differences (applying to all Applications) can be configured in `argocd-cm`:

```yaml
data:
  resource.customizations.ignoreDifferences.all: |
    jsonPointers:
      - /metadata/resourceVersion
      - /metadata/generation
```

## Multi-Cluster Management

### Adding Clusters

```bash
# Add a cluster using a kubeconfig context
argocd cluster add <context-name> --name <display-name>

# Add with specific service account
argocd cluster add <context-name> --service-account argocd-manager

# Add with project restrictions
argocd cluster add <context-name> --project my-project
```

### Cluster Secrets

Each external cluster is stored as a Secret:

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
  server: https://prod-east.example.com:6443
  config: |
    {
      "bearerToken": "<token>",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "<base64-ca-cert>"
      }
    }
```

### In-Cluster Reference

The cluster where Argo CD runs is always available as:
- `server: https://kubernetes.default.svc`

No Secret needed.

## Orphaned Resource Monitoring

Detects resources in a namespace that are not managed by any Application:

```yaml
# In AppProject spec
spec:
  orphanedResources:
    warn: true                          # Show warning in UI for orphaned resources
    ignore:                             # Exclude certain resources from orphan detection
      - group: ""
        kind: ConfigMap
        name: kube-root-ca.crt
      - group: ""
        kind: ServiceAccount
        name: default
```

## Multi-Source Applications

Combine multiple sources (e.g., Helm chart + separate values repo):

```yaml
spec:
  sources:
    - repoURL: https://charts.example.com
      chart: my-app
      targetRevision: 1.2.3
      helm:
        valueFiles:
          - $values/apps/my-app/values-prod.yaml
    - repoURL: https://github.com/org/config-repo.git
      targetRevision: main
      ref: values                       # Reference name used as $values above
```

The `ref` field creates a named reference. The `$ref` prefix in `valueFiles` resolves to the path of the referenced source.
