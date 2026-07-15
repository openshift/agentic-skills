# GitOps Repository Patterns Reference

## Overview

The structure of your Git repositories determines how Argo CD discovers, manages, and deploys applications. Choosing the right pattern affects team autonomy, blast radius, scalability, and operational complexity.

## Pattern 1: App of Apps

A root Application manages child Applications. The root Application points to a directory containing Application manifests.

### Structure

```
gitops-repo/
├── root-app.yaml                    # Root Application (bootstraps everything)
└── apps/
    ├── app-a.yaml                   # Child Application manifest
    ├── app-b.yaml                   # Child Application manifest
    ├── app-c.yaml                   # Child Application manifest
    └── platform/
        ├── cert-manager.yaml
        ├── ingress-nginx.yaml
        └── monitoring.yaml
```

### Root Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/gitops-repo.git
    targetRevision: main
    path: apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd                    # Child Applications created in argocd namespace
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Child Application

```yaml
# apps/app-a.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-a
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/org/app-a.git
    targetRevision: main
    path: deploy/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: app-a
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### When to Use

- Small to medium number of applications (< 50)
- Each application needs unique, hand-crafted configuration
- You want full visibility into each Application manifest in Git
- Bootstrap/initial cluster setup

### Trade-offs

- **Pro:** Full control over each Application; easy to understand
- **Pro:** Sync waves on child Applications control deploy order
- **Con:** Manual maintenance of each Application YAML
- **Con:** No auto-discovery of new applications
- **Con:** Can become unwieldy at scale (hundreds of files)

## Pattern 2: ApplicationSet

Use ApplicationSet generators to auto-create Applications from patterns.

### Structure

```
gitops-repo/
├── applicationset.yaml              # ApplicationSet definition
└── apps/
    ├── app-a/
    │   ├── kustomization.yaml
    │   └── deployment.yaml
    ├── app-b/
    │   ├── kustomization.yaml
    │   └── deployment.yaml
    └── app-c/
        ├── kustomization.yaml
        └── deployment.yaml
```

### ApplicationSet Definition

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: apps
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  generators:
    - git:
        repoURL: https://github.com/org/gitops-repo.git
        revision: main
        directories:
          - path: apps/*
  template:
    metadata:
      name: '{{.path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/gitops-repo.git
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
```

### When to Use

- Many applications following a common pattern
- Auto-discovery of new applications (add a directory = get an Application)
- Multi-cluster deployments (cluster generator)
- Dynamic environments (PR preview environments)

### Trade-offs

- **Pro:** Auto-discovery; add a directory and Application appears
- **Pro:** Consistent configuration across all generated Applications
- **Pro:** Progressive syncs for controlled rollout
- **Con:** Less flexibility per Application (all share a template)
- **Con:** Harder to debug template rendering issues
- **Con:** `preserveResourcesOnDeletion` should be `true` in production

## Pattern 3: Monorepo

Single repository containing all application manifests, organized by directory.

### Structure

```
k8s-configs/
├── base/                            # Shared base manifests
│   ├── app-a/
│   │   ├── kustomization.yaml
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   └── app-b/
│       ├── kustomization.yaml
│       ├── deployment.yaml
│       └── service.yaml
├── overlays/
│   ├── dev/
│   │   ├── app-a/
│   │   │   ├── kustomization.yaml
│   │   │   └── patch-replicas.yaml
│   │   └── app-b/
│   │       └── kustomization.yaml
│   ├── staging/
│   │   ├── app-a/
│   │   │   └── kustomization.yaml
│   │   └── app-b/
│   │       └── kustomization.yaml
│   └── production/
│       ├── app-a/
│       │   ├── kustomization.yaml
│       │   └── patch-replicas.yaml
│       └── app-b/
│           └── kustomization.yaml
└── platform/                        # Platform services
    ├── cert-manager/
    ├── ingress-nginx/
    └── monitoring/
```

### Application per Environment

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-a-production
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-configs.git
    targetRevision: main
    path: overlays/production/app-a
  destination:
    server: https://kubernetes.default.svc
    namespace: app-a
