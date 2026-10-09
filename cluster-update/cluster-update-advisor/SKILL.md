---
name: cluster-update-advisor
description: Assess OpenShift cluster update (upgrade) readiness and risk, and produce a concrete remediation plan when the upgrade is feasible. Use when evaluating whether a cluster is safe to update, when an update is available, or when the user asks about update risks, prerequisites, blockers, or best practices.
license: Apache-2.0
compatibility: Requires oc/kubectl CLI
---

# Cluster Update — Assessment & Planning

## Purpose

Assess cluster update readiness, produce a structured risk report with
actionable prerequisites, blockers, and recommendations, and — when the
upgrade is feasible — generate a concrete, ordered remediation plan with
executable `ProposedAction[]` entries.

The proposal request includes pre-collected cluster readiness data (JSON)
gathered by the Cluster Version Operator. Analyze this data, classify findings,
and produce a decision with evidence. Do not re-collect cluster data — it is
already in the request.

If the assessment determines the upgrade is not feasible or no viable
remediation path exists, do not produce a remediation plan — explain why in the
diagnosis instead.

## Inputs

The proposal request contains:
- Current and target version metadata
- Channel and update path classification — `Recommended` or `Conditional`
- Conditional update risks — risks that apply to this cluster, with `Applies` condition status and admin acceptance state
- **Cluster readiness JSON** — cluster health checks with context relevant to preparing for the update

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
    "olm_operator_lifecycle": { "_status": "ok", "summary": {...}, "operators": [...] }
  }
}
```

Each check contains `_status` (`ok` or `error`) and check-specific data
with a `summary` section for quick parsing.

---

## Phase 1 — Risk Assessment

### 1. Parse readiness data

Extract the JSON from the proposal request.
Count checks with `_status` `ok` vs `error` for completeness.

### 2. Verify data completeness

Any check with `_status` `error` represents a gap in visibility.
Note incomplete areas — they reduce confidence.

### 3. Evaluate findings in detail

If the system prompt includes organization-specific policy (thresholds, scheduling preferences, risk tolerance), apply those constraints.
Otherwise use sensible defaults.
Walk through each check's summary and detail data:

- Compare numeric thresholds (node headroom, etcd backup age)
- Evaluate conditional update risks against cluster state
- Identify compounding risks (e.g., paused MCP + cert expiry)
- Estimate update duration (~10 min/node)

### 4. Classify findings

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

For other checks, treat an issue as a blocker if would cause data loss, a performance regression, or a failed update.
Treat the issue as a warning if would cause temporary disruption or slow updates.

### 5. Investigate with other skills

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

### 6. Classify overall recommendation

Aggregate finding classification, and make a decision on the overall assessment:

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

### 7. Produce a structured risk report

Produce the risk report with the decision and evidence.

The output schema is enforced by the OlsAgent CR's `outputSchema` field —
the operator handles structured output compliance via the LLM API.

**If the decision is `escalate` or `block` with no viable remediation, stop here.** Do not produce a remediation plan — explain why in the diagnosis.

---

## Phase 2 — Remediation Plan

Proceed only when the assessment indicates the upgrade is feasible (decision is `recommend` or `warn`, or `block` with actionable remediation).

### 1. Identify required operator upgrades

Use the OLM operator data at `.checks.olm_operator_lifecycle`. The `operators` array contains one entry per installed OLM-managed operator:

| Field | Description |
|---|---|
| `name` | Subscription / operator name |
| `package` | Package name in the catalog |
| `namespace` | Installed namespace |
| `channel` | Current subscription channel |
| `available_channels` | Channels available in the catalog for this operator |
| `installed_version` | Currently installed version |
| `installed_csv` | Current ClusterServiceVersion name |
| `csv_phase` | CSV phase (`Succeeded`, `Failed`, etc.) |
| `install_plan_approval` | `Automatic` or `Manual` |
| `pending_upgrade` | Whether an upgrade is pending approval |
| `source` | CatalogSource name |
| `source_namespace` | CatalogSource namespace |
| `state` | Subscription state (`AtLatestKnown`, etc.) |

The `summary` section reports aggregate counts: `incompatible_with_target`, `manual_approval`, `pending_upgrades`, `total_operators`.

**Operator scope — only evaluate operators whose `package` matches this list:**

`cluster-logging`, `openshift-gitops-operator`, `kubernetes-nmstate-operator`, `cert-manager-operator`, `local-storage-operator`, `oadp-operator`, `mcg-operator`, `ocs-operator`, `odf-csi-addons-operator`, `odf-operator`, `loki-operator`, `kubevirt-hyperconverged-operator`, `openshift-pipelines-operator-rh`, `metallb-operator`, `devworkspace-operator`, `web-terminal`, `mtv-operator`, `multicluster-engine`, `advanced-cluster-management`, `rhacs-operator`, `compliance-operator`, `nfd`, `quay-operator`, `cluster-observability-operator`, `ocs-client-operator`, `recipe`, `odf-prometheus-operator`, `rook-ceph-operator`, `cephcsi-operator`, `odf-dependencies`, `grafana-operator`, `odf-external-snapshotter-operator`

Skip any operator not in this list — do not evaluate, upgrade, or report on it.

**Critical operators** (require upgrade before the platform upgrade) are those in the list above where:
- `summary.incompatible_with_target > 0` — at least one operator is incompatible with the target OCP version
- The operator's current channel does not support the target OCP version (use `available_channels` to identify a compatible channel)
- The operator is in an EOL state flagged by the `product-lifecycle` skill

**Do NOT upgrade operators** where:
- The operator is not in the allowed list above
- The operator is already compatible with the target OCP version
- The operator is non-critical and the upgrade is optional

**If a critical operator has no compatible channel in `available_channels`**, the upgrade should NOT proceed. Detail which operators are blocking and why in the Remediation Option.

### 2. Build the plan

Produce a single `RemediationOption` with these sections:

#### Pre-checks

Essential validation before any mutations:

- Verify cluster is not currently upgrading (`Progressing=False`)
- Verify no critical operators are degraded
- Verify target version exists in available or conditional updates

#### OLM Operator Upgrades (if needed)

For each critical operator requiring upgrade:

**OLMv0 (Subscription/InstallPlan):**

```bash
# Update subscription channel (triggers new InstallPlan), only if channel is different
oc patch subscription <name> -n <namespace> --type=merge -p '{"spec":{"channel":"<target-channel>"}}'

