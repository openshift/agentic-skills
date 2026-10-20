---
name: cluster-update-advisor
description: Assess OpenShift cluster update (upgrade) readiness and risk, and produce a concrete remediation plan when the upgrade is feasible. Use when evaluating whether a cluster is safe to update, when an update is available, or when the user asks about update risks, prerequisites, blockers, or best practices.
license: Apache-2.0
---

# Cluster Update Advisor

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


## Risk Assessment Phase

### Parse readiness data

Extract the JSON from the proposal request.
Count checks with `_status` `ok` vs `error` for completeness.

### Verify data completeness

Any check with `_status` `error` represents a gap in visibility.
Note incomplete areas — they reduce confidence.

### Evaluate findings in detail

If the system prompt includes organization-specific policy (thresholds, scheduling preferences, risk tolerance), apply those constraints.
Otherwise use sensible defaults.
Walk through each check's summary and detail data:

- Compare numeric thresholds (node headroom, etcd backup age)
- Evaluate conditional update risks against cluster state
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

For other checks, treat an issue as a blocker if would cause data loss, a performance regression, or a failed update.
Treat the issue as a warning if would cause temporary disruption or slow updates.

### Investigate with other skills

If additional information or context is needed to classify a finding, these skills may be useful:

- **`openshift-docs`** — Read official OpenShift update docs for version-specific
  procedures and breaking changes.

- **`prometheus`** — Query cluster metrics for trend analysis (etcd latency,
  CPU headroom, firing alerts).

- **`jira`** — Search Red Hat Jira for bugs and known issues affecting the target version.

- **`product-lifecycle`** — Query the Red Hat Product Life Cycle API for operator
  support status, OCP compatibility, and the versions/catalogs/channels needed to
  become compatible. This is the authoritative source for deciding whether an
  operator needs upgrading; see "Determine which operators need upgrading" below
  for how to invoke it. Flag operators whose product version is End of life or
  whose `ocp_compatible` is `false` for the target OCP version.

### Classify overall recommendation

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

### Produce a structured risk report

Produce the risk report with the decision and evidence.

The output schema is enforced by the OlsAgent CR's `outputSchema` field —
the operator handles structured output compliance via the LLM API.

**If the decision is `escalate` or `block` with no viable remediation, stop here.** Do not produce a remediation plan — explain why in the diagnosis.

---

## Remediation Plan Phase

Proceed only when the assessment indicates the upgrade is feasible (decision is `recommend` or `warn`, or `block` with actionable remediation).

### Identify required operator upgrades

Use the OLM operator data at `.checks.olm_operator_lifecycle`. The `operators` array contains one entry per installed OLM-managed operator with fields like `name`, `package`, `namespace`, `channel`, `available_channels`, `installed_version`, and `state`.

Key behaviors to note:
- `install_plan_approval` determines whether an InstallPlan requires manual approval (`Manual`) or proceeds automatically (`Automatic`)
- `installed_csv` and `install_plan_approval` indicate OLMv0 (Subscription-managed) operators

The `summary` section reports aggregate counts: `incompatible_with_target`, `manual_approval`, `pending_upgrades`, `total_operators`.

This data establishes **which** operators are installed, how each is managed, and
where its resources live — it is what you feed into `olm-check` and what you use to
name resources in commands. It does not establish which operators need upgrading or
what to upgrade them to; `olm-check` does, as described next. In particular,
`summary.incompatible_with_target` is a hint that some work is likely needed, not a
substitute for the per-operator verdict, and `available_channels` lists what exists
rather than what is compatible.

**Supported operator scope:**

`cluster-logging`, `openshift-gitops-operator`, `kubernetes-nmstate-operator`, `openshift-cert-manager-operator`, `local-storage-operator`, `redhat-oadp-operator`, `mcg-operator`, `ocs-operator`, `odf-csi-addons-operator`, `odf-operator`, `loki-operator`, `kubevirt-hyperconverged-operator`, `openshift-pipelines-operator-rh`, `metallb-operator`, `devworkspace-operator`, `web-terminal`, `mtv-operator`, `multicluster-engine`, `advanced-cluster-management`, `rhacs-operator`, `compliance-operator`, `nfd`, `quay-operator`, `cluster-observability-operator`, `ocs-client-operator`, `recipe`, `odf-prometheus-operator`, `rook-ceph-operator`, `cephcsi-operator`, `odf-dependencies`, `grafana-operator`, `odf-external-snapshotter-operator`

**If the cluster has any installed operator whose `package` is not in this list, do not produce a remediation plan.** Report in the diagnosis that the cluster contains operators outside the supported scope and recommend performing the upgrade manually without AI assistance. List the unsupported operators found.

