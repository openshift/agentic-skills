# Red Hat Security Data API Reference

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `GET /hydra/rest/securitydata/cve/<CVE-ID>.json` | GET | Full detail for a single CVE |
| `GET /hydra/rest/securitydata/cve.json` | GET | Search/list CVEs with filters |

Base host: `https://access.redhat.com`

No authentication required.

## Search Filter Parameters (`/cve.json`)

| Parameter | Type | Description |
|---|---|---|
| `package` | string | Affects-package filter — substring match against `affected_packages` |
| `advisory` | string | Return CVEs included in the given advisory (e.g. `RHSA-2024:1614`) |
| `severity` | string | One of `low`, `moderate`, `important`, `critical` |
| `after` | date | ISO 8601 — only CVEs with `public_date` on/after |
| `before` | date | ISO 8601 — only CVEs with `public_date` on/before |
| `cwe` | string | CWE ID (e.g. `CWE-168`) |
| `bug` | string | Bugzilla ID |
| `per_page` | int | Page size (default is small; cap to what's actually needed) |
| `page` | int | 1-indexed page number |

Filters combine with AND. The endpoint returns a JSON array — empty `[]` when nothing matches.

## Single-CVE Detail Schema (`/cve/<CVE-ID>.json`)

| Field | Type | Description |
|---|---|---|
| `name` | string | CVE ID (echoes the path component) |
| `threat_severity` | string | `Critical` \| `Important` \| `Moderate` \| `Low` |
| `public_date` | string | ISO 8601 |
| `bugzilla` | object | `{ id, url, description }` |
| `cvss` | object | CVSS v2 (legacy; may be absent). When present: `{ cvss_base_score, cvss_scoring_vector, status }` |
| `cvss3` | object | CVSS v3. When present: `{ cvss3_base_score, cvss3_scoring_vector, status }` |

### `cvss3` sub-fields

| Field | Type | Description |
|---|---|---|
| `cvss3_base_score` | string | CVSS v3 base score as a decimal string (e.g. `"10.0"`) |
| `cvss3_scoring_vector` | string | CVSS v3 vector (e.g. `"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"`) |
| `status` | string | `draft` \| `verified` |

| `cwe` | string | CWE ID, dash-prefixed |
| `details` | string[] | Multi-paragraph narrative description |
| `statement` | string | Red Hat's contextual statement (may be empty) |
| `acknowledgement` | string | Reporter credit |
| `mitigation` | object | `{ value, lang }` when present |
| `package_state` | object[] | Products with no released fix — see below |
| `affected_release` | object[] | Products where a fix has shipped — see below |
| `references` | string[] | External URLs (NVD, CVE.org, blog posts, KBs) |
| `upstream_fix` | string | Upstream version where the issue is fixed |

### `package_state[]` — pre-fix state

Per-product entries that describe how a CVE applies to a product **before** an advisory has shipped a fix.

| Field | Type | Description |
|---|---|---|
| `product_name` | string | Red Hat product name |
| `package_name` | string | Package within the product |
| `cpe` | string | CPE identifier |
| `fix_state` | string | See enumeration below |

`fix_state` values:

| Value | Meaning |
|---|---|
| `Affected` | Product is vulnerable; a fix is planned |
| `Not affected` | Product does not ship the vulnerable code path |
| `Will not fix` | Deliberate decision not to ship a fix (typically older releases) |
| `Out of support scope` | Product version is past its support window |
| `Under investigation` | Red Hat has not finished triage |
| `Fix deferred` | Acknowledged but de-prioritized |

### `affected_release[]` — post-fix state

Per-product entries for releases that **have** shipped a fix.

| Field | Type | Description |
|---|---|---|
| `product_name` | string | Red Hat product name |
| `release_date` | string | ISO 8601 advisory release date |
| `advisory` | string | RHSA / RHBA / RHEA ID (e.g. `RHSA-2024:1718`) |
| `cpe` | string | CPE identifier |
| `package` | string | Fixed package NVR (name-version-release) |

A product appears in **either** `package_state` or `affected_release` for a given CVE, not both.

The same `(product_name, advisory)` pair can appear multiple times in `affected_release` — typically once per architecture or sub-package. Use `unique_by(.advisory)` or `unique_by([.product_name, .advisory])` when listing or counting.

Product names also share base prefixes across support tiers. `"Red Hat Enterprise Linux 9"` (the base product), `"Red Hat Enterprise Linux 9.0 Extended Update Support"`, `"Red Hat Enterprise Linux 9.2 Extended Update Support"`, etc., are distinct entries. Use exact `==` match when targeting the base product only; use `startswith` only when the caller wants the whole family including EUS / AUS / E4S.

## Search List Schema (`/cve.json`)

Compact summary per CVE. Drill into `resource_url` for full data.

| Field | Type | Description |
|---|---|---|
| `CVE` | string | CVE ID |
| `severity` | string | Lowercase — `low` \| `moderate` \| `important` \| `critical` |
| `public_date` | string | ISO 8601 |
| `advisories` | string[] | All RHSAs that include this CVE (may be empty) |
| `bugzilla` | string | Bugzilla ID |
| `bugzilla_description` | string | Short summary |
| `CWE` | string | CWE ID |
| `cvss_score` | string\|null | CVSS v2 base score |
| `cvss_scoring_vector` | string\|null | CVSS v2 vector |
| `cvss3_score` | string\|null | CVSS v3 base score |
| `cvss3_scoring_vector` | string\|null | CVSS v3 vector |
| `affected_packages` | string[] | Fixed-package NVRs across all advisories |
| `package_state` | object[]\|null | Same shape as the single-detail endpoint when present |
| `resource_url` | string | Single-detail endpoint for this CVE |

Note: `severity` is lowercase in search results and capitalized in single-detail responses. The values are the same; the casing differs.

## What this API does **not** expose

These shapes are referenced elsewhere on access.redhat.com but are not available on this public endpoint:

| Wanted | Status | Workaround |
|---|---|---|
| Advisory (RHSA) body / errata text | Not on this API | Construct the public URL `https://access.redhat.com/errata/<RHSA-ID>` and surface it to the user — HTML, not JSON |
| CVRF / CSAF documents | Not on this API at the paths probed | None — surface the advisory URL |
| KB solutions (`/solutions/<id>`) | Authenticated, not part of the security data API | Out of scope for this skill |
| Bugzilla bug detail beyond the ID and summary | Separate Bugzilla API (`bugzilla.redhat.com`) | Outside the scope of this skill |

If a use case requires advisory contents, surface the public URL to the user rather than trying to fetch it via this API.

## Pagination and rate limits

- The endpoint does not return total counts in headers. To know if there are more results, request `per_page + 1` and check whether the extra entry came back.
- No documented public rate limit, but batch where possible — prefer one search call with `per_page=N` over `N` single-detail calls when only summary data is needed.

## Search Tips

1. **Validate first, then fetch.** A 404 from `/cve/<CVE-ID>.json` is the definitive "Red Hat does not track this CVE." Use it before doing any other work with a CVE ID.
2. **Use `?advisory=` to enumerate.** Given an RHSA, listing its CVEs via search is the fastest correlation.
3. **`?package=` is a substring match.** `openssh` matches both `openssh` and `openssh-clients`. Combine with `?severity=` and `?after=` to narrow.
4. **Search returns the lighter shape.** If you need `affected_release` or `package_state` detail, the `resource_url` on each search hit points to the single-detail endpoint.
