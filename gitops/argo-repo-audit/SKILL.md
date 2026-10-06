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
bash skills/argo-repo-audit/scripts/discover.sh -d <repo-root>
```

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

### Phase 2: Manifest Validation

**If `yq`, `kustomize`, and `kubeconform` are available**, run the validation script:
```bash
bash skills/argo-repo-audit/scripts/validate.sh -d <repo-root>
```

This performs YAML syntax checks, Kubernetes schema validation (using Argo CRD schemas
from `assets/schemas/`), and Kustomize overlay builds.

**If tools are not available**, skip this phase and note it in the report:
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
- **Workflow resource limits** — activeDeadlineSeconds, retry strategies, pod GC

Skip categories with zero matching resources.

### Phase 4: Security Review

**Read `references/security-audit.md` and work through each checklist item.** This file
contains specific things to look for and grep commands to find them. Check:

- **AppProject restrictions** — sourceRepos, destinations, clusterResourceWhitelist
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

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Not an Argo repo (no `argoproj.io` CRDs) | Report "No Argo resources detected", skip Phases 3-4 |
| Mixed tooling (Argo + Terraform, Argo + Flux) | Note in summary, audit only Argo resources |
| SOPS-encrypted secrets | Detect by `sops:` metadata, note as "encrypted — OK" |
| Helm chart directories | Skip directories with `Chart.yaml` — rendered by Argo at sync time |
| Third-party CRDs | Skipped by kubeconform — not an error |

## Argo CRD Reference

All CRDs use `apiVersion: argoproj.io/v1alpha1`:

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
| Workflow | Argo Workflows | DAG/step-based job execution |
| WorkflowTemplate | Argo Workflows | Reusable workflow definition |
| ClusterWorkflowTemplate | Argo Workflows | Cluster-scoped WorkflowTemplate |
| CronWorkflow | Argo Workflows | Scheduled workflow execution |
| EventSource | Argo Events | Event ingestion (webhooks, SNS, SQS, etc.) |
| EventBus | Argo Events | Event transport (NATS, Jetstream, Kafka) |
| Sensor | Argo Events | Event-driven trigger execution |
