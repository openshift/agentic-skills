---
name: argo-team-onboard
description: >
  Onboard app teams onto Argo CD the GitOps way — generates tenant onboarding
  config (AppProject, Application, RBAC, Namespace, quotas, NetworkPolicies)
  and commits it to the GitOps repo for Argo CD to reconcile, rather than
  applying it to the cluster imperatively. Discovery-first: adapts to the
  team's existing stack (Helm, Kustomize, or plain YAML). Recommended path is
  a per-tenant values file rendered by an onboarding Helm chart and discovered
  by an ApplicationSet. Does NOT generate CI pipelines, registry config, or
  secrets backends. Use when users ask about onboarding teams, adding tenants,
  setting up new teams, bootstrapping first apps, or self-service onboarding.
license: MIT
compatibility: Requires git; optionally kubectl and argocd CLI for read-only verification
---

# Argo Team Onboard

> **Component selectors:** `$CR` is the ArgoCD instance's name — `openshift-gitops`,
> `team-b`, etc. Operator-managed workloads are labelled `<cr-name>-<component>`, so a
> hardcoded `app.kubernetes.io/name=argocd-server` matches **nothing** and the component
> reads as absent. Resolve it alongside `$NS`:
>
> ```bash
> CR=$(kubectl get argocd -n "$NS" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
> CR=${CR:-argocd}   # falls back to the Helm/standalone naming
> ```
>
> On a Helm or plain-manifest install the components really are `argocd-*`, so the
> fallback makes the same commands work on both.

