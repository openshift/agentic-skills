---
name: argo-knowledge
description: >
  Knowledge base for Red Hat OpenShift GitOps — Argo CD and Argo Rollouts as shipped by
  the OpenShift GitOps operator. Use when generating, reviewing, debugging, or explaining
  CRDs (Application, ApplicationSet, AppProject, ArgoCD, Rollout, AnalysisTemplate,
  Experiment, RolloutManager, NotificationsConfiguration, NamespaceManagement,
  ImageUpdater), configuring notifications, image updater, sync policies, progressive
  delivery strategies, or designing GitOps repository patterns. Argo Workflows and Argo
  Events are out of scope. Also use when the user asks about Argo best practices,
  common mistakes, or needs to choose between Argo approaches (e.g., app-of-apps vs
  ApplicationSet, canary vs blue-green, directory vs branch-per-environment).
license: MIT
---

# Argo Knowledge Base

## Rules

1. **Always use correct apiVersion and kind.** Most Argo CRDs use `apiVersion: argoproj.io/v1alpha1` — see the CRD Table below — but **not all of them**, and assuming otherwise produces a manifest the API server rejects. The exceptions:
   - **`argoproj.io/v1beta1`** — the OpenShift GitOps / Argo CD Operator `ArgoCD` CR (`references/openshift.md`). `v1alpha1` is deprecated for this kind.
   - **`promoter.argoproj.io/v1alpha1`** — every GitOps Promoter kind (`PromotionStrategy`, `ChangeTransferPolicy`, `GitRepository`, `ScmProvider`, `CommitStatus`, `ArgoCDCommitStatus`, `PullRequest`, and others — see the CRD Table and `references/gitops-promoter.md`). Note the different API **group**, not just a different version.

   Never invent CRDs or apiVersions that do not exist. When in doubt, check the reference file for that topic rather than defaulting to `argoproj.io/v1alpha1`.
2. **Load references on-demand.** Only read reference files when the user's question requires detailed field-level knowledge. Do not preload all references.
3. **Max 1-2 topic reference files per question** (`references/patterns.md` does not count toward that budget — load it whenever a manifest is requested). Keep context focused. If a question spans more than two reference areas, answer the primary question first and offer to elaborate.
4. **Validate YAML before presenting.** Every YAML example must be syntactically valid and use real field names from the Argo CRD schemas.
5. **Prefer canonical patterns.** When the user needs a manifest, load `references/patterns.md` and start from the matching numbered pattern. Adapt it to the user's specifics rather than writing YAML from memory or inventing from scratch.
6. **State trade-offs.** When recommending an approach, briefly note what you give up.

## Scope: OpenShift GitOps

These skills target **Red Hat OpenShift GitOps** — the productized Argo CD distribution —
not the whole Argo ecosystem. The boundary is what the OpenShift GitOps operator actually
ships and supports:

- **Argo CD** — Declarative GitOps continuous delivery. Watches Git repos and syncs
  Kubernetes resources to match desired state. Supports Helm, Kustomize, plain YAML,
  Jsonnet, and config management plugins. On OpenShift it is operator-managed through the
  `ArgoCD` CR (`argoproj.io/v1beta1`), not a raw Helm install.
- **Argo Rollouts** — Progressive delivery. Extends Deployments with canary, blue-green,
  experimentation, and analysis-driven promotion/rollback. Deployed via the operator's
  `RolloutManager` CR.
- **Argo CD Image Updater** — Automated image bumps, operator-managed via the
  `ImageUpdater` CR.
- **Notifications** — operator-managed via `ArgoCD.spec.notifications` and the
  `NotificationsConfiguration` CR.