# If InstallPlan approval is Manual, approve the InstallPlan
oc wait subscription <name> -n <namespace> --for=jsonpath='{.status.installplan.name}'
oc patch installplan <installplan-name> -n <namespace> --type=merge -p '{"spec":{"approved":true}}'

# Wait for operator upgrade to complete
oc wait installplan <installplan-name> -n <namespace> --for='jsonpath={.status.phase}=Complete' --timeout=300s
```

**OLMv1 (ClusterExtension):**

```bash
# Update ClusterExtension channel or version
oc patch clusterextension <name> --type=merge -p '{"spec":{"source":{"catalog":{"channels":["<target-channel>"]}}}}'

# Wait for upgrade to complete
oc wait clusterextension <name> --for=condition=Installed=True --timeout=300s
```

#### Platform Upgrade

Construct the `desiredUpdate` patch with target version and image:

```bash
oc patch clusterversion version --type=merge -p '{
  "spec": {
    "desiredUpdate": {
      "version": "<target-version>",
      "image": "<target-image>",
    }
  }
}'
```

#### Post-checks

Verify the upgrade has started:

```bash
# Check that ClusterVersion status reflects the new desiredUpdate
oc get clusterversion version -o jsonpath='{.status.desired.version}'

# Verify upgrade is progressing (initial check only)
oc get clusterversion version -o jsonpath='{.status.conditions[?(@.type=="Progressing")].status}'
```

### 3. Structure as RemediationOption

The plan must conform to the `RemediationOption` schema expected by the lightspeed-agentic-operator.

Each `ProposedAction` has:

| Field | Description |
|---|---|
| `type` | One of: `pre-check`, `mutation`, `wait`, `post-check` |
| `command` | The exact `oc` or `kubectl` command to execute |
| `description` | Human-readable explanation of what this action does |

Mark the platform upgrade action with:

```yaml
risk: "Medium" or "High"  # based on conditional risks and findings
reversible: "Irreversible"
rollbackPlan:
  description: "Platform upgrade cannot be rolled back once started. OLM operator upgrades may be irreversible without reinstallation of operators at previous versions."