### Determine which operators need upgrading

Do not decide this from the readiness data alone. The `product-lifecycle` skill's
`olm-check` command is the authority on whether an installed operator version is
compatible with the target OCP version, and on what it must be upgraded to.

**Split the operators by OLM API type.** An entry with `installed_csv` or
`install_plan_approval` is OLMv0 (Subscription-managed); everything else is OLMv1
(ClusterExtension). Build one JSON array per type from `package` and
`installed_version`.

**Call `olm-check` once** for the whole cluster. Pass the target OCP version as
**major.minor only** (`4.21`, not `4.21.8`), and always pass `--compatibleonly` —
without it the tool reports every known version instead of the ones that reach the
target, and it emits no upgrade guidance.

```bash
python3 product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 --compatibleonly \
  --olmv0 '[{"package":"cluster-logging","version":"5.9.14"},{"package":"web-terminal","version":"1.9.0"}]' \
  --olmv1 '[{"package":"quay-operator","version":"3.11.0"}]'
```

The `--olmv0` path reads PackageManifests from the cluster with `oc`, which is how
it learns the catalog sources, channels and exact versions available. If the
top-level `packagemanifest_error` is present, no OLMv0 catalog data was obtained —
treat every OLMv0 operator needing an upgrade as unassessable (see table below).

**Decide per operator from its entry in `results`:**

| `olm-check` result | Upgrade needed? | Action |
|---|---|---|
| `ocp_compatible: true` | No | Leave the operator alone. Emit no commands for it. |
| `ocp_compatible: false`, `source_catalogs` present (OLMv0) | Yes | Plan the upgrade from `source_catalogs` — see below. |
| `ocp_compatible: false`, `available_versions` non-empty (OLMv1) | Yes | Plan the version-range bump — see below. |
| `ocp_compatible: false`, no reachable version | **Blocker** | Only lower versions are compatible; an upgrade cannot fix it. Report as a blocker, no plan. |
| `ocp_compatible: null` | Unknown | PLC tracks no `openshift_compatibility` for that version. Do not guess — report as a warning and leave the operator alone. |
| `error` set (listed in `lifecycle_unavailable`) | Unknown | The upgrade should NOT proceed. Name the operators and the reason in the Remediation Option. |

`ocp_compatible: false` is the **only** trigger for an operator upgrade. Being on
an older channel, having a pending InstallPlan, or a newer version existing are
not, on their own, reasons to upgrade. An operator whose product is End of life
but still `ocp_compatible: true` for the target is a warning, not an upgrade.

**Critical operators** are those in the supported list whose `olm-check` result is
`ocp_compatible: false` with a reachable upgrade. Those are the only ones that get
commands in the plan.

### Build the plan

Produce a single `RemediationOption` with these sections:

#### Pre-checks

Essential validation before any mutations:

- Verify cluster is not currently upgrading (`Progressing=False`)
- Verify no critical operators are degraded
- Verify target version exists in available or conditional updates

#### OLM Operator Upgrades (if needed)

**IMPORTANT:** Every command in the plan must be concrete and executable — resolve all variable values from the `olm-check` output and the readiness data. Never emit raw placeholders.

Emit commands only for the critical operators identified above.

**Choosing the target version.** From the operator's `olm-check` result, prefer the
**lowest version that is both compatible with the target OCP and higher than the
installed version.** For OLMv0 the `source_catalogs` versions are already filtered
to exactly that set, so take the smallest. For OLMv1, `available_versions` is
filtered for compatibility but not against the installed version — discard any
entry at or below the installed version first. Deviate from the lowest only when:
- The product's lifecycle `status` for that version is `End of life` or
  `Maintenance Support` — step up to the lowest version in `Full Support` instead.
- The readiness data shows another operator requires a higher minimum version.

**OLMv0 (Subscription/InstallPlan):**

Use the operator's `source_catalogs` entry. Each entry gives `catalog`,
`catalog_namespace`, and a `versions` map of full SemVer →
`{channels, bundle}`. Resolve the subscription constraints as follows:

| Subscription field | Source |
|---|---|
| `spec.name` | the `package` from the `olm-check` result |
| `spec.channel` | a channel listed for the chosen version in `versions.<version>.channels` |
| `spec.source` | the `catalog` of the entry the chosen version came from |
| `spec.sourceNamespace` | that entry's `catalog_namespace` |
| `spec.installPlanApproval` | leave as installed — do not change it |

Constraints that must hold, in order:

