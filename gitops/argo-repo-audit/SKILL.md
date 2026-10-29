---
name: argo-repo-audit
description: >
  Audit and validate Argo CD GitOps repositories by scanning local repo files (not live clusters) —
  reviews AppProject RBAC and security restrictions, checks sync policies and operational best
  practices, optionally runs schema validation, and produces a prioritized GitOps report. Use when
  users ask to audit, analyze, validate, review, or security-check an Argo CD GitOps repo.
license: MIT
compatibility: Optional tools for deeper validation — awk, yq, kustomize, kubeconform
---

# Argo Repo Audit

Audit and validate Argo CD GitOps repositories by scanning local files — no live cluster required.

## How This Skill Works

The audit has two layers:

1. **Checklist-driven analysis** (primary) — load comprehensive checklists from reference files
   and work through each item against the repo's YAML files. This is where most findings come from.

2. **Automated validation** (optional, deeper) — run bundled scripts for schema validation and
   resource discovery. Use when the tools are available; skip gracefully if not.

## Workflow

### Phase 1: Discovery

Inventory all Argo and Kubernetes resources in the repository.

**Option A — If `awk` is available**, run the discovery script for structured counts:
```bash
bash <skill-dir>/scripts/discover.sh -d <repo-root>
```

`<skill-dir>` is the directory containing this `SKILL.md`, **not** the repo being audited —
when installed as a plugin the two are different. Use the absolute path to this skill's
directory. `-d` is the root of the repo under audit.

**Option B — Otherwise**, scan YAML files directly:
- Find all `.yaml`/`.yml` files (skip `.git/`, `Chart.yaml` dirs, `.tf` dirs)
- Extract `apiVersion` and `kind` from each document
- Count Argo resources (`argoproj.io`) by kind
- Count Kubernetes resources by kind
- Note Kustomize overlays (`kustomize.config.k8s.io`)

With the inventory:

1. **Classify the repo pattern** using the heuristics in `references/repo-patterns.md`:
   - **App of Apps**: Application resources whose `spec.source.path` points to directories containing other Application YAMLs
   - **ApplicationSet**: Presence of ApplicationSet resources with generators
   - **Monorepo**: Single repo with path-based Applications and environment overlays
   - **Multi-Repo**: Applications referencing different `repoURL` values
   - **Environment Branch**: Same `repoURL` but different `targetRevision` per environment

2. **Detect clusters and environments** from directory names, `spec.destination` values,
   ApplicationSet generator parameters, and overlay directories.

3. **Note mixed tooling** — Terraform, Flux, or Helm-only charts co-existing with Argo resources.

4. **Check for duplicate `metadata.name` within a kind+namespace.** Two files declaring
   the same AppProject or Application is last-apply-wins: whichever syncs last silently
   overwrites the other, and under either winner some Applications may be rejected by the
   surviving project's `sourceRepos`/`destinations`. Schema validation cannot catch this —
   each file is individually valid.

   Use a YAML-aware scan. A grep over `kind:`/`name:` proximity breaks on documents
   ordered `apiVersion / metadata / kind`, on labels appearing before `name:`, and on any
   indentation other than two spaces — and with `-h` it prints no file paths, which this
   step asks for. Select at the **document** level: a recursive `..` match also picks up
   `clusterResourceWhitelist[].kind`, producing phantom `*` entries.

   ```bash
   # Requires yq. Reports kind|namespace|name collisions with the files involved.
   find <repo-root> \( -name '*.yaml' -o -name '*.yml' \) -print | while read -r f; do
     yq -r "select(.kind == \"Application\" or .kind == \"AppProject\" or .kind == \"ApplicationSet\")
            | [.kind, (.metadata.namespace // \"-\"), .metadata.name, \"$f\"] | @tsv" "$f" 2>/dev/null
   done | awk -F'\t' 'NF>=4{k=$1"|"$2"|"$3; seen[k]=seen[k]" "$4; n[k]++}
                      END{c=0; for(x in n) if(n[x]>1){print x" ->"seen[x]; c++}
                          if(!c) print "no duplicates"}'
   ```

   Namespace is part of the key: the same Application name in two namespaces is legal, and
   flagging it is a false positive. If `yq` is unavailable, say so in the report and mark
   this check as not run rather than substituting a grep that silently under-reports.
   Any output is a **Critical** finding — report both file paths.

