# GitOps Promoter

Reference for the gitops-promoter project — a Kubernetes-native environment promotion
tool that uses Git branches, pull requests, and commit statuses to gate promotions
through environment sequences.

**Project:** [argoproj-labs/gitops-promoter](https://github.com/argoproj-labs/gitops-promoter)
**Docs:** [gitops-promoter.readthedocs.io](https://gitops-promoter.readthedocs.io/en/latest/)
**Status:** Experimental (v0.31.0), active development, 461 stars
**API Group:** `promoter.argoproj.io/v1alpha1`

## Core Concepts

### How Promotion Works

1. A hydrator (CI pipeline, Argo CD, etc.) pushes rendered manifests to a `-next` branch
   (e.g., `environment/development-next`)
2. GitOps Promoter opens a PR from `-next` to the environment branch (`environment/development`)
3. Commit statuses gate the merge (security scans, health checks, tests)
4. When all checks pass and `autoMerge: true`, the PR merges automatically
5. The promoter then creates a PR for the next environment in the sequence
6. This continues until the change reaches the final environment (e.g., production)

### Key Principles

- **Drift-free:** promotion happens via Git merges, not file rewrites
- **PR-based gating:** every promotion is a reviewable pull request
- **Commit status gates:** both "active" (running in env) and "proposed" (pre-merge) checks
- **No fragile file changes:** the promoter doesn't modify user-facing files
- **Branch-per-environment:** each environment has its own Git branch

## CRDs

| Kind | apiVersion | Purpose |
|------|-----------|---------|
| PromotionStrategy | promoter.argoproj.io/v1alpha1 | Defines the environment sequence and gating rules |
| ChangeTransferPolicy | promoter.argoproj.io/v1alpha1 | Controls how changes transfer between branches (auto-generated) |
| ScmProvider | promoter.argoproj.io/v1alpha1 | SCM credentials and provider config (namespace-scoped) |
| ClusterScmProvider | promoter.argoproj.io/v1alpha1 | Cluster-scoped SCM provider config |
| GitRepository | promoter.argoproj.io/v1alpha1 | Repository reference (owner, name, SCM provider ref) |
| CommitStatus | promoter.argoproj.io/v1alpha1 | Set commit status on a SHA (pending/success/failure) |
| ArgoCDCommitStatus | promoter.argoproj.io/v1alpha1 | Auto-reports Argo CD Application health as a CommitStatus — see *Integration with Argo CD* |
| PullRequest | promoter.argoproj.io/v1alpha1 | Manage PR lifecycle (open/merged/closed) |
| RevertCommit | promoter.argoproj.io/v1alpha1 | Revert a specific commit |
| GitCommitStatus | promoter.argoproj.io/v1alpha1 | Commit status derived from Git state |
| TimedCommitStatus | promoter.argoproj.io/v1alpha1 | Time-based gate — soak/bake period before promotion |
| WebRequestCommitStatus | promoter.argoproj.io/v1alpha1 | Gate on an external HTTP check |
| ControllerConfiguration | promoter.argoproj.io/v1alpha1 | Promoter controller settings |

> To see what is actually installed on a cluster:
> `kubectl get crd -o name | grep promoter.argoproj.io`

### How a gate is matched to a commit status

A `PromotionStrategy` references gates by **key**, not by resource name:

```yaml
spec:
  activeCommitStatuses:
    - key: argocd-app-health      # matches a CommitStatus whose spec.name is this key
  proposedCommitStatuses:
    - key: security-scan
```

The key is matched against the CommitStatus resource's `spec.name`. Writing one from CI:

```yaml
apiVersion: promoter.argoproj.io/v1alpha1
kind: CommitStatus
metadata:
  name: security-scan-abc1234
spec:
  name: security-scan          # <- the key the PromotionStrategy gates on
  sha: abc1234def5678          # the commit being gated
  phase: success               # pending | success | failure
  description: "Trivy scan passed, 0 critical"
  url: https://ci.example.com/runs/4821   # surfaced in the SCM status check
  gitRepositoryRef:
    name: my-repo
```

Verified `spec` fields: `name`, `sha`, `phase`, `description`, `url`, `gitRepositoryRef`.

A gate whose key has no corresponding CommitStatus **blocks the promotion indefinitely**
rather than erroring — the PR simply never merges. When a promotion appears stuck with no
failure, list the statuses and compare keys before looking anywhere else:

```bash
kubectl get commitstatus -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,KEY:.spec.name,PHASE:.status.phase
```

## Supported SCM Providers

| Provider | Secret Key | ScmProvider Field |
|----------|-----------|------------------|
| GitHub | `githubAppPrivateKey` (GitHub App) | `github: {appID, installationID}` |
| GitLab | `token` (Access Token, Developer role, api + write_repository) | `gitlab: {}` |
| Forgejo / Codeberg | `token` (read/write repo) | `forgejo: {}` |
| Gitea | `token` (read/write repo) | `gitea: {domain}` |
| Bitbucket Cloud | `token` (repo access token, read/write repos + PRs) | `bitbucketCloud: {}` |
| Azure DevOps | `token` (PAT, Code read/write) | `azureDevOps: {organization}` |

## PromotionStrategy

The core CRD that defines the promotion pipeline:

```yaml
apiVersion: promoter.argoproj.io/v1alpha1
kind: PromotionStrategy
metadata:
  name: my-app
spec:
  gitRepositoryRef:
    name: my-repo

  # Commit statuses that gate ALL environments
  activeCommitStatuses:
    - key: argocd-app-health
  proposedCommitStatuses:
    - key: security-scan

  environments:
    - branch: environment/development
      # autoMerge defaults to true
    - branch: environment/staging
    - branch: environment/production
      autoMerge: false  # require manual merge for production
      activeCommitStatuses:
        - key: performance-test  # additional gate for prod only
      proposedCommitStatuses:
        - key: deployment-freeze  # block during freeze windows
```

### Environment Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `branch` | string | required | Active branch name for this environment |
| `autoMerge` | bool | `true` | Auto-merge PRs when all checks pass |
| `activeCommitStatuses` | list | `[]` | Additional checks for running deployments (per-env) |
| `proposedCommitStatuses` | list | `[]` | Additional checks before merge (per-env) |

### Commit Status Types

- **Active:** checked while a commit is live in an environment. If active status fails,
  the commit won't promote to the next environment. Use for: Argo CD app health,
  synthetic monitoring, error rate checks.
- **Proposed:** checked before merging a PR. If proposed status fails, the PR stays
  open. Use for: security scans, integration tests, deployment freezes.

### Monorepo Support

For monorepos with multiple apps sharing environment branches, use `activePath`:

```yaml
spec:
  activePath: apps/payments
  gitRepositoryRef:
    name: my-monorepo
  environments:
    - branch: environment/development
    - branch: environment/production
```

Proposed branches become `environment/development-next/apps/payments`, enabling
independent promotion per app on shared active branches.

## SCM Provider Setup

### GitHub (Recommended)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-app-secret
type: Opaque
stringData:
  githubAppPrivateKey: |
    <paste the GitHub App's PEM private key here, including its
     BEGIN/END lines, indented to this level>
---
apiVersion: promoter.argoproj.io/v1alpha1
kind: ScmProvider
metadata:
  name: github
spec:
  secretRef:
    name: github-app-secret
  github:
    appID: 123456
    installationID: 789012
---
apiVersion: promoter.argoproj.io/v1alpha1
kind: GitRepository
metadata:
  name: my-repo
spec:
  scmProviderRef:
    kind: ScmProvider
    name: github
  github:
    owner: my-org
    name: my-app
```

### GitLab

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-token
type: Opaque
stringData:
  token: <your-access-token>
---
apiVersion: promoter.argoproj.io/v1alpha1
kind: ScmProvider
metadata:
  name: gitlab
spec:
  secretRef:
    name: gitlab-token
  gitlab: {}
---
apiVersion: promoter.argoproj.io/v1alpha1
kind: GitRepository
metadata:
  name: my-repo
spec:
  scmProviderRef:
    kind: ScmProvider
    name: gitlab
  gitlab:
    name: my-app
    namespace: my-group/my-subgroup
    projectId: 12345
```

## Integration with Argo CD

GitOps Promoter is designed to work alongside Argo CD:

1. **Argo CD watches environment branches** — each environment branch (`environment/dev`,
   `environment/prod`) is a source for an Argo CD Application or ApplicationSet
2. **Argo CD reports health via CommitStatus** — use the `argocd-app-health` commit status
   key as an `activeCommitStatus` to gate promotions on Argo CD sync/health
3. **ArgoCD CommitStatus CRD** — the promoter includes an `ArgoCDCommitStatus` resource
   that automatically reports Argo CD Application health as a commit status

### Example: Argo CD Application per Environment

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-app
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - list:
        elements:
          - env: development
            branch: environment/development
            namespace: my-app-dev
          - env: staging
            branch: environment/staging
            namespace: my-app-staging
          - env: production
            branch: environment/production
            namespace: my-app-prod
  template:
    metadata:
      name: 'my-app-{{ .env }}'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/my-app.git
        targetRevision: '{{ .branch }}'
        path: .
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ .namespace }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

### Example: ArgoCD CommitStatus for Health Gating

```yaml
apiVersion: promoter.argoproj.io/v1alpha1
kind: ArgoCDCommitStatus        # note the capitalisation: ArgoCD, not Argocd
metadata:
  name: my-app-health
spec:
  # Both fields below are REQUIRED by the CRD.
  promotionStrategyRef:         # which PromotionStrategy this status feeds
    name: my-app-promotion
  applicationSelector:          # which Argo CD Applications to report health for
    matchLabels:
      app.kubernetes.io/name: my-app
  # url:                        # OPTIONAL — and it is an OBJECT, not a string.
  #   template: "https://argocd.example.com/applications/{{.app.metadata.name}}"
  #   options: []
  # A bare string here fails admission. Verified: `kubectl explain
  # argocdcommitstatus.spec.url` returns <Object> with template/options.
```

> Verified against the installed CRD: `spec` accepts **`promotionStrategyRef`**,
> **`applicationSelector`** (both required) and optional `url`. There is **no
> `gitRepositoryRef`** on this kind — that field belongs to `CommitStatus`, and using it
> here fails admission. Confirm on your cluster with:
> `kubectl explain argocdcommitstatus.spec`

This automatically creates CommitStatus resources reflecting the Argo CD Application
health, which the PromotionStrategy uses as an `activeCommitStatus` gate.

## Installation

### Manifest

```bash
kubectl apply -f https://github.com/argoproj-labs/gitops-promoter/releases/download/v0.31.0/install.yaml
```

### Helm

```bash
helm repo add gitops-promoter https://argoproj-labs.github.io/gitops-promoter
helm install gitops-promoter gitops-promoter/gitops-promoter -n gitops-promoter-system --create-namespace
```

### Dashboard UI

```bash
# Download CLI from releases page
gitops-promoter dashboard
# Opens at http://localhost:8080
```

## Important Notes

- **Branch naming convention is hard-coded:** proposed branches are always
  `<environment-branch>-next` (e.g., `environment/development-next`)
- **Don't auto-delete staging branches:** disable auto-deletion on `-next` branches
  or add branch protection rules for `environment/*-next`
- **Webhook recommended:** without webhooks, set lower reconciliation intervals via
  `ControllerConfiguration` (`promotionStrategyRequeueDuration`, `changeTransferPolicyRequeueDuration`)
- **GitLab limitation:** can't update existing commit status descriptions without a state transition
- **All resources must be in the same namespace:** ScmProvider, GitRepository, and
  PromotionStrategy must coexist in one namespace