1. **The channel must actually carry the chosen version.** Only use a channel from
   that version's own `channels` list. Never infer a channel name from the version
   number, and never reuse `available_channels` from the readiness data — those are
   not filtered for compatibility.
2. **The catalog source and channel must come from the same `source_catalogs`
   entry.** A package can be served by several catalogs with different channel
   names; mixing a channel from one catalog with the `catalog` of another produces
   a Subscription that never resolves.
3. **If more than one channel carries the chosen version**, prefer a `stable`
   channel over `fast`, `candidate`, or `preview`; among version-scoped channels
   (`stable-6.5`) prefer the one pinned to the chosen version's minor over a
   floating one, so the upgrade lands on the intended version.
4. **If more than one catalog carries the chosen version**, prefer the catalog the
   operator is already subscribed to. Switching catalog source as well as channel
   is a larger change and should be called out in the description.
5. **Do not set `spec.startingCSV`** when patching an existing Subscription — it
   only applies at install time and is ignored on upgrade. Use the `bundle` value
   for verification and for the action description instead.

Patch only the fields that actually change. If the installed subscription is
already on the right catalog, patch the channel alone:

```bash
# Update subscription channel (triggers a new InstallPlan), only if the channel differs
# Requires: patch on subscriptions.operators.coreos.com
oc patch subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} --type=merge -p '{"spec":{"channel":"${TARGET_CHANNEL}"}}'
```

If the chosen version is only available from a different catalog, patch the source
in the same operation so the subscription is never left in an inconsistent state:

```bash
oc patch subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} --type=merge -p '{"spec":{"channel":"${TARGET_CHANNEL}","source":"${CATALOG}","sourceNamespace":"${CATALOG_NAMESPACE}"}}'
```

Then resolve and, if approval is `Manual`, approve the InstallPlan.
`${INSTALLPLAN_NAME}` comes from the subscription's `.status.installplan.name`
*after* the channel patch:

```bash
# Wait for the subscription to generate an InstallPlan
oc wait subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} --for=jsonpath='{.status.installplan.name}' --timeout=60s

# If InstallPlan approval is Manual, approve the InstallPlan
# Requires: patch on installplans.operators.coreos.com
oc patch installplans.operators.coreos.com ${INSTALLPLAN_NAME} -n ${NAMESPACE} --type=merge -p '{"spec":{"approved":true}}'

# Wait for operator upgrade to complete
oc wait installplans.operators.coreos.com ${INSTALLPLAN_NAME} -n ${NAMESPACE} --for='jsonpath={.status.phase}=Complete' --timeout=300s

# Confirm the expected bundle is now installed
oc get subscriptions.operators.coreos.com ${SUBSCRIPTION_NAME} -n ${NAMESPACE} -o jsonpath='{.status.installedCSV}'
```

If approval is `Automatic`, omit the approve step but keep the waits.

**OLMv1 (ClusterExtension):**

`olm-check` returns no catalog or channel data for OLMv1 operators, so **drive the
upgrade with a version constraint, not a channel.** Patching `channels` is not
sufficient: a channel is not guaranteed to be bounded by the compatible version
range, so OLMv1 — which resolves to the *latest* version satisfying the
constraint — can land on a version outside it.

Build the constraint from `available_versions`, which holds the major.minor
versions compatible with the target OCP:

- **Single compatible minor** (e.g. `["6.5"]`) → `>=6.5.0, <6.6.0`. The equivalent
  shorthands `~6.5.0` and `6.5.x` are also correct.
- **Several contiguous compatible minors** (e.g. `["6.4", "6.5"]`) → span them with
  `>=6.4.0, <6.6.0`. OLMv1 resolves to the latest version in range, so this lands
  on the newest compatible release.
- **Non-contiguous compatible minors** (e.g. `["6.3", "6.5"]`) → do not span the
  gap; the intervening minor is not compatible. Use `||` to express the union, or
  pin to the single lowest compatible minor above the installed version.

The lower bound must never be below the installed version — OLMv1 will not
downgrade under the default `CatalogProvided` policy, and a range that permits one
is a planning error. If every compatible version is *below* the installed version,
there is no upgrade path; report it as a blocker rather than emitting a patch.

```bash
# Set the compatible version range (OLMv1 resolves to the latest version in range)
# Requires: patch on clusterextensions.olm.operatorframework.io
oc patch clusterextensions.olm.operatorframework.io ${EXTENSION_NAME} --type=merge -p '{"spec":{"source":{"catalog":{"version":"${VERSION_RANGE}"}}}}'

# Wait for upgrade to complete
oc wait clusterextensions.olm.operatorframework.io ${EXTENSION_NAME} --for=condition=Installed=True --timeout=300s

# Confirm the resolved version falls inside the compatible range
oc get clusterextensions.olm.operatorframework.io ${EXTENSION_NAME} -o jsonpath='{.status.install.bundle.version}'
```

