---
name: cluster-update-planner
description: Produce concrete, executable OpenShift cluster upgrade plans. Use to generate a remediation plan for a cluster update. Use only after checking whether a cluster is safe to update.
license: Apache-2.0
compatibility: Requires oc/kubectl CLI and Python 3 for OLM queries
---

# Cluster Update Planner

## Purpose

Generate a concrete, ordered remediation plan for upgrading an OpenShift cluster. The plan includes pre-checks to verify cluster readiness for upgrade, OLM operator upgrade commands for any OLM managed operator incompatible with the target OCP version for the upgrade, platform upgrade commands for the actual OCP upgrade, post-checks to verify upgrade completion, and wait commands with appropriate timeouts for each command if needed. The output is a structured `RemediationOption` containing ordered `ProposedAction[]` entries with the commands required for a cluster update.

## Inputs

The proposal request contains:

- **Current and target version metadata** — what upgrade is being planned
- **Update path classification** — `Recommended` or `Conditional`
- **Conditional update risks** — risks that apply to this cluster, with `Applies` condition status and admin acceptance state
- **Cluster readiness assessment** — findings from the `cluster-update-advisor` skill
- **OLM operator lifecycle data** — installed operators and their compatibility with the target OCP version

Readiness data is embedded in the request. Parse it to understand what needs remediation before the platform upgrade can proceed.

## CLI Tool

Use `cluster-update-planner/scripts/olm_upgrade_checker.py` to query OLM resources:

```bash
python3 cluster-update-planner/scripts/olm_upgrade_checker.py --help
```

### Commands

#### `check-operators` — Query installed operators and compatibility

```bash
# Check all operators against target OCP version
python3 cluster-update-planner/scripts/olm_upgrade_checker.py check-operators --target-ocp 4.21.8

# Check specific operators
python3 cluster-update-planner/scripts/olm_upgrade_checker.py check-operators --target-ocp 4.21.8 \
  --packages cluster-logging,web-terminal
```

Returns JSON with installed operators, their current versions, OLM API type (OLMv0 or OLMv1), compatibility status, and available upgrade channels.

Output format:

```json
{
  "operators": [
    {
      "name": "cluster-logging",
      "namespace": "openshift-logging",
      "api_type": "OLMv0",
      "current_version": "5.8.0",
      "channel": "stable-5.8",
      "compatible_with_target": false,
      "requires_upgrade": true,
      "upgrade_action": {
        "type": "channel_change",
        "target_channel": "stable-5.9",
        "reason": "Current channel maxOpenShiftVersion is 4.20, target OCP is 4.21"
      },
      "install_plan_approval": "Manual",
      "pending_install_plan": null
    },
    {
      "name": "web-terminal",
      "namespace": "openshift-operators",
      "api_type": "OLMv1",
      "current_version": "1.9.0",
      "channel": "fast",
      "compatible_with_target": true,
      "requires_upgrade": false
    }
  ],
  "critical_upgrades": ["cluster-logging"],
  "non_critical_upgrades": []
}
```

## Planning Process

### 1. Parse Input Data

Extract from the proposal request:
- Target OCP version
- Conditional risks (name, `Applies` status, admin acceptance)
- Readiness findings (blockers, warnings)
- OLM operator lifecycle data

### 2. Identify Required Operator Upgrades

Use the helper script to query installed operators:

```bash
python3 cluster-update-planner/scripts/olm_upgrade_checker.py check-operators --target-ocp <target>
```

**Critical operators** are those where:
- `requires_upgrade: true` — incompatible with target OCP version
- The operator's `maxOpenShiftVersion` constraint blocks the platform upgrade
- The operator is in an EOL state that requires upgrading first

**Do NOT upgrade operators** where:
- `compatible_with_target: true` — already compatible
- The operator is non-critical and the upgrade is optional

**Check that none of critical operators have no returned upgrade_action**: If any critical operator identified have no upgrade action or an error, the upgrade should NOT proceed. The critical operators responsible for blocking an upgrade should be noted clearly detailed in the Remediation Option built.

### 3. Build the Remediation Plan

Produce a single `RemediationOption` with these sections:

#### Phase 1: Pre-checks

Essential validation before any mutations:

- Verify cluster is not currently upgrading (`Progressing=False`)
- Verify no critical operators are degraded
- Verify target version exists in available or conditional updates

#### Phase 2: OLM Operator Upgrades (if needed)

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

**OLM v1 (ClusterExtension):**

```bash
# Update ClusterExtension channel or version
oc patch clusterextension <name> --type=merge -p '{"spec":{"source":{"catalog":{"channels":["<target-channel>"]}}}}'

# Wait for upgrade to complete
oc wait clusterextension <name> --for=condition=Installed=True --timeout=300s
```

#### Phase 3: Platform Upgrade

Construct the `desiredUpdate` patch with:
- Target version and image

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

#### Phase 4: Post-checks

Verify the upgrade has started:

```bash
# Check that ClusterVersion status reflects the new desiredUpdate
oc get clusterversion version -o jsonpath='{.status.desired.version}'

# Verify upgrade is progressing (initial check only)
oc get clusterversion version -o jsonpath='{.status.conditions[?(@.type=="Progressing")].status}'
```

### 4. Structure as RemediationOption

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

1. **Never upgrade all operators blindly.** Only upgrade operators that are incompatible with the target OCP version or whose `maxOpenShiftVersion` blocks the upgrade.

2. **Never produce generic or placeholder commands.** Every command must be specific, with actual operator names, namespaces, channels, and versions filled in.

3. **Never skip the pre-check phase.** Verify cluster readiness before any mutations.

4. **Never assume OLM API type.** Query both `subscriptions` and `clusterextensions` to determine which mechanism manages each operator.

5. **Never proceed if there are unresolved blockers.** If the readiness assessment shows critical issues, the plan should address those first or flag them as blocking the upgrade.

6. **Never dry-run with --dry-run=client.** Always use `--dry-run=server` to validate against the actual cluster API.

7. **Detail reasons for failure** If no valid remediation plans can be generated, detail the root cause in the remediationOptions.

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
                  "image": "quay.io/openshift-release-dev/ocp-release@sha256:abc123...",
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

- **`cluster-update-advisor`** — Provides the readiness assessment and findings that inform what needs remediation
- **`product-lifecycle`** — Used to verify operator support status and OCP compatibility before planning upgrades

The analysis phase of an AgenticRun uses `cluster-update-advisor` and `product-lifecycle` to assess readiness, then this skill (`cluster-update-planner`) to produce the executable plan.
