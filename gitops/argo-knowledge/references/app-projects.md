# AppProject Reference

## Overview

AppProject defines a logical grouping of Applications with RBAC, source/destination restrictions, and sync windows. Every Application must reference a project. The `default` project is created automatically and allows all sources/destinations.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: <project-name>
  namespace: argocd
spec:
  description: <description>
  sourceRepos: []
  sourceNamespaces: []
  destinations: []
  clusterResourceWhitelist: []
  clusterResourceBlacklist: []
  namespaceResourceWhitelist: []
  namespaceResourceBlacklist: []
  orphanedResources: {}
  roles: []
  syncWindows: []
  signatureKeys: []
  permitOnlyProjectScopedClusters: false
```

## Source Restrictions

### sourceRepos

Restrict which Git repositories or Helm chart repositories Applications can use:

```yaml
spec:
  sourceRepos:
    - https://github.com/org/repo.git           # Specific repo
    - https://github.com/org/*                    # Wildcard org
    - https://charts.example.com                  # Helm repo
    - '*'                                         # Allow all (default project)
```

### sourceNamespaces

Allow Applications to be created in namespaces other than the Argo CD namespace:

```yaml
spec:
  sourceNamespaces:
    - team-a-argocd
    - team-b-argocd
```

Requires `--application-namespaces` on the Argo CD controller.

## Destination Restrictions

Control which clusters and namespaces Applications can deploy to:

```yaml
spec:
  destinations:
    - server: https://kubernetes.default.svc
      namespace: team-a-*                         # Wildcard namespace
    - server: https://prod.example.com
      namespace: production
      name: prod-cluster                          # Optional cluster name
    - server: '*'
      namespace: '*'                              # Allow all (default project)
```

**Fields:**
- `server` — Cluster API URL. Use `*` for all clusters.
- `namespace` — Target namespace. Use `*` for all namespaces. Wildcards supported.
- `name` — Cluster name (alternative to server).

If both `server` and `name` are specified, both must match.

## Cluster Resource Allow/Deny Lists

Control which cluster-scoped resources (ClusterRole, Namespace, etc.) Applications can manage:

```yaml
spec:
  # Allow specific cluster-scoped resources
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
    - group: rbac.authorization.k8s.io
      kind: ClusterRole
    - group: rbac.authorization.k8s.io
      kind: ClusterRoleBinding

  # Deny specific cluster-scoped resources (applied after whitelist)
  clusterResourceBlacklist:
    - group: ''
      kind: ResourceQuota
```

- Empty `clusterResourceWhitelist` = no cluster-scoped resources allowed
- `group: '*'`, `kind: '*'` = allow all

## Namespace Resource Allow/Deny Lists

Control which namespace-scoped resources Applications can manage:

```yaml
spec:
  # Allow only specific resources
  namespaceResourceWhitelist:
    - group: ''
      kind: ConfigMap
    - group: ''
      kind: Secret
    - group: apps
      kind: Deployment
    - group: ''
      kind: Service

  # Deny specific resources (applied after whitelist)
  namespaceResourceBlacklist:
    - group: ''
      kind: LimitRange
```

Default: all namespace-scoped resources are allowed (if no whitelist specified).

## Orphaned Resource Monitoring

Detect resources in a namespace that aren't managed by any Application:

```yaml
spec:
  orphanedResources:
    warn: true                                    # Show warning in UI/CLI
    ignore:
      - group: ""
        kind: ConfigMap
        name: kube-root-ca.crt                    # Ignore specific resource
      - group: ""
        kind: ServiceAccount
        name: default                             # Ignore default SA
      - group: ""
        kind: Endpoints                           # Ignore all Endpoints
```

- `warn: true` — Display orphaned resources as warnings in the Application UI
- `ignore` — Exclude specific resources from orphan detection. Supports `group`, `kind`, and optional `name`.

## Roles and Policies (Project-Level RBAC)

Define roles with specific permissions within a project:

```yaml
spec:
  roles:
    - name: developer
      description: Developer access
      policies:
        - p, proj:my-project:developer, applications, get, my-project/*, allow
        - p, proj:my-project:developer, applications, sync, my-project/*, allow
        - p, proj:my-project:developer, applications, action/*, my-project/*, allow
      groups:
        - my-org:developers                       # SSO group binding
      jwtTokens:
        - iat: 1535390316                          # API token (managed via CLI)

    - name: ops
      description: Operations team
      policies:
        - p, proj:my-project:ops, applications, *, my-project/*, allow
        - p, proj:my-project:ops, logs, get, my-project/*, allow
      groups:
        - my-org:ops-team
```

**Policy format:** `p, <role>, <resource>, <action>, <project>/<object>, <allow|deny>`

**Resources and actions:**
| Resource | Actions |
|----------|---------|
| applications | get, create, update, delete, sync, override, action/<group>/<kind>/<action> |
| logs | get |
| exec | create |
| repositories | get, create, update, delete |
| clusters | get, create, update, delete |

## Sync Windows

Restrict when syncs can occur:

```yaml
spec:
  syncWindows:
    - kind: allow                                 # "allow" or "deny"
      schedule: '0 8 * * 1-5'                     # Cron schedule (UTC)
      duration: 10h                               # Window duration
      applications:
        - '*'                                     # Apply to all apps in project
      namespaces:
        - production
      clusters:
        - prod-*
      manualSync: true                            # Also restrict manual syncs (default: false)
      timeZone: America/New_York                  # Optional timezone

    - kind: deny
      schedule: '0 0 * * 5'                       # Deny on Fridays midnight UTC
      duration: 48h                               # Until Sunday midnight UTC
      applications:
        - '*'
      manualSync: false                           # Allow manual syncs during deny window
```

**Logic:**
- If only `allow` windows exist: syncs are blocked outside all allow windows
- If only `deny` windows exist: syncs are allowed outside all deny windows
- If both exist: sync is allowed when it falls inside an allow window AND outside all deny windows
- `manualSync: true` means the window applies to manual syncs too (default is automated only)

## Signature Verification

Require GPG signature verification on Git commits:

```yaml
spec:
  signatureKeys:
    - keyID: ABCDEF1234567890
    - keyID: 1234567890ABCDEF
```

When configured, only commits signed by listed keys can be synced. Unsigned or differently-signed commits are rejected.

GPG public keys must be imported into the `argocd-gpg-keys-cm` ConfigMap.

## Complete Example

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-platform
  namespace: argocd
spec:
  description: Platform team project

  sourceRepos:
    - https://github.com/org/platform-*.git
    - https://charts.bitnami.com/bitnami

  destinations:
    - server: https://kubernetes.default.svc
      namespace: platform-*
    - server: https://prod.example.com
      namespace: platform-*

  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
    - group: rbac.authorization.k8s.io
      kind: ClusterRole
    - group: rbac.authorization.k8s.io
      kind: ClusterRoleBinding

  namespaceResourceBlacklist:
    - group: ''
      kind: LimitRange
    - group: ''
      kind: ResourceQuota

  orphanedResources:
    warn: true
    ignore:
      - group: ""
        kind: ConfigMap
        name: kube-root-ca.crt

  roles:
    - name: admin
      policies:
        - p, proj:team-platform:admin, applications, *, team-platform/*, allow
      groups:
        - org:platform-admins
    - name: viewer
      policies:
        - p, proj:team-platform:viewer, applications, get, team-platform/*, allow
      groups:
        - org:platform-viewers

  syncWindows:
    - kind: deny
      schedule: '0 18 * * 5'
      duration: 62h
      applications:
        - '*'
      clusters:
        - prod-*
      manualSync: false
```