Leave `upgradeConstraintPolicy` at its default (`CatalogProvided`). Never set it to
`SelfCertified` to force a jump the catalog's upgrade graph does not allow — if the
resolution fails under `CatalogProvided`, the upgrade path does not exist and that
is a blocker to report, not a constraint to override.

#### Platform Upgrade

Resolve from the assessment data: `${TARGET_VERSION}` from the chosen update target in the cluster's available updates.

Request a platform update with `oc adm upgrade --to="${TARGET_VERSION}"`, which requires the ability to `patch` the `version` instance of the `clusterversions.config.openshift.io` resource.

```bash
oc adm upgrade --to=${TARGET_VERSION}
```

#### Post-checks

Verify the upgrade has started:

```bash
# Check that ClusterVersion status reflects the new desiredUpdate
oc get -o jsonpath='{.status.desired.version}' clusterversions.config.openshift.io version

# Verify upgrade is progressing (initial check only)
oc get -o jsonpath='{.status.conditions[?(@.type=="Progressing")].status}' clusterversions.config.openshift.io version
```

### Structure as RemediationOption

The plan must conform to the `RemediationOption` schema expected by the lightspeed-agentic-operator.

Each `ProposedAction` has:

| Field | Description |
|---|---|
| `type` | One of: `pre-check`, `mutation`, `wait`, `post-check` |
| `command` | The exact `oc` or `kubectl` command to execute |
| `description` | Human-readable explanation of what this action does |

Mark the action with:

```yaml
risk: "Medium" or "High"  # based on conditional risks and findings
reversible: "Irreversible"
rollbackPlan:
  description: "Platform upgrade cannot be rolled back once started."
```

**Derive RBAC for every planned action.** For each `oc` command in the plan, use the fully qualified resource name to identify the Kubernetes PolicyRule it requires (resource, apiGroup, verbs, resourceNames where applicable). Include the full list of required RBAC permissions in the remediation option output.

## Action Type Classification

| Action | Type | Example |
|---|---|---|
| Check cluster conditions | `pre-check` | `oc get clusterversions.config.openshift.io version -o jsonpath=...` |
| Check operator health | `pre-check` | `oc get clusteroperators.config.openshift.io -o json` |
| Update Subscription channel | `mutation` | `oc patch subscriptions.operators.coreos.com ... --type=merge -p '{...}'` |
| Approve InstallPlan | `mutation` | `oc patch installplans.operators.coreos.com ... --type=merge -p '{...}'` |
| Update ClusterExtension | `mutation` | `oc patch clusterextensions.olm.operatorframework.io ... --type=merge -p '{...}'` |
| Wait for operator install | `wait` | `oc wait clusterextensions.olm.operatorframework.io ... --for=condition=Installed` |
| Trigger platform upgrade | `mutation` | `oc adm upgrade --to=...` |
| Verify upgrade started | `post-check` | `oc get clusterversions.config.openshift.io version -o jsonpath=...` |

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

8. **Never upgrade all operators blindly.** Only upgrade operators whose `olm-check` result is `ocp_compatible: false`, or whose `maxOpenShiftVersion` blocks the upgrade.

9. **Never decide compatibility by eye.** Do not infer that an operator needs an upgrade from its version number, channel name, or a newer release existing. Run `olm-check` and act on `ocp_compatible`. Do not call it without `--compatibleonly` and then filter the versions yourself.

10. **Never invent a channel or version constraint.** For OLMv0, the channel must appear in the chosen version's `channels` list in `source_catalogs`, paired with the `catalog` from the same entry. For OLMv1, the version range must be derived from `available_versions` and must exclude every incompatible version.

11. **Never treat missing lifecycle data as compatible.** `ocp_compatible: null`, an `error` entry, or a `packagemanifest_error` means unknown. Report it; do not plan an upgrade on a guess, and do not silently skip the operator.

12. **Never produce generic or placeholder commands.** Every command must be specific, with actual operator names, namespaces, channels, and versions filled in.

13. **Never skip the pre-check phase.** Verify cluster readiness before any mutations.

14. **Never assume OLM API type.** The readiness data operator entries contain fields that indicate their management type — `installed_csv` and `install_plan_approval` indicate OLMv0 (Subscription-managed). Use the correct command templates, and pass each operator to `olm-check` under the matching `--olmv0` / `--olmv1` flag.

