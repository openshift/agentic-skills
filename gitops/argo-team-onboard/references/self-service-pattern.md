# Self-Service Onboarding Pattern

PR-driven team onboarding using ApplicationSet or Kustomize overlays.
Teams add themselves to a config file, platform team reviews and merges,
Argo CD provisions everything automatically.

## teams.yaml Schema

Central registry of onboarded teams. Lives in the GitOps repo.

```yaml
# teams.yaml — single source of truth for tenant configuration
teams:
  - name: payments                                   # Team identifier (used in resource names)
    repos:
      - https://github.com/acme/payments-api.git
      - https://github.com/acme/payments-worker.git
    namespaces:                                      # All namespaces this team can target
      - payments-dev
      - payments-staging
      - payments-prod
    sourceType: kustomize                            # kustomize | helm | directory
    ssoGroup: acme-payments-developers               # IdP group for RBAC binding
    ssoGroupReadonly: acme-payments-viewers           # Optional: read-only access group
    quotaTier: medium                                # small | medium | large
    environments:
      - name: dev
        namespace: payments-dev
        cluster: https://kubernetes.default.svc
        autoSync: true                               # Automated sync + prune + selfHeal
        path: deploy/overlays/dev                    # Source path in repo
      - name: staging
        namespace: payments-staging
        cluster: https://kubernetes.default.svc
        autoSync: true
        path: deploy/overlays/staging
      - name: prod
        namespace: payments-prod
        cluster: https://kubernetes.default.svc
        autoSync: false                              # Manual sync for production
        path: deploy/overlays/prod
    notifications:                                   # Optional
      slack: "#payments-deploys"
    syncWindows:                                     # Optional — applied to prod only
      denyWeekends: true

  - name: checkout
    repos:
      - https://github.com/acme/checkout-service.git
    namespaces:
      - checkout-dev
      - checkout-staging
      - checkout-prod
    sourceType: helm
    ssoGroup: acme-checkout-developers
    quotaTier: small
    environments:
      - name: dev
        namespace: checkout-dev
        cluster: https://kubernetes.default.svc
        autoSync: true
        chart: checkout                              # Helm-specific fields
        chartRepo: https://charts.acme.com
        chartVersion: "2.1.0"
      - name: staging
        namespace: checkout-staging
        cluster: https://kubernetes.default.svc
        autoSync: true
        chart: checkout
        chartRepo: https://charts.acme.com
        chartVersion: "2.1.0"
      - name: prod
        namespace: checkout-prod
        cluster: https://kubernetes.default.svc
        autoSync: false
        chart: checkout
        chartRepo: https://charts.acme.com
        chartVersion: "2.1.0"
```

### Schema Field Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | string | Team identifier. Used in resource names: `team-<name>`, `<name>-<env>` |
| `repos` | Yes | list[string] | Git repo URLs for `sourceRepos`. Helm chart repos go in `environments[].chartRepo` |
| `namespaces` | Yes | list[string] | All namespaces team can deploy to. Maps to AppProject `destinations` |
| `sourceType` | Yes | enum | `kustomize`, `helm`, or `directory`. Determines Application source config |
| `ssoGroup` | Yes | string | IdP/SSO group for developer role binding |
| `ssoGroupReadonly` | No | string | IdP/SSO group for viewer role binding |
| `quotaTier` | No | enum | `small`, `medium`, `large`. Maps to ResourceQuota templates. Default: `small` |
| `environments` | Yes | list[object] | Per-environment config. At least one entry required |
| `environments[].name` | Yes | string | Environment identifier (dev, staging, prod) |
| `environments[].namespace` | Yes | string | Target namespace. Must exist in `namespaces` list |
| `environments[].cluster` | Yes | string | Cluster API URL |
| `environments[].autoSync` | Yes | bool | Enable automated sync. `false` for production recommended |
| `environments[].path` | Conditional | string | Git path for kustomize/directory source types |
| `environments[].chart` | Conditional | string | Helm chart name (helm sourceType only) |
| `environments[].chartRepo` | Conditional | string | Helm chart repository URL (helm sourceType only) |
| `environments[].chartVersion` | Conditional | string | Helm chart version (helm sourceType only) |
| `notifications.slack` | No | string | Slack channel for sync notifications |
| `syncWindows.denyWeekends` | No | bool | Add Fri 6pm - Mon 8am deny window to prod |

## ApplicationSet Approach

Use a git-file generator to read `teams.yaml` and produce AppProject + Application per team per environment.

