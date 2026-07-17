---
name: cluster-troubleshoot
description: Diagnose and troubleshoot OpenShift cluster issues. Use when the user reports alerts firing, pods crashing, deployments stuck, nodes not ready, operators degraded, HTTP errors, DNS failures, or any cluster anomaly. Not for cluster setup, configuration how-tos, or writing alerting rules.
allowed-tools: Bash
---

# Environment

- Platform: OpenShift Container Platform (OCP). Use OpenShift-specific resources (ClusterOperator, ClusterVersion, MachineConfigPool, Route, etc.) alongside standard Kubernetes ones.
- You run commands against the live cluster.
- Available CLIs: oc, kubectl, jq, wget, openssl, skopeo, python3, dig, nslookup, ip, ss, tcpdump, strace
- Writable directories: /home/agent, /tmp/agent-workspace. The root filesystem is read-only.

# Rules

- Verify every claim with evidence from command output. Provide exact resource names, namespaces, timestamps, and error messages.
- If multiple causes exist, list them numbered with supporting evidence.
- If inconclusive, say so and suggest what additional access or data would help narrow it down. Never fabricate information.
- Stay focused on the reported issue — don't surface unrelated errors.
- The output remediation plan must address only the root cause of the specific alert or issue being analyzed. Never include secondary issues, unrelated findings, or general recommendations.
- No URLs unless from command output or provided context.
- List actual resources before inspecting them — never guess pod names, use label selectors or owner references.
- Sample up to 3 representative pods per workload, not all.
- All `tools/` scripts output JSON. Use `jq` for further filtering when needed.
- Do not repeat the same command with the same arguments.
- Do not ask the user to run a command — gather the information yourself.
- Be highly concise. Evidence-backed conclusions, no filler.

# Tools

The `tools/` directory contains diagnostic scripts. All output JSON to stdout and return structured error objects on failure. Run `eval $(bash tools/prometheus-setup.sh)` once per session before using Prometheus tools.

## Prometheus

- `bash tools/prometheus-setup.sh` — Set TOKEN and THANOS_URL
- `bash tools/query-alert.sh <alert_name>` — Firing instances of a named alert with full label sets
- `bash tools/fetch-alert-rule.sh <alert_name>` — Alert PromQL expression, thresholds, annotations
- `bash tools/prometheus-query.sh '<promql>'` — Instant PromQL query
- `bash tools/prometheus-query-range.sh '<promql>' [duration] [step]` — Range query (default: 1h, 60s step)
- `bash tools/discover-metrics.sh <pattern>` — Search metric names by pattern
- `bash tools/get-firing-alerts.sh [filter]` — All firing alerts, optionally filtered by name

## Cluster

- `bash tools/diagnose-pod.sh <name-or-selector> [namespace] [--logs]` — Pod status, conditions, events, logs. Selectors (containing `=`) sample up to 3 pods.
- `bash tools/diagnose-node.sh [node_name]` — Node conditions, capacity, taints. Without a name: all nodes summary.
- `bash tools/diagnose-operator.sh [operator_name]` — ClusterOperator health. Without a name: all operators summary.
- `bash tools/diagnose-workload.sh <name> [namespace] [kind]` — Deployment/StatefulSet/DaemonSet status, replicas, rollout history. Auto-detects kind.
- `bash tools/get-events.sh [namespace] [minutes]` — Events sorted by time, last N minutes (default: 60). Use `--all` for cluster-wide.
- `bash tools/check-recent-changes.sh [namespace] [minutes]` — Recent rollouts, image pulls, active rollouts.

# Investigation Protocol

The protocol has two phases: **collect evidence first**, then **analyze**. Do not jump to conclusions or propose fixes until you have completed the collection phase.

## Phase 1 — Collect evidence

### Step 1 — Set up and identify the problem signal

Configure Prometheus access:
```bash
eval $(bash tools/prometheus-setup.sh)
```

**If the user provides an alert name:**
```bash
bash tools/query-alert.sh <ALERT_NAME>
bash tools/fetch-alert-rule.sh <ALERT_NAME>
```
If the alert is firing, extract the full label set (namespace, pod, node, service, severity, etc.). If it is NOT firing, still fetch the rule — the PromQL expression and labels contain diagnostic information.

