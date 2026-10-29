---
name: product-lifecycle
description: Query Red Hat Product Life Cycle data for support phases, end-of-life dates, and OpenShift version compatibility, and work out which operator versions, catalog sources and channels to use to reach a target OCP version. Use when evaluating whether installed operators or layered products are supported on a given OCP version, approaching end of life, or need upgrading before a cluster upgrade. Also use when the user asks about product support status, EOL dates, or lifecycle phases for any Red Hat product.
license: Apache-2.0
compatibility: Requires Python 3 (stdlib only) and network access to https://access.redhat.com/product-life-cycles/api/v2/products. `olm-check --olmv0` additionally requires `oc` on PATH with cluster access, to read PackageManifests.
---

# Red Hat Product Life Cycle

All queries go through `product-lifecycle/scripts/plc_lookup.py`, a standalone Python 3
script. Both commands print JSON to stdout. Run with `-h` for full usage.

## `products` — look up a product by name

```bash
python3 product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift" --ocp 4.21
```

Substring match on the product name — be specific, or the result set is large.
Returns `{"results": [...], "total": N}`, plus `ocp_target` when `--ocp` is given. Each
result carries `product`, `former_names`, `package`, `version`, `status`, `ocp_versions`,
`phases`, and — with `--ocp` — `ocp_compatible`.

## `olm-check` — check installed OLM operators against a target OCP version

```bash
python3 product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 --compatibleonly \
  --olmv0 '[{"package":"cluster-logging","version":"5.9.14"},{"package":"web-terminal"}]' \
  --olmv1 '[{"package":"quay-operator","version":"3.11.0"}]'
```

| Flag | Required | Meaning |
|---|---|---|
| `--ocp` | yes | Target OCP version, major.minor (`4.21`) |
| `--olmv0` | one of the two | JSON array of Subscription-managed (OLM classic) operators |
| `--olmv1` | one of the two | JSON array of ClusterExtension-managed operators |
| `--compatibleonly` | no | Restrict output to versions compatible with `--ocp` |

Array entries take `package` (required — the OLM package name, i.e. a Subscription's
`spec.name`) and `version` (optional). Supply `version` whenever it is known: without it
the tool only answers "what can run on the target OCP" and emits no `ocp_compatible`
verdict.

**Pass `--compatibleonly` for upgrade planning.** Without it the tool reports every
version the PLC API tracks and every catalog version it found — a full inventory, but not
narrowed to the versions that reach the target OCP — and it suppresses the
reachable-upgrade output described below.

**`--olmv0` reads the cluster.** It runs `oc get packagemanifests.packages.operators.coreos.com -A -o json`
to learn which catalog sources carry each package, which versions each carries, and which
channels expose each version. If that call fails or times out the run still completes:
lifecycle data is returned, a top-level `packagemanifest_error` explains the failure, and
no `source_catalogs` appear. `--olmv1` entries are lifecycle-only and never carry
`source_catalogs`.

### Output

Top level: `ocp_target`, `operators_checked`, `lifecycle_unavailable` (packages whose
result has an `error`), `results`, and `packagemanifest_error` when the PackageManifest
lookup failed.

| Field in `results[]` | Present when | Description |
|---|---|---|
| `package` | always | OLM package name queried |
| `error` | lookup failed | Package not in PLC API, version not tracked, or empty package name |
| `requested_version` | `version` supplied | Version normalized to major.minor (`1.9.0` → `1.9`, leading `v` stripped) |
| `product` | package found | PLC product name |
| `status` | `version` supplied | Support status, e.g. `Full Support`, `Maintenance Support`, `End of life` |
| `ocp_compatible` | `version` supplied | `true` / `false` / `null` (PLC tracks no compatibility for that version) |
| `ocp_versions` | `version` supplied | OCP versions the requested version supports |
| `phases` | `version` supplied | Lifecycle phases with `name`, `start_date`, `end_date` |
| `available_versions` | no version supplied, `ocp_compatible: false`, or version untracked | Compatible PLC major.minor versions (`6.5`) to move to |
| `source_catalogs` | OLMv0 only, alongside `available_versions` | Catalogs, channels and full SemVer versions providing them |

When `ocp_compatible` is `true` no upgrade guidance is emitted, because none is needed.
When it is `false` (with `--compatibleonly`), `source_catalogs` is filtered to versions
that are both compatible with the target OCP **and** strictly higher by SemVer precedence
than the supplied version — so everything listed is reachable by an upgrade rather than a
downgrade. It is omitted entirely if no such version exists in any catalog.

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

## Caveats

- `ocp_versions` exists only on **layered product** versions, not on OCP itself.
- Match on `package`, never on product name. One PLC product may list several
  comma-separated packages; each is matched independently.
- Not every operator has a lifecycle entry; those get `error` and are listed in
  `lifecycle_unavailable`.
- PLC tracks compatibility at major.minor granularity only. Catalog data carries full
  SemVer, so one compatible major.minor can map to several installable patch versions.
- A package can be served by more than one catalog source; each is a separate
  `source_catalogs` entry, and the same version may appear in several channels.
