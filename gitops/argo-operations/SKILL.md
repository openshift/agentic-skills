---
name: argo-operations
description: >
  Set up, deploy, promote, and manage Red Hat OpenShift GitOps resources on live
  OpenShift and Kubernetes clusters. Covers Argo CD installation (OpenShift GitOps
  operator, Helm, Autopilot),
  Application and ApplicationSet lifecycle, Rollout promotion and rollback, and
  day-2 operations (upgrades, API migration, scaling replica counts). Every write operation uses
  dry-run first and requires explicit user confirmation before applying. Use when
  users want to install Argo CD, create or sync Applications, promote Rollouts,
  or perform operational changes on their OpenShift GitOps setup. Argo Workflows and
  Argo Events are out of scope.
license: MIT
compatibility: Requires oc or kubectl; optionally argocd, argo, kubectl-argo-rollouts, helm
---

# Argo Operations

Set up, deploy, promote, and manage Argo ecosystem resources on live clusters.

This is the **write** skill. It modifies clusters and repositories. The read-only
skills (`argo-knowledge`, `argo-repo-audit`, `argo-cluster-debug`) answer questions,
audit repos, and diagnose problems without changes. This skill **acts**.

## Safety Model

**Every write operation follows this protocol: Generate, Preview, Blast radius, Confirm,
Verify.** Preview shows what changes on the object; blast radius shows who else is
affected. They are different questions and a diff only answers the first.

The fourth step is not optional. A benchmark run found this skill losing to an unaided
baseline on exactly one thing: it stopped at the confirmation gate and never checked that
the change worked. Applying without verifying is how a "successful" upgrade is discovered
to be broken hours later.

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
| Create resource | `kubectl apply --dry-run=server --validate=strict -f <file> -o yaml` — **prefer server** |
| Update resource | `kubectl diff -f <file>` or `oc diff -f <file>` |
| Sync Application | `argocd app diff <name>` |
| Helm install/upgrade | `helm template` or `helm upgrade --dry-run` |
| Delete resource | `kubectl get <kind> <name> -n <ns>` (show what exists) |
| Promote Rollout | `kubectl argo rollouts status <name> -n <ns>` (show current state) |

Show the preview output to the user. Explain what will change in plain language.

#### `--dry-run=client` is a weak preview — do not rely on it

It renders your file locally. It contacts no admission or schema validation, and it does
not merge against live state, so **for an update it cannot show what will change** — it
just echoes your input back. Measured against a real cluster:

```
manifest with a nonexistent field AND a wrong-typed value
  kubectl apply --dry-run=client   -> ACCEPTED   (no validation at all)
  kubectl apply --dry-run=server --validate=strict   -> REJECTED   (schema validated)
```

So:
- **Creating?** Use `--dry-run=server --validate=strict`. Fall back to client only if the API rejects a
  server dry-run outright (CRD absent), and say plainly that nothing was validated.
- **Updating?** Use `kubectl diff`. A client dry-run is not a preview of an update under
  any circumstances; presenting one as the Preview step gives the user false assurance
  that the change is understood and safe.

### Step 2b: Blast radius — who else does this touch?

A dry-run or diff answers "what changes on **this object**". It does not answer "what
**else** is affected", and for Argo CD those are rarely the same question: most of its
objects are fan-out points. A one-field diff on an `ArgoCD` CR looks trivial and restarts
components every Application on the instance depends on.

**Compute it, then show the user the result before asking to confirm:**

```bash
<repo-root>/scripts/blast-radius.sh <kind> <name> [namespace]
```

It handles `ArgoCD`, `AppProject`, `ApplicationSet`, `Application`, `RolloutManager` and
the shared ConfigMaps, and is strictly read-only. Exit 3 means no cluster was reachable —
reason the impact out instead and say it was not verified.

Say the number out loud. "This restarts the repo-server serving 47 Applications" lands
very differently from "this changes one field". An empty result is worth saying too:
"blast radius: just this Application, nothing else references it".

This applies to **recommendations as well as writes.** If you tell the user to do
something you are not executing, it still needs its impact stated — see the Report
Format. Most of the harm from a bad recommendation happens after the session ends.

### Step 3: Confirm

Ask the user explicitly: **"Apply this? (yes/no)"**

Do not proceed without an affirmative response. Acceptable confirmations: "yes", "y",
"apply", "do it", "go ahead", "ship it". Anything else is a no.

### Step 4: Verify

**After every applied change, check that it actually took effect, and show the user the
output.** An apply that returns `configured` means the API accepted your object — not
that the operator reconciled it, the pods rolled, or the thing you wanted is true.

| Operation | Verify with |
|-----------|-------------|
| Create/update a resource | `$KCTL get <kind> <name> -n "$NS" -o yaml` — confirm the field you set is actually present (the operator may reconcile it away) |
| Operator-managed change (ArgoCD CR) | `$KCTL get argocd <name> -n "$NS" -o jsonpath='{.status}'` then confirm the affected pods restarted: `$KCTL get pods -n "$NS"` |
| Install | `$KCTL get pods -n "$NS"` — every component `Running` and `READY`; then `$KCTL get argocd -A` |
| Upgrade | `$KCTL get csv -n <operator-ns>` is `Succeeded` (**not** Subscription `state`, which reports `AtLatestKnown` while the CSV is stuck), plus component versions and pod health |
| Sync an Application | `argocd app get <name> --refresh` or `$KCTL get applications.argoproj.io <name> -n "$NS" -o jsonpath='sync={.status.sync.status} health={.status.health.status}'` |
| Promote/abort/retry a Rollout | `kubectl argo rollouts get rollout <name> -n <ns>` — report the **resulting phase**, not just that the command returned |
| Credential rotation | `argocd repo get <url>` or a connectivity test — a credential that applies cleanly and cannot authenticate is the whole failure mode |
| Delete | confirm it is gone *and* that nothing you did not intend went with it (check for cascading finalizer deletions) |