### Phase 2: Manifest Validation

Run the validation script whenever **any** of `yq`, `kustomize`, or `kubeconform` is
available — it degrades per tool and runs whichever passes it can:

```bash
bash <skill-dir>/scripts/validate.sh -d <repo-root>
```

| Tool | Pass it enables | Missing → |
|------|----------------|-----------|
| `yq` | 1 — YAML syntax | that pass is skipped, others still run |
| `kubeconform` | 2 — schema validation against `assets/schemas/` | that pass is skipped, others still run |
| `kustomize` | 3 — overlay builds | that pass is skipped, others still run |

Exit codes: `0` pass, `1` validation errors found, `2` none of the three tools installed
(nothing could be checked). **Only exit `2` means "no validation happened".** Read the
script's `Skipped:` summary line and carry it into the report — a reduced run that finds
nothing is not a clean bill of health.

This performs YAML syntax checks, Kubernetes schema validation (using Argo CRD schemas
from `assets/schemas/`), and Kustomize overlay builds.

**Two coverage limits to state in the report rather than let the reader assume away:**

- **Secrets are not inspected here.** The script runs kubeconform with `-skip=Secret`, so
  a validate-only run can never surface a plain-text Secret. Those are Phase 4 findings.
  Never let a clean Pass 2 imply the repo is free of hardcoded credentials.

**Never print a credential value.** Report file, line and key name; run
`scripts/scan-credentials.sh <repo-root>`, which redacts values by construction. Do not
`cat` a Secret manifest, and do not `base64 -d` a `data:` value to "confirm" it — the
decoded secret lands in the transcript, and whether it decodes cleanly was never the
question. If judging severity genuinely requires seeing a value, ask the user first.
- **Schemas ship for every in-scope kind** — Application, AppProject, ApplicationSet,
  ArgoCD, Rollout, AnalysisTemplate, AnalysisRun, Experiment. Argo Workflows and Argo
  Events kinds are out of scope for OpenShift GitOps; if a repo contains them, note that
  they were not validated rather than silently passing over them.

**If none of the three tools are available** (exit code `2`), skip this phase and note it:
"Schema validation skipped — install yq, kustomize, kubeconform for deeper validation."

### Phase 3: Best Practices Assessment

**Read `references/best-practices.md` and work through each checklist item** against the
repo files. For each item, read the relevant YAML files and check compliance.

Focus on categories that match the discovery results:
- **Sync policies** — automated sync, selfHeal, prune, retry configuration
- **ApplicationSet configuration** — progressive syncs, generators, preserveResourcesOnDeletion, goTemplate
- **Resource tracking method** — annotation vs label-based tracking
- **Health checks** — custom health checks for CRDs
- **Ignore differences** — fields managed by controllers (HPA replicas, mutating webhooks)
- **Sync waves and hooks** — ordering via sync-wave annotations and PreSync/PostSync hooks
- **Rollout configurations** — AnalysisTemplates, canary steps, traffic management

Skip categories with zero matching resources.

### Phase 4: Security Review

**Read `references/security-audit.md` and work through each checklist item.** This file
contains specific things to look for and grep commands to find them. Check:

- **AppProject restrictions** — sourceRepos, destinations, clusterResourceWhitelist.
  **Wildcards are the easy case; do not stop there.** An *enumerated*
  `clusterResourceWhitelist` containing `ClusterRole`/`ClusterRoleBinding` (or webhook
  configs, CRDs, SCCs) grants cluster-wide privilege escalation while passing every
  wildcard grep and reading as careful least-privilege. Same for project role policies
  like `applications, *` or any `exec, create` — scoped, but still too broad. Run the
  enumerated-escalation and scoped-but-dangerous scans in `security-audit.md`.
- **RBAC** — SSO integration, project roles, default policy, admin access
- **Secrets management** — plain-text Secrets (should be sealed-secrets, external-secrets, SOPS, or Vault)
- **Cluster credentials** — argocd-cluster-secret not in plain text
- **Source/destination wildcards** — `*` in sourceRepos or destinations
- **Network policies** — ingress TLS, GRPC configuration