### AppProject Generator

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: team-projects
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  generators:
    - git:
        repoURL: https://github.com/{{ORG}}/gitops-platform.git
        revision: main
        files:
          - path: teams.yaml
  template:
    metadata:
      name: 'appproject-{{ range .teams }}{{ .name }}{{ end }}'
    spec:
      # This ApplicationSet creates one Application per team.
      # That Application points to a rendered AppProject manifest.
      project: default
      source:
        repoURL: https://github.com/{{ORG}}/gitops-platform.git
        targetRevision: main
        path: 'generated/projects'                   # Pre-rendered by CI or controller
      destination:
        server: https://kubernetes.default.svc
        namespace: argocd
```

The above is complex. A simpler pattern uses one ApplicationSet per resource type:

### Per-Team AppProject + Applications (Recommended)

```yaml
# ApplicationSet: one AppProject per team
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: team-onboarding
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  generators:
    - git:
        repoURL: https://github.com/acme/gitops-platform.git
        revision: main
        files:
          - path: "teams/*/config.yaml"              # One file per team
  template:
    metadata:
      name: 'team-{{ .team.name }}-onboarding'
    spec:
      project: default                               # Platform-level project
      source:
        repoURL: https://github.com/acme/gitops-platform.git
        targetRevision: main
        path: 'teams/{{ .team.name }}/manifests'     # Team's rendered manifests
      destination:
        server: https://kubernetes.default.svc
        namespace: argocd
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

Each team directory contains pre-rendered manifests:

```
teams/
├── payments/
│   ├── config.yaml                                  # Team config (subset of teams.yaml)
│   └── manifests/
│       ├── appproject.yaml                          # Rendered AppProject
│       ├── app-dev.yaml                             # Application for dev
│       ├── app-staging.yaml                         # Application for staging
│       ├── app-prod.yaml                            # Application for prod
│       ├── ns-dev.yaml                              # Namespace
│       ├── ns-staging.yaml
│       ├── ns-prod.yaml
│       ├── quota-dev.yaml                           # ResourceQuota (tier-based)
│       ├── quota-staging.yaml
│       └── quota-prod.yaml
└── checkout/
    ├── config.yaml
    └── manifests/
        └── ...
```

## Kustomize Overlay Approach

Alternative to ApplicationSet. Uses Kustomize bases and per-team overlays.

### Repository Structure

```
onboarding/
├── base/
│   ├── kustomization.yaml
│   ├── appproject.yaml                              # Templated base AppProject
│   ├── application.yaml                             # Templated base Application
│   ├── namespace.yaml
│   └── quotas/
│       ├── small.yaml
│       ├── medium.yaml
│       └── large.yaml
├── overlays/
│   ├── payments/
│   │   ├── kustomization.yaml                       # Patches for payments team
│   │   ├── appproject-patch.yaml
│   │   └── application-patch.yaml
│   └── checkout/
│       ├── kustomization.yaml
│       ├── appproject-patch.yaml
│       └── application-patch.yaml
└── kustomization.yaml                               # Top-level: includes all overlays
```

### Base AppProject

```yaml
# onboarding/base/appproject.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-PLACEHOLDER
  namespace: argocd
spec:
  description: "Team project"
  sourceRepos: []
  destinations: []
  clusterResourceWhitelist: []
  namespaceResourceBlacklist:
    - group: ''
      kind: ResourceQuota
    - group: ''
      kind: LimitRange
    - group: networking.k8s.io
      kind: NetworkPolicy
  orphanedResources:
    warn: true
  roles: []
```

### Base Kustomization

```yaml
# onboarding/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - appproject.yaml
  - application.yaml
  - namespace.yaml
```

### Team Overlay

```yaml
# onboarding/overlays/payments/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
patches:
  - path: appproject-patch.yaml
  - path: application-patch.yaml
namePrefix: ""                                       # No prefix needed, patches handle naming
```

```yaml
# onboarding/overlays/payments/appproject-patch.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-payments
  namespace: argocd
spec:
  description: "Payments team project"
  sourceRepos:
    - https://github.com/acme/payments-api.git
    - https://github.com/acme/payments-worker.git
  destinations:
    - server: https://kubernetes.default.svc
      namespace: payments-dev
    - server: https://kubernetes.default.svc
      namespace: payments-staging
    - server: https://kubernetes.default.svc
      namespace: payments-prod
  roles:
    - name: developer
      policies:
        - p, proj:team-payments:developer, applications, get, team-payments/*, allow
        - p, proj:team-payments:developer, applications, sync, team-payments/*, allow
        - p, proj:team-payments:developer, applications, action/*, team-payments/*, allow
      groups:
        - acme-payments-developers
```

### App-of-Apps for Overlays

One parent Application syncs all team overlays:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: team-onboarding
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/acme/gitops-platform.git
    targetRevision: main
    path: onboarding                                 # Top-level kustomization
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## PR-Based Workflow

