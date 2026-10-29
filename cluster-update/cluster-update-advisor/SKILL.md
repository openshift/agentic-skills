---
name: cluster-update-advisor
description: Assess OpenShift cluster update (upgrade) readiness and risk, and produce a concrete remediation plan when the upgrade is feasible. Use when evaluating whether a cluster is safe to update, when an update is available, or when the user asks about update risks, prerequisites, blockers, or best practices.
license: Apache-2.0
---

# Cluster Update Advisor

Assess whether an OpenShift cluster is ready to update, and — when the update is
feasible — produce a concrete, ordered remediation plan.

## Input

The proposal request already contains everything needed to start: current and target
version metadata, the update path classification (`Recommended` or `Conditional`), and
pre-collected **cluster readiness JSON** gathered by the Cluster Version Operator,
embedded between ` ```json ` markers under the "Cluster Readiness Data" heading.
**Do not re-collect cluster data.** Parse that JSON to begin.

```json
{
  "current_version": "4.21.5",
  "target_version": "4.21.8",
  "checks": {
    "cluster_conditions":     { "_status": "ok", "summary": {...}, ... },
    "operator_health":        { "_status": "ok", "summary": {...}, ... },
    "api_deprecations":       { "_status": "ok", "summary": {...}, ... },
    "node_capacity":          { "_status": "ok", "summary": {...}, ... },
    "pdb_drain":              { "_status": "ok", "summary": {...}, ... },
    "etcd_health":            { "_status": "ok", "summary": {...}, ... },
    "network":                { "_status": "ok", "summary": {...}, ... },
    "crd_compat":             { "_status": "ok", "summary": {...}, ... },
    "olm_operator_lifecycle": { "_status": "ok", "summary": {...}, "operators": [...] }
  }
}
```

Every check has `_status` (`ok` or `error`) and a `summary` for quick parsing. A check
with `_status: error` is a gap in visibility — note it; it lowers confidence.

## Output format

Output must conform to the `RemediationOption` schema enforced by the OlsAgent CR's
`outputSchema` field; the operator handles structured-output compliance. Plan actions are
typed `pre-check`, `mutation`, `wait`, or `post-check`, and appear in that order.
When the update cannot proceed, structure the `RemediationOption` to include the
causes in within the RemediationOption. If any single cause is blocking the cluster
update, also assess if a cluster update ignoring that factor is possible as a viable
path, generating a `RemediationOption`. In such cases also include a plan blocked on user
upgrade instructing user on steps to take or what conditions need to be met or waited for
in order to perform a safe cluster update. If a plan makes destructive changes to a cluster,
include steps to restore any removed components or backed up data if appropriate.

## Assess update readiness

Apply any organization-specific policy from the system prompt (thresholds, scheduling
preferences, risk tolerance); otherwise use sensible defaults. Walk each check's summary
and detail data:

- Compare numeric thresholds (node headroom, etcd backup age)
- Evaluate conditional update risks against actual cluster state — never dismiss them
- Identify compounding risks (e.g. paused MCP + cert expiry)
- Estimate update duration (~10 min/node)

### Classify each finding

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

For checks not listed: blocker if the issue would cause data loss, a performance
regression, or a failed update; warning if it would cause temporary disruption or a slow
update.

### Decide

| Blockers | Warnings | Decision |
|---|---|---|
| Unable to assess | any | `escalate` — insufficient data for a confident assessment |
| 1+ | any | `block` — findings must be resolved before updating |
| 0 | 1+ | `warn` — findings exist but are manageable with prerequisites |
| 0 | 0 | `recommend` — all checks pass within acceptable thresholds |

Report the decision with the evidence behind it. **If the decision is `escalate`, or
`block` with no viable remediation, stop here** — explain why in the diagnosis and
produce no plan.

## Build the remediation plan

Proceed only when the update is feasible: the decision is `recommend`, `warn`, or `block`
with actionable remediation. Produce a single `RemediationOption`.

### Determine if any operators need upgrading

`.checks.olm_operator_lifecycle.operators[]` tells you **what is installed and how it is
managed** — `name`, `package`, `namespace`, `channel`, `available_channels`,
`installed_version`, `installed_csv`, `install_plan_approval`, `state`. Use it to feed
`olm-check` and to name resources in commands. It does **not** decide what needs
upgrading: `summary.incompatible_with_target` is a hint that work is likely needed, not a
per-operator verdict, and `available_channels` lists what exists rather than what is
compatible.

**Split by OLM API type.** An entry with `installed_csv` or `install_plan_approval` is
OLMv0 (Subscription-managed); everything else is OLMv1 (ClusterExtension). Build one JSON
array per type from `package` and `installed_version`.

When using the `olm-check` skill call it **once** for the whole cluster, with the target OCP as **major.minor**
(`4.21`, not `4.21.8`) and always `--compatibleonly`

Decide per operator from its entry in `results` — never from a version number, a channel
name, or the mere existence of a newer release:

| `olm-check` result | Action |
|---|---|
| `ocp_compatible: true` | Leave it alone, emit no commands. If its product is `End of life`, report that as a warning. |
| `ocp_compatible: false` + `source_catalogs` (OLMv0) | Upgrade — plan from `source_catalogs`. |
| `ocp_compatible: false` + non-empty `available_versions` (OLMv1) | Upgrade — plan the version-range bump. |
| `ocp_compatible: false`, no reachable version | **Blocker.** No upgrade fixes the incompatibility; report it and produce no plan. |
| `ocp_compatible: null` | **Unknown** — PLC tracks no compatibility for that version. Report as a warning and leave the operator alone. |
| `error` set (listed in `lifecycle_unavailable`), or top-level `packagemanifest_error` | **Unknown** — the update should not proceed. Name the operators and the reason in the remediation option. |

`ocp_compatible: false` with a reachable upgrade is the **only** trigger for an operator
upgrade; those operators are the only ones that get commands in the plan.

### Commands

Every command must be concrete and executable: resolve every value from the `olm-check`
output and the readiness data before emitting it, and never leave a placeholder variable
in the plan. Patch only the fields that actually change.

**Choosing the target version:** the lowest version that is compatible with the target
OCP, strictly higher than the installed version, and not `End of life` in its product
lifecycle `status`.

#### Pre-checks

Validate before any mutation — never skip this phase:

- Cluster is not already updating (`Progressing=False`)
- No critical operator is degraded
- Target version exists in available or conditional updates

#### OLMv0 operator upgrade (Subscription / InstallPlan)

Each `source_catalogs` entry gives a `catalog`, a `catalog_namespace`, and a `versions`
map of full SemVer → `{channels, bundle}`. From the chosen version's entry:

1. Take the channel **only** from that version's own `channels` list. Never infer a
   channel from a version number, and never reuse `available_channels` from the readiness
   data — it is not filtered for compatibility.
2. Take the catalog and the channel from the **same** `source_catalogs` entry.
3. If several channels carry the chosen version, prefer `stable` over `fast`, `candidate`
   or `preview`; among version-scoped channels (`stable-6.5`) prefer the one pinned to the
   chosen version's minor over a floating one, so the upgrade lands on the intended version.
4. Do **not** set `spec.startingCSV` — it applies at install time only and is ignored on
   upgrade. Use the `bundle` value for verification and in the action description instead.

If the subscription is already on the right catalog, patch the channel alone (and skip
the patch entirely if the channel already matches):

```bash
# Requires: patch on subscriptions.operators.coreos.com
oc patch subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} --type=merge -p '{"spec":{"channel":"${TARGET_CHANNEL}"}}'
```

If the chosen version is only available from a different catalog, patch the source and
channel in one operation so the subscription is never left inconsistent:

```bash
oc patch subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} --type=merge -p '{"spec":{"channel":"${TARGET_CHANNEL}","source":"${CATALOG}","sourceNamespace":"${CATALOG_NAMESPACE}"}}'
```

Then wait for the InstallPlan, approve it when `install_plan_approval` is `Manual` (omit
the approve step for `Automatic`, keep the waits), and verify. `${INSTALLPLAN_NAME}` comes
from the subscription's `.status.installplan.name` *after* the channel patch:

```bash
# Wait for the subscription to generate an InstallPlan
oc wait subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} --for=jsonpath='{.status.installplan.name}' --timeout=60s

