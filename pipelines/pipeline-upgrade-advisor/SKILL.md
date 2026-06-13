---
name: pipeline-upgrade-advisor
description: Assess OpenShift Pipelines upgrade readiness and risk. Use when evaluating whether the Pipelines operator can safely upgrade, when an operator upgrade is available, or when the user asks about Pipelines upgrade risks, prerequisites, or blockers.
---

# Pipeline Upgrade Advisor

## 1. Purpose

Assess OpenShift Pipelines operator upgrade readiness and produce a structured
risk report with actionable prerequisites, blockers, and recommendations.

The proposal request includes pre-collected upgrade readiness data (JSON)
gathered by the OpenShift Pipelines operator. Analyze this data, classify
findings, and produce a decision with evidence. Do not re-collect cluster
data -- it is already in the request.

## 2. Inputs

The proposal request contains:
- Current and target Pipelines operator version metadata
- Tekton component versions (pipeline, triggers, chains, hub)
- **Upgrade readiness JSON** -- pre-collected by the operator with results from multiple checks

The readiness JSON is embedded in the request between ` ```json ` markers under
the "Upgrade Readiness Data" heading. Parse it to begin analysis.

**Readiness JSON structure:**

```json
{
  "current_version": "1.15.0",
  "target_version": "1.16.0",
  "tekton_versions": {
    "current": {
      "pipeline": "0.59.0",
      "triggers": "0.27.0",
      "chains": "0.22.0",
      "hub": "1.18.0"
    },
    "target": {
      "pipeline": "0.62.0",
      "triggers": "0.28.0",
      "chains": "0.23.0",
      "hub": "1.19.0"
    }
  },
  "api_versions": {
    "v1beta1_pipelines": 5,
    "v1beta1_tasks": 12,
    "v1beta1_pipelineruns": 0,
    "v1beta1_taskruns": 0,
    "v1_pipelines": 42,
    "v1_tasks": 87,
    "v1_custom_runs": 3
  },
  "running_pipelines": {
    "active_pipeline_runs": 3,
    "active_task_runs": 7,
    "namespaces_with_active_runs": ["ci", "staging", "build-system"],
    "oldest_active_run_age_minutes": 45
  },
  "tekton_health": {
    "controllers": {
      "tekton-pipelines-controller": {"ready": true, "restarts": 0, "version": "0.59.0"},
      "tekton-pipelines-webhook": {"ready": true, "restarts": 0, "version": "0.59.0"},
      "tekton-triggers-controller": {"ready": true, "restarts": 0, "version": "0.27.0"},
      "tekton-triggers-webhook": {"ready": true, "restarts": 0, "version": "0.27.0"},
      "tekton-chains-controller": {"ready": true, "restarts": 0, "version": "0.22.0"}
    },
    "crds_installed": ["pipelines.tekton.dev", "tasks.tekton.dev", "triggers.tekton.dev"],
    "operator_condition": "Upgradeable=True"
  },
  "custom_tasks": {
    "custom_task_definitions": [
      {
        "name": "my-custom-task",
        "api_version": "example.com/v1",
        "compatible_tekton_versions": ["0.59.0", "0.62.0"]
      }
    ],
    "cluster_tasks_in_use": 8,
    "cluster_tasks_deprecated": true
  },
  "cluster_info": {
    "ocp_version": "4.16.0",
    "target_ocp_compatibility": ["4.14", "4.15", "4.16", "4.17"],
    "platform": "AWS"
  },
  "meta": {
    "total_checks": 6,
    "checks_ok": 5,
    "checks_errored": 1,
    "elapsed_seconds": 1.2
  }
}
```

Each section provides readiness data from a different perspective. Parse all
sections before forming conclusions.

### What the sections cover

| Section | What it assesses |
|---|---|
| `tekton_versions` | Current and target versions for all Tekton components |
| `api_versions` | Count of resources using deprecated (v1beta1) vs stable (v1) API versions |
| `running_pipelines` | Active PipelineRuns and TaskRuns that would be disrupted by upgrade |
| `tekton_health` | Controller/webhook readiness, restart counts, CRD status, operator condition |
| `custom_tasks` | Custom task definitions and their compatibility with the target Tekton version |
| `cluster_info` | OCP version and target operator compatibility matrix |

## 3. When to Investigate Further

After analyzing the readiness JSON, use other skills to dig deeper into
specific findings:

- **`prometheus`** -- if `tekton_health` shows degraded conditions or elevated
  restart counts, query `tekton_pipelines_controller_running_pipelineruns_count`
  and `tekton_pipelines_controller_pipelinerun_duration_seconds` for trends.

- **`platform-docs`** -- read the OpenShift Pipelines release notes for the
  target version to identify breaking changes, deprecated features, and
  migration requirements.

- **`tekton-docs`** -- if `api_versions` shows v1beta1 resources, read the
  Tekton migration guides for v1beta1 to v1 conversion.

- **`redhat-support`** -- search Jira for bugs against the target Pipelines
  operator version, check KB for known upgrade issues.

- **`product-lifecycle`** -- cross-reference the installed Pipelines operator
  version with Red Hat Product Life Cycle data to check support status and
  EOL dates.

## 4. Decision Policy

### 4.1 Workflow

```
Step 1: Parse readiness data
  Extract the JSON from the proposal request. Review
  meta.checks_ok vs meta.total_checks for completeness.
                     |