15. **Never dry-run with --dry-run=client.** Always use `--dry-run=server` to validate against the actual cluster API.

16. **Detail reasons for failure.** If no valid remediation plans can be generated, detail the root cause.

## Example Output Structure

The example below assumes `olm-check --ocp 4.21 --compatibleonly` returned, for the
OLMv0 operator `cluster-logging` at `5.9.14`, `ocp_compatible: false` with a
`source_catalogs` entry for catalog `redhat-operators` in
`openshift-marketplace` offering `6.5.0` in channel `stable-6.5`; and for the OLMv1
extension `quay-operator`, `ocp_compatible: false` with
`available_versions: ["3.15"]`.

```yaml
remediationOptions:
  - name: "OpenShift 4.21.5 → 4.21.8 upgrade with operator alignment"
    description: "Upgrade cluster-logging to 6.5.0 via the stable-6.5 channel and quay-operator into the 3.15 range (both reported ocp_compatible=false for OCP 4.21 by product-lifecycle), then upgrade the platform to 4.21.8"
    plan:
      risk: "Medium"
      reversible: "Irreversible"
      rollbackPlan:
        description: "Platform upgrade cannot be rolled back once started."
      actions:
        # Pre-checks
        - type: pre-check
          command: "oc get -o jsonpath='{.status.conditions[?(@.type==\"Progressing\")].status}' clusterversions.config.openshift.io version"
          description: "Verify cluster is not currently progressing (expected: False)"

        - type: pre-check
          command: "oc get clusteroperators.config.openshift.io -o json | jq -r '.items[] | select(.status.conditions[] | select(.type==\"Degraded\" and .status==\"True\")) | .metadata.name'"
          description: "Check for degraded cluster operators (expected: no output)"

        # OLM operator upgrades — OLMv0, channel carrying the chosen version
        - type: mutation
          command: "oc patch subscriptions.operators.coreos.com cluster-logging -n openshift-logging --type=merge -p '{\"spec\":{\"channel\":\"stable-6.5\"}}'"
          description: "Switch cluster-logging to the stable-6.5 channel of the redhat-operators catalog, which carries 6.5.0 (the lowest version compatible with OCP 4.21)"

        - type: wait
          command: "oc wait subscriptions.operators.coreos.com cluster-logging -n openshift-logging --for=jsonpath='{.status.state}'=AtLatestKnown --timeout=300s"
          description: "Wait for cluster-logging operator upgrade to complete"

        - type: post-check
          command: "oc get subscriptions.operators.coreos.com cluster-logging -n openshift-logging -o jsonpath='{.status.installedCSV}'"
          description: "Verify the installed CSV is cluster-logging.v6.5.0"

        # OLM operator upgrades — OLMv1, compatible version range
        - type: mutation
          command: "oc patch clusterextensions.olm.operatorframework.io quay-operator --type=merge -p '{\"spec\":{\"source\":{\"catalog\":{\"version\":\">=3.15.0, <3.16.0\"}}}}'"
          description: "Pin quay-operator to the 3.15 range, the only range compatible with OCP 4.21; OLMv1 resolves to the latest release within it"

        - type: wait
          command: "oc wait clusterextensions.olm.operatorframework.io quay-operator --for=condition=Installed=True --timeout=300s"
          description: "Wait for quay-operator upgrade to complete"

        - type: post-check
          command: "oc get clusterextensions.olm.operatorframework.io quay-operator -o jsonpath='{.status.install.bundle.version}'"
          description: "Verify the resolved version falls within >=3.15.0, <3.16.0"

        # Platform upgrade
        - type: mutation
          command: "oc adm upgrade --to=4.21.8"
          description: "Trigger platform upgrade to 4.21.8 (patches clusterversions.config.openshift.io/version)"

        # Post-checks
        - type: post-check
          command: "oc get -o jsonpath='{.status.desired.version}' clusterversions.config.openshift.io version"
          description: "Verify desiredUpdate has been set (expected: 4.21.8)"

        - type: post-check
          command: "oc get -o jsonpath='{.status.conditions[?(@.type==\"Progressing\")].status}' clusterversions.config.openshift.io version"
          description: "Verify upgrade has started progressing (expected: True)"
```

## Integration with Other Skills

This skill is typically used in conjunction with:

- **`product-lifecycle`** — The single source of truth for operator upgrade
  planning. Its `olm-check` command determines whether each installed operator is
  compatible with the target OCP version, which versions are, and — for OLMv0 —
  which catalog sources and channels provide them. Both the "needs an upgrade"
  decision and the upgrade constraints come from its output.

