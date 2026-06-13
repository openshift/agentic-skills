---
name: acs-image-scanner
description: Evaluate ACS-flagged container image CVEs, validate applicability, and recommend the safest upgrade path. Use when ACS flags a container image, when triaging scanner output, or when the user asks about upgrading a vulnerable image.
allowed-tools: Bash(./scripts/*),Bash(skopeo:*)
---

# ACS Image Scanner

## 1. Purpose

Recommend safe container image upgrades for ACS-flagged vulnerabilities.

This agent:
- validates whether a CVE actually affects the image before recommending changes
- chooses only among validated, scanned candidates
- selects the least disruptive fix path
- escalates risky or ambiguous cases instead of guessing

This agent does **not**:
- generate vulnerability data (tools do that)
- verify image signatures (tools do that)
- decide organizational policy (policy.yaml does that)

## 2. Inputs

The agent expects these inputs to begin work:

| Input | Required | Source |
|---|---|---|
| Flagged image reference | Yes | ACS violation / user |
| CVE ID(s) | Yes | ACS violation / user |
| Image digest | Preferred | ACS violation or `inspect-image.sh` |
| ACS scan results | No — agent will invoke `scan-image.sh` | ACS / tool |
| Policy config | Yes | `policy.yaml` loaded by runtime |

## 3. Tool Expectations

Facts **must** come from tools, never from the model's training data.

All scripts live in the `scripts/` directory next to this SKILL.md file. Resolve the
path from this file's location:

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# or, if SKILL_DIR is already set by the runtime, use that directly
```

Invoke each script as `"${SKILL_DIR}/scripts/<name>.sh" <args>`. Every script
outputs structured JSON to stdout and exits 0 even on API errors (error details
are in the JSON `error` field).

| Fact | Invocation | Auth |
|---|---|---|
| CVE severity, fix status, KEV listing | `${SKILL_DIR}/scripts/validate-cve.sh <CVE>` | None (public) |
| VEX applicability | `${SKILL_DIR}/scripts/check-vex.sh <CVE>` | None (public) |
| Vulnerable component + fixed version | `${SKILL_DIR}/scripts/identify-component.sh <IMAGE> <CVE>` | `ACS_CENTRAL_URL`, `ACS_API_TOKEN` |
| Candidate image repositories | `${SKILL_DIR}/scripts/search-candidates.sh <APP> [ubi9\|ubi8]` | None (public) |
| Available tags in a repository | `${SKILL_DIR}/scripts/list-tags.sh <REGISTRY> <REPO>` | None (public) |
| Scan + policy check for a candidate | `${SKILL_DIR}/scripts/scan-image.sh <IMAGE>` | `ACS_CENTRAL_URL`, `ACS_API_TOKEN` |
| Image metadata and digest | `${SKILL_DIR}/scripts/inspect-image.sh <IMAGE>` | None (needs skopeo) |
| Product lifecycle and support phase | `${SKILL_DIR}/scripts/check-lifecycle.sh <PRODUCT> [VERSION]` | None (public) |

Run scripts and use their JSON output as evidence. Do not fabricate CVE details, version numbers, or scan results.

## 4. Decision Policy

### 4.1 Workflow

```
scripts/validate-cve.sh ──┐
                           ├─ GATE: if VEX says "known_not_affected" → decision: no_action
scripts/check-vex.sh ─────┘
                           │
                    ┌──────┴──────┐
                    ▼             ▼
scripts/identify-component.sh   scripts/search-candidates.sh
                    │             │
                    └──────┬──────┘
                           ▼
                  Evaluate upgrade paths (model reasoning)
                           ▼
                  Recommend with evidence (model output)
```

Run `validate-cve.sh` and `check-vex.sh` in parallel. Gate on VEX result. Then run `identify-component.sh` and `search-candidates.sh` in parallel. Evaluation and recommendation are sequential model reasoning.

### 4.2 VEX Gate

| VEX Status | KEV Listed | Decision |
|---|---|---|
| `known_not_affected` | No | `no_action` — report CVE does not apply |
| `known_not_affected` | Yes | `no_action` — but flag KEV status for user awareness |
| `fixed` | Any | Continue to candidate evaluation |
| `known_affected` | No | `monitor` — no fix available yet |
| `known_affected` | Yes | `escalate` — actively exploited, no fix |
| `under_investigation` | Any | `monitor` — check back later |
| No VEX document (404) | Any | Continue — fall back to Security Data API status |

### 4.3 Search Order

Search for fix candidates in this order. Stop at the first viable candidate.

1. **Z-stream tag** — newer tag in the same stream (use `list-tags.sh`, then `scan-image.sh`)
2. **Minor stream** — next supported minor version (use `search-candidates.sh`, then `scan-image.sh`)
3. **UBI equivalent** — Red Hat UBI image replacing upstream (use `search-candidates.sh`)

Use these as starting hints when searching for UBI equivalents:

| Upstream | Search term | Typical UBI repo |
|---|---|---|
| nginx | `nginx` | `ubi9/nginx-124` |
| httpd/apache | `httpd` | `ubi9/httpd-24` |
| python | `python` | `ubi9/python-312` |
| nodejs/node | `nodejs` | `ubi9/nodejs-22` |
| postgresql/postgres | `postgresql` | `ubi9/postgresql-16` |
| mysql/mariadb | `mariadb` | `ubi9/mariadb-1011` |
| redis | `redis` | `ubi9/redis-7` |
| ruby | `ruby` | `ubi9/ruby-33` |
| php | `php` | `ubi9/php-83` |
| golang/go | `go-toolset` | `ubi9/go-toolset` |

### 4.4 Candidate Ranking

Scan every candidate with `scan-image.sh` and `inspect-image.sh`. Then rank:

1. **Target CVE resolved** — disqualify if the flagged CVE is still present
2. **ACS policy check passes** — disqualify if FAIL
3. **Lifecycle phase** — disqualify if EOL; warn if Maintenance-only (check `policy.yaml`)
4. **Registry is approved** — disqualify if not in `policy.yaml` approved list
5. **No new critical/important CVEs introduced** vs. original scan
6. **Fewest fixable CVEs**
7. **Signed image preferred** (if `policy.yaml` requires signatures, disqualify unsigned)
8. **Highest content grade** (A > B > C)
9. **Freshest build** (< 30 days preferred; flag > 90 days)
10. **Same distro family preferred**

### 4.5 Upgrade Path Selection

After ranking candidates, choose the least disruptive path:

| Path | Risk | When |
|---|---|---|
| Z-stream tag update | Low | Newer tag in same stream includes the fix |
| RPM rebuild | Low | Fixed RPM exists, Dockerfile available |
| Minor stream upgrade | Medium | Fix only in newer minor version |
| Image replacement | High | No fix in current ecosystem; UBI equivalent exists |

Always pin the recommendation to a digest, not just a tag.

### 4.6 Dependency Risks to Flag

Before recommending any upgrade, check and report:
- Config file path changes between versions
- Default port changes (e.g., 80 → 8080 on UBI)
- User ID changes (root → non-root)
- Volume mount path differences
- Health check endpoint or port changes
- Whether the deployment is operator-managed (operator may revert changes)
- Image pull access to the recommended registry

## 5. Escalation Rules

Escalate to human review (decision: `escalate`) when:

- No safe candidate found after searching all paths
- Major version jump required (e.g., UBI8 → UBI9)
- Base-image family change (e.g., Debian → RHEL)
- Candidate is unsigned and `policy.yaml` requires signatures
- Candidate introduces new critical or important CVEs
- Tools produce conflicting outputs (e.g., VEX says fixed but ACS scan still shows CVE)
- KEV-listed CVE with no fix available
- Confidence is below threshold set in `policy.yaml`
- Recommended image is from a registry not in `policy.yaml` approved list

## 6. Output Contract

Return a single JSON object with this schema:

```json
{
  "decision": "upgrade | no_action | escalate | monitor",
  "confidence": "high | medium | low",

  "cve": {
    "id": "CVE-2024-XXXXX",
    "severity": "Critical | Important | Moderate | Low",
    "cvss3_score": 8.6,
    "in_kev": false,
    "vex_status": "fixed | known_not_affected | known_affected | under_investigation | unknown"
  },

  "current_image": {
    "reference": "docker.io/library/nginx:1.21",
    "digest": "sha256:...",
    "scan": {
      "total_vulns": 47,
      "critical": 2,
      "important": 8,
      "fixable": 15
    },
    "policy_pass": false,
    "policy_violations": 3
  },

  "recommended_image": {
    "reference": "registry.access.redhat.com/ubi9/nginx-124:1-92",
    "digest": "sha256:...",
    "scan": {
      "total_vulns": 3,
      "critical": 0,
      "important": 0,
      "fixable": 0
    },
    "policy_pass": true,
    "lifecycle_phase": "Full Support",
    "content_grade": "A",
    "build_date": "2024-11-20",
    "signed": true
  },

  "upgrade_path": "z-stream | minor-upgrade | image-replacement | rpm-rebuild",
  "risk_level": "low | medium | high",
  "dependency_risks": [
    "UBI nginx listens on 8080, not 80 — update Service and probes",
    "Runs as non-root — check volume permissions"
  ],

  "rollback": {
    "original_reference": "docker.io/library/nginx:1.21",
    "original_digest": "sha256:...",
    "commands": [
      "oc set image deployment/<name> <container>=docker.io/library/nginx:1.21@sha256:... -n <namespace>",
      "oc rollout status deployment/<name> -n <namespace>"
    ]
  },

  "reasoning": "Short explanation of why this path was chosen over alternatives."
}
```

Fields:
- `decision`: required. The action to take.
- `recommended_image`: required when decision is `upgrade`. Null otherwise.
- `rollback`: required when decision is `upgrade`. Always include original digest.
- `dependency_risks`: required when decision is `upgrade`. Empty array if none found.
- `reasoning`: required. Explain the decision in 2-3 sentences.

## 7. Failure Mode Warnings

The agent must **never**:

- Recommend a tag without a digest
- Recommend an image it has not scanned through ACS
- Recommend an image from an unapproved registry without escalating
- Recommend an EOL image without explicit warning
- Assume `latest` is the safest tag
- Assume a CVE applies without checking VEX
- Assume a CVE is fixed without checking scan results
- Ignore backport semantics (a lower version number may contain the fix)
- Fabricate scan results, CVE details, or version numbers
- Skip evidence-based reasoning — every recommendation must cite tool output
- Silently accept conflicting tool outputs — escalate instead
- Auto-approve upgrades that `policy.yaml` restricts to human review

## References

Background documentation for edge cases and deep context:

| Topic | File |
|---|---|
| CVE validation, VEX parsing, KEV, component ID | [references/cve-intelligence.md](references/cve-intelligence.md) |
| Pyxis search, ACS scan/check, Skopeo, ranking | [references/container-catalog.md](references/container-catalog.md) |
| Upgrade decision tree, dependency safety, rollback | [references/upgrade-paths.md](references/upgrade-paths.md) |
| Product lifecycle, support phases, EOL | [references/product-lifecycle.md](references/product-lifecycle.md) |
