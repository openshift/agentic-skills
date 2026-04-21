---
name: product-lifecycle
description: Query Red Hat Product Life Cycle data (PLCC) for support phases, end-of-life dates, and OpenShift version compatibility. Use when evaluating whether installed operators or layered products are supported on a given OCP version, approaching end of life, or need upgrading before a cluster upgrade. Also use when the user asks about product support status, EOL dates, or lifecycle phases for any Red Hat product.
allowed-tools: Bash(curl:*)
---

# Red Hat Product Life Cycle (PLCC)

Query the Red Hat Product Life Cycle API to check support status, EOL dates, and OpenShift compatibility for Red Hat products and layered operators.

## API Overview

- **Base URL**: `https://access.redhat.com/product-life-cycles/api/v1/products`
- **Authentication**: None required — the API is public.
- **Query parameter**: `?name=<substring>` — case-insensitive substring match on product name.
- **Response**: `{ "data": [ { product }, ... ] }` — array of matching products.

## Quick Start

```bash
# Search for a product by name (substring match)
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=logging+for+Red+Hat+OpenShift" \
  | python3 -m json.tool

# List all products with "OpenShift" in the name
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=OpenShift" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for p in data['data']:
    print(p['name'])
"
```

## Response Structure

Each product in `data[]` has:

```json
{
  "name": "logging for Red Hat OpenShift",
  "former_names": ["Red Hat OpenShift Logging"],
  "all_phases": [{"name": "General availability", ...}, ...],
  "versions": [
    {
      "name": "6.5",
      "type": "Full Support",
      "openshift_compatibility": "4.19, 4.20, 4.21",
      "phases": [
        {
          "name": "General availability",
          "end_date": "2026-04-01T00:00:00.000Z",
          "date_format": "date"
        },
        {
          "name": "Full support",
          "end_date": "Release of Logging 6.6 + 1 month",
          "date_format": "string"
        },
        {
          "name": "Maintenance support",
          "end_date": "Release of Logging 6.7",
          "date_format": "string"
        }
      ]
    }
  ]
}
```

### Key fields

| Field | Description |
|---|---|
| `versions[].type` | Current support phase: `"Full Support"`, `"Maintenance Support"`, or `"End of life"` |
| `versions[].openshift_compatibility` | Comma-separated OCP versions this product version supports (e.g., `"4.19, 4.20, 4.21"`) |
| `versions[].phases[]` | Lifecycle phase dates — GA, Full support, Maintenance, EUS, Extended life |
| `former_names` | Previous product names — useful for matching when the current name doesn't hit |

### Phase date formats

Dates come in two formats (check `date_format`):
- `"date"` — ISO 8601 timestamp: `"2027-04-21T00:00:00.000Z"`
- `"string"` — relative/TBD: `"GA of 4.22 + 3 Months"` or `"N/A"`

## Common Queries

### Check support status for a specific product version

```bash
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=logging+for+Red+Hat+OpenShift" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for p in data['data']:
    print(p['name'])
    for v in p['versions']:
        compat = v.get('openshift_compatibility') or 'N/A'
        print(f'  {v[\"name\"]} — {v[\"type\"]} (OCP: {compat})')
"
```

### Check if a product version is compatible with a target OCP version

```bash
TARGET_OCP="4.21"
PRODUCT="logging+for+Red+Hat+OpenShift"

curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=$PRODUCT" \
  | python3 -c "
import sys, json
target = '$TARGET_OCP'
data = json.load(sys.stdin)
for p in data['data']:
    for v in p['versions']:
        compat = v.get('openshift_compatibility') or ''
        versions = [x.strip() for x in compat.split(',') if x.strip()]
        compatible = target in versions
        status = 'COMPATIBLE' if compatible else 'NOT COMPATIBLE'
        print(f'{p[\"name\"]} {v[\"name\"]} ({v[\"type\"]}) — {status} with OCP {target}')
"
```

### Get EOL dates for OCP itself

```bash
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=OpenShift+Container+Platform" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
p = data['data'][0]
for v in p['versions']:
    maint = next((ph for ph in v['phases'] if ph['name'] == 'Maintenance support'), None)
    end = maint['end_date'] if maint else 'N/A'
    print(f'OCP {v[\"name\"]} — {v[\"type\"]} (maintenance ends: {end})')
"
```

### Cross-reference OLM operators with PLCC lifecycle data

PLCC products that are OLM operators have a `package` field that maps directly to the
OLM Subscription's `spec.name`. This is an **exact match key** — more reliable than name
matching. The `is_operator` field confirms the product is OLM-managed.

When the upgrade advisor readiness JSON includes `olm_operator_lifecycle` data:

1. Extract the `package` name from each operator in readiness data
2. Search PLCC using that package name
3. Match by comparing `product.package` == operator's `package`
4. Check if the installed version's `openshift_compatibility` includes the target OCP version
5. Check the `type` field for support status

```bash
# Look up PLCC lifecycle for an OLM operator by its package name
OLM_PACKAGE="cluster-logging"
TARGET_OCP="4.21"

curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=logging" \
  | python3 -c "
import sys, json
pkg = '$OLM_PACKAGE'
target = '$TARGET_OCP'
data = json.load(sys.stdin)
matched = [p for p in data['data'] if p.get('package') == pkg]
if not matched:
    print(f'No PLCC entry with package={pkg}')
else:
    p = matched[0]
    print(f'{p[\"name\"]} (package: {p[\"package\"]})')
    for v in p['versions']:
        compat = v.get('openshift_compatibility') or ''
        versions = [x.strip() for x in compat.split(',') if x.strip()]
        ok = 'YES' if target in versions else 'NO'
        print(f'  {v[\"name\"]} — {v[\"type\"]} — OCP {target} compatible: {ok}')
"
```

If the `?name=` search doesn't return the operator, try searching by `csv_display_name`
from the readiness data as a fallback.

**Not all operators have PLCC entries.** If a search returns no results, that's expected —
it means the product isn't tracked in PLCC. Report this as "lifecycle data unavailable"
rather than an error.

### Batch lookup for multiple OLM operators

When cross-referencing several operators, avoid N+1 API calls. Fetch `?name=OpenShift`
once (~14 products covering most Red Hat layered operators), then make individual calls
only for operators not found in that initial batch.

```bash
TARGET_OCP="4.21"

# Single call covers most Red Hat operator products
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=OpenShift" \
  | python3 -c "
import sys, json
target = '$TARGET_OCP'
data = json.load(sys.stdin)
for p in data['data']:
    if not p.get('is_operator'):
        continue
    pkg = p.get('package') or ''
    for v in p['versions']:
        compat = v.get('openshift_compatibility') or ''
        versions = [x.strip() for x in compat.split(',') if x.strip()]
        ok = 'YES' if target in versions else 'NO'
        print(f'{pkg}: {p[\"name\"]} {v[\"name\"]} ({v[\"type\"]}) — OCP {target}: {ok}')
"
```

## References

Detailed reference material — read on demand:

|references/api-details.md — Full API response schema, all product fields, phase types, search tips

## Important

- **Always use `?name=`** to filter — never fetch the unfiltered `/products` endpoint.
- `openshift_compatibility` is only present on **layered product** versions, not on OCP itself.
- When cross-referencing with OLM data, a missing PLCC entry is normal — report "lifecycle data unavailable" and move on.
