# ApplicationSet Reference

## Overview

ApplicationSet is a controller that generates Argo CD Applications from a template combined with one or more generators. It enables managing many Applications at scale.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: <name>
  namespace: argocd
spec:
  goTemplate: true                      # Use Go templates (recommended)
  goTemplateOptions:
    - missingkey=error                  # Fail on missing template keys
  generators: []                        # List of generators
  template:                             # Application template
    metadata:
      name: '<templated-name>'
      labels: {}
      annotations: {}
    spec:
      project: <project>
      source: {}
      destination: {}
      syncPolicy: {}
  preserveResourcesOnDeletion: false    # Keep generated Applications' resources when deleting AppSet
  strategy: {}                          # Progressive sync strategy
  templatePatch: ""                     # JSON merge patch applied to template
```

## Go Template vs Fasttemplate

| Feature | Fasttemplate | Go Template |
|---------|-------------|-------------|
| Syntax | `{{name}}` | `{{.name}}` |
| Functions | None | Full Go template functions (sprig) |
| Conditionals | No | `{{if}}` / `{{else}}` / `{{end}}` |
| Loops | No | `{{range}}` |
| String ops | No | `upper`, `lower`, `replace`, `trimSuffix`, etc. |
| Enable | Default (legacy) | `goTemplate: true` |

**Always use Go templates** for new ApplicationSets. Fasttemplate is legacy.

Go template pitfall: `{{.path.basename}}` works, but `{{.path[0]}}` does not. Use `index .path 0` for array access.

## Generators

### Git Directory Generator

Generates one Application per directory matching a path pattern:

```yaml
generators:
  - git:
      repoURL: https://github.com/org/repo.git
      revision: main
      directories:
        - path: apps/*                    # Include all dirs under apps/
        - path: apps/excluded-app         # Exclude specific dirs
          exclude: true
        - path: apps/experimental-*       # Exclude by pattern
          exclude: true
```

**Template variables available:**
- `{{.path.path}}` — Full path (e.g., `apps/my-app`)
- `{{.path.basename}}` — Directory name (e.g., `my-app`)
- `{{.path.basenameNormalized}}` — DNS-safe name (e.g., `my-app`)
- `{{.path[N]}}` — Nth path segment (use `index .path N`)

### Git File Generator

Generates one Application per JSON/YAML file:

```yaml
generators:
  - git:
      repoURL: https://github.com/org/repo.git
      revision: main
      files:
        - path: config/**/config.json
```

Example `config.json`:
```json
{
  "appName": "my-app",
  "namespace": "production",
  "replicaCount": 3,
  "cluster": {
    "server": "https://prod.example.com"
  }
}
```

Template usage: `{{.appName}}`, `{{.cluster.server}}`

### List Generator

Explicit list of parameter sets:

```yaml
generators:
  - list:
      elements:
        - cluster: staging
          url: https://staging.example.com
          values:
            environment: staging
            replicas: "1"
        - cluster: production
          url: https://prod.example.com
          values:
            environment: production
            replicas: "3"
```

Template: `{{.cluster}}`, `{{.url}}`, `{{.values.environment}}`

### Cluster Generator

Generates one Application per registered Argo CD cluster:

```yaml
generators:
  - clusters:
      selector:
        matchLabels:
          environment: production
          tier: frontend
      values:
        revision: release-2.0
        namespace: frontend
```

**Template variables:**
- `{{.name}}` — Cluster name
- `{{.server}}` — Cluster API server URL
- `{{.metadata.labels.<key>}}` — Cluster labels
- `{{.metadata.annotations.<key>}}` — Cluster annotations
- `{{.values.<key>}}` — Values defined in the generator

Note: The in-cluster (where Argo CD runs) has `name: in-cluster` and `server: https://kubernetes.default.svc`.

### Cluster Decision Resource Generator

Uses an external custom resource to determine cluster selection:

```yaml
generators:
  - clusterDecisionResource:
      configMapRef: my-placement-decision
      name: placement-decision
      requeueAfterSeconds: 180
```

Used with Open Cluster Management (OCM) Placement decisions.

### Matrix Generator

Cartesian product of two generators — every combination of outputs:

```yaml
generators:
  - matrix:
      generators:
        - clusters:
            selector:
              matchLabels:
                tier: production
        - git:
            repoURL: https://github.com/org/apps.git
            revision: main
            directories:
              - path: apps/*
```

This produces one Application for each `(cluster, directory)` pair. Template has access to all variables from both generators.

**Nesting rules:**
- Matrix can contain any two generators
- Nested matrix (matrix within matrix) is supported up to one level
- The inner generators cannot be matrix or merge generators

### Merge Generator

Combines outputs from multiple generators, merging by key:

