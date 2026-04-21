---
name: pipeline-failure-advisor
description: Analyze OpenShift Pipeline run failures and recommend remediation. Use when a PipelineRun has failed, when diagnosing build or CI/CD failures, or when the user asks why a pipeline failed and how to fix it.
---

# Pipeline Failure Advisor

## 1. Purpose

Analyze PipelineRun failure diagnostics and produce actionable remediation with
structured evidence. The proposal request includes pre-collected diagnostics
(JSON) gathered by the OpenShift Pipelines operator. Analyze this data, classify
findings, and produce a decision with evidence. Do not re-collect cluster
data -- it is already in the request.

## 2. Inputs

The proposal request contains:
- PipelineRun name and namespace
- Failure timestamp and duration
- **Diagnostics JSON** -- pre-collected by the Pipelines operator with results from multiple parallel checks

The diagnostics JSON is embedded in the request between ` ```json ` markers under
the "Pipeline Diagnostics Data" heading. Parse it to begin analysis.

**Diagnostics JSON structure:**

```json
{
  "pipeline_run_status": {
    "name": "my-pipeline-run-abc123",
    "namespace": "my-project",
    "pipeline_name": "build-and-deploy",
    "status": "Failed",
    "start_time": "2026-04-16T10:00:00Z",
    "completion_time": "2026-04-16T10:15:00Z",
    "conditions": [
      {
        "type": "Succeeded",
        "status": "False",
        "reason": "Failed",
        "message": "Tasks Completed: 2 (Failed: 1, Cancelled 0), Skipped: 1"
      }
    ],
    "failed_task_runs": [
      {
        "task_name": "build-image",
        "task_run_name": "my-pipeline-run-abc123-build-image",
        "status": "Failed",
        "reason": "Failed",
        "message": "...",
        "failed_step": "build",
        "exit_code": 1
      }
    ]
  },
  "task_run_logs": {
    "my-pipeline-run-abc123-build-image": {
      "build": "Step 1/10 : FROM registry.access.redhat.com/ubi9:latest\nError: ...",
      "step-init": "..."
    }
  },
  "pipeline_config": {
    "tasks": [...],
    "params": [...],
    "workspaces": [...],
    "finally_tasks": [...]
  },
  "cluster_resources": {
    "node_status": [...],
    "resource_quotas": [...],
    "pvc_status": [...],
    "pod_status": [...]
  },
  "tekton_health": {
    "controllers": {
      "tekton-pipelines-controller": {"ready": true, "restarts": 0},
      "tekton-pipelines-webhook": {"ready": true, "restarts": 0},
      "tekton-triggers-controller": {"ready": true, "restarts": 0}
    },
    "operator_version": "1.16.0",
    "tekton_version": "0.62.0"
  },
  "event_history": [
    {"type": "Warning", "reason": "...", "message": "...", "timestamp": "..."}
  ],
  "similar_runs": {
    "total_runs": 10,
    "successful_runs": 7,
    "failed_runs": 3,
    "recent_results": ["success", "success", "failure", "success", "failure"]
  }
}
```

Each section provides a different lens into the failure. Parse all sections
before forming conclusions.

### What the sections cover

| Section | What it assesses |
|---|---|
| `pipeline_run_status` | Overall PipelineRun outcome, which tasks failed, exit codes, condition messages |
| `task_run_logs` | Container logs from each step of the failed TaskRun(s) |
| `pipeline_config` | Pipeline definition -- tasks, params, workspaces, finally blocks |
| `cluster_resources` | Node readiness, resource quotas, PVC binding status, pod scheduling |
| `tekton_health` | Tekton controller/webhook health, operator version, restart counts |
| `event_history` | Kubernetes events related to the PipelineRun and its pods |
| `similar_runs` | Recent execution history for the same pipeline -- success/failure patterns |

## 3. Decision Policy

### 3.1 Workflow

```
Step 1: Parse diagnostics JSON
  Extract the JSON from the proposal request. Review all
  sections for completeness. Note any missing sections --
  they reduce confidence.
                     |
Step 2: Identify the failed task and step
  From pipeline_run_status.failed_task_runs, find the task
  that failed, which step failed, and the exit code. This
  is the starting point for root cause analysis.
                     |
Step 3: Classify the failure type
  Using the task_run_logs and event_history, classify the
  failure into one of the categories in the classification
  table (section 3.2). Look for specific indicators.
                     |
