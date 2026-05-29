---
name: product-lifecycle
description: Query Red Hat Product Life Cycle data for support phases, end-of-life dates, and OpenShift version compatibility. Use when evaluating whether installed operators or layered products are supported on a given OCP version, approaching end of life, or need upgrading before a cluster upgrade. Also use when the user asks about product support status, EOL dates, or lifecycle phases for any Red Hat product.
allowed-tools: Bash(python3:*)
---

# Red Hat Product Life Cycle

Query the Red Hat Product Life Cycle API (v2) to check support status, EOL
dates, and OpenShift compatibility for Red Hat products and layered operators.

## CLI Tool

All queries go through `cluster-update/product-lifecycle/scripts/plc_lookup.py` — a standalone Python 3 script
with no dependencies beyond stdlib. Run with `-h` for full usage:

```bash
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py -h
```

### Commands

#### `products` — Query products by name

Maps directly to `GET /v2/products?name=<name>`.

```bash
# Look up a product
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift"

# With OCP compatibility check
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "logging for Red Hat OpenShift" --ocp 4.21

# Paginate broad queries
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "OpenShift" --limit 5
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py products "OpenShift" --limit 5 --offset 5
```

Returns matching product versions with normalized support status, OCP
compatibility, and lifecycle phase dates. When `--ocp` is provided, adds
`ocp_target` and `ocp_compatible` (true/false/null) to each version entry.

Use `--limit` and `--offset` for broad queries that return many results.
The response includes `total`, `returned`, and `next_offset` (when more
results are available) so you can paginate through the full result set.

#### `olm-check` — Batch check OLM operators

```bash
python3 cluster-update/product-lifecycle/scripts/plc_lookup.py olm-check --ocp 4.21 \
  --operators '[{"package":"cluster-logging"},{"package":"elasticsearch-operator"}]'
```

Looks up each operator by its OLM `package` name. First searches the bulk
"OpenShift" product set, then falls back to individual queries. Reports
`lifecycle_unavailable` for operators not tracked in the API.

### Output Format

All commands output JSON. Each product version entry includes:

| Field | Description |
|---|---|
| `status` | Normalized: `supported`, `maintenance`, `extended`, `end-of-maintenance`, `eol`, or `unknown` |
| `status_raw` | Original API value (e.g. `"Full Support"`, `"End of life"`) |
| `ocp_versions` | List of compatible OCP versions (empty for non-layered products) |
| `ocp_compatible` | `true`/`false`/`null` — only present when `--ocp` is used |
| `ga_date` | General availability date |
| `full_support_end` | End of full support phase |
| `maintenance_end` | End of maintenance support phase |

Date fields are objects with `date` (ISO 8601 or descriptive string) and
`format` (`"date"` or `"string"`).

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
