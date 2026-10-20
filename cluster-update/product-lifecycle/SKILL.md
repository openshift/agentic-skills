---
name: product-lifecycle
description: Query Red Hat Product Life Cycle data for support phases, end-of-life dates, and OpenShift version compatibility, and work out which operator versions, catalog sources and channels to use to reach a target OCP version. Use when evaluating whether installed operators or layered products are supported on a given OCP version, approaching end of life, or need upgrading before a cluster upgrade. Also use when the user asks about product support status, EOL dates, or lifecycle phases for any Red Hat product.
license: Apache-2.0
compatibility: Requires Python 3 and network access to query https://access.redhat.com/product-life-cycles/api/v2/products. The `olm-check --olmv0` path also requires `oc` on PATH with access to a cluster (it reads PackageManifests).
---

# Red Hat Product Life Cycle

Query the Red Hat Product Life Cycle (PLC) API to check support status, EOL dates,
and OpenShift compatibility for Red Hat products and layered operators — and, for
OLM-managed operators, to work out the concrete versions, catalog sources and
channels needed to become compatible with a target OCP version.

## CLI Tool

All queries go through `product-lifecycle/scripts/plc_lookup.py` — a standalone
Python 3 script with no dependencies beyond stdlib. Run with `-h` for full usage:

```bash
python3 product-lifecycle/scripts/plc_lookup.py -h
```

### Commands

#### `products` — Query products by name

```bash
# Look up a product
python3 product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift"

# With OCP compatibility check
python3 product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift" --ocp 4.21

# Look up OCP itself
python3 product-lifecycle/scripts/plc_lookup.py products "Red Hat OpenShift Container Platform"
```

Returns matching product versions with support status, OCP compatibility,
and lifecycle phase dates. When `--ocp` is provided, adds `ocp_target` and
`ocp_compatible` (true/false/null) to each version entry.

Be specific with product names to avoid overly broad results.

#### `olm-check` — Batch check OLM operators against a target OCP version

```bash
# OLMv0 operators (reads PackageManifests from the cluster via oc)
python3 product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 --compatibleonly \
  --olmv0 '[{"package":"cluster-logging","version":"5.9.14"},{"package":"web-terminal"}]'

# OLMv1 operators
python3 product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 --compatibleonly \
  --olmv1 '[{"package":"openshift-pipelines-operator-rh","version":"1.22.0"}]'

# Both in one invocation
python3 product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 --compatibleonly \
  --olmv0 '[{"package":"cluster-logging"}]' \
  --olmv1 '[{"package":"quay-operator"}]'
```

| Flag | Required | Meaning |
|---|---|---|
| `--ocp` | yes | Target OCP version, e.g. `4.21` |
| `--olmv0` | one of the two | JSON array of OLMv0 (Subscription/OLM classic) operators |
| `--olmv1` | one of the two | JSON array of OLMv1 (ClusterExtension) operators |
| `--compatibleonly` | no | Restrict version and catalog output to versions compatible with `--ocp` |

At least one of `--olmv0` / `--olmv1` must be given. Each entry in either array
accepts `package` (required, the OLM package name) and `version` (optional).

**`--olmv0` requires cluster access.** For OLMv0 operators the script shells out to
`oc get packagemanifests.packages.operators.coreos.com -A -o json` to learn which
catalog sources carry the package, what versions each carries, and which channels
expose each version. If that call fails or times out, the run still completes — the
lifecycle data is returned and a top-level `packagemanifest_error` explains the
failure, but no `source_catalogs` appear. `--olmv1` entries are lifecycle-only;
they never carry `source_catalogs`.

**Use `--compatibleonly` for upgrade planning.** Without it, the tool reports every
version the PLC API tracks and every catalog version it found — useful for a full
inventory, but it will not narrow the result down to the versions that actually get
you to the target OCP, and it suppresses the "upgrade from here" output described
below.

### What `olm-check` returns per operator

The result shape depends on whether `version` was supplied and, if so, whether it
is already compatible with `--ocp`.

**1. No version supplied** — "what can I run on the target OCP?"

- `available_versions`: the operator versions compatible with `--ocp`
  (with `--compatibleonly`; otherwise every version the PLC API tracks). These are
  PLC major.minor strings, e.g. `6.5`.