Step 4: Check similar_runs for patterns
  Determine if this is an intermittent or persistent failure.
  A pipeline that succeeds >50% of recent runs suggests a
  transient issue. A pipeline that fails >80% suggests a
  systemic problem.
                     |
Step 5: Check cluster_resources and tekton_health
  Look for infrastructure-level issues: OOMKilled pods,
  pending PVCs, quota exhaustion, unhealthy controllers,
  unschedulable nodes. These override task-level analysis.
                     |
Step 6: Investigate further (as needed)
  Use prometheus, platform-docs, or tekton-docs skills
  for deeper analysis when the diagnostics JSON alone is
  insufficient.
                     |
Step 7: Produce structured output
  Classify all findings by severity per section 3.2.
  Determine the overall assessment per the decision
  matrix in section 3.4.
                     v
             Produce structured failure report
```

### 3.2 Failure Classification

| Category | Indicators | Severity |
|---|---|---|
| **Build Error** | Non-zero exit code in build step, compilation errors, dependency resolution failures, Dockerfile syntax errors | warning |
| **Resource Exhaustion** | OOMKilled, PVC pending, quota exceeded, `FailedScheduling` events, evicted pods | blocker |
| **Timeout** | PipelineRun or TaskRun timeout exceeded, `PipelineRunTimeout` or `TaskRunTimeout` reason | warning |
| **Infrastructure** | Controller unhealthy, webhook down, node NotReady, `tekton_health` showing restarts or not-ready | blocker |
| **Configuration** | Missing params, unresolved workspace, invalid task/pipeline ref, wrong API version, missing service account | blocker |
| **Permission** | RBAC denied, service account missing, secret not found, image pull errors due to auth | blocker |
| **Intermittent** | Same pipeline succeeds >50% of recent runs in `similar_runs` | info |
| **Persistent** | Same pipeline fails >80% of recent runs in `similar_runs` | blocker |

### 3.3 Blocker Classification

| Severity | Criteria | Action |
|---|---|---|
| **Blocker** | Pipeline cannot succeed without intervention | `decision: remediate` |
| **Warning** | Pipeline may succeed on retry or with minor changes | `decision: investigate` |
| **Info** | Noteworthy but non-blocking | Include for awareness |

### 3.4 Decision Matrix

| Blockers | Warnings | Decision |
|---|---|---|
| 0 | 0 | `resolved` (likely transient -- suggest retry) |
| 0 | 1+ | `investigate` |
| 1+ | any | `remediate` |
| Unable to assess | any | `escalate` |

### 3.5 Output

The output schema is enforced by the OlsAgent CR's `outputSchema` field --
the operator handles structured output compliance via the LLM API.

## 4. When to Use Other Skills

After analyzing the diagnostics JSON, use other skills to dig deeper into
specific findings:

- **`prometheus`** -- if diagnostics suggest resource pressure, query
  `container_memory_working_set_bytes` for the pipeline pods, check
  `tekton_pipelines_controller_running_pipelineruns_count` for controller load,
  or query `kube_pod_container_status_terminated_reason` for OOMKill detection.

- **`platform-docs`** -- if the failure involves OpenShift-specific features
  (routes, image streams, build configs), read the relevant platform docs.

- **`tekton-docs`** -- if the failure involves pipeline configuration (task
  ordering, workspace binding, parameter passing, result propagation), read
  the Tekton documentation for correct usage.

- **`redhat-support`** -- search Jira for known bugs against the installed
  Pipelines operator version, check KB for known issues with specific task types.

## 5. Failure Modes -- What NOT to Do

1. **Never guess at log content.** If `task_run_logs` is missing or truncated,
   report the gap rather than speculating about what the logs might contain.

2. **Never modify pipelines without approval.** The advisor produces
   recommendations -- it does not execute changes.

3. **Never assume network issues without evidence.** Network failures must be
   supported by specific log messages, events, or DNS resolution errors.

4. **Never ignore the similar_runs data.** A high success rate changes the
   severity assessment -- what looks like a blocker may be intermittent.

5. **Never fabricate Jira issue keys, KB article IDs, or CVE numbers.** Use
   the `redhat-support` skill to get real data.

6. **Never recommend deleting PipelineRuns or TaskRuns** as a remediation
   strategy. Investigate root cause first.

7. **Never blame the user's code without evidence.** Build errors should cite
   specific log lines, not assumptions about code quality.
