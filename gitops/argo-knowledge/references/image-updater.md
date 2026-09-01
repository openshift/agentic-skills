# Argo CD Image Updater Reference

## Overview

Argo CD Image Updater is a tool that automatically updates container image versions in Argo CD Applications. It watches container registries for new image versions and updates the Application accordingly.

## How It Works

1. Image Updater watches Applications with image-updater annotations
2. It queries container registries for available image tags
3. Based on the update strategy, it selects the newest/best tag
4. It updates the Application via parameter overrides (argocd method) or Git commit (git method)

## Annotation Reference

All annotations are placed on the Application resource's metadata.

### Image List

```yaml
argocd-image-updater.argoproj.io/image-list: <alias>=<image>[:<version-constraint>]
```

Examples:
```yaml
# Single image with alias
argocd-image-updater.argoproj.io/image-list: myapp=registry.example.com/my-app

# Multiple images
argocd-image-updater.argoproj.io/image-list: >-
  frontend=registry.example.com/frontend,
  backend=registry.example.com/backend

# With semver constraint
argocd-image-updater.argoproj.io/image-list: myapp=registry.example.com/my-app:~1.2

# Semver constraints
# ~1.2   = >=1.2.0, <1.3.0
# ^1.2   = >=1.2.0, <2.0.0
# 1.x    = >=1.0.0, <2.0.0
# >=1.2  = >=1.2.0
# 1.2.x  = >=1.2.0, <1.3.0
```

### Update Strategy

```yaml
argocd-image-updater.argoproj.io/<alias>.update-strategy: <strategy>
```

| Strategy | Description | Use When |
|----------|-------------|----------|
| `semver` | Select highest semver tag matching constraint | Tags follow semantic versioning |
| `latest` | Select most recently built image | Tags are arbitrary (git SHAs, timestamps) |
| `digest` | Select most recently pushed digest | Always pull latest, track by digest |
| `name` | Select alphabetically last tag | Tags are sortable strings (e.g., dates) |

Default: `semver`

### Tag Filtering

```yaml
# Allow only tags matching regex
argocd-image-updater.argoproj.io/<alias>.allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"

# Shorthand: fn prefix for named functions
argocd-image-updater.argoproj.io/<alias>.allow-tags: "regexp:^(main|release)-[a-f0-9]{7}$"

# Ignore specific tags
argocd-image-updater.argoproj.io/<alias>.ignore-tags: "latest,dev,nightly"

# Ignore tags matching pattern
argocd-image-updater.argoproj.io/<alias>.ignore-tags: "regexp:^.*-rc[0-9]+$"
```

### Pull Secret

```yaml
# Reference a Kubernetes Secret
argocd-image-updater.argoproj.io/<alias>.pull-secret: pullsecret:<namespace>/<secret-name>

# Reference a Secret in the Argo CD namespace
argocd-image-updater.argoproj.io/<alias>.pull-secret: pullsecret:argocd/registry-creds

# Use environment variable
argocd-image-updater.argoproj.io/<alias>.pull-secret: env:DOCKER_PASSWORD

# Use script
argocd-image-updater.argoproj.io/<alias>.pull-secret: ext:/path/to/script
```

Secret format for `pullsecret`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: registry-creds
  namespace: argocd
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded-docker-config>
```

### Helm Integration

Map images to Helm value parameters:

```yaml
# Set the image name and tag via Helm values
argocd-image-updater.argoproj.io/<alias>.helm.image-name: image.repository
argocd-image-updater.argoproj.io/<alias>.helm.image-tag: image.tag

# For charts using a single image value
argocd-image-updater.argoproj.io/<alias>.helm.image-spec: image
```

This translates to Helm parameter overrides:
```
--set image.repository=registry.example.com/my-app
--set image.tag=v1.2.3
```

### Kustomize Integration

```yaml
# Override the original image name in kustomization.yaml
argocd-image-updater.argoproj.io/<alias>.kustomize.image-name: original-image-name

# Example: if kustomization.yaml has "nginx:1.19", and you want to override:
argocd-image-updater.argoproj.io/image-list: myapp=registry.example.com/my-nginx
argocd-image-updater.argoproj.io/myapp.kustomize.image-name: nginx
```

### Write-Back Method

```yaml
# Method: argocd (parameter overrides) or git (commit to repo)
argocd-image-updater.argoproj.io/write-back-method: git

# Git target for write-back
# Format: <file-type>[:<path>]
argocd-image-updater.argoproj.io/write-back-target: kustomization
# OR
argocd-image-updater.argoproj.io/write-back-target: helmvalues:path/to/values.yaml
# OR (default for git method)
argocd-image-updater.argoproj.io/write-back-target: argocd

# Git branch for write-back (default: same as targetRevision)
argocd-image-updater.argoproj.io/git-branch: main

# Custom commit message template
argocd-image-updater.argoproj.io/write-back-method: "git:message=build: update {{range .Changes}}{{.Image}} to {{.NewTag}}{{end}}"
```

## Update Strategies Detailed

### semver

Selects the highest tag matching semver constraints:

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: app=reg.io/app:~1.2
  argocd-image-updater.argoproj.io/app.update-strategy: semver
```

Tags must be valid semver (with optional `v` prefix). Non-semver tags are ignored.

Constraint syntax:
- `~1.2.3` — Patch-level changes: `>=1.2.3, <1.3.0`
- `^1.2.3` — Minor-level changes: `>=1.2.3, <2.0.0`
- `1.x` — Any `1.*.*` version
- `>=1.2, <2.0` — Explicit range
- No constraint — Latest semver tag

### latest

Selects the most recently built image by creation timestamp:

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: app=reg.io/app
  argocd-image-updater.argoproj.io/app.update-strategy: latest
  argocd-image-updater.argoproj.io/app.allow-tags: "regexp:^main-[a-f0-9]{7}$"