# Manual approval only
oc patch installplans.operators.coreos.com ${INSTALLPLAN_NAME} -n ${NAMESPACE} --type=merge -p '{"spec":{"approved":true}}'

# Wait for the operator upgrade to complete, then confirm the expected bundle is installed
oc wait installplans.operators.coreos.com ${INSTALLPLAN_NAME} -n ${NAMESPACE} --for='jsonpath={.status.phase}=Complete' --timeout=300s
oc get subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} -o jsonpath='{.status.installedCSV}'
```

#### OLMv1 operator upgrade (ClusterExtension)

Set a version range derived from `available_versions`, excluding every incompatible
version; OLMv1 resolves to the newest version in range. If the only version `olm-check`
returns is the installed one, do not patch the ClusterExtension.

```bash
# Requires: patch on clusterextensions.olm.operatorframework.io
oc patch clusterextensions.olm.operatorframework.io ${EXTENSION_NAME} --type=merge -p '{"spec":{"source":{"catalog":{"version":"${VERSION_RANGE}"}}}}'

# Wait for the upgrade, then confirm the resolved version is inside the compatible range
oc wait clusterextensions.olm.operatorframework.io ${EXTENSION_NAME} --for=condition=Installed=True --timeout=300s
oc get clusterextensions.olm.operatorframework.io ${EXTENSION_NAME} -o jsonpath='{.status.install.bundle.version}'
```

#### Platform update

`${TARGET_VERSION}` is the chosen target from the cluster's available updates. All plans that include this are **Irreversible**

```bash
# Requires: patch on the version instance of clusterversions.config.openshift.io
oc adm upgrade --to=${TARGET_VERSION}
```

#### Post-checks

Verify the update has started:

```bash
oc get -o jsonpath='{.status.desired.version}' clusterversions.config.openshift.io version
oc get -o jsonpath='{.status.conditions[?(@.type=="Progressing")].status}' clusterversions.config.openshift.io version
```

### RBAC

For each `oc` command in the plan, derive the Kubernetes PolicyRule it requires from the
fully qualified resource name (resource, apiGroup, verbs, and `resourceNames` where
applicable), and include the complete list in the remediation option. Include permissions
required for reading and modifying resources as needed. Do not skip RBAC required to `get` or `list`
resources checked by any command in the plan.
Ensure there are patch permissions for clusterversions.config.openshift.io for actual cluster upgrade.


## Hard rules

- Never recommend skipping an update version unless the readiness data shows that path
  exists, and never recommend force-updating. If the standard path is blocked, report it
  as blocked.
- Never treat missing lifecycle data as compatible. `ocp_compatible: null`, an `error`
  entry, or a `packagemanifest_error` means unknown — report it; do not guess, and do not
  silently skip the operator.
- Never dry-run with `--dry-run=client`; use `--dry-run=server` so validation hits the
  real cluster API.
- If no valid remediation plan can be produced, say so and give the root cause.