```yaml
generators:
  - merge:
      mergeKeys:
        - server
      generators:
        - clusters:
            selector:
              matchLabels:
                tier: production
            values:
              replicas: "3"
              helmRelease: stable
        - list:
            elements:
              - server: https://prod-east.example.com
                values:
                  replicas: "5"          # Override for this cluster
```

The merge generator lets you define defaults via one generator and overrides via another, merging on a shared key.

### Pull Request Generator

Creates one Application per open pull request:

```yaml
generators:
  - pullRequest:
      github:
        owner: my-org
        repo: my-app
        tokenRef:
          secretName: github-token
          key: token
        labels:
          - preview                       # Only PRs with this label
      requeueAfterSeconds: 60
```

**Template variables:**
- `{{.number}}` — PR number
- `{{.branch}}` — Source branch name
- `{{.branch_slug}}` — DNS-safe branch name
- `{{.head_sha}}` — Head commit SHA
- `{{.head_short_sha}}` — Short head commit SHA
- `{{.labels}}` — PR labels

**Supported providers:** GitHub, GitLab, Bitbucket Server, Bitbucket Cloud

### SCM Provider Generator

Discovers repositories from a SCM organization/group:

```yaml
generators:
  - scmProvider:
      github:
        organization: my-org
        tokenRef:
          secretName: github-token
          key: token
      filters:
        - repositoryMatch: "^service-.*"
          pathsExist:
            - deploy/kustomization.yaml
        - labelMatch: "deploy-with-argocd"
      cloneProtocol: https
```

**Template variables:**
- `{{.organization}}` — Org name
- `{{.repository}}` — Repo name
- `{{.url}}` — Clone URL
- `{{.branch}}` — Default branch
- `{{.labels}}` — Repo topics/labels

**Supported providers:** GitHub, GitLab, Bitbucket Server, Bitbucket Cloud, Azure DevOps, Gitea

### Plugin Generator

Calls an external HTTP endpoint to generate parameters:

```yaml
generators:
  - plugin:
      configMapRef: my-plugin-cm
      requeueAfterSeconds: 300
      input:
        parameters:
          team: platform
```

The plugin ConfigMap contains the endpoint URL and token. The endpoint returns a JSON array of parameter sets.

## Template Override

Per-generator template overrides the top-level template:

```yaml
generators:
  - list:
      elements:
        - name: special-app
          namespace: special
      template:
        metadata:
          name: 'override-{{.name}}'      # Overrides top-level template
        spec:
          project: special-project
template:
  metadata:
    name: 'default-{{.name}}'             # Used by other generators
  spec:
    project: default
```

## Progressive Syncs (RollingSync)

Roll out generated Applications in stages:

```yaml
spec:
  strategy:
    type: RollingSync
    rollingSync:
      steps:
        - matchExpressions:
            - key: envLabel
              operator: In
              values:
                - dev
          maxUpdate: 100%                  # Deploy all dev apps first
        - matchExpressions:
            - key: envLabel
              operator: In
              values:
                - staging
          maxUpdate: 100%                  # Then all staging
        - matchExpressions:
            - key: envLabel
              operator: In
              values:
                - production
          maxUpdate: 25%                   # Then 25% of prod at a time
```

**Step fields:**
- `matchExpressions` — Label selectors to match Applications generated by this step. Labels come from `template.metadata.labels`.
- `maxUpdate` — How many Applications to sync in parallel. Integer count or percentage string.

Applications must have labels matching the `matchExpressions` for steps to apply. Unmatched Applications sync in the final implicit step.

## Sync Policy for ApplicationSets

Controls what happens when the ApplicationSet or its generators change:

```yaml
spec:
  syncPolicy:
    preserveResourcesOnDeletion: true   # When AppSet is deleted, keep managed Applications' cluster resources
    applicationsSync: create-only       # Only create, never update existing Applications
    # applicationsSync: create-update   # Create and update (default)
    # applicationsSync: create-delete   # Create and delete, but don't update
```

## preserveResourcesOnDeletion

```yaml
spec:
  preserveResourcesOnDeletion: true
```

When the ApplicationSet is deleted:
- `false` (default) — All generated Applications and their cluster resources are deleted
- `true` — Generated Applications are deleted, but their managed cluster resources are left in place (orphaned)

This is a safety mechanism. Use `true` in production to prevent accidental mass deletion.

## templatePatch

Apply a JSON merge patch to the generated Application template based on generator parameters:

```yaml
spec:
  goTemplate: true
  generators:
    - list:
        elements:
          - name: my-app
            autoSync: "true"
  template:
    metadata:
      name: '{{.name}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        path: 'apps/{{.name}}'
        targetRevision: main
      destination:
        server: https://kubernetes.default.svc
  templatePatch: |
    {{- if eq .autoSync "true" }}
    spec:
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
    {{- end }}
```

This is useful for conditionally adding fields to the Application spec based on generator parameters without duplicating templates.
