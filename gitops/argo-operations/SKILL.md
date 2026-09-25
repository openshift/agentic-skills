---
name: argo-operations
description: >
  Set up, deploy, promote, and manage Argo ecosystem resources on live Kubernetes
  and OpenShift clusters. Covers Argo CD installation (Helm, operator, Autopilot),
  Application and ApplicationSet lifecycle, Rollout promotion and rollback, and
  day-2 operations (upgrades, API migration, scaling). Every write operation uses
  dry-run first and requires explicit user confirmation before applying. Use when
  users want to install Argo CD, create or sync Applications, promote Rollouts,
  or perform operational changes on their Argo setup.
license: MIT
compatibility: Requires oc or kubectl; optionally argocd, argo, kubectl-argo-rollouts, helm
---

# Argo Operations

Set up, deploy, promote, and manage Argo ecosystem resources on live clusters.

This is the **write** skill. It modifies clusters and repositories. The read-only
skills (`argo-knowledge`, `argo-repo-audit`, `argo-cluster-debug`) answer questions,
audit repos, and diagnose problems without changes. This skill **acts**.

## Safety Model

**Every write operation follows a 3-step protocol: Generate, Preview, Confirm.**

**Read-only operations** (backup/export, status checks, version queries) do NOT require
confirmation — just execute them and report results. The safety model applies only to
operations that modify cluster or repo state.

### Step 1: Generate

Produce the YAML manifest or CLI command for the requested operation. Show it to the
user in a fenced code block. Do not execute anything yet.

### Step 2: Preview

Show what the operation would change on the cluster before applying:

| Operation | Preview Command |
|-----------|----------------|
| Create resource | `kubectl apply --dry-run=client -f <file> -o yaml` |
| Create resource (server-validated) | `kubectl apply --dry-run=server -f <file> -o yaml` |
| Update resource | `kubectl diff -f <file>` or `oc diff -f <file>` |
| Sync Application | `argocd app diff <name>` |
| Helm install/upgrade | `helm template` or `helm upgrade --dry-run` |
| Delete resource | `kubectl get <kind> <name> -n <ns>` (show what exists) |
| Promote Rollout | `kubectl argo rollouts status <name> -n <ns>` (show current state) |

Show the preview output to the user. Explain what will change in plain language.

### Step 3: Confirm

Ask the user explicitly: **"Apply this? (yes/no)"**

Do not proceed without an affirmative response. Acceptable confirmations: "yes", "y",
"apply", "do it", "go ahead", "ship it". Anything else is a no.

### Safety Rules

These are hard constraints. Violating any of them is a blocker.

1. **NEVER apply without showing the user what will change first.** No silent writes.
2. **NEVER delete resources without listing what will be removed.** Show kind, name,
   namespace, and age of each resource before deletion.
3. **NEVER force-sync or force-push without explicit user request.** If the user says
   "sync", use normal sync. Only use `--force` if the user says "force sync".
4. **For destructive operations (delete, prune, rollback), require the user to type
   the resource name.** Do not accept "yes" alone for destructive ops. Ask:
   "Type the resource name `<name>` to confirm deletion."
5. **Log every applied change.** After each successful apply, report:
   `[APPLIED] <timestamp> <kind>/<namespace>/<name> — <action>`
6. **If a command fails, show the error and suggest recovery.** Do not retry
   automatically. Let the user decide.
7. **NEVER run `kubectl delete --all` or `kubectl delete ns` without explicit
   confirmation of the namespace name and a list of resources that will be destroyed.**
8. **NEVER modify Secrets containing credentials directly.** Generate the Secret
   manifest and let the user apply it, or use `kubectl create secret --dry-run=client`.

### Destructive Operations Checklist

Before executing any destructive operation, verify:

- [ ] The current cluster context is correct (`kubectl config current-context`)
- [ ] The target namespace is correct
- [ ] The resource exists and is the right one
- [ ] The user has explicitly confirmed with the resource name
- [ ] A preview of what will be removed has been shown

## Prerequisites

Before any operation, check the environment:

```bash
# Required
command -v kubectl >/dev/null && echo "kubectl: $(kubectl version --client -o json 2>/dev/null | grep gitVersion)" || echo "kubectl: MISSING"

# Optional — enhances capabilities
command -v argocd >/dev/null && echo "argocd: $(argocd version --client -o json 2>/dev/null | grep Version)" || echo "argocd: not installed"
command -v helm >/dev/null && echo "helm: $(helm version --short 2>/dev/null)" || echo "helm: not installed"
command -v kubectl-argo-rollouts >/dev/null && echo "rollouts plugin: available" || echo "rollouts plugin: not installed"

# Cluster context
kubectl config current-context
kubectl cluster-info --request-timeout=5s 2>/dev/null || echo "WARN: cluster not reachable"
```