```

Requires registry API support for image metadata. Works with most registries.

### digest

Tracks the latest digest for a specific tag:

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: app=reg.io/app:latest
  argocd-image-updater.argoproj.io/app.update-strategy: digest
```

Useful when a mutable tag (like `latest`) is updated in-place. Updates the Application to use `image@sha256:...`.

### name

Selects the alphabetically last tag:

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: app=reg.io/app
  argocd-image-updater.argoproj.io/app.update-strategy: name
  argocd-image-updater.argoproj.io/app.allow-tags: "regexp:^20[0-9]{6}-[0-9]+$"
```

Useful for date-based tags like `20240115-1`, `20240116-2`.

## Registries Configuration

Configure container registries in the `argocd-image-updater-config` ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  registries.conf: |
    registries:
      - name: Docker Hub
        prefix: docker.io
        api_url: https://registry-1.docker.io
        credentials: secret:argocd/dockerhub-creds#creds
        default: true
        defaultns: library

      - name: GitHub Container Registry
        prefix: ghcr.io
        api_url: https://ghcr.io
        credentials: secret:argocd/ghcr-creds#creds

      - name: ECR
        prefix: 123456789.dkr.ecr.us-east-1.amazonaws.com
        api_url: https://123456789.dkr.ecr.us-east-1.amazonaws.com
        credentials: ext:/scripts/ecr-login.sh
        credsexpire: 10h

      - name: Private Registry
        prefix: registry.example.com
        api_url: https://registry.example.com
        credentials: pullsecret:argocd/registry-creds
        insecure: false
        ping: true

  log.level: info
  applications_api: argocd
  git.commit-signing-key: ""
  git.commit-signing-method: ""
  git.commit-message-template: |
    build: update image(s)

    {{ range .Changes -}}
    updates image {{ .Image }} tag '{{ .OldTag }}' to '{{ .NewTag }}'
    {{ end -}}
```

## Write-Back Methods Detailed

### argocd (Parameter Overrides)

Default method. Updates the Application's parameter overrides directly:

```yaml
annotations:
  argocd-image-updater.argoproj.io/write-back-method: argocd
```

- Modifies the Application resource in Kubernetes
- Changes are visible in `app.spec.source.helm.parameters` or `app.spec.source.kustomize.images`
- No Git commits
- Changes are lost if the Application is recreated from Git
- Fastest method

### git (Git Commit)

Commits image updates to the Git repository:

```yaml
annotations:
  argocd-image-updater.argoproj.io/write-back-method: git
  argocd-image-updater.argoproj.io/git-branch: main
```

**For Helm:**

With `write-back-target: argocd` (default for git method), creates/updates `.argocd-source-<app-name>.yaml`:

```yaml
# .argocd-source-my-app.yaml (auto-generated)
helm:
  parameters:
    - name: image.tag
      value: v1.2.4
      forcestring: true
```

With `write-back-target: helmvalues:<path>`, modifies the values file directly.

**For Kustomize:**

With `write-back-target: kustomization`, updates the `kustomization.yaml` images section:

```yaml
# kustomization.yaml (modified by image updater)
images:
  - name: original-image
    newName: registry.example.com/my-app
    newTag: v1.2.4
```

### Git Credentials for Write-Back

Image updater uses the same credentials configured for the Application's source repo in Argo CD. Ensure the credentials have write (push) access.

For SSH:
```yaml
annotations:
  argocd-image-updater.argoproj.io/write-back-method: git
  argocd-image-updater.argoproj.io/git-branch: main
```

Argo CD repo credentials must have push access.

## Complete Example: Helm Application with Image Updater

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
  annotations:
    # Image list with semver constraint
    argocd-image-updater.argoproj.io/image-list: >-
      app=registry.example.com/my-app:~1.x,
      sidecar=registry.example.com/sidecar:^2.0

    # App image config
    argocd-image-updater.argoproj.io/app.update-strategy: semver
    argocd-image-updater.argoproj.io/app.allow-tags: "regexp:^v?[0-9]+\\.[0-9]+\\.[0-9]+$"
    argocd-image-updater.argoproj.io/app.helm.image-name: app.image.repository
    argocd-image-updater.argoproj.io/app.helm.image-tag: app.image.tag
    argocd-image-updater.argoproj.io/app.pull-secret: pullsecret:argocd/registry-creds

    # Sidecar image config
    argocd-image-updater.argoproj.io/sidecar.update-strategy: semver
    argocd-image-updater.argoproj.io/sidecar.helm.image-name: sidecar.image.repository
    argocd-image-updater.argoproj.io/sidecar.helm.image-tag: sidecar.image.tag

    # Write-back via Git
    argocd-image-updater.argoproj.io/write-back-method: git
    argocd-image-updater.argoproj.io/write-back-target: helmvalues:values.yaml
    argocd-image-updater.argoproj.io/git-branch: main
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-configs.git
    targetRevision: main
    path: apps/my-app
    helm:
      valueFiles:
        - values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## Troubleshooting

### Check Image Updater Logs

```bash
kubectl -n argocd logs deployment/argocd-image-updater
```

### Common Issues

1. **"could not get tags"** — Registry credentials missing or invalid. Check `pull-secret` annotation and registry config.
2. **"no updates found"** — `allow-tags` regex doesn't match any tags, or semver constraint too restrictive.
3. **"git push failed"** — Repository credentials don't have write access for `write-back-method: git`.
4. **Image updater ignoring Application** — Missing `image-list` annotation, or Application not in a watched namespace.
5. **Updates not triggering sync** — With `write-back-method: argocd`, ensure automated sync is enabled. With `write-back-method: git`, ensure Argo CD detects the commit.