### Step-by-Step

1. **Team submits PR** — adds entry to `teams.yaml` or creates overlay directory
2. **Automated validation** (CI):
   - YAML schema validation against teams.yaml schema
   - Namespace conflict check (no two teams share a namespace)
   - Repo URL format validation
   - SSO group exists in IdP (optional API check)
   - Kustomize build or ApplicationSet template dry-render
3. **Platform team reviews**:
   - Quota tier appropriate for team size
   - Source repos are correct and accessible
   - Namespace naming follows convention
   - No overly permissive destinations
4. **Merge** triggers Argo CD sync
5. **ApplicationSet generates** (or Kustomize renders) AppProject + Applications
6. **Applications sync** — team's namespaces and resources are live
7. **Notify team** — Slack/email with Argo CD UI link and getting-started instructions

### PR Validation Script

```bash
#!/usr/bin/env bash
# validate-team-pr.sh — run in CI on PRs touching teams.yaml
set -euo pipefail

TEAMS_FILE="${1:-teams.yaml}"

# 1. YAML syntax
yq eval '.' "$TEAMS_FILE" > /dev/null || { echo "FAIL: invalid YAML"; exit 1; }

# 2. Required fields
for team in $(yq eval '.teams[].name' "$TEAMS_FILE"); do
  repos=$(yq eval ".teams[] | select(.name == \"$team\") | .repos | length" "$TEAMS_FILE")
  envs=$(yq eval ".teams[] | select(.name == \"$team\") | .environments | length" "$TEAMS_FILE")
  sso=$(yq eval ".teams[] | select(.name == \"$team\") | .ssoGroup" "$TEAMS_FILE")

  [[ "$repos" -gt 0 ]] || { echo "FAIL: $team has no repos"; exit 1; }
  [[ "$envs" -gt 0 ]] || { echo "FAIL: $team has no environments"; exit 1; }
  [[ -n "$sso" && "$sso" != "null" ]] || { echo "FAIL: $team has no ssoGroup"; exit 1; }
done

# 3. Namespace uniqueness across all teams
all_ns=$(yq eval '.teams[].namespaces[]' "$TEAMS_FILE" | sort)
dupes=$(echo "$all_ns" | uniq -d)
[[ -z "$dupes" ]] || { echo "FAIL: duplicate namespaces: $dupes"; exit 1; }

# 4. No wildcard repos
wildcards=$(yq eval '.teams[].repos[]' "$TEAMS_FILE" | grep -c '^\*$' || true)
[[ "$wildcards" -eq 0 ]] || { echo "FAIL: wildcard repo detected"; exit 1; }

echo "PASS: all validations passed"
```

## Guard Rails: Platform vs Team

### Platform Team Controls (Immutable Base)

| Resource | Platform Controls | Cannot Be Changed By Team |
|----------|------------------|--------------------------|
| AppProject | `namespaceResourceBlacklist`, `clusterResourceWhitelist`, `orphanedResources` | Teams cannot unblock ResourceQuota, NetworkPolicy |
| ResourceQuota | Tier definitions (small/medium/large compute limits) | Teams choose a tier, cannot define custom limits |
| LimitRange | Default/max container resource bounds | Teams cannot override min/max |
| RBAC baseline | No `delete`, `override`, or `exec` in developer role | Teams cannot escalate permissions |
| Sync windows | Production deny-window templates | Teams can opt in/out, cannot modify window schedule |
| Base templates | AppProject and Application structure, required labels | Teams cannot remove finalizers, change sync options |

### Team Controls (Customizable)

| Field | Team Configures | Constraints |
|-------|----------------|-------------|
| `repos` | Git repository URLs | Must be valid URLs, no wildcards |
| `namespaces` | Target namespace names | Must follow `<team>-<env>` convention, unique across all teams |
| `sourceType` | kustomize, helm, directory | Must be a supported type |
| `ssoGroup` | SSO/IdP group name | Must exist in IdP |
| `quotaTier` | small, medium, large | Must be a defined tier |
| `environments[].autoSync` | true/false per env | Recommended: false for prod |
| `environments[].path` | Git path to manifests | Must exist in declared repo |
| `notifications.slack` | Slack channel | Must be a channel the bot can post to |

### Escalation Path

If a team needs something outside the guard rails:

1. **Custom quota** — open a platform ticket, platform team creates a custom tier
2. **Cluster-scoped resources** — requires platform team approval, added to `clusterResourceWhitelist`
3. **Cross-namespace access** — requires architecture review, separate AppProject entry
4. **exec access** — requires security review, added per-project with audit logging