Step 2: Check for running pipelines
  Active PipelineRuns and TaskRuns will be disrupted by
  an operator upgrade. If running_pipelines.active_pipeline_runs
  > 0, this is a disruption risk.
                     |
Step 3: Check API version deprecations
  Count v1beta1 resources in api_versions. The Tekton
  v1beta1 APIs are deprecated and will be removed in
  future versions. Resources must be migrated to v1.
                     |
Step 4: Check custom task compatibility
  For each custom task in custom_tasks.custom_task_definitions,
  verify the target Tekton version is in
  compatible_tekton_versions. Also check if ClusterTasks
  are in use -- they are deprecated in newer versions.
                     |
Step 5: Check Tekton component health
  All controllers and webhooks in tekton_health must be
  ready with low restart counts. Unhealthy components
  must be fixed before upgrading.
                     |
Step 6: Check cluster compatibility
  Verify the target operator version is compatible with
  the current OCP version using cluster_info.
                     |
Step 7: Classify and decide
  Assign each finding a severity per the classification
  table in section 4.2. Then determine the overall
  assessment per the decision matrix in section 4.4.
                     |
Step 8: Investigate (as needed)
  Use prometheus, platform-docs, tekton-docs,
  redhat-support, or product-lifecycle skills for
  deeper analysis.
                     v
             Produce structured risk report
```

### 4.2 Blocker Classification

| Severity | Criteria | Action |
|---|---|---|
| **Blocker** | Upgrade will fail or cause data loss / pipeline breakage | `decision: block` |
| **Warning** | Upgrade may cause disruption or require follow-up work | `decision: caution` |
| **Info** | Noteworthy but non-blocking | Include for awareness |

Classification rules:

| Check | Blocker if... | Warning if... |
|---|---|---|
| Running pipelines | N/A | Active PipelineRuns or TaskRuns exist |
| API deprecations | v1beta1 resources exist and target removes v1beta1 support | v1beta1 resources exist but target still supports v1beta1 |
| Custom tasks | Custom task incompatible with target Tekton version | ClusterTasks in use (deprecated but still functional) |
| Tekton health | Any controller or webhook not ready | Elevated restart counts (>3 in last hour) |
| Operator condition | Upgradeable=False | N/A |
| OCP compatibility | Target operator version does not support current OCP version | Current OCP version is at end of compatibility range |
| ClusterTasks | N/A | ClusterTasks in use and deprecated in target version |

### 4.3 API Migration Assessment

The v1beta1 to v1 migration is a critical upgrade consideration:

| v1beta1 Resources | Target Support | Assessment |
|---|---|---|
| 0 | any | No migration needed |
| 1+ | v1beta1 still served | Warning -- plan migration |
| 1+ | v1beta1 removed | Blocker -- must migrate first |

Key migration areas:
- `Pipeline` and `Task` definitions (structural changes in params, workspaces)
- `PipelineRun` and `TaskRun` specs (status field changes)
- `ClusterTask` to `Task` with cluster resolver (ClusterTask is deprecated)

### 4.4 Decision Matrix

| Blockers | Warnings | Decision |
|---|---|---|
| 0 | 0 | `recommend` |
| 0 | 1+ | `caution` |
| 1+ | any | `block` |
| Unable to assess | any | `escalate` |

### 4.5 Output

The output schema is enforced by the OlsAgent CR's `outputSchema` field --
the operator handles structured output compliance via the LLM API.

## 5. Failure Modes -- What NOT to Do

1. **Never recommend upgrading without analyzing the readiness data.** The JSON
   in the request is the source of truth.

2. **Never dismiss API deprecation warnings.** Workloads using removed APIs will
   break after upgrade.

3. **Never recommend upgrading while pipelines are actively running** without
   explicitly calling out the disruption risk and recommending a maintenance window.

4. **Never assume custom tasks are compatible** without checking
   `compatible_tekton_versions` against the target version.

5. **Never fabricate Jira issue keys, KB article IDs, or CVE numbers.** Use the
   `redhat-support` skill to get real data.

6. **Never recommend skipping an operator version** unless the readiness data
   shows that path exists.

7. **Never recommend force-upgrading.** If the operator condition is
   Upgradeable=False, report the blocker.

## 6. Using Other Skills

- **`platform-docs`** -- Read official OpenShift Pipelines release notes and
  upgrade documentation for version-specific procedures and breaking changes.

- **`tekton-docs`** -- Read Tekton upstream migration guides for API version
  changes, feature deprecations, and behavioral differences between versions.

- **`prometheus`** -- Query cluster metrics for trend analysis (controller
  performance, pipeline duration trends, resource consumption).

- **`redhat-support`** -- Search Red Hat Jira and Knowledge Base for bugs and
  solutions affecting the target Pipelines operator version.

- **`product-lifecycle`** -- Query Red Hat Product Life Cycle (PLCC) API to
  check support status and EOL dates for the installed Pipelines operator version.
