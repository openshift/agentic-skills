---
name: redhat-support
description: Query Red Hat security data — look up CVEs, check which Red Hat products are affected by a vulnerability, and find the advisory (RHSA) that fixes a given CVE. Use when validating a CVE ID, assessing whether a CVE affects a specific Red Hat product or package, or correlating a CVE with the Red Hat advisory that resolves it.
---

# Red Hat Security Data

Query the Red Hat Security Data API to retrieve CVE details, affected-product state, and the advisories (RHSAs) that address each CVE. This is the source of record for validating that a CVE ID exists and for understanding how Red Hat has classified and addressed it.

## API Overview

- **Base URL**: `https://access.redhat.com/hydra/rest/securitydata`
- **Authentication**: None required — the endpoints used here are public.
- **Two shapes**:
  - **Single CVE detail**: `GET /cve/<CVE-ID>.json`
  - **CVE search**: `GET /cve.json` with filter parameters (`package`, `advisory`, `severity`, `after`, `before`, `cwe`, `per_page`)

The single-CVE endpoint returns the full vulnerability record (severity, CVSS, affected products, fix state, references). The search endpoint returns a compact list — use it to enumerate, then drill into individual CVEs with the single-detail endpoint when needed.

## Quick Start

```bash
# Single CVE lookup
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve/CVE-2024-3094.json" | jq .

# Find CVEs affecting a package
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve.json?package=openssh&per_page=10" | jq .

# Find CVEs included in a specific advisory
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve.json?advisory=RHSA-2024:1614&per_page=20" | jq '.[].CVE'
```

## Response Structure

### Single CVE detail (`/cve/<CVE-ID>.json`)

```json
{
  "threat_severity": "Critical",
  "public_date": "2024-03-29T00:00:00Z",
  "bugzilla": { "id": "2272210", "url": "...", "description": "..." },
  "cvss3": {
    "cvss3_base_score": "10.0",
    "cvss3_scoring_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
    "status": "draft"
  },
  "cwe": "CWE-506",
  "details": ["..."],
  "statement": "...",
  "package_state": [
    {
      "product_name": "Red Hat Enterprise Linux 9",
      "package_name": "xz",
      "fix_state": "Not affected",
      "cpe": "cpe:/o:redhat:enterprise_linux:9"
    }
  ],
  "affected_release": [
    {
      "product_name": "Red Hat Enterprise Linux 8",
      "release_date": "2024-04-02T00:00:00Z",
      "advisory": "RHSA-2024:1718",
      "cpe": "cpe:/o:redhat:enterprise_linux:8",
      "package": "openssh-0:8.0p1-19.el8_9"
    }
  ],
  "references": ["..."]
}
```

The key fields for agent reasoning:

- `threat_severity` — Red Hat's classification (`Critical`, `Important`, `Moderate`, `Low`)
- `package_state[]` — per-product status when there is **no released fix yet** (`Affected`, `Not affected`, `Will not fix`, `Under investigation`, `Out of support scope`)
- `affected_release[]` — per-product fix metadata when an advisory **has shipped** (includes the `advisory` ID and the fixed `package` NVR)
- `references[]` — links to NVD, CVE.org, blog posts, and KB articles

A given product appears in either `package_state` *or* `affected_release` for a given CVE — not both. If a product is in `affected_release`, the CVE is fixed there.

### CVE search list (`/cve.json`)

Each entry is a compact summary:

```json
{
  "CVE": "CVE-2026-35414",
  "severity": "moderate",
  "public_date": "2026-04-02T17:08:15Z",
  "advisories": ["RHSA-2026:16059", "RHSA-2026:13383"],
  "bugzilla": "2454490",
  "bugzilla_description": "...",
  "cvss3_score": "4.8",
  "cvss3_scoring_vector": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:L/A:N",
  "CWE": "CWE-168",
  "affected_packages": ["openssh-0:9.9p1-14.el10_1", "..."],
  "resource_url": "https://access.redhat.com/hydra/rest/securitydata/cve/CVE-2026-35414.json"
}
```

`resource_url` is the single-CVE-detail endpoint for that entry — follow it for full data.

For full field descriptions, supported filter parameters, and pagination rules, see `references/security-data-api.md`.

## Common Queries

### Validate that a CVE ID exists and is real

```bash
CVE="CVE-2024-3094"
curl -fsS "https://access.redhat.com/hydra/rest/securitydata/cve/$CVE.json" \
  > /dev/null && echo "valid" || echo "not found"
```

