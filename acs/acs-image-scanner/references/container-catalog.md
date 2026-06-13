# Container Catalog

Search Red Hat Container Catalog (Pyxis) for candidate images, inspect with Skopeo, and scan/policy-check via ACS.

## Pyxis Repository Search

The Pyxis API at `catalog.redhat.com` is public (no auth needed). Use a range query on the `repository` field to find images matching the application name.

### Search UBI9 repositories

```bash
APP="nginx"
curl -s "https://catalog.redhat.com/api/containers/v1/repositories?page_size=10&sort_by=repository&filter=repository%3E%3Dubi9/${APP};repository%3C%3Dubi9/${APP}z" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for r in d.get('data', []):
    repo = r.get('repository', '')
    reg = r.get('registry', '')
    eol = r.get('eol_date', '')
    grade = ''
    grades = r.get('content_stream_grades', [])
    if grades:
        grade = grades[0].get('grade', '')
    desc = r.get('display_data', {}).get('short_description', '')[:80]
    auto = 'auto-rebuild' if r.get('auto_rebuild_tags') else 'manual'
    status = 'EOL' if eol else 'Active'
    print(f'{reg}/{repo} [{status}] [Grade: {grade}] [{auto}] — {desc}')
"
```

### Search UBI8 (fallback)

```bash
curl -s "https://catalog.redhat.com/api/containers/v1/repositories?page_size=10&sort_by=repository&filter=repository%3E%3Dubi8/${APP};repository%3C%3Dubi8/${APP}z"
```

### List available tags for a repository

Query the `/images` sub-resource to get all image builds with their tags:

```bash
REGISTRY="registry.access.redhat.com"
REPO="ubi9/nginx-124"
curl -s "https://catalog.redhat.com/api/containers/v1/repositories/registry/${REGISTRY}/repository/${REPO}/images?page_size=20" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Total builds: {d.get(\"total\", 0)}')
seen = set()
for img in d.get('data', []):
    created = img.get('creation_date', '')[:10]
    arch = img.get('architecture', '')
    if arch != 'amd64':
        continue
    tags = []
    for repo in img.get('repositories', []):
        for t in repo.get('tags', []):
            tags.append(t.get('name', ''))
    tag_str = ', '.join(tags[:5])
    if tag_str not in seen:
        seen.add(tag_str)
        print(f'  {created}  tags=[{tag_str}]')
"
```

This is critical for finding newer tags in the same stream (Z-stream fix path).

## Pyxis Image Details

### Get image by repository and tag

```bash
REGISTRY="registry.access.redhat.com"
REPO="ubi9/nginx-124"
TAG="latest"
curl -s "https://catalog.redhat.com/api/containers/v1/repositories/registry/${REGISTRY}/repository/${REPO}/images?filter=repositories.tags.name==${TAG}&page_size=1" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for img in d.get('data', []):
    print(f'Image ID:    {img.get(\"_id\")}')
    print(f'Digest:      {img.get(\"docker_image_digest\", \"\")[:40]}...')
    print(f'Architecture: {img.get(\"architecture\")}')
    print(f'Build date:  {img.get(\"creation_date\", \"\")[:10]}')
    # Extract parsed data
    pd = img.get('parsed_data', {})
    print(f'OS:          {pd.get(\"os\", \"?\")}')
    print(f'Size:        {pd.get(\"size\", 0) // 1024 // 1024} MB')
"
```

### Get RPM manifest for an image

Use the image ID from the previous query:

```bash
IMAGE_ID="<image-id-from-above>"
curl -s "https://catalog.redhat.com/api/containers/v1/images/id/${IMAGE_ID}/rpm-manifest" | python3 -c "
import json, sys
d = json.load(sys.stdin)
rpms = d.get('rpms', [])
print(f'Total RPMs: {len(rpms)}')
for rpm in sorted(rpms, key=lambda r: r.get('name','')):
    print(f'  {rpm.get(\"nvra\", \"\")}')
"
```

### Get vulnerability data from catalog

```bash
curl -s "https://catalog.redhat.com/api/containers/v1/images/id/${IMAGE_ID}/vulnerabilities" | python3 -c "
import json, sys
d = json.load(sys.stdin)
vulns = d.get('data', [])
by_sev = {}
for v in vulns:
    sev = v.get('severity', 'unknown')
    by_sev.setdefault(sev, []).append(v)
for sev in ['Critical', 'Important', 'Moderate', 'Low']:
    items = by_sev.get(sev, [])
    if items:
        print(f'{sev}: {len(items)}')
        for v in items[:5]:
            print(f'  {v.get(\"cve_id\")} — {v.get(\"package\", \"?\")} — fix: {v.get(\"fixed_in\", \"none\")}')
"
```

## Skopeo Inspect

Inspect image metadata without pulling the image. Useful for checking labels, architecture, and comparing digests.

