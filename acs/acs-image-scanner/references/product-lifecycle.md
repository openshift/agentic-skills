# Product Lifecycle

Check whether candidate images and their underlying product streams are still supported before recommending an upgrade.

## Product Lifecycle API

Query Red Hat product lifecycle data. No authentication required.

```bash
PRODUCT="Red Hat Enterprise Linux"
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=$(echo $PRODUCT | sed 's/ /+/g')" | python3 -c "
import json, sys
from datetime import datetime
d = json.load(sys.stdin)
today = datetime.now().strftime('%Y-%m-%d')
for product in d.get('data', []):
    print(f'Product: {product[\"name\"]}')
    for ver in product.get('versions', []):
        name = ver.get('name', '')
        phases = ver.get('phases', [])
        current_phase = 'Unknown'
        for phase in phases:
            start = phase.get('date_start', '')
            end = phase.get('date_end', '')
            if start <= today and (not end or end >= today):
                current_phase = phase.get('name', 'Unknown')
        eol = ''
        for phase in phases:
            if phase.get('name') == 'End of life':
                eol = phase.get('date_start', '')
        print(f'  {name:15s} Phase: {current_phase:25s} EOL: {eol or \"TBD\"}')
"
```

### Common product names for lifecycle queries

| Image base | Product name to query |
|---|---|
| UBI9, RHEL 9 | `Red Hat Enterprise Linux` (version 9.x) |
| UBI8, RHEL 8 | `Red Hat Enterprise Linux` (version 8.x) |
| OpenShift | `Red Hat OpenShift Container Platform` |
| Node.js streams | `Red Hat Software Collections` or check UBI app stream EOL in catalog |
| Python/Ruby/PHP streams | `Red Hat Software Collections` or check UBI app stream EOL in catalog |

## Support Phases

| Phase | Meaning | Recommendation |
|---|---|---|
| **Full Support** | Active development, security fixes, bug fixes, new features | Preferred — recommend freely |
| **Maintenance Support** | Critical and security fixes only, no new features | Acceptable — note in recommendation |
| **Extended Life Support** | Very limited fixes, usually paid add-on | Avoid — warn user; recommend newer stream |
| **End of Life** | No fixes of any kind | Disqualified — never recommend; flag existing usage |

### Determine current phase

Compare today's date against the phase dates:

```bash
# Quick check: is RHEL 9 still in Full Support?
curl -s "https://access.redhat.com/product-life-cycles/api/v1/products?name=Red+Hat+Enterprise+Linux" | python3 -c "
import json, sys
from datetime import datetime
d = json.load(sys.stdin)
today = datetime.now()
for product in d.get('data', []):
    for ver in product.get('versions', []):
        if ver.get('name', '').startswith('9'):
            for phase in ver.get('phases', []):
                start = datetime.strptime(phase['date_start'], '%Y-%m-%d') if phase.get('date_start') else None
                end = datetime.strptime(phase['date_end'], '%Y-%m-%d') if phase.get('date_end') else None
                if start and start <= today and (not end or end >= today):
                    print(f'RHEL {ver[\"name\"]}: currently in {phase[\"name\"]}')
                    if end:
                        days_left = (end - today).days
                        print(f'  Ends: {phase[\"date_end\"]} ({days_left} days remaining)')
"
```

## UBI Stream Mapping

UBI image lifecycles follow their underlying RHEL version:

| UBI base | Follows | Notes |
|---|---|---|
| UBI9 | RHEL 9 lifecycle | Full Support until ~2027, Maintenance until ~2032 |
| UBI8 | RHEL 8 lifecycle | Maintenance Support now, EOL ~2029 |
| UBI7 | RHEL 7 lifecycle | End of Life — never recommend |

### Application stream lifecycles

Application streams within UBI (e.g., `ubi9/nodejs-22`, `ubi9/python-312`) may have **shorter lifecycles** than the base RHEL. These follow the upstream project's release cadence.

Check the Pyxis repository `eol_date` field as a quick indicator:

```bash
REGISTRY="registry.access.redhat.com"
REPO="ubi9/nodejs-22"
curl -s "https://catalog.redhat.com/api/containers/v1/repositories?filter=registry==${REGISTRY};repository==${REPO}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for r in d.get('data', []):
    eol = r.get('eol_date', '')
    print(f'Repository: {r[\"registry\"]}/{r[\"repository\"]}')
    print(f'EOL date:   {eol or \"Not set (active)\"}')
    grades = r.get('content_stream_grades', [])
    if grades:
        print(f'Grade:      {grades[0].get(\"grade\", \"?\")}')
"
```

## Container Catalog Health Indicators

Beyond lifecycle dates, these Pyxis fields indicate image health:

### Content stream grades

| Grade | Meaning |
|---|---|
| **A** | No known vulnerabilities, recently built, well-maintained |
| **B** | Minor issues, generally safe |
| **C** | Moderate issues, review recommended |
| **D** | Significant issues, upgrade recommended |
| **F** | Critical issues, do not use |

### Auto-rebuild tags

If the repository has `auto_rebuild_tags` set, the publisher automatically rebuilds the image when base image security fixes are released. This is a strong positive signal — the image stays patched without manual intervention.

### Build freshness

Check the image's build date via Skopeo or Pyxis `creation_date`:

| Age | Signal |
|---|---|
| < 30 days | Fresh — likely includes recent security fixes |
| 30-90 days | Acceptable — check if any critical advisories were published since |
| > 90 days | Stale — high chance of missing security fixes. Flag as concern. |
| > 180 days | Very stale — recommend finding a newer build or alternative |