A 404 here means Red Hat has no record of the CVE — treat it as not a real Red Hat-tracked CVE. (NVD may still have it; this endpoint reflects Red Hat's view only.)

### Get severity, CVSS, and one-line description for a CVE

```bash
CVE="CVE-2024-3094"
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve/$CVE.json" \
  | jq -r '
    "Severity: \(.threat_severity)",
    "CVSS3: \(.cvss3.cvss3_base_score) (\(.cvss3.cvss3_scoring_vector))",
    "Bugzilla: \(.bugzilla.description)"'
```

### Check whether a CVE affects a specific Red Hat product

```bash
CVE="CVE-2024-3094"
PRODUCT="Red Hat Enterprise Linux 9"

curl -s "https://access.redhat.com/hydra/rest/securitydata/cve/$CVE.json" \
  | jq -r --arg p "$PRODUCT" '
    (.package_state // []) as $ps |
    (.affected_release // []) as $ar |
    ([$ps[] | select(.product_name == $p)] + [$ar[] | select(.product_name == $p)]) as $hits |
    if ($hits | length) == 0 then "\($p): not listed for this CVE"
    else $hits[] |
      if .advisory then "\($p): fixed in \(.advisory) (\(.package))"
      else "\($p): \(.fix_state) (package: \(.package_name))"
      end
    end'
```

### Find the Red Hat advisory (RHSA) that fixes a CVE for a given product

```bash
CVE="CVE-2024-1086"
PRODUCT="Red Hat Enterprise Linux 9"

# Exact match — RHEL 9 proper only, excludes EUS / E4S / AUS variants
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve/$CVE.json" \
  | jq -r --arg p "$PRODUCT" '
    [(.affected_release // [])[] | select(.product_name == $p)] | unique_by(.advisory)[] |
    "\(.product_name): \(.advisory) (\(.release_date[:10]))"'
```

A single `(product_name, advisory)` pair can appear multiple times in `affected_release` (typically one per architecture or sub-package); `unique_by(.advisory)` collapses these.

To include EUS / Extended Update Support / Advanced Update Support variants too, broaden the filter:

```bash
# Family match — includes RHEL 9 proper AND its EUS/AUS/E4S variants
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve/$CVE.json" \
  | jq -r --arg p "$PRODUCT" '
    [(.affected_release // [])[] | select(.product_name | startswith($p))] | unique_by([.product_name, .advisory])[] |
    "\(.product_name): \(.advisory) (\(.release_date[:10]))"'
```

Be explicit about which one the user wants — `startswith` will match `"Red Hat Enterprise Linux 9.0 Extended Update Support"`, `"...9.2 Extended Update Support"`, etc., not just RHEL 9 proper.

### List recent CVEs affecting a package

```bash
PACKAGE="openssh"
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve.json?package=$PACKAGE&per_page=20" \
  | jq -r '.[] | "\(.CVE) \(.severity) \(.public_date[:10]) — \(.bugzilla_description)"'
```

### List all CVEs included in an advisory

```bash
ADVISORY="RHSA-2024:1614"
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve.json?advisory=$ADVISORY&per_page=100" \
  | jq -r '.[].CVE'
```

### Filter by severity and date

```bash
# Critical CVEs disclosed since the start of 2026, affecting OpenShift
curl -s "https://access.redhat.com/hydra/rest/securitydata/cve.json?severity=critical&after=2026-01-01&package=openshift&per_page=50" \
  | jq -r '.[] | "\(.CVE) \(.public_date[:10]) — \(.bugzilla_description)"'
```

## Cross-reference with other skills

- **`update-advisor`** — Use this skill to validate any CVE IDs `update-advisor` cites in its risk report. Never repeat a CVE ID the agent hasn't checked against `/cve/<CVE-ID>.json`.
- **`product-lifecycle`** — When a CVE's `affected_release` lists a product, use `product-lifecycle` to confirm the product is still in a support phase that receives the advisory.

## Important

- **The `/cve/<CVE-ID>.json` endpoint is the source of truth for whether a CVE is recognized by Red Hat.** If it returns 404, do not assume the CVE applies to any Red Hat product — even if NVD or cve.org has an entry.
- **`package_state` and `affected_release` are mutually exclusive per product per CVE.** A product is in `package_state` when no fix has shipped (whatever the reason), and in `affected_release` once an advisory has shipped a fixed package.
- **`fix_state: "Will not fix"`, `"Out of support scope"`, and `"Affected"` are not all the same.** "Will not fix" is a deliberate decision; "Out of support scope" means the product version is past its support window; "Affected" means a fix is planned but not yet shipped.
- **Use `?per_page=` on search endpoints.** Default page size is small and the result set can be large; cap to what's needed.
- **`/cvrf/`, `/csaf/`, and direct advisory-detail endpoints are not available on this public API.** To get advisory contents, follow the public web URL at `https://access.redhat.com/errata/<RHSA-ID>` — but those pages are HTML, not JSON, and not appropriate to scrape from this skill. If full advisory contents are needed, surface the URL to the user.
- **Do not fabricate CVE IDs, RHSA IDs, or CVSS scores.** Only report values returned by these endpoints.