```

### When to Use

- Centralized platform team managing all configurations
- Kustomize-based overlays for environment differences
- Want atomic commits across multiple applications
- Tight coupling between application configs

### Trade-offs

- **Pro:** Single source of truth; atomic cross-app changes
- **Pro:** Works naturally with Kustomize bases/overlays
- **Pro:** Easy to audit and review all changes in one place
- **Con:** Large repo can be slow to clone/sync
- **Con:** Broad blast radius — bad commit affects everything
- **Con:** Access control is repo-wide (use CODEOWNERS for review gating)

## Pattern 4: Multi-Repo

Separate Git repositories per team or service.

### Structure

```
# Repo: org/app-a
app-a/
├── src/                             # Application source code
├── Dockerfile
└── deploy/
    ├── base/
    │   ├── kustomization.yaml
    │   ├── deployment.yaml
    │   └── service.yaml
    └── overlays/
        ├── dev/
        ├── staging/
        └── production/

# Repo: org/app-b
app-b/
├── src/
├── Dockerfile
└── deploy/
    └── ...

# Repo: org/platform-config
platform-config/
├── cert-manager/
├── ingress-nginx/
└── monitoring/
```

### When to Use

- Multiple autonomous teams owning their deployment configs
- Different release cadences per service
- Teams need independent Git access control
- Microservices architecture with clear ownership boundaries

### Trade-offs

- **Pro:** Team autonomy; each team owns their deploy config
- **Pro:** Independent release cycles
- **Pro:** Fine-grained Git access control
- **Con:** Cross-cutting changes require multiple PRs
- **Con:** Harder to ensure consistency across repos
- **Con:** Need a registry pattern (app-of-apps or ApplicationSet) to discover repos

## Pattern 5: Environment Branch

Separate Git branches per environment (dev, staging, production).

### Structure

```
# Branch: main (or dev)
├── apps/
│   ├── app-a/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   └── app-b/
│       └── ...

# Branch: staging
├── apps/
│   ├── app-a/
│   │   ├── deployment.yaml    # Different image tag
│   │   └── service.yaml
│   └── app-b/
│       └── ...

# Branch: production
├── apps/
│   └── ...
```

### Application per Branch

```yaml
# Dev
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-a-dev
spec:
  source:
    repoURL: https://github.com/org/configs.git
    targetRevision: main
    path: apps/app-a

# Production
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-a-prod
spec:
  source:
    repoURL: https://github.com/org/configs.git
    targetRevision: production
    path: apps/app-a
```

### When to Use

- Simple promotion model (merge dev -> staging -> production)
- Teams familiar with branch-based workflows
- Small number of environments

### Trade-offs

- **Pro:** Simple mental model; promotion = merge/cherry-pick
- **Pro:** Easy to diff between environments (branch diff)
- **Con:** Merge conflicts between branches
- **Con:** Branch drift is hard to detect and fix
- **Con:** Doesn't scale well with many environments
- **Con:** Generally **not recommended** — prefer directory-based overlays

## Choosing a Pattern

| Factor | App of Apps | ApplicationSet | Monorepo | Multi-Repo | Env Branch |
|--------|-----------|---------------|---------|-----------|-----------|
| Scale (# apps) | Small-Med | Large | Med-Large | Large | Small |
| Auto-discovery | No | Yes | No | No | No |
| Team autonomy | Low | Low | Low | High | Medium |
| Consistency | Manual | Enforced | Manual | Varies | Manual |
| Multi-cluster | Manual | Built-in | Manual | Manual | Manual |
| Complexity | Low | Medium | Low | Medium | Low |
| Recommended | Bootstrap | At scale | Centralized | Distributed teams | Avoid |

### Common Combinations

1. **ApplicationSet + Monorepo** — Git directory generator discovers apps from a monorepo. Best for platform teams.
2. **ApplicationSet + Multi-Repo** — SCM provider generator discovers repos from a GitHub org. Best for distributed teams.
3. **App-of-Apps + Multi-Repo** — Root app bootstraps child apps pointing to team repos. Good for medium-scale.
4. **ApplicationSet (cluster generator) + Monorepo** — Deploy same apps to all clusters. Best for multi-cluster platforms.

## Anti-Patterns

1. **Storing secrets in Git** — Use sealed-secrets, external-secrets, or Vault CSI provider instead.
2. **One giant Application** — Break into logical units. Each Application should map to a team or service boundary.
3. **Environment branches for more than 3 environments** — Use Kustomize overlays or Helm values per environment instead.
4. **Mixing app source code and deploy manifests in the same commit flow** — Separate CI (build) from CD (deploy). Use image updater or CI-triggered Git commits.
5. **No AppProject restrictions** — Always use AppProjects to limit blast radius, especially in multi-tenant setups.
