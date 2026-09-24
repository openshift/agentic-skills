---
name: cluster-update-advisor
description: Assess OpenShift cluster update (upgrade) readiness and risk. Use when evaluating whether a cluster is safe to update, when an update is available, or when the user asks about update risks, prerequisites, blockers, or best practices.
license: Apache-2.0
---

# Cluster Update Advisor

## Purpose

Assess cluster update readiness and produce a structured risk report with
actionable prerequisites, blockers, and recommendations.

The proposal request includes pre-collected cluster readiness data (JSON)
gathered by the Cluster Version Operator. Analyze this data, classify findings,
and produce a decision with evidence. Do not re-collect readiness data — it is
already in the request. For conditional updates, query pre-accepted risks from
the cluster — see "Query accepted risks" below.

## Inputs

The proposal request contains:
- Current and target version metadata
- Channel and update path information
- **Cluster readiness JSON** — cluster health checks with context relevant to preparing for the update
- **Conditional update risks** (when update path is `Conditional`) — risk metadata listed under `Conditional Update Risks:` with `Name` and `Applies` fields per risk

The readiness JSON is embedded in the request between ` ```json ` markers under
the "Cluster Readiness Data" heading. Parse it to begin analysis.

**Readiness JSON structure:**

```json
{
  "current_version": "4.21.5",
  "target_version": "4.21.8",
  "checks": {
    "cluster_conditions":    { "_status": "ok", "summary": {...}, ... },
    "operator_health":       { "_status": "ok", "summary": {...}, ... },
    "api_deprecations":      { "_status": "ok", "summary": {...}, ... },
    "node_capacity":         { "_status": "ok", "summary": {...}, ... },
    "pdb_drain":             { "_status": "ok", "summary": {...}, ... },
    "etcd_health":           { "_status": "ok", "summary": {...}, ... },
    "network":               { "_status": "ok", "summary": {...}, ... },
    "crd_compat":            { "_status": "ok", "summary": {...}, ... },
    "olm_operator_lifecycle": { "_status": "ok", "summary": {...}, ... }
  }
}
```

Each check contains `_status` (`ok` or `error`) and check-specific data
with a `summary` section for quick parsing.

## Evaluation

### Parse readiness data

Extract the JSON from the proposal request.
Count checks with `_status` `ok` vs `error` for completeness.

### Query accepted risks

When the update path is `Conditional`, query the cluster for pre-accepted risks:

```bash
oc get clusterversion version -o jsonpath='{.spec.desiredUpdate.acceptedRisks}'
```

The result is a JSON array of objects with a `name` field (the risk slug),
e.g. `[{"name":"PDBDrainBlocker"}]`. If the field is missing or the jsonpath
returns empty, no risks have been accepted.

Skip this step when the update path is `Recommended` (no conditional risks).

**Feature gate check:** If the jsonpath returns empty or an error, the
`ClusterUpdateAcceptRisks` feature gate is likely off. In that case:
- Set accepted risks to an empty list
- Proceed with Phase 1 scoring (all applicable conditional risks are warnings)
- Note in findings that the accepted risk API is unavailable
- Do NOT treat this as an escalation trigger

Cross-reference each conditional risk from the request (by its `Name` field)
against the accepted risks list to determine accepted/not-accepted status.

### Verify data completeness

Any check with `_status` `error` represents a gap in visibility.
Note incomplete areas — they reduce confidence.

### Evaluate findings in detail

If the system prompt includes organization-specific policy (thresholds, scheduling preferences, risk tolerance), apply those constraints.
Otherwise use sensible defaults.
Walk through each check's summary and detail data:

- Compare numeric thresholds (node headroom, etcd backup age)
- Evaluate conditional update risks using risk scoring v2:
  - Risk `Applies: True` AND accepted → no penalty (not a warning or blocker)
  - Risk `Applies: True` AND NOT accepted → classify as **warning**
  - Risk `Applies: Unknown` → classify as **warning** (cannot confirm risk does not apply)
  - Risk `Applies: False` → no action needed
  - Feature gate off (accepted risk API unavailable) → all applicable risks are warnings
- Identify compounding risks (e.g., paused MCP + cert expiry)
- Estimate update duration (~10 min/node)

### Classify findings

Assign each finding a severity per the classification table.

| Check | Blocker if... | Warning if... |
|---|---|---|
| Cluster conditions | Upgradeable=False (non-z-stream) | Update already in progress |
| API deprecations | Workloads use APIs **removed** in target | Workloads use **deprecated** APIs |
| Operator health | Any operator has Upgradeable=False | Any operator is Degraded=True |
| MachineConfigPool | Any MCP paused or degraded | MCP updating or not all machines ready |
| Node capacity | Headroom < 20% | Headroom < 40% |
| PDB config | PDB blocks ALL replicas from draining | PDB has maxUnavailable: 0 |
| etcd health | Any member unhealthy | No recent backup (within 24h) |
| Network plugin | SDN in use and target requires OVN (4.17+) | Using deprecated SDN (< 4.17) |
| CRD compatibility | Stored version not served; operator maxOpenShiftVersion < target | Deprecated versions still served |
| OLM operator lifecycle | Installed operator incompatible with target OCP; operator product EOL | Operator has pending update; operator product in Maintenance Support |
| Conditional update risk | n/a | Risk applies (or Unknown) AND not accepted by admin |

For other checks, treat an issue as a blocker if would cause data loss, a performance regression, or a failed update.
Treat the issue as a warning if would cause temporary disruption or slow updates.

#### Investigate with other skills

If additional information or context is needed to classify a finding, these skills may be useful:

- **`openshift-docs`** — Read official OpenShift update docs for version-specific
  procedures and breaking changes.

- **`prometheus`** — Query cluster metrics for trend analysis (etcd latency,
  CPU headroom, firing alerts).

- **`jira`** — Search Red Hat Jira for bugs and known issues affecting the target version.

- **`product-lifecycle`** — Query Red Hat Product Life Cycle API to check
  support status and OCP compatibility for installed operators. Use the operator's
  `package` name from OLM readiness data to look up entries via the `package`
  field (exact match). Flag operators whose product version is End of life or whose
  `openshift_compatibility` does not include the target OCP version.

### Classify overall recommendation

Aggregate finding classification, and and make a decision on the overall assessment:

* escalate  — insufficient data for confident assessment.
* block     — findings must be resolved before update.
* warn — findings exist but manageable with prerequisites.
* recommend — all checks pass within acceptable thresholds.

| Blockers | Warnings | Decision |
|---|---|---|
| Unable to assess | any | `escalate` |
| 1+ | any | `block` |
| 0 | 1+ | `warn` |
| 0 | 0 | `recommend` |

### Pass accepted risk context to planner

Include each applicable conditional risk's name and accepted/not-accepted
status in the output findings. The `cluster-update-planner` skill uses this
to decide whether to include `acceptRisks` in the `oc patch clusterversion`
command. If the accepted risk API is unavailable (feature gate off), note it
so the planner omits `acceptRisks` from the patch command.

### Produce a structured risk report

The output schema is enforced by the OlsAgent CR's `outputSchema` field —
the operator handles structured output compliance via the LLM API.

## Failure Modes — What NOT to Do

1. **Never recommend updating without analyzing the readiness data.** The JSON
   in the request is the source of truth.

2. **Never dismiss conditional update risks.** If the update path is conditional,
   evaluate each risk against the cluster.

3. **Never skip the API deprecation check.** Workloads using removed APIs will
   break after the update.

4. **Never assume etcd is healthy.** Always check member health in the readiness data.

5. **Never fabricate Jira issue keys, KB article IDs, or CVE numbers.** Use the
   `redhat-support` skill to get real data.

6. **Never recommend skipping an update version** unless the readiness data shows
   that path exists.

7. **Never recommend force-updating.** If the standard path is blocked, report it.

8. **Never skip the accepted risk query for conditional updates.** When the
   update path is `Conditional`, always query
   `ClusterVersion.spec.desiredUpdate.acceptedRisks` at analysis time.
