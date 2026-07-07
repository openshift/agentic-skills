---
name: product-lifecycle
description: Query Red Hat Product Life Cycle data for support phases, end-of-life dates, and OpenShift version compatibility. Use when evaluating whether installed operators or layered products are supported on a given OCP version, approaching end of life, or need upgrading before a cluster upgrade. Also use when the user asks about product support status, EOL dates, or lifecycle phases for any Red Hat product.
---

# Red Hat Product Life Cycle

Query the Red Hat Product Life Cycle API to check support status, EOL dates, and OpenShift compatibility for Red Hat products and layered operators.

## CLI Tool

All queries go through `product-lifecycle/scripts/plc_lookup.py` — a standalone
Python 3 script with no dependencies beyond stdlib. Run with `-h` for full usage:

```bash
./product-lifecycle/scripts/plc_lookup.py -h
```

### Commands

#### `products` — Query products by name

```bash
# Look up a product
./product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift"

# With OCP compatibility check
./product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift" --ocp 4.21

# Look up OCP itself
./product-lifecycle/scripts/plc_lookup.py products "Red Hat OpenShift Container Platform"
```

Returns matching product versions with support status, OCP compatibility,
and lifecycle phase dates. When `--ocp` is provided, adds `ocp_target` and
`ocp_compatible` (true/false/null) to each version entry.

Be specific with product names to avoid overly broad results.

#### `olm-check` — Batch check OLM operators

```bash
./product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 \
  --operators '[{"package":"cluster-logging"},{"package":"web-terminal"}]'
```

Looks up each operator by its OLM `package` name. Reports
`lifecycle_unavailable` for operators not tracked in the API.

## Output Format

All commands output JSON. Each product version entry includes:

| Field | Description |
|---|---|
| `product` | Current product name |
| `former_names` | Previous product names (useful for search fallback) |
| `package` | OLM package name (maps to Subscription `spec.name`) |
| `version` | Version number |
| `status` | Raw API support status (e.g. `"Full Support"`, `"End of life"`) |
| `ocp_versions` | List of compatible OCP versions (empty for non-layered products) |
| `ocp_compatible` | `true`/`false`/`null` — only present when `--ocp` is used |
| `phases` | Array of lifecycle phases with `name`, `start_date`, `end_date` |

## When to Use

- **Upgrade readiness**: check if installed operators are compatible with the
  target OCP version before upgrading
- **EOL planning**: identify products approaching or past end of life
- **Support status**: determine current support phase for any Red Hat product
- **Cross-reference with update-advisor**: when `olm_operator_lifecycle` data
  is present in readiness JSON, use `olm-check` to verify lifecycle status

## Important

- `ocp_versions` is only present on **layered product** versions, not on OCP itself.
- Not all operators have lifecycle entries — report "lifecycle data unavailable"
  rather than treating missing data as an error.
- The `package` field in API responses maps to the OLM Subscription's
  `spec.name` — use this for exact matching, not product name.