**Out of scope — Argo Workflows and Argo Events.** They are separate upstream projects,
not part of OpenShift GitOps, and the operator does not own their CRDs. For those, see the
[Argo Workflows](https://argo-workflows.readthedocs.io/) and
[Argo Events](https://argoproj.github.io/argo-events/) docs. On OpenShift, CI/CD pipelines
are generally OpenShift Pipelines (Tekton) rather than Argo Workflows. Say this plainly if
asked rather than improvising coverage.

**GitOps Promoter** is covered (`references/gitops-promoter.md`) but is **installed
separately** — it is an argoproj-labs project, not operator-owned. Flag that when
recommending it.

**Determine what a given cluster actually has** rather than assuming:

```bash
kubectl get csv -n openshift-gitops-operator -o json | \
  jq -r '.items[].spec.customresourcedefinitions.owned[]?.name' | sort -u
```

## CRD Table

| Kind | apiVersion | Project | Purpose |
|------|-----------|---------|---------|
| Application | argoproj.io/v1alpha1 | Argo CD | Defines a single application to sync from Git to a cluster |
| AppProject | argoproj.io/v1alpha1 | Argo CD | RBAC boundary: restricts sources, destinations, and resources |
| ApplicationSet | argoproj.io/v1alpha1 | Argo CD | Generates multiple Applications from templates + generators |
| Rollout | argoproj.io/v1alpha1 | Rollouts | Progressive delivery replacement for Deployment |
| AnalysisTemplate | argoproj.io/v1alpha1 | Rollouts | Defines metric queries for automated rollout analysis |
| ClusterAnalysisTemplate | argoproj.io/v1alpha1 | Rollouts | Cluster-scoped AnalysisTemplate |
| AnalysisRun | argoproj.io/v1alpha1 | Rollouts | Instance of an AnalysisTemplate execution (auto-created) |
| Experiment | argoproj.io/v1alpha1 | Rollouts | Runs multiple ReplicaSet versions simultaneously for comparison |
| ArgoCD | **argoproj.io/v1beta1** | OpenShift GitOps | Operator-managed Argo CD instance (`v1alpha1` is deprecated for this kind) |
| RolloutManager | argoproj.io/v1alpha1 | OpenShift GitOps | **How Rollouts is deployed on OpenShift** — the operator reconciles the argo-rollouts controller from this CR, not a raw install |
| NotificationsConfiguration | argoproj.io/v1alpha1 | OpenShift GitOps | Operator-managed notification triggers/templates. Enable via `ArgoCD.spec.notifications.enabled`. **A hand-written `argocd-notifications-cm` is reconciled away by the operator** |
| NamespaceManagement | **argoproj.io/v1beta1** | OpenShift GitOps | Declares which namespaces an Argo CD instance may manage — relevant to multi-tenant onboarding |
| ImageUpdater | **argocd-image-updater.argoproj.io/v1alpha1** | OpenShift GitOps | Operator-managed Image Updater. Note the **separate API group** |
| GitopsService | pipelines.openshift.io/v1alpha1 | OpenShift GitOps | Owns the default `openshift-gitops` instance. Manual edits to that ArgoCD CR are reverted (`blockOwnerDeletion: true`) |
| PromotionStrategy | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | Environment sequence and gating rules |
| ChangeTransferPolicy | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | How changes move between branches (auto-generated) |
| GitRepository | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | Repository reference (owner, name, SCM provider ref) |
| ScmProvider / ClusterScmProvider | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | SCM credentials and provider config (namespaced / cluster-scoped) |
| CommitStatus | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | Set a commit status on a SHA — the generic promotion gate |
| ArgoCDCommitStatus | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | Surfaces Argo CD health/sync as a promotion gate |
| PullRequest | **promoter.argoproj.io/v1alpha1** | GitOps Promoter | PR lifecycle (open/merged/closed) |

> The promoter also ships `GitCommitStatus`, `TimedCommitStatus`,
> `WebRequestCommitStatus`, `RevertCommit`, and `ControllerConfiguration`. For the full
> installed set on a given cluster: `kubectl get crd -o name | grep promoter.argoproj.io`.

## How Argo CD Works

### Sync Loop

1. **Desired state:** Argo CD reads manifests from a Git repo (source). The source can be Helm charts, Kustomize overlays, plain YAML directories, Jsonnet, or custom config management plugins.
2. **Live state:** Argo CD queries the target Kubernetes cluster (destination) for the current state of resources it manages.
3. **Diff:** Argo CD compares desired vs live state. Resources that differ are marked `OutOfSync`.
4. **Sync:** When triggered (manually or via automated sync policy), Argo CD applies the desired state to the cluster using `kubectl apply`, server-side apply, or `kubectl create/replace` depending on sync options.
5. **Health assessment:** After sync, Argo CD evaluates resource health using built-in health checks (Deployments, StatefulSets, Services, Ingresses, etc.) and custom health checks (Lua scripts in `argocd-cm`). Resources are marked Healthy, Progressing, Degraded, Suspended, or Missing.

### Resource Tracking

Argo CD tracks which resources belong to an Application using one of three methods:

- **`label`** — Adds `app.kubernetes.io/instance: <app-name>` label. Simple but can conflict with other tools using this label.
- **`annotation`** — Adds `argocd.argoproj.io/tracking-id` annotation. Avoids label conflicts. Default in modern Argo CD.
- **`annotation+label`** — Uses both. Maximum compatibility.

Configured via `resource.trackingMethod` in `argocd-cm` ConfigMap.

### Multi-Cluster

Argo CD manages applications across multiple clusters from a single control plane:

- The cluster running Argo CD is the **in-cluster** target (referenced as `https://kubernetes.default.svc`).
- External clusters are added via `argocd cluster add <context-name>`, which creates a ServiceAccount + ClusterRoleBinding on the target cluster and stores credentials as a Secret in the Argo CD namespace.
- Cluster Secrets have label `argocd.argoproj.io/secret-type: cluster` and contain `server`, `name`, `config` (with `bearerToken`, `tlsClientConfig`).

## Decision Trees

### Application vs ApplicationSet

Use **Application** when:
- You have a single application or a small, fixed number of applications
- Each application has unique configuration that doesn't follow a pattern
- You want direct, explicit control over each application

Use **ApplicationSet** when:
- You need to generate many Applications from a pattern (e.g., per-directory, per-cluster, per-team)
- Applications share a common template with parameterized differences
- You want Applications auto-created/deleted when directories or clusters appear/disappear
- You need progressive rollout across environments (rollingSync)

### Rollout vs Deployment

Use **Deployment** when:
- You want simple rolling updates
- You don't need traffic shaping, analysis, or manual promotion gates
- The application is non-critical or internal-only

Use **Rollout** when:
- You need canary or blue-green deployment strategies
- You want automated analysis (metrics-based promotion/rollback)
- You need traffic percentage control via service mesh or ingress
- You need manual approval gates between rollout steps
- You want experiment-based A/B testing

### Which ApplicationSet Generator

- **Git directory** — One Application per directory in a monorepo. Best for: environments or services organized as directories.
- **Git file** — One Application per JSON/YAML config file in a repo. Best for: externalized app configs with arbitrary fields.
- **List** — Explicitly enumerated Applications. Best for: small, fixed sets with no dynamic discovery.
- **Cluster** — One Application per registered Argo CD cluster. Best for: deploying the same app to all clusters matching a selector.
- **Matrix** — Cartesian product of two generators. Best for: deploy N apps to M clusters.
- **Merge** — Combine generator outputs, overriding fields from a secondary generator. Best for: cluster-specific overrides on top of a base config.
- **Pull request** — One Application per open PR. Best for: PR preview environments.
- **SCM provider** — One Application per repo in a GitHub org or GitLab group. Best for: auto-onboarding repos.
## Canonical YAML Patterns

Nine validated starting points live in `references/patterns.md`. **Load that file when the
user needs a manifest** — do not reproduce these from memory.

| # | Pattern | Use when |
|---|---------|----------|
| 1 | Application with Helm source | Deploying a chart from a Helm or OCI registry |
| 2 | Application with Kustomize source | Deploying an overlay directory from Git |
| 3 | ApplicationSet with git directory generator | One Application per directory in a monorepo |
| 4 | ApplicationSet with cluster generator + matrix | N apps across M registered clusters |
| 5 | Rollout with canary + AnalysisTemplate | Metric-gated progressive delivery |
| 6 | Rollout with blue-green strategy | Preview/active cutover with promotion gates |
| 7 | Notifications config (`argocd-notifications-cm`) | Slack/email alerts on sync or health events |
| 8 | Image updater annotations | Automated image bumps written back to Git |
| 9 | Multi-source Application (chart + external values) | Chart in one repo, values in another — `spec.sources[]` + `$values` |

## Common Mistakes

1. **Missing `namespace: argocd` on Application metadata.** Applications must live in the Argo CD namespace (or a namespace explicitly allowed via `--application-namespaces`). Omitting this causes Argo CD to never see the Application.

2. **Using `helm.values` (string) instead of `helm.valuesObject` (map).** `helm.values` is a multiline YAML string which is error-prone. `helm.valuesObject` is a structured map and should be preferred.

3. **Setting `automated.prune: true` without understanding consequences.** This deletes resources from the cluster that are no longer in Git. If you accidentally remove a manifest from Git, prune will delete the live resource. Use `prune: false` until you trust the workflow, or use `preserveResourcesOnDeletion` on ApplicationSets.

4. **Forgetting `CreateNamespace=true` sync option.** Argo CD does not create namespaces by default. Without this option, syncing to a non-existent namespace fails.

5. **Using `targetRevision: HEAD` in production.** This follows the default branch and makes deployments unpredictable. Pin to a specific tag, commit SHA, or semver range.

6. **Rollout without matching Services.** Canary and blue-green strategies require correctly configured `stableService` and `canaryService`/`previewService`. Forgetting these Services causes traffic routing failures.

7. **AnalysisTemplate with no `count` or `interval`.** Without these, the analysis runs once and completes immediately, which is rarely useful. Set `count` and `interval` for continuous monitoring during rollout.

8. **ApplicationSet with `goTemplate: true` but using `{{name}}` syntax.** Go templates use `{{.name}}`, not `{{name}}` (which is fasttemplate syntax). Mixing them produces empty strings silently.

9. **Notification trigger `when` expression referencing wrong fields.** Common mistake: `app.status.sync.status` vs `app.status.operationState.phase`. Sync status is Synced/OutOfSync. Operation phase is Succeeded/Failed/Error/Running.

10. **Image updater `write-back-method: git` without write access.** The image updater needs push access to the Git repo. Without it, updates silently fail. Check the image updater logs.

11. **Putting `oci://` in a Helm `repoURL`.** The Argo CD docs are explicit: *"the `oci://` syntax is not included."* Use the registry host and path (`registry.example.com/charts`) with the chart name in `chart:`, and register the repository with `enableOCI: "true"`. The resulting failure looks like an auth or network error, not a URL format error.

12. **`preserveResourcesOnDeletion` at `spec` level on an ApplicationSet.** It only exists at `spec.syncPolicy.preserveResourcesOnDeletion`. The CRD is a structural schema, so the misplaced key is silently pruned — you get no deletion protection and no error.

13. **Top-level `spec.dex` on an ArgoCD CR.** Unsupported since Argo CD Operator v0.8.0; use `spec.sso.provider: dex` with `spec.sso.dex`. The old form does not take effect, so SSO quietly never comes up.

14. **One notification trigger driving multiple commit-status states.** `oncePer` is scoped per trigger, so a single trigger fires once per revision and then stops — typically leaving the commit status stuck on `pending`. Use one trigger per state. Also note `operationState.syncResult.revision` is empty while the operation is `Running`.

## Reference Index

| Topic | Reference File | When to Load |
|-------|---------------|-------------|
| 9 canonical YAML patterns (Application, multi-source, ApplicationSet, Rollout, notifications, image updater) | `references/patterns.md` | **Any request to generate or review a manifest** |
| Application spec, **multi-source (`sources[]` + `$values`)**, sync policies, sync waves, health checks, ignore differences, multi-cluster | `references/applications.md` | Questions about Application configuration, multi-source, sync behavior, health, or multi-cluster |
| ApplicationSet generators, templates, progressive syncs, `preserveResourcesOnDeletion`, `ignoreApplicationDifferences` | `references/applicationsets.md` | Questions about ApplicationSet generators, templating, progressive rollout, or suppressing drift on generated Applications |
| AppProject RBAC, source/destination restrictions, sync windows | `references/app-projects.md` | Questions about RBAC, project policies, sync windows |
| Rollout canary/blue-green, traffic management, AnalysisTemplate, experiments | `references/rollouts.md` | Questions about progressive delivery, canary/blue-green, analysis metrics |
| Notification services, templates, triggers, subscriptions | `references/notifications.md` | Questions about alerting and notifications |
| Image updater annotations, strategies, write-back | `references/image-updater.md` | Questions about automated image updates |
| App-of-apps, monorepo, multi-repo patterns | `references/repo-patterns.md` | Questions about repository structure and GitOps patterns |
| Sync policy, RBAC, health checks, secret management | `references/best-practices.md` | General architecture and operational best practices |
| Agent mode, principal/agent architecture, managed/autonomous modes, hub-and-spoke | `references/agent-mode.md` | Questions about argocd-agent, multi-cluster at scale, air-gapped, edge deployments |
| Applications in any namespace, multi-instance, multi-tenancy, Autopilot | `references/multi-tenancy.md` | Questions about multi-tenancy, team isolation, --application-namespaces, Autopilot bootstrap |
| OpenShift GitOps Operator, ArgoCD CRD, Routes, SCCs, OAuth, managed namespaces | `references/openshift.md` | Questions about running Argo on OpenShift, operator-managed instances, OpenShift-specific patterns |
| **Operator-only CRDs** — RolloutManager, NotificationsConfiguration, NamespaceManagement, ImageUpdater, GitopsService | `references/openshift-gitops-operator.md` | Anything that will not stay changed on OpenShift GitOps; deploying Rollouts; notifications; attaching tenant namespaces; image updates |
| GitOps Promoter, PromotionStrategy, environment promotion, commit status gating | `references/gitops-promoter.md` | Questions about environment promotion, PR-based gating, branch-per-environment, gitops-promoter CRDs |