> **Namespace:** `$NS` below is the Argo CD instance's namespace. It is **`openshift-gitops`
> on OpenShift GitOps**, `argocd` on a standalone install, and something else entirely for a
> second instance. There is frequently more than one — resolve it once and reuse it:
>
> ```bash
> kubectl get argocd -A    # operator-managed instances and their namespaces
> NS=openshift-gitops      # set to the instance you are working on
> ```
>
> The same applies to `namespace: argocd` inside the YAML below — it is a placeholder for
> the Argo CD instance's namespace. An Application created in `argocd` on a cluster whose
> instance lives in `openshift-gitops` is never picked up, with no error anywhere.
> (`namespace:` on an Application's **destination** is a different field — that one is the
> workload's namespace and is unrelated.)

Onboard application teams onto Argo CD with discovery-first workflows.

This is a **write** skill focused on multi-tenancy setup. It generates tenant onboarding
config and **commits it to Git**, where Argo CD reconciles it. The read-only skills
(`argo-knowledge`, `argo-repo-audit`, `argo-cluster-debug`) answer questions, audit repos,
and diagnose problems without changes. This skill **acts** — by writing to a repo.

**Scope boundary:** This skill generates Argo CD and tenant-boundary resources only —
AppProject, Application, ApplicationSet, RBAC entries, and optionally Namespace,
ResourceQuota, LimitRange, and NetworkPolicy. It does NOT generate CI pipelines, container
registry configuration, or secrets backend setup. It references how to wire those in but
delegates the actual config to the appropriate tools.

## The GitOps Rule (read this first)

**Onboarding artifacts are GitOps artifacts. Write them to the repo; do not `kubectl apply`
them.**

An onboarding tool that applies AppProjects and Applications straight to the cluster
creates exactly the drift that Argo CD exists to eliminate: the tenant boundary now lives
only in cluster state, is invisible in review, has no audit trail, and will be silently
reverted or duplicated the first time anyone reconciles from Git. "If it is not in Git, it
does not exist" applies to the onboarding config itself, not just to the team's workloads.

So the default output of this skill is **a commit or pull request**, not an apply.

**The one exception — bootstrap.** If there is no GitOps control loop yet (no Argo CD, or
no onboarding ApplicationSet watching the repo), someone must apply the very first
resources imperatively to break the circular dependency. That is the only case where
`kubectl apply` is correct here. When you do it, say explicitly that it is a one-time
bootstrap, apply the *minimum* needed to start the control loop, and commit the same
manifests to Git in the same session so the cluster and the repo agree.

## Rules

1. **Commit, don't apply.** Generate into the GitOps repo and hand off to Argo CD. Use
   `kubectl apply` only for the documented bootstrap exception above, and name it as such.

2. **Always discover before generating.** Never assume the team's stack. Ask what CI
   system, container registry, source type (Helm/Kustomize/directory), and secrets
   management they use — **and where the GitOps repo lives and how tenants are laid out in
   it**. The discovery phase is non-negotiable — skipping it produces generic output that
   will need rework.

3. **AppProject is the security boundary — get it right.** Scope `sourceRepos` to exact
   repo URLs, `destinations` to exact namespace/cluster pairs, and `clusterResourceWhitelist`
   to only what the team needs. This is the single most important resource in the
   onboarding output.

   **Never a bare `*`.** A *bounded* prefix glob is acceptable when the team genuinely
   adds repos often — `https://github.com/acme/payments-*.git` is scoped to one team in
   one org. `https://github.com/acme/*` is not: it grants every repo in the org. The test
   is whether the pattern can match a repo belonging to another team.

4. **Generate only Argo CD and tenant-boundary resources.** Do not generate CI pipelines,
   registry setup, or secrets backend config. When the team's answers reveal they need
   those, reference how to wire them into the Argo CD config (e.g., "add your registry
   credentials as an `argocd-image-updater` annotation") but do not create the external
   resource itself.

5. **Use the team's existing source type.** If they use Helm, generate a Helm Application.
   If Kustomize, Kustomize. If plain YAML, directory. Do not convert between source types
   unless the user explicitly asks.

6. **Redirect non-Argo questions.** CI/pipeline questions go to `argo-knowledge` or
   platform-skills. Secrets backend setup goes to the relevant tool's docs. Cluster setup
   questions go to `argo-operations`. Be explicit about the redirect.

7. **Follow the safety model.** Generate -> show diff -> confirm -> commit. Read-only
   discovery operations do not need confirmation.

## Safety Model

**Every write operation follows a 3-step protocol: Generate, Diff, Confirm — and the
write is a commit to the GitOps repo, not an apply to the cluster.**

**Read-only operations** (cluster detection, namespace listing, version queries, RBAC
checks, `git status`) do NOT require confirmation — just execute them and report results.

### Step 1: Generate

Produce the onboarding config for the requested tenant and **place it at the correct path
in the GitOps repo** (discovered in Phase 1). Show the user the files and their paths.
Do not commit anything yet.

### Step 2: Diff

Show exactly what will enter the repo:

| Operation | Preview Command |
|-----------|----------------|
| New tenant files (untracked — the usual case) | `git add -N <paths>` first, then `git diff` — **plain `git diff` shows nothing for untracked files** |
| Content review | `git diff` (or `git diff --cached` once staged) |
| Change to an existing tenant | `git diff -- <tenant-path>` |
| What Argo CD will then do (read-only, optional) | `argocd app diff <onboarding-app>` |
| Render check before commit (optional) | `helm template <chart> -f <tenant-values>` |

Show the diff and explain in plain language what Argo CD will create once this merges.

For an existing tenant, always show the *diff against the committed file* — never
overwrite a tenant's config without showing what changed.

### Step 2b: Blast radius

The default output here is a **commit**, not an apply, so the question is "what will Argo
CD do when it syncs this?" rather than "what does this kubectl change touch". Usually the
answer is "nothing existing" — onboarding is additive. Say that; it is reassuring and
costs one command.

Three cases are not additive, and each needs its impact stated:

- **Editing an existing `AppProject`** rather than creating one. Tightening `sourceRepos`,
  `destinations` or the resource whitelists can push Applications already in that project
  to `InvalidSpecError` — they stop syncing with nobody touching them.
  `<repo-root>/scripts/blast-radius.sh AppProject <name> <namespace>` lists them.
- **Attaching a tenant to a shared instance** via `NamespaceManagement` or
  `sourceNamespaces`. Name the instance and who else is already on it:
  `<repo-root>/scripts/blast-radius.sh ArgoCD <name> <namespace>`.
- **An ApplicationSet whose generator will now match more tenants.** It creates
  Applications on merge; a narrowed generator can prune existing ones and delete their
  workloads unless `preserveResourcesOnDeletion` is set.

### Step 3: Confirm

Ask the user explicitly: **"Commit this? (yes/no)"** — and, if they use a review flow,
**"Open a PR or commit to a branch?"**

Do not proceed without an affirmative response. Acceptable confirmations: "yes", "y",
"commit", "do it", "go ahead", "ship it". Anything else is a no.

After committing, state plainly that **the tenant is not onboarded until Argo CD syncs**,
and how to watch it:

```bash
argocd app get <onboarding-app> --refresh
```

### Safety Rules

1. **NEVER commit without showing the diff first.**
2. **NEVER `kubectl apply` onboarding resources** except for the documented one-time
   bootstrap. If you bootstrap, commit the same manifests in the same session.
3. **NEVER use wildcards in AppProject sourceRepos or destinations.** This is the
   entire point of scoped onboarding.
4. **NEVER overwrite an existing tenant's config without showing the diff first.**
5. **NEVER create cluster-admin-equivalent RBAC.** Team roles should be scoped to their
   project's resources.
6. **Log every committed change.** After each successful commit, report:
   `[COMMITTED] <timestamp> <repo-path> -- <action>` and the resulting commit SHA or PR URL.
7. **If a command fails, show the error and suggest recovery.** Do not retry automatically.

## Prerequisites

The GitOps repo is the primary target, so `git` is what's actually required. `kubectl` and
`argocd` are optional and used only for read-only verification.

```bash
# Required — the repo you will write to
command -v git >/dev/null && echo "git: $(git --version)" || echo "git: MISSING"
git -C <gitops-repo> rev-parse --abbrev-ref HEAD   # confirm the branch you're writing to
git -C <gitops-repo> status --short                # must be clean before generating

# Optional — read-only verification that Argo CD picked the change up
command -v kubectl >/dev/null && echo "kubectl: available" || echo "kubectl: not installed"
command -v argocd  >/dev/null && echo "argocd: available"  || echo "argocd: not installed"
```

Working without cluster access is fine and expected — you can generate, diff, and commit a
complete onboarding without ever reaching a cluster. Say so rather than blocking.

If `kubectl` is available, optionally verify Argo CD is installed (read-only):

```bash
# Check for Argo CD
kubectl get crd applications.argoproj.io 2>/dev/null && echo "Argo CD CRDs: installed" || echo "Argo CD CRDs: NOT FOUND"

# Find Argo CD namespace
# The CRD check above is the PRIMARY signal. Do not detect Argo CD by the part-of label:
# operator-managed installs do not set it on pods, so this returns nothing on a cluster
# running several instances. Use the ArgoCD CR, falling back to the label for Helm.
kubectl get argocd -A --no-headers 2>/dev/null | awk '{print $1"\t"$2"\t(operator)"}'
kubectl get pods -A -l app.kubernetes.io/part-of=argocd --no-headers 2>/dev/null | awk '{print $1"\t-\t(helm)"}' | sort -u

# Check for OpenShift GitOps operator
kubectl get crd argocds.argoproj.io 2>/dev/null && echo "OpenShift GitOps: installed" || echo "OpenShift GitOps: not detected"

# Argo CD version
kubectl get pods -n "$NS" -l app.kubernetes.io/name=$CR-server -o jsonpath='{.items[0].spec.containers[0].image}' 2>/dev/null || \
  kubectl get pods -n openshift-gitops -l app.kubernetes.io/name=openshift-gitops-server -o jsonpath='{.items[0].spec.containers[0].image}' 2>/dev/null
```

If Argo CD is not installed at all, redirect to `argo-operations` for setup — but you can
still generate and commit the tenant config now; it will reconcile once Argo CD exists.

## Choosing the Onboarding Model

Pick this before generating anything. All three commit to Git; they differ in what gets
committed.

| Model | What you commit per tenant | Use when | Reference |
|-------|---------------------------|----------|-----------|
| **Helm values (recommended)** | One small `values.yaml` describing the tenant; a shared onboarding chart renders every object | You onboard tenants repeatedly and want one reviewed template, not N copies of the same YAML | `references/gitops-onboarding.md` |
| Rendered manifests | The literal AppProject / Application / Namespace / quota YAML | One-off onboarding, or no appetite for a chart | `references/onboarding-guide.md` |
| Kustomize overlay | A per-tenant overlay on an immutable platform base | You already standardize on Kustomize and want platform-enforced bases | `references/self-service-pattern.md` |

**Default to the Helm values model** when the user has more than a couple of tenants or
asks about self-service: the per-tenant diff stays a few readable lines, and changing the
standard for everyone is a single chart change rather than an N-file sweep.

## Workflow Phases

### How to Route Requests

| User says | Phase | Reference |
|-----------|-------|-----------|
| "Onboard team X" / "Add a new team" | Phase 1 + 2 + 3 | `references/gitops-onboarding.md` (or `onboarding-guide.md` for raw manifests) |
| "Set up self-service onboarding" | Phase 4 | `references/gitops-onboarding.md` + `references/self-service-pattern.md` |
| "Bootstrap first app for team" | Phase 1 + 2 + 3 | `references/onboarding-guide.md` + `references/onboarding-variants.md` |
| "Generate AppProject for team" | Phase 2 (skip discovery if info given) | `references/onboarding-guide.md` |
| "Scale onboarding to many teams" | Phase 4 | `references/gitops-onboarding.md` |
| "Just apply it to the cluster" | Push back — see **The GitOps Rule**; offer the commit path, or confirm it is a genuine bootstrap | -- |
| "Install Argo CD" | Redirect to `argo-operations` | -- |
| "How do AppProjects work?" | Redirect to `argo-knowledge` | -- |
| "Set up CI pipeline" | Redirect: out of scope | -- |
| "Set up secrets management" | Redirect: out of scope | -- |

Load the matching reference file before starting. Max 1-2 reference files per request.

---

### Phase 1: Discovery

**This phase is mandatory.** Do not skip it even if the user provides partial information.

#### Step 1: Locate the GitOps Repo

**This is the most important discovery step — it is where the output goes.** Establish it
before anything else:

- **Which repo** holds tenant/platform config? (May differ from the teams' app repos.)
- **What is the existing tenant layout?** Inspect it rather than inventing one:
  ```bash
  git -C <gitops-repo> ls-files | grep -Ei 'tenant|project|onboard|team' | head -30
  ```
  Match the convention already in the repo. A new tenant should be indistinguishable in
  shape from the existing ones.
- **Which onboarding model is in use** — per-tenant values + chart, rendered manifests, or
  Kustomize overlays? (See *Choosing the Onboarding Model*.) An existing repo has already
  decided this; follow it.
- **What picks the files up** — an ApplicationSet, an app-of-apps, or nothing yet?
- **Branch and review flow** — direct commit, or branch + PR?

If there is no GitOps repo yet, say so plainly and offer to scaffold one — that is a
larger decision than onboarding a single team and the user should make it deliberately.

#### Step 2: Cluster Check (optional, read-only)

Only if `kubectl` is available. Skip without blocking if it is not — you do not need
cluster access to produce a correct commit.

```bash
# Platform detection
kubectl api-resources --api-group=route.openshift.io 2>/dev/null && echo "Platform: OpenShift" || echo "Platform: Kubernetes"

# Argo CD installation
kubectl get argocd -A --no-headers 2>/dev/null   # operator-managed: the authoritative check
kubectl get pods -A -l app.kubernetes.io/part-of=argocd --no-headers 2>/dev/null  # Helm only

# Existing AppProjects (to avoid conflicts)
kubectl get appprojects -A --no-headers 2>/dev/null

# Existing namespaces (to check if team namespaces exist)
kubectl get namespaces --no-headers 2>/dev/null | awk '{print $1}'
```

Treat anything found here as *observed state to cross-check against Git*, not as the
source of truth. If a tenant exists on the cluster but not in the repo, that is drift
worth flagging to the user.

#### Step 3: Team Profile Questions

Ask the user about the team. Do not assume answers. If the user provides all info
up front, acknowledge and confirm rather than re-asking.

**Required:**
- Team name (used for AppProject name, namespace prefix, RBAC group)
- Git repository URL(s) for the team's application manifests
- Target namespace(s) and cluster(s)
- SSO group name for RBAC binding (e.g., LDAP group, OIDC claim)

**Required — Source Type:**
- What source type does the team use? (Helm / Kustomize / plain YAML directory)
- If Helm: chart repo URL or OCI registry? In-repo chart or remote?
- If Kustomize: base + overlays structure?

**Optional (ask if relevant, don't interrogate):**
- Environments (dev/staging/prod) — affects whether to generate multiple Applications
- CI system (GitHub Actions, GitLab CI, Tekton, Jenkins) — noted but NOT generated
- Container registry — noted but NOT generated
- Secrets management (Sealed Secrets, ESO, Vault) — noted but NOT generated
- Need progressive delivery? (Rollouts) — generates scaffold if yes
- Notification preferences (Slack, email) — generates annotations if yes

#### Step 4: Build Team Profile

Summarize the gathered information as a profile block:

```yaml
# Team Profile
team: frontend
sso_group: team-frontend
source_type: helm
repos:
  - https://github.com/org/frontend-app.git
namespaces:
  - frontend-dev
  - frontend-staging
  - frontend-prod
cluster: in-cluster
environments: [dev, staging, prod]
notes:
  ci: github-actions  # not generated, for reference
  registry: ghcr.io   # not generated, for reference
  secrets: sealed-secrets  # not generated, for reference
```

Show this profile to the user and confirm before proceeding to generation.

---

### Phase 2: Generate

Generate the tenant's onboarding config from the team profile and **write it into the
GitOps repo** at the path discovered in Phase 1.

If the user chose the **Helm values model** (the default), what you generate is a single
per-tenant `values.yaml` — load `references/gitops-onboarding.md` for the schema and the
chart contract, and stop here; the chart renders everything below. The table that follows
describes what that chart produces, and is also the checklist for the rendered-manifest
model.

**`references/onboarding-guide.md` holds the authoritative manifest templates — load it
and fill in the team profile. Do not write these manifests from memory.** This section
covers *what* to generate and the decisions behind it; the guide has the YAML.

#### Always Generated

| # | Resource | Template section in `onboarding-guide.md` |
|---|----------|-------------------------------------------|
| 1 | AppProject — the security boundary, the most important resource | *AppProject Template* |
| 2 | Application — one per environment, matching the team's source type | *Application Templates* (Kustomize / Helm / Multi-Source Helm / Directory) |
| 3 | RBAC — **pick one**, do not generate both | *RBAC Template* |
| 4 | Namespace with Pod Security Standards + monitoring labels | *Namespace* |
| 5 | Default NetworkPolicies — deny-all egress plus explicit allows | *Default NetworkPolicies* |

**The two RBAC placements are alternatives, not a pair.** AppProject `spec.roles[]` with
`groups:` scopes permissions to that project and travels with it — prefer it. A
`argocd-rbac-cm` entry is for centrally managed, cross-project policy. Generating both
produces duplicate policy lines for the same group, which is confusing to audit and easy
to half-revoke later. `onboarding-guide.md`'s AppProject template already contains the
project-scoped form; only add the ConfigMap patch if the user's estate manages RBAC
centrally.
**Namespaces and NetworkPolicies are not optional extras.** A tenant namespace with no
`pod-security.kubernetes.io/enforce` label and no NetworkPolicy is open to lateral traffic
from every other tenant on the cluster, which defeats the AppProject boundary you just
scoped so carefully. Generate them unless the user has a platform-wide mechanism already
doing it — and if they do, confirm that rather than assuming it.

**AppProject constraints** — these are what make onboarding safe:
- `sourceRepos`: exact URLs, never `*`
- `destinations`: exact namespace/server pairs, never `*`
- `clusterResourceWhitelist`: empty by default; add only the specific CRD groups the team needs
- `namespaceResourceBlacklist`: block ResourceQuota, LimitRange, and NetworkPolicy — the
  platform team owns those
- `orphanedResources.warn: true`: always enable drift detection
- `roles`: scoped to this project's Applications only

**Application decisions:**
- `CreateNamespace=false` by default — the platform team manages namespaces
- `automated.selfHeal: true` + `prune: true` for non-production environments
- For production: consider manual sync, or add `syncWindows` for change control
- Always include `retry` with backoff
- `targetRevision`: environment-specific branches or tags, never `HEAD`

**RBAC is a patch, not a replacement.** The `argocd-rbac-cm` entry is the one piece most
likely to already exist in Git with other tenants' lines in it. Read the committed file,
add the team's lines, and show the diff — never regenerate the whole ConfigMap:

```bash
git -C <gitops-repo> diff -- <path-to-argocd-rbac-cm.yaml>
```

#### Conditionally Generated

Generate these only when discovery indicates they are needed:

| Resource | When to Generate | Template section |
|----------|-----------------|------------------|
| ResourceQuota + LimitRange | Tenant needs enforced capacity limits | *Conditional Resources* |
| Custom NetworkPolicies | Tenant needs ingress/egress beyond the defaults | *Default NetworkPolicies* |
| Local admin Group + RoleBinding | SSO groups are not synced from the IdP | *RoleBinding (kubectl Access)* |
| RoleBinding | Team needs `kubectl` access beyond the Argo CD UI | *RoleBinding (kubectl Access)* |
| Notification annotations | Team requested Slack/email notifications | *Notification Subscriptions* |
| Rollout scaffold | Team wants progressive delivery | `references/onboarding-variants.md` |
| SyncWindow | Production environment needs change control | *Sync Windows* |

The guide's ResourceQuota tiers are reasonable defaults, not universal — ask the user to
confirm or adjust the values for their team.

---

### Phase 3: Commit and Hand Off to Argo CD

This is where onboarding actually happens. Do not skip it, and do not substitute an apply.

1. **Show the diff.** New tenant files are untracked, and `git diff` ignores untracked
   files — so stage them as intent-to-add first or you will show the user an empty diff:
   ```bash
   git -C <repo> add -N <tenant-paths>     # intent-to-add: makes new files visible to diff
   git -C <repo> status --short
   git -C <repo> diff                      # now shows the full tenant config
   ```
   Walk the user through what Argo CD will create.
2. **Confirm** — "Commit this? (yes/no)", and whether they want a branch + PR or a direct
   commit to the tracked branch.
3. **Commit** with a message naming the tenant and what was granted, e.g.
   `onboard: add tenant checkout (dev/staging/prod, scoped to checkout-svc.git)`.
4. **Push — ask again before you do.** "Commit this?" authorizes a commit, not a push to
   a shared remote. Confirm separately: **"Push to `<remote>/<branch>`? (yes/no)"**. A
   commit is local and trivially undone; a push to a branch an ApplicationSet watches can
   start reconciling immediately. Open a PR if that is their flow.
5. **Report** `[COMMITTED] <timestamp> <path> -- <action>` plus the commit SHA or PR URL.
6. **State the handoff explicitly:** the tenant exists once Argo CD syncs the change, not
   at commit time. Give them the command to watch it:
   ```bash
   argocd app get <onboarding-app> --refresh
   ```

If the repo has CI validation on tenant configs (see *PR Validation Script* in
`references/self-service-pattern.md`), mention that it will gate the merge.

---

### Phase 4: Self-Service (if requested)

Use when the platform team wants to scale onboarding beyond manual generation: teams
submit a PR adding their own config, and an ApplicationSet generates their resources.

**Load `references/self-service-pattern.md` — it holds the authoritative `teams.yaml`
schema, both ApplicationSet approaches, and the PR workflow. Do not improvise the file
schema or the generator; the two must agree or the ApplicationSet fails to render.**

Two approaches, both in the reference:

| Approach | Use when |
|----------|----------|
| Per-team AppProject + Applications via git **file** generator (recommended) | One `teams/<name>/config.yaml` per team; platform team reviews each PR |
| Kustomize overlay with an immutable platform base | Platform team needs to enforce non-negotiable settings teams cannot override |

**Schema and generator must match.** The recommended pattern uses one file per team at
`teams/*/config.yaml`, each with a top-level `team:` key, which is what makes
`{{ .team.name }}` resolve. A single central file containing a `teams:` *array* is a
different shape and will not populate those template variables — with
`goTemplateOptions: [missingkey=error]` set, it fails loudly rather than silently.

#### Onboarding Workflow

1. New team forks the GitOps config repo
2. Adds their `teams/<team-name>/config.yaml`
3. Opens a PR — platform team reviews AppProject scope and quotas
4. PR merges — ApplicationSet auto-generates all resources
5. Team's Applications appear in Argo CD within the sync interval

See *Guard Rails: Platform vs Team* in the reference for what teams may and may not
change, and *PR Validation Script* for automated scope checks on incoming PRs.

---

### Phase 5: Validate

Run this **after Argo CD has synced the commit**, not immediately after committing — the
resources do not exist until reconciliation completes. If the onboarding Application is
still `OutOfSync` or `Progressing`, wait or refresh before concluding anything failed.

All checks below are read-only and require cluster access. If you have none, say the
onboarding is committed but unverified rather than implying it is live.

```bash
# Confirm Argo CD actually reconciled the commit before checking anything else
argocd app get <onboarding-app> --refresh

# Verify AppProject was created with correct restrictions
kubectl get appproject team-<team-name>   # templates prefix with 'team-' -n <argocd-namespace> -o yaml

# Verify Application syncs successfully
argocd app get <team-app-name> 2>/dev/null || \
  kubectl get applications.argoproj.io <team-app-name> -n <argocd-namespace> -o jsonpath='sync={.status.sync.status} health={.status.health.status}'

# Verify RBAC — team member can see their apps
argocd account can-i get applications '<team-name>/*' --auth-token <token> 2>/dev/null

# Verify RBAC — team member CANNOT see other projects
argocd account can-i get applications 'other-project/*' --auth-token <token> 2>/dev/null

# Verify namespace-level access
kubectl auth can-i create deployments -n <team-ns> --as=<user> 2>/dev/null

# Verify AppProject restrictions hold
kubectl auth can-i create resourcequotas -n <team-ns> --as=<user> 2>/dev/null  # should be "no"
```

Report results as a checklist:

```
Onboarding Validation:
  [PASS] AppProject <name> created with scoped sourceRepos
  [PASS] AppProject <name> has orphanedResources.warn enabled
  [PASS] Application <name> synced successfully (Synced/Healthy)
  [PASS] RBAC: team can access their project
  [PASS] RBAC: team cannot access other projects
  [FAIL] Namespace <name> ResourceQuota not yet applied
```

## CRD Reference

Only AppProject, Application, and ApplicationSet are directly generated by this skill.
Cross-reference `argo-knowledge` for full CRD documentation.

| Kind | apiVersion | Purpose in Onboarding |
|------|-----------|----------------------|
| AppProject | argoproj.io/v1alpha1 | Security boundary — scopes repos, destinations, RBAC |
| Application | argoproj.io/v1alpha1 | Deploys the team's app from Git to cluster |
| ApplicationSet | argoproj.io/v1alpha1 | Self-service: generates Applications from teams.yaml |

## Common Mistakes

1. **Wildcard AppProject.** `sourceRepos: ['*']` or `destinations: [{namespace: '*'}]`
   defeats the entire purpose of multi-tenant onboarding. Every team gets access to
   every repo and namespace. Always use exact values.

2. **Missing namespaceResourceBlacklist.** Without it, teams can create their own
   ResourceQuotas, LimitRanges, and NetworkPolicies — overriding platform constraints.
   Always blacklist resources the platform team owns.

3. **Missing orphanedResources.warn.** Without orphan detection, resources manually
   created in the team's namespace go unnoticed. Drift accumulates silently. Always
   enable `orphanedResources.warn: true`.

4. **All environments on the same branch.** Using `targetRevision: main` for dev,
   staging, and prod means every commit deploys everywhere simultaneously. Use
   environment-specific branches or tags for promotion gating.

5. **Overprivileged project roles.** Using `action: '*'` or granting `exec` access
   in AppProject roles gives teams more power than they need. Scope to `get`, `sync`,
   and `override` at most. Never grant `delete` or `exec` without explicit justification.

6. **Onboarding by `kubectl apply`.** The most common one, and the reason this skill is
   commit-first. Applying the AppProject directly means the tenant boundary exists only
   in cluster state: invisible in review, absent from the audit trail, and liable to be
   reverted the next time anything reconciles from Git. Commit it instead.

7. **Namespace with no Pod Security Standards labels.** Without
   `pod-security.kubernetes.io/enforce`, the tenant can run privileged pods regardless of
   how carefully the AppProject is scoped. Default to `restricted`.

8. **Blacklisting NetworkPolicy without creating any.** `namespaceResourceBlacklist`
   stops teams from editing policies; it does not create them. Blacklisting alone leaves
   the namespace fully open to lateral traffic *and* prevents the team from fixing it.
   Generate the defaults.

9. **Default-deny egress with no DNS exception.** Breaks name resolution cluster-wide for
   the tenant, and the symptoms look like application bugs. Always allow UDP/TCP 5353 to
   the DNS namespace.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Argo CD not installed | **Do not stop.** Cluster access is optional for this skill — generate and commit the tenant config now; it reconciles once Argo CD exists. Mention `argo-operations` for the install, and say plainly that the tenant is committed but not yet live. Only stop if the user has no GitOps repo *either*, since then there is nowhere to commit. |
| Single-tenant cluster | Generate a simpler AppProject — less restrictive destinations OK, but still scope sourceRepos. Note that `namespaceResourceBlacklist` may not be needed. |
| Existing AppProject with same name | Find it in Git first (`git -C <repo> grep -l "name: <name>"`). Show the committed definition and ask whether to update it or pick a different name. Show the `git diff` before committing. |
| Tenant exists on the cluster but not in Git | Drift — the tenant was applied imperatively at some point. Flag it, and offer to import the live definition into the repo so Argo CD owns it going forward. |
| User asks to apply directly instead of committing | Explain the drift cost in one sentence and offer the commit path. If they confirm it is a genuine bootstrap (no control loop yet), proceed, label it a bootstrap, and commit the same manifests in the same session. If they simply prefer apply, say plainly that it puts the tenant boundary outside GitOps, then respect their decision. |
| No GitOps repo exists yet | Do not silently fall back to applying. Offer to scaffold the repo structure and the onboarding ApplicationSet — that is the actual blocker. |
| Multiple Argo CD instances | Detect by checking for ArgoCD CRs or argocd-labeled pods in multiple namespaces. Ask which instance to target. |
| OpenShift with GitOps operator | Check for `ArgoCD` CR (`kubectl get argocd -A`). Use the operator-managed namespace (typically `openshift-gitops` or a namespace-scoped instance). Adjust RBAC to use OpenShift groups. |
| Team namespaces already exist | Skip Namespace creation. Still offer ResourceQuota and LimitRange if missing. |
| Team already has partial onboarding | Inventory existing resources (`kubectl get appproject,application -A`). Show what exists, ask what to add or update. |
| User provides all info up front | Skip interactive discovery. Parse the info, build the team profile, confirm, and proceed to generation. |

## Reference Index

These files hold the **authoritative manifests** for this skill. Phase 2 and Phase 3 above
describe what to generate and why; the YAML itself lives here. Load the relevant file
rather than writing manifests from memory.

| Topic | Reference File | When to Load |
|-------|---------------|-------------|
| **Recommended model** — per-tenant values + onboarding Helm chart, discovery ApplicationSet, t-shirt sizes, default NetworkPolicies, Pod Security Standards labels, two-instance split | `references/gitops-onboarding.md` | **Default for Phase 2 and Phase 4** — any repeat or self-service onboarding |
| AppProject / Application / RBAC templates, conditional resources (Namespace, quota tiers, LimitRange, NetworkPolicies, RoleBinding, notifications, sync windows), validation checklist | `references/onboarding-guide.md` | Phase 2 when committing rendered manifests rather than values |
| `teams.yaml` schema, both ApplicationSet approaches, PR workflow, platform-vs-team guard rails | `references/self-service-pattern.md` | Phase 4 — scaling or self-service requests |
| Source type variants (Helm / Kustomize / directory), Rollouts, notifications, sync windows, gitops-promoter | `references/onboarding-variants.md` | When adapting to a specific stack |