If the cluster is not reachable, stop and report the error. Do not generate manifests
for a cluster you cannot validate against.

## Workflow Phases

### How to Route Requests

| User says | Phase | Reference |
|-----------|-------|-----------|
| "Install/set up Argo CD" | Phase 1: Setup | `references/setup.md` |
| "Create an Application/ApplicationSet" | Phase 2: Deploy | `references/deployment.md` |
| "Sync/deploy/promote/rollback" | Phase 3: Promote | `references/progressive-delivery.md` |
| "Upgrade/migrate/scale/backup" | Phase 4: Maintain | `references/day2-operations.md` |
| "Debug/troubleshoot/why is X broken" | Redirect to `argo-cluster-debug` | — |
| "What is/how does/explain" | Redirect to `argo-knowledge` | — |
| "Audit/review my repo" | Redirect to `argo-repo-audit` | — |
| "Set up environment promotion/promoter" | Phase 2: Deploy | `argo-knowledge/references/gitops-promoter.md` |

Load the matching reference file before starting. Max 1-2 reference files per request.

---

### Phase 1: Setup — Installing and Configuring Argo CD

Load `references/setup.md` for detailed procedures.

**Supported install methods:**

| Method | When to Use | Tools Required |
|--------|------------|----------------|
| Helm | Vanilla K8s, full control over values | helm, kubectl |
| OpenShift GitOps Operator | OpenShift clusters, OperatorHub | oc or kubectl |
| Autopilot | Bootstrapping a new GitOps repo | argocd-autopilot |

**Workflow:**

1. Detect the cluster platform:
   ```bash
   kubectl api-resources --api-group=route.openshift.io 2>/dev/null && echo "OpenShift" || echo "Kubernetes"
   ```
2. Ask the user which install method they prefer (if not specified).
3. Load `references/setup.md` and follow the matching procedure.
4. Generate the install manifests/commands.
5. **Preview** — show what will be created (namespace, CRDs, Deployments, Services).
6. **Confirm** — wait for user approval.
7. Apply and verify:
   ```bash
   kubectl get pods -n <namespace> -l app.kubernetes.io/part-of=argocd
   ```

**Covers:**
- Helm install (HA vs non-HA, values customization)
- OpenShift GitOps Operator (Subscription, ArgoCD CR)
- Autopilot bootstrap (`argocd-autopilot repo bootstrap`)
- Dex/SSO configuration (OpenShift OAuth, OIDC, SAML, Keycloak)
- RBAC configuration (argocd-rbac-cm, AppProject roles)
- External cluster registration (`argocd cluster add`)
- AppProject creation (sourceRepos, destinations, clusterResourceWhitelist, roles)

---

### Phase 2: Deploy — Creating and Managing Applications

Load `references/deployment.md` for detailed procedures.

**Workflow:**

1. Determine the source type from the user's request:
   | Source | Indicators |
   |--------|-----------|
   | Helm chart | OCI URL, chart repo URL, `values.yaml` |
   | Kustomize | Overlays directory, `kustomization.yaml` |
   | Plain directory | Path to YAML files, no Helm/Kustomize |
   | Multi-source | Multiple repos, values from separate repo |
2. Generate the Application or ApplicationSet YAML.
3. **Preview** — `kubectl apply --dry-run=server -f <file>` or `argocd app diff`.
4. **Confirm** — wait for user approval.
5. Apply and verify:
   ```bash
   argocd app get <name> 2>/dev/null || kubectl get application <name> -n argocd -o jsonpath='{.status.sync.status}'
   ```

**Covers:**
- Application (all source types, multi-source with `$values` refs)
- ApplicationSet (git, list, cluster, matrix, merge, PR, SCM generators)
- Sync policies (automated, manual, selfHeal, prune, retry)
- Notifications (argocd-notifications-cm, Secret, Application annotations)
- Image updater (annotations, registries config, write-back method)
- Sync waves and hooks (annotation patterns, ordering, PreSync/PostSync)

---

### Phase 3: Promote — Progressive Delivery Operations

Load `references/progressive-delivery.md` for detailed procedures.

**Workflow:**

1. Check the current state before any promotion:
   ```bash
   kubectl argo rollouts status <name> -n <namespace> 2>/dev/null || \
     kubectl get rollout <name> -n <namespace> -o jsonpath='{.status.phase}'
   ```
   For Application syncs:
   ```bash
   argocd app get <name> -o json 2>/dev/null | jq '.status.sync.status, .status.health.status' || \
     kubectl get application <name> -n argocd -o jsonpath='sync={.status.sync.status} health={.status.health.status}'
   ```