```

**Derive RBAC for every planned action.** For each `oc` command in the plan, map it to the Kubernetes PolicyRule it requires (resource, apiGroup, verbs, resourceNames where applicable). Include the full list of required RBAC permissions in the remediation option output. Use the RBAC Declaration table below as reference.

---

## RBAC Declaration

The skill declares the following RBAC permissions needed for execution:

| Resource | API Group | Verbs | Purpose |
|---|---|---|---|
| `clusterversions` | `config.openshift.io` | `get`, `patch` | Query current version, trigger platform upgrade |
| `clusterextensions` | `olm.operatorframework.io` | `get`, `list`, `patch` | OLMv1 operator upgrades |
| `subscriptions` | `operators.coreos.com` | `get`, `list`, `patch` | OLMv0 operator upgrades |
| `installplans` | `operators.coreos.com` | `get`, `list`, `patch` | OLMv0 install plan approval |
| `clusteroperators` | `config.openshift.io` | `get`, `list` | Pre-checks and post-checks |

These permissions are scoped and temporary — granted only to the execution pod for the duration of the AgenticRun.

## Action Type Classification

| Action | Type | Example |
|---|---|---|
| Check cluster conditions | `pre-check` | `oc get clusterversion -o jsonpath=...` |
| Check operator health | `pre-check` | `oc get clusteroperators -o json` |
| Update Subscription channel | `mutation` | `oc patch subscription ... --type=merge -p '{...}'` |
| Approve InstallPlan | `mutation` | `oc patch installplan ... --type=merge -p '{...}'` |
| Update ClusterExtension | `mutation` | `oc patch clusterextension ... --type=merge -p '{...}'` |
| Wait for operator install | `wait` | `oc wait clusterextension ... --for=condition=Installed` |
| Trigger platform upgrade | `mutation` | `oc patch clusterversion ... --type=merge -p '{...}'` |
| Verify upgrade started | `post-check` | `oc get clusterversion -o jsonpath=...` |

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

8. **Never upgrade all operators blindly.** Only upgrade operators that are incompatible with the target OCP version or whose `maxOpenShiftVersion` blocks the upgrade.

9. **Never produce generic or placeholder commands.** Every command must be specific, with actual operator names, namespaces, channels, and versions filled in.

10. **Never skip the pre-check phase.** Verify cluster readiness before any mutations.

11. **Never assume OLM API type.** The readiness data operator entries contain fields that indicate their management type — `installed_csv` and `install_plan_approval` indicate OLMv0 (Subscription-managed). Use the correct command templates.

12. **Never dry-run with --dry-run=client.** Always use `--dry-run=server` to validate against the actual cluster API.

13. **Detail reasons for failure.** If no valid remediation plans can be generated, detail the root cause.

## Example Output Structure

```yaml
remediationOptions:
  - name: "OpenShift 4.21.5 → 4.21.8 upgrade with operator alignment"
    description: "Upgrade cluster-logging operator to target-compatible channel, then upgrade platform to 4.21.8"
    plan:
      risk: "Medium"
      reversible: "Irreversible"
      rollbackPlan:
        description: "Platform upgrade cannot be rolled back once the ClusterVersion desiredUpdate is set. OLM operator upgrades can be reverted by switching channels back to previous versions and waiting for operator reconciliation."
      actions:
        # Pre-checks
        - type: pre-check
          command: "oc get clusterversion version -o jsonpath='{.status.conditions[?(@.type==\"Progressing\")].status}'"
          description: "Verify cluster is not currently progressing (expected: False)"

        - type: pre-check
          command: "oc get clusteroperators -o json | jq -r '.items[] | select(.status.conditions[] | select(.type==\"Degraded\" and .status==\"True\")) | .metadata.name'"
          description: "Check for degraded cluster operators (expected: no output)"

        # OLM operator upgrades
        - type: mutation
          command: "oc patch subscription cluster-logging -n openshift-logging --type=merge -p '{\"spec\":{\"channel\":\"stable-5.9\"}}'"
          description: "Update cluster-logging operator to stable-5.9 channel (compatible with OCP 4.21.8)"

        - type: wait
          command: "oc wait subscription cluster-logging -n openshift-logging --for=jsonpath='{.status.state}'=AtLatestKnown --timeout=300s"
          description: "Wait for cluster-logging operator upgrade to complete"

        # Platform upgrade
        - type: mutation
          command: |
            oc patch clusterversion version --type=merge -p '{
              "spec": {
                "desiredUpdate": {
                  "version": "4.21.8",
                  "image": "quay.io/openshift-release-dev/ocp-release@sha256:abc123..."
                }
              }
            }'
          description: "Trigger platform upgrade to 4.21.8"

        # Post-checks
        - type: post-check
          command: "oc get clusterversion version -o jsonpath='{.status.desired.version}'"
          description: "Verify desiredUpdate has been set (expected: 4.21.8)"

        - type: post-check
          command: "oc get clusterversion version -o jsonpath='{.status.conditions[?(@.type==\"Progressing\")].status}'"
          description: "Verify upgrade has started progressing (expected: True)"
```

## Integration with Other Skills

This skill is typically used in conjunction with:

- **`product-lifecycle`** — Used to verify operator support status and OCP compatibility before planning upgrades
- **`prometheus`** — Used for cluster metrics trend analysis during risk assessment
