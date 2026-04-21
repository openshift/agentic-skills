# PLCC API Reference

## Endpoint

```
GET https://access.redhat.com/product-life-cycles/api/v1/products?name=<substring>
```

No authentication required. The `name` parameter is a case-insensitive substring match.

## Product Object

| Field | Type | Description |
|---|---|---|
| `name` | string | Current product name |
| `former_names` | string[] | Previous product names (useful for search fallback) |
| `is_operator` | bool | Whether this product is an OLM-managed operator |
| `is_layered_product` | bool | Whether this product is layered on OpenShift |
| `is_retired` | bool | Whether the entire product has been retired |
| `package` | string\|null | **OLM package name** — maps to Subscription `spec.name` |
| `versions` | object[] | Per-version lifecycle data |

### The `package` field

The `package` field is the OLM package name and provides an **exact match key** to correlate
PLCC products with OLM Subscriptions. This is more reliable than name matching.

Mapping: `product.package` == `subscription.spec.name`

## Version Object

| Field | Type | Description |
|---|---|---|
| `name` | string | Version number (e.g., `"6.5"`, `"4.21"`) |
| `type` | string | **Current support status**: `"Full Support"`, `"Maintenance Support"`, or `"End of life"` |
| `openshift_compatibility` | string\|null | Comma-separated OCP versions (e.g., `"4.19, 4.20, 4.21"`) — only on layered products |
| `phases` | object[] | Lifecycle phase details with dates |

### Support status (`type`)

| Value | Meaning |
|---|---|
| `"Full Support"` | Active development, bug fixes, security patches |
| `"Maintenance Support"` | Critical/security fixes only, no new features |
| `"End of life"` | No fixes, no support — must upgrade |

## Phase Object

| Field | Type | Description |
|---|---|---|
| `name` | string | Phase name (e.g., `"General availability"`, `"Full support"`, `"Maintenance support"`) |
| `start_date` | string | Phase start — ISO 8601 date or descriptive string |
| `end_date` | string | Phase end — ISO 8601 date or descriptive string |
| `date_format` | string | `"date"` (ISO 8601) or `"string"` (relative/TBD) |

Common phases:
- **General availability** — when the version was released
- **Full support** — active development period
- **Maintenance support** — critical fixes only
- **Extended update support** — EUS add-on terms (1, 2, 3)

## Search Tips

1. **Be specific with `?name=`** — `"logging+for+Red+Hat+OpenShift"` is better than `"logging"`
2. **Try former names** — if `"OpenShift Logging"` returns nothing, the product may have been renamed
3. **Use `is_operator: true`** to filter for OLM operators in results
4. **Use `package` for OLM correlation** — more reliable than name matching
5. **Never omit `?name=`** — the unfiltered response is very large
