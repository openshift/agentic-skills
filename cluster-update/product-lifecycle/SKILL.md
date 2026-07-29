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

#### `olm-check` — Batch check OLM operators

```bash
python3 product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 \
  --operators '[{"package":"cluster-logging","version":"6.5.1"},{"package":"web-terminal"}]'
```

Looks up each operator by its OLM `package` name. Each operator in the
JSON array accepts `package` (required) and `version` (optional).

Returns **one result per operator**. The shape depends on whether a
`version` was provided:

- **With version (matched):** `package`, `requested_version`, `product`,
  `status`, `ocp_compatible`, `phases`. No `error` field.
- **Without version (package exists):** `package`, `product`,
  `available_versions`. No `error` field.
- **Error:** `error` field set — explains what went wrong (package not
  found, version not tracked). Includes `available_versions` when the
  package exists but the version doesn't.

When a version is provided, the tool normalizes it to major.minor
(e.g. `1.9.0` → `1.9`) and matches against API version names.

Reports `lifecycle_unavailable` listing every operator whose result has `error` set.


## Output Format

All commands output JSON.

### `products` output

Each product version entry includes `product`, `former_names`, `package`,
`version`, `status`, `ocp_versions`, `ocp_compatible`, and `phases`.

### `olm-check` output

One entry per operator:

| Field | Description |
|---|---|
| `package` | OLM package name queried |
| `requested_version` | Normalized version checked (when provided) |
| `error` | Why data is unavailable — absent on success, set on failure |
| `product` | Product name (on success) |
| `status` | Raw API support status, e.g. `"Full Support"`, `"End of life"` (on success) |
| `ocp_compatible` | `true`/`false`/`null` — whether the version is compatible with the target OCP (on success) |
| `phases` | Lifecycle phases with `name`, `start_date`, `end_date` (on success) |
| `available_versions` | Versions the API does track (when package exists but version doesn't) |

## When to Use

- **Upgrade readiness**: check if installed operators are compatible with the
  target OCP version before upgrading
- **EOL planning**: identify products approaching or past end of life
- **Support status**: determine current support phase for any Red Hat product
- **Cross-reference with update-advisor**: when `olm_operator_lifecycle` data
  is present in readiness JSON, use `olm-check` to verify lifecycle status

## Important

- `ocp_versions` is only present on **layered product** versions, not on OCP itself.
- Not all operators have lifecycle entries — `olm-check` sets `error` on the
  result for operators without data.
- The `package` field in API responses maps to the OLM Subscription's
  `spec.name` — use this for exact matching, not product name.
