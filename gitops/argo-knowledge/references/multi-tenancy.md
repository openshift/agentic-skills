# Argo CD Multi-Tenancy and Multi-Instance Patterns

Reference for running Argo CD in multi-tenant environments — from single-instance with
AppProjects to multiple instances and the Applications-in-any-namespace feature.

## Applications in Any Namespace (v2.5+)

Allows Application resources to live outside the `argocd` namespace, enabling teams
to manage their own Applications declaratively in their own namespaces.

**Docs:** [argo-cd.readthedocs.io/en/stable/operator-manual/app-any-namespace/](https://argo-cd.readthedocs.io/en/stable/operator-manual/app-any-namespace/)

### Prerequisites

- **Cluster-scoped Argo CD installation** — does NOT work with namespace-scoped installs
- **Switch resource tracking** — change from `label` (default) to `annotation` or `annotation+label` because
  composite names (`<namespace>/<name>`) can exceed the 63-char label limit

### Enabling

Option 1 — Startup flag on both `argocd-server` and `argocd-application-controller`:
```
--application-namespaces=team-a,team-b,app-*
```

Option 2 — ConfigMap `argocd-cmd-params-cm`:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  application.namespaces: team-a, team-b, app-*
```

Supports shell-style wildcards (`app-*`) and regex (`/^((?!excluded).)*$/`).

After changing, restart workloads:
```bash
kubectl rollout restart -n argocd deployment argocd-server
kubectl rollout restart -n argocd statefulset argocd-application-controller
```

### AppProject sourceNamespaces

Each AppProject must explicitly allow namespaces via `.spec.sourceNamespaces`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-frontend
  namespace: argocd
spec:
  sourceNamespaces:
    - team-frontend-apps
    - team-frontend-staging
  sourceRepos:
    - https://github.com/org/frontend-*.git
  destinations:
    - server: https://kubernetes.default.svc
      namespace: frontend-*
```

An Application in `team-frontend-apps` can only reference `team-frontend` project.
Referencing any other project is a permission violation.

### Application Naming

Applications are now referenced as `<namespace>/<name>`:
```bash
argocd app get team-frontend-apps/webapp
argocd app sync team-frontend-apps/webapp
```

For apps in `argocd` namespace, the prefix is optional (backward compatible).

### RBAC Changes

RBAC syntax becomes `<project>/<namespace>/<application>`:
```
p, frontend-devs, applications, get, team-frontend/team-frontend-apps/*, allow
p, frontend-devs, applications, sync, team-frontend/team-frontend-apps/*, allow
```

Wildcard across namespaces:
```
p, frontend-devs, applications, get, team-frontend/*/*, allow
```

### Security Constraints

- **Never add user-controlled namespaces to the `default` AppProject** — this bypasses isolation
- **Never grant `sourceNamespaces` access to the `argocd` namespace** in a tenant AppProject
- **ApplicationSets cannot generate Applications cross-namespace** (issue #11104)
- **Extend RBAC for argocd-server** to cover tenant namespaces:
  ```bash
  kubectl apply -k examples/k8s-rbac/argocd-server-applications/
  ```

## Multi-Tenancy Patterns

### Pattern 1: Single Instance + AppProjects (Recommended)

One Argo CD instance, team isolation via AppProjects.

```
argocd/                          # Single Argo CD install
├── argocd-server
├── argocd-application-controller (--application-namespaces=team-*)
├── argocd-repo-server
└── argocd-redis

team-frontend-apps/              # Team namespace
├── Application: webapp
├── Application: api-gateway
└── (references AppProject: team-frontend)

team-backend-apps/               # Team namespace
├── Application: payments
├── Application: users
└── (references AppProject: team-backend)
```

**Checklist:**
- [ ] One AppProject per team with restricted sourceRepos and destinations
- [ ] `sourceNamespaces` configured per project
- [ ] SSO groups mapped to project roles
- [ ] Cluster resource access denied by default (explicit allowlist)
- [ ] Sync windows for production namespaces
- [ ] Resource quotas per team namespace
- [ ] Network policies between tenant namespaces
- [ ] `--application-namespaces` configured with specific namespaces (not `*`)

### Pattern 2: Multiple Instances (Hard Isolation)

Separate Argo CD deployments per team in dedicated namespaces.

```
argocd-team-a/                   # Team A's Argo CD
├── argocd-server
├── argocd-application-controller
├── argocd-repo-server
└── argocd-redis

argocd-team-b/                   # Team B's Argo CD
├── argocd-server
├── argocd-application-controller
├── argocd-repo-server
└── argocd-redis
```

**When to use:**
- Regulatory/compliance requires complete isolation
- Teams need different Argo CD versions
- Independent upgrade cycles required
- Blast radius must be zero between teams

**Trade-offs:**
- Higher resource consumption (full Argo CD stack per team)
- Higher operational overhead (upgrades, monitoring, RBAC per instance)
- CRDs are cluster-wide — all instances share the same CRD definitions
- Each instance manages its own ConfigMaps/Secrets in its namespace

### Comparison

| Aspect | Single + AppProjects | Multiple Instances |
|--------|---------------------|-------------------|
| Isolation | Soft (RBAC) | Hard (process) |
| Resource cost | Low | High (N × full stack) |
| Operational overhead | Low | High |
| Upgrade coordination | One upgrade | N independent upgrades |
| Recommended for | Most organizations | Regulated / compliance |
| Max teams | 100+ | < 10 |

## Argo CD Autopilot

**Project:** [argoproj-labs/argocd-autopilot](https://github.com/argoproj-labs/argocd-autopilot)
**Status:** Pre-v1 (v0.4.20), under active development, not production-ready
**Supports:** Raw YAML and Kustomize (Helm not yet supported)

Autopilot is an opinionated CLI for bootstrapping Argo CD with a self-managing GitOps
repository structure.

### What It Does

1. `argocd-autopilot repo bootstrap` — installs Argo CD on a cluster and creates a
   self-managing Application in Git (Argo CD manages its own installation via GitOps)
2. `argocd-autopilot project create` — creates AppProjects with directory structure
3. `argocd-autopilot app create` — adds applications with base + overlay pattern
4. After bootstrap, Autopilot only needs Git access (no direct cluster access)

### Repository Structure

```
bootstrap/
├── argo-cd/                     # Argo CD installation manifests
└── cluster-resources/           # Cluster-scoped resources
projects/
├── team-a.yaml                  # AppProject definitions
└── team-b.yaml
apps/
├── webapp/
│   ├── base/                    # Shared config
│   └── overlays/
│       ├── staging/
│       └── production/
└── api/
    ├── base/
    └── overlays/
```

### Disaster Recovery

The primary value proposition: bootstrap a new cluster from the Git repo and all
projects, applications, and configuration are automatically restored.

```bash
argocd-autopilot repo bootstrap \
  --repo https://github.com/org/gitops.git \
  --token $GITHUB_TOKEN
```

### Limitations

- Pre-v1, not production-ready
- No Helm support yet (only raw YAML and Kustomize)
- Opinionated structure — may not fit existing repo layouts