- `source_catalogs` (OLMv0 only): one entry per catalog source carrying the package,
  each with `catalog`, `catalog_namespace`, and a `versions` map of full
  SemVer → `{channels, bundle}` — the channels to subscribe to in order to reach
  that version. With `--compatibleonly` this is filtered to versions whose
  major.minor is compatible with the target OCP.

For OLMv1 operators this is just the compatible version list — no catalog or
channel data.

**2. Version supplied and already compatible** (`ocp_compatible: true`)

Just the package's lifecycle information: `package`, `requested_version`,
`product`, `status`, `ocp_compatible`, `ocp_versions`, `phases`. No upgrade
guidance is emitted, because none is needed.

**3. Version supplied and not compatible** (`ocp_compatible: false`, with `--compatibleonly`)

The same lifecycle fields, plus:

- `available_versions`: compatible versions to move to.
- `source_catalogs` (OLMv0 only): catalogs, channels and versions filtered to
  versions that are both compatible with the target OCP **and** strictly higher
  (SemVer precedence) than the supplied version — i.e. reachable by an upgrade
  rather than a downgrade. Omitted if no such version exists in any catalog.

Report this as: upgrade to one of `available_versions`, by subscribing to a listed
channel from the listed catalog source.

**4. Error** — `error` is set: package not found in the PLC API, version not tracked,
or empty package name. `available_versions` is included when the package exists but
the version doesn't. Every such package is also listed in top-level
`lifecycle_unavailable`.

When a version is provided, the tool normalizes it to major.minor
(e.g. `1.9.0` → `1.9`, leading `v` stripped) for PLC matching, but compares
against catalog versions using full SemVer precedence.

## Output Format

All commands output JSON.

### `products` output

Each product version entry includes `product`, `former_names`, `package`,
`version`, `status`, `ocp_versions`, `ocp_compatible`, and `phases`.

### `olm-check` output

Top level: `ocp_target`, `operators_checked`, `lifecycle_unavailable`, `results`,
and `packagemanifest_error` when the PackageManifest lookup failed.

One entry in `results` per operator:

| Field | Description |
|---|---|
| `package` | OLM package name queried |
| `requested_version` | Normalized major.minor version checked (when provided) |
| `error` | Why data is unavailable — absent on success, set on failure |
| `product` | Product name (on success) |
| `status` | Raw API support status, e.g. `"Full Support"`, `"End of life"` |
| `ocp_compatible` | `true`/`false`/`null` — whether the requested version is compatible with the target OCP |
| `ocp_versions` | OCP versions the requested version supports |
| `phases` | Lifecycle phases with `name`, `start_date`, `end_date` |
| `available_versions` | Compatible versions (no version supplied, incompatible version, or version not tracked) |
| `source_catalogs` | OLMv0 only — catalogs/channels/versions to install or upgrade to |

`source_catalogs` entry shape:

```json
{
  "catalog": "redhat-operators",
  "catalog_namespace": "openshift-marketplace",
  "versions": {
    "6.5.1": {"channels": ["stable-6.5"], "bundle": "cluster-logging.v6.5.1"}
  }
}
```

## When to Use

- **Upgrade readiness**: check if installed operators are compatible with the
  target OCP version before upgrading
- **Remediation planning**: for incompatible OLMv0 operators, get the catalog
  source, channel and version to upgrade to before the cluster upgrade
- **EOL planning**: identify products approaching or past end of life
- **Support status**: determine current support phase for any Red Hat product
- **Cross-reference with update-advisor**: when `olm_operator_lifecycle` data
  is present in readiness JSON, use `olm-check` to verify lifecycle status

## Important

- `ocp_versions` is only present on **layered product** versions, not on OCP itself.
- Not all operators have lifecycle entries — `olm-check` sets `error` on the
  result for operators without data.
- The `package` field in API responses maps to the OLM Subscription's
  `spec.name` — use this for exact matching, not product name. A PLC product may
  list several comma-separated packages; each is matched independently.
- PLC tracks compatibility at major.minor granularity only. Catalog data carries
  full SemVer, so a compatible major.minor may map to several installable patch
  versions.
- A package can be served by more than one catalog source; `source_catalogs` lists
  each separately, and the same version may appear in several channels.