If the repo targets **OpenShift** (presence of `Route`, `ArgoCD` CRD, `DeploymentConfig`),
also check the OpenShift-specific section in `security-audit.md`.

### Phase 5: Report

Produce a structured markdown report:

#### 1. Summary

| Field | Value |
|-------|-------|
| Repository | `<name>` |
| Pattern | App of Apps / ApplicationSet / Monorepo / Multi-Repo / Environment Branch |
| Clusters | list of detected clusters |
| Argo Resources | count by kind |
| Kubernetes Resources | count by kind |
| Overall Status | PASS / WARN / FAIL |

#### 2. Directory Structure

Relevant directory tree with annotations.

#### 3. Validation Results

If validation was run, table of findings (file, kind, issue, severity).
If skipped, note why.

#### 4. Best Practices

For each applicable category:
- Status (Pass / Fail / N/A)
- Findings with file paths and line references
- Recommendation if failing

#### 5. Security

For each applicable check:
- Status (Pass / Fail / N/A)
- Evidence (file path, line, value)
- Risk level (Critical / High / Medium / Low)

#### 6. Recommendations

Prioritized list:
- **Critical** — Security vulnerabilities, plain-text secrets, wildcard permissions in production
- **Warning** — Missing best practices that increase operational risk
- **Info** — Suggestions for improved maintainability or performance

**State the impact of acting on each finding, not just its severity.** Severity says how
bad it is; impact says what changes when someone fixes it. These are repo findings, so
the impact is usually "what happens on the next sync", and that is exactly what a
reviewer cannot infer from the finding alone.

```
Critical — Plain-text password in helm.values (app.yaml:16)
  Impact: rotating it requires updating the Secret AND re-syncing the Application.
          The credential should be treated as compromised — it is in git history,
          so removing it from HEAD is not sufficient.

Warning  — AppProject 'team-a' allows sourceRepos: '*'
  Impact: tightening this can push existing Applications in the project to
          InvalidSpecError if any uses a repo outside the new list. Enumerate
          them before narrowing it.
```

This skill reads files and does not touch a cluster, so impact is reasoned from the
manifests — **say so** rather than implying it was verified live. If a cluster happens
to be reachable and the finding concerns a fan-out object, `<repo-root>/scripts/blast-radius.sh`
will resolve the real affected set.

"Impact: none beyond this file" is a fine answer and should be stated, not omitted.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Not an Argo repo (no `argoproj.io` CRDs) | Report "No Argo resources detected", skip Phases 3-4 |
| Mixed tooling (Argo + Terraform, Argo + Flux) | Note in summary, audit only Argo resources |
| SOPS-encrypted secrets | Detect by `sops:` metadata, note as "encrypted — OK" |
| Helm chart directories | Skip directories with `Chart.yaml` — rendered by Argo at sync time |
| Third-party CRDs | Skipped by kubeconform — not an error |

## Argo CRD Reference

Most CRDs use `apiVersion: argoproj.io/v1alpha1`. **The `ArgoCD` CR is
`argoproj.io/v1beta1`** (v1alpha1 is deprecated for that kind), as are
`NamespaceManagement` and the OpenShift GitOps operator CRDs — schemas for those ship in
`assets/schemas/`. Check the kind before asserting a version:

| Kind | Project | Description |
|------|---------|-------------|
| Application | Argo CD | Defines a deployed application |
| AppProject | Argo CD | Groups applications with RBAC and restrictions |
| ApplicationSet | Argo CD | Templated multi-cluster/multi-env application generation |
| Rollout | Argo Rollouts | Advanced deployment with canary/blue-green |
| AnalysisTemplate | Argo Rollouts | Metrics-based promotion criteria |
| ClusterAnalysisTemplate | Argo Rollouts | Cluster-scoped AnalysisTemplate |
| AnalysisRun | Argo Rollouts | Instance of an analysis execution |
| Experiment | Argo Rollouts | Temporary ReplicaSet for A/B testing |