```bash
skopeo inspect docker://registry.access.redhat.com/ubi9/nginx-124:latest | python3 -c "
import json, sys
d = json.load(sys.stdin)
labels = d.get('Labels', {})
print(f'Name:       {labels.get(\"name\", \"?\")}')
print(f'Version:    {labels.get(\"version\", \"?\")}')
print(f'Release:    {labels.get(\"release\", \"?\")}')
print(f'Component:  {labels.get(\"com.redhat.component\", \"?\")}')
print(f'Build host: {labels.get(\"com.redhat.build-host\", \"?\")}')
print(f'Arch:       {d.get(\"Architecture\", \"?\")}')
print(f'Digest:     {d.get(\"Digest\", \"?\")}')
print(f'Created:    {d.get(\"Created\", \"?\")[:10]}')
"
```

### Compare two tags by digest

```bash
DIGEST_OLD=$(skopeo inspect docker://registry.access.redhat.com/ubi9/nginx-124:1-88 | python3 -c "import json,sys;print(json.load(sys.stdin).get('Digest',''))")
DIGEST_NEW=$(skopeo inspect docker://registry.access.redhat.com/ubi9/nginx-124:latest | python3 -c "import json,sys;print(json.load(sys.stdin).get('Digest',''))")
if [ "$DIGEST_OLD" = "$DIGEST_NEW" ]; then
    echo "Same build — no new content"
else
    echo "Different builds — newer content available"
fi
```

## ACS Image Scan

Scan a candidate image through ACS Central to get full vulnerability data.

```bash
curl -sk -H "Authorization: Bearer $ACS_API_TOKEN" \
  "$ACS_CENTRAL_URL/v1/images/scan" \
  -X POST -H "Content-Type: application/json" \
  -d "{\"imageName\": \"registry.access.redhat.com/ubi9/nginx-124:latest\"}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
s = d.get('scan', {})
comps = s.get('components', [])
total = sum(len(c.get('vulns', [])) for c in comps)
fixable = d.get('fixableCves', 0)
crit = sum(1 for c in comps for v in c.get('vulns', []) if 'CRITICAL' in str(v.get('severity', '')))
imp = sum(1 for c in comps for v in c.get('vulns', []) if 'IMPORTANT' in str(v.get('severity', '')))
print(f'Vulns: {total}, Critical: {crit}, Important: {imp}, Fixable: {fixable}, OS: {s.get(\"operatingSystem\", \"?\")}')
"
```

### Per-component vulnerability breakdown

```bash
# Enhanced parsing: list components with vulnerabilities
echo "$SCAN_RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for comp in d.get('scan', {}).get('components', []):
    vulns = comp.get('vulns', [])
    if vulns:
        fixable = sum(1 for v in vulns if v.get('fixedBy'))
        print(f'{comp[\"name\"]}:{comp.get(\"version\",\"?\")} — {len(vulns)} vulns ({fixable} fixable)')
        for v in vulns:
            fixed = v.get('fixedBy', 'no fix')
            print(f'  {v.get(\"cve\",\"?\")} [{v.get(\"severity\",\"?\")}] fix: {fixed}')
"
```

## ACS Policy Check

Verify a candidate image passes all ACS policies before recommending it.

```bash
curl -sk -H "Authorization: Bearer $ACS_API_TOKEN" \
  "$ACS_CENTRAL_URL/v1/images/check" \
  -X POST -H "Content-Type: application/json" \
  -d "{\"imageName\": \"registry.access.redhat.com/ubi9/nginx-124:latest\"}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
alerts = d.get('alerts', [])
if not alerts:
    print('PASS — no policy violations')
else:
    print(f'FAIL — {len(alerts)} policy violations:')
    for a in alerts:
        print(f'  - {a.get(\"policy\", {}).get(\"name\")} ({a.get(\"policy\", {}).get(\"severity\")})')
"
```

## Candidate Ranking Criteria

Rank candidate images using these criteria in priority order:

| Priority | Criterion | Best | Worst | Disqualifying? |
|---|---|---|---|---|
| 1 | Same stream as original | Yes (Z-stream fix) | No (different image) | No |
| 2 | Target CVE fixed | Yes | No | Yes — skip if target CVE still present |
| 3 | Fixable CVEs | 0 | Many | No |
| 4 | Critical/Important CVEs | 0 | Any | No |
| 5 | Policy check | PASS | FAIL | Yes — skip if FAIL |
| 6 | Product lifecycle | Full Support | EOL | Yes — skip if EOL |
| 7 | Content grade | A | C or lower | No |
| 8 | Build freshness | < 30 days | > 90 days | No |

## Image Comparison Template

Present the comparison between the original and recommended image:

```markdown
| | Original | Recommended |
|---|---|---|
| Image | `docker.io/library/nginx:1.21` | `registry.access.redhat.com/ubi9/nginx-124:latest` |
| Digest | `sha256:abc123...` | `sha256:def456...` |
| Total CVEs | 47 | 3 |
| Critical | 2 | 0 |
| Important | 8 | 0 |
| Fixable | 15 | 0 |
| Policy check | FAIL (3 violations) | PASS |
| Lifecycle | N/A (upstream) | Full Support |
| Content grade | N/A | A |
| Build date | 2023-06-15 | 2024-11-20 |
```