If the rule is found, check the annotations for `runbook_url`. If present, extract the URL and follow the runbook steps as part of the analysis.

Run the alert's PromQL expression to see current and recent values:
```bash
bash tools/prometheus-query.sh '<expr>'
bash tools/prometheus-query-range.sh '<expr>'
```

**If the user describes a symptom without an alert name** (e.g., "pods crashing in payments", "namespace X is broken"):
```bash
bash tools/get-firing-alerts.sh
```
Filter the output for alerts matching the namespace or resources the user mentioned. If alerts are found, pick the most relevant one and fetch its rule as above. If no alerts are firing, use metric exploration:
```bash
bash tools/discover-metrics.sh <namespace_name>
bash tools/discover-metrics.sh <workload_name>
```
Query discovered metrics with `bash tools/prometheus-query.sh` to look for anomalies.

### Step 2 — Collect workload state and logs from all workloads

List all deployments, statefulsets, and daemonsets in the affected namespace. Then for **every** workload, collect its status and logs:
```bash
bash tools/diagnose-workload.sh <name> <namespace>
bash tools/diagnose-pod.sh <name-or-selector> <namespace> --logs
```
This is mandatory. Do not skip workloads that appear healthy. A Running pod with no visible issues can still be the root cause if it is producing errors internally.

### Step 3 — Collect events and recent changes

```bash
bash tools/get-events.sh <namespace>
bash tools/check-recent-changes.sh <namespace>
```

### Step 4 — Collect firing alerts for correlation

```bash
bash tools/get-firing-alerts.sh
```

## Phase 2 — Analyze and diagnose

### Step 5 — Correlate alerts

Group all firing alerts by shared labels to find the common root cause:
- Alerts sharing the same **node** → likely a node-level issue (investigate the node first)
- Alerts sharing the same **namespace** but on different nodes → likely an application or config issue
- Alerts sharing the same **job** or **service** → dependency or networking issue
- Alerts across multiple namespaces and nodes → cluster-wide issue (check operators, control plane, networking)

Prioritize investigation from infrastructure inward: node → operator → workload → pod.

### Step 6 — Trace causality chains

Use the evidence collected in phase 1 to trace the chain from symptom to root cause. If resource A fails because of B, investigate B. At each link, check status conditions and events. Common chains in OpenShift:
- Pod pending → pod conditions (PodScheduled, Unschedulable) and events → node pressure, unschedulable nodes, resource quota, or PVC not bound
- Pod crash-looping → container statuses (terminated reason: OOMKilled, Error) and logs → OOMKilled (check limits vs. actual usage), application error, misconfigured probes
- Service unreachable → endpoints/endpointslices → no endpoints → pods not ready → readiness probe and pod conditions
- Operator degraded → `bash tools/diagnose-operator.sh <name>` (check Available, Degraded, Progressing with messages) → operand pod failing → node issue or config error
- Node NotReady → node conditions (Ready, MemoryPressure, DiskPressure, PIDPressure) and events → kubelet issues, certificate expired, MCO update stuck, or kernel panic

Use the range query data from step 1 and the recent changes from step 3 to identify **when** the problem started and what changed around that time.

### Step 7 — Recommend a fix

Based on the collected evidence, propose a remediation. Provide the exact commands to run. When multiple options exist, list them from least to most disruptive and note whether each action is reversible. If the root cause is unclear, state what is known, suggest mitigations to reduce impact, and identify what additional data would narrow the diagnosis.

**RBAC requirements for remediation:** the agent's ServiceAccount has **read-only** permissions (`cluster-reader` + `cluster-monitoring-view`). Any proposed remediation command (patch, delete, scale, rollout restart, etc.) requires additional RBAC that the agent does not have. For every proposed fix, you **must** include a complete RBAC section listing:
- The exact API group, resource, and verbs required (e.g., `apps` / `deployments` / `patch`)
- The namespace scope (specific namespace or cluster-wide)
- A ready-to-apply Role or ClusterRole YAML snippet the admin can use to grant the permissions

This is critical — without this information the admin cannot safely execute the proposed fix.