2. Show the user the current state and what the operation will do.
3. **Preview** — show what will change (new weight, promoted ReplicaSet, synced resources).
4. **Confirm** — wait for user approval.
5. Execute and monitor:
   ```bash
   kubectl argo rollouts get rollout <name> -n <namespace> --watch 2>/dev/null
   ```

**Covers:**
- Sync Applications (`argocd app sync` or `kubectl apply`)
- Promote Rollouts (`kubectl argo rollouts promote`)
- Abort Rollouts (`kubectl argo rollouts abort`)
- Retry Rollouts (`kubectl argo rollouts retry`)
- Run manual AnalysisRuns
- Set canary weight (`kubectl argo rollouts set-weight`)
- Rollback (`kubectl argo rollouts undo` or `argocd app rollback`)

---

### Phase 4: Maintain — Day-2 Operations

Load `references/day2-operations.md` for detailed procedures.

**Workflow:**

1. Assess current state:
   ```bash
   argocd version 2>/dev/null || kubectl get pods -n argocd -o jsonpath='{.items[0].spec.containers[0].image}'
   ```
2. Identify what needs to change and the target state.
3. **For upgrades — always include these two items in your response:**
   - "Recommend backing up Applications and AppProjects before proceeding (run backup export)"
   - "Check the release notes at https://github.com/argoproj/argo-cd/releases for breaking changes between current and target versions"
   These are non-negotiable for any upgrade operation regardless of install method.
4. Generate the upgrade/migration/scaling commands.
5. **Preview** — show the diff between current and target state.
6. **Confirm** — wait for user approval.
7. Apply in stages (CRDs first, then components) and verify after each stage.

**For backup operations:** export Applications, AppProjects, and relevant ConfigMaps
(argocd-cm, argocd-rbac-cm). Also offer to export credential Secrets (repo creds,
cluster secrets) with a clear security warning that exported Secrets contain sensitive
data. This is a read-only operation — no confirmation needed.

**Covers:**
- Upgrade Argo CD (Helm, operator, image bump)
- Migrate deprecated APIs (`argocd admin migrate`)
- Scale components (controller replicas, repo-server, redis sentinel)
- HA setup (redis sentinel, multiple controller replicas)
- Backup/restore (export Applications, AppProjects, ConfigMaps, Secrets with warnings)
- Credential rotation (Git SSH keys, PATs, GitHub Apps, cluster tokens)
- Disaster recovery (re-bootstrap from Git)
- Enable/disable features (notifications, image updater, SSO)

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Cluster not reachable | Report error, do not generate apply commands. Ask user to fix connectivity. |
| Insufficient RBAC permissions | Run `kubectl auth can-i` to identify missing permissions. Report what's needed. |
| Resource already exists | Use `kubectl apply` (update) not `kubectl create`. Show the diff. |
| Conflicting changes (sync in progress) | Check `operationState.phase`. If `Running`, wait or ask user to cancel. |
| OpenShift vs vanilla K8s | Detect platform first. Use `oc` and Routes on OpenShift, `kubectl` and Ingress on K8s. |
| Dry-run fails (CRD not installed) | Fall back to `--dry-run=client`. Warn that server-side validation was skipped. |
| Helm chart not reachable | Report the error. Suggest checking `helm repo update` or OCI registry auth. |
| Application name conflict | Check if an Application with the same name exists. Show the existing one and ask. |
| Multiple Argo CD instances | Detect by checking for ArgoCD CRs or argocd-labeled pods in multiple namespaces. Ask which instance. |
| Rollout already completed | Report that the rollout is already Healthy. No action needed. |
| Rollout already aborted | Show the aborted state. Ask if user wants to retry or update the spec. |

## Reference Index

| Topic | Reference File | When to Load |
|-------|---------------|-------------|
| Helm install, operator install, Autopilot, SSO, RBAC, clusters, AppProjects | `references/setup.md` | Phase 1 — setup and installation requests |
| Application creation, ApplicationSet, sync policies, notifications, image updater, sync waves | `references/deployment.md` | Phase 2 — creating and configuring applications |
| Rollout promotion, canary/blue-green, AnalysisRuns, rollback, traffic management | `references/progressive-delivery.md` | Phase 3 — promotion and progressive delivery |
| Upgrades, API migration, scaling, HA, backup/restore, credential rotation | `references/day2-operations.md` | Phase 4 — maintenance and operational changes |