Rules for this step:

1. **Report the verification output**, do not just claim success. "Applied and verified"
   with no command output is not a verification.
2. **Allow for reconciliation lag.** Operator-managed and Argo-managed changes are not
   instant. If the first check does not show the expected state, say so and re-check
   rather than declaring success or failure immediately.
3. **If verification fails, say so plainly** and do not auto-remediate. Report what you
   observed versus what you expected and let the user decide.
4. **Read-only operations still get a result summary** — a backup reports what it wrote
   and, critically, what it did *not* capture.
5. **If the operation could not be executed, still state the verification plan.** Missing
   tool, absent resource, unreachable cluster, or stopping at the confirmation gate — name
   the checks you *would* run and what each should show. Dropping verification because
   nothing was applied is the most common way this step gets skipped, and it leaves the
   user with no way to tell afterwards whether it worked.

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
5. **Log every applied change, then verify it.** After each successful apply, report:
   `[APPLIED] <timestamp> <kind>/<namespace>/<name> — <action>`
   followed by the Step 4 verification output. An `[APPLIED]` line on its own is a claim,
   not evidence.
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

### Resolving the cluster CLI

**`kubectl` in this skill means "the cluster CLI" — resolve it once, then substitute it
into every command below.** Do not report a broken environment just because the binary is
literally named `kubectl` and is absent; on OpenShift hosts `oc` is frequently the only
one installed, and it accepts every `kubectl` command in this skill verbatim.

Run this first and use `$KCTL` for every cluster command afterwards:

```bash
# Detect the platform and pick the CLI — on OpenShift, oc is the default.
if command -v oc >/dev/null 2>&1 && oc api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes; then
  KCTL=oc; PLATFORM=OpenShift
elif command -v kubectl >/dev/null 2>&1; then
  KCTL=kubectl
  PLATFORM=$(kubectl api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes && echo OpenShift || echo Kubernetes)
elif command -v oc >/dev/null 2>&1; then
  KCTL=oc; PLATFORM=Kubernetes
else
  echo "ERROR: no cluster CLI found — install kubectl or oc" >&2; exit 1
fi
echo "Platform: $PLATFORM — using '$KCTL'"

# Resolve the Argo CD namespace too — `argocd` is the upstream default and is almost
# never right on OpenShift, where it is `openshift-gitops` (and often several instances).
$KCTL get argocd -A --no-headers 2>/dev/null || \
  $KCTL get pods -A -l app.kubernetes.io/part-of=argocd --no-headers 2>/dev/null | awk '{print $1}' | sort -u
NS=openshift-gitops      # set to the instance you are working on; every command below uses $NS
```

**On OpenShift, default to `oc`.** `Route`, `project`, `SecurityContextConstraints`, and
`oc adm` have no `kubectl` equivalent, and they are exactly what you need when a Route is
misconfigured or an SCC is blocking a pod. `oc` also accepts every `kubectl` command in
this skill verbatim, so there is no downside.

This also replaces the separate OpenShift check in Phase 1 — `$PLATFORM` is already set.
Only report a missing prerequisite when **neither** binary exists.

```bash
# Optional — enhances capabilities
command -v argocd >/dev/null && echo "argocd: $(argocd version --client -o json 2>/dev/null | grep Version)" || echo "argocd: not installed"
command -v helm >/dev/null && echo "helm: $(helm version --short 2>/dev/null)" || echo "helm: not installed"
command -v kubectl-argo-rollouts >/dev/null && echo "rollouts plugin: available" || echo "rollouts plugin: not installed"

# Cluster context — use the CLI resolved above
$KCTL config current-context
$KCTL cluster-info --request-timeout=5s 2>/dev/null || echo "WARN: cluster not reachable"
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
| "Tune for performance/scale, fix OOM/timeouts, speed up sync" | Redirect to `argo-performance-tuning` | — |
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
   echo "$PLATFORM"   # already resolved in Prerequisites — do not re-detect
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
3. **Preview** — `kubectl apply --dry-run=server --validate=strict -f <file>` or `argocd app diff`.
4. **Confirm** — wait for user approval.
5. Apply and verify:
   ```bash
   argocd app get <name> 2>/dev/null || kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='{.status.sync.status}'
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
     kubectl get applications.argoproj.io <name> -n "$NS" -o jsonpath='sync={.status.sync.status} health={.status.health.status}'
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
   argocd version 2>/dev/null || kubectl get pods -n "$NS" -o jsonpath='{.items[0].spec.containers[0].image}'
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
| Dry-run fails (CRD not installed) | Fall back to `--dry-run=client`, but state explicitly that **nothing was validated** — client dry-run accepts nonexistent fields and wrong types silently. Treat the preview as 'here is the YAML I would send', not 'this is valid'. For an update, say that no diff was possible. |
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
