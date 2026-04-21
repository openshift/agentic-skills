#!/usr/bin/env bash
# Scan an image via ACS and identify the component containing a specific CVE.
# Usage: identify-component.sh <IMAGE> <CVE-ID>
# Output: JSON to stdout
# Requires: curl, python3, ACS_CENTRAL_URL, ACS_API_TOKEN
set -euo pipefail

IMAGE="${1:?Usage: identify-component.sh <IMAGE> <CVE-ID>}"
CVE_ID="${2:?Usage: identify-component.sh <IMAGE> <CVE-ID>}"

: "${ACS_CENTRAL_URL:?ACS_CENTRAL_URL must be set}"
: "${ACS_API_TOKEN:?ACS_API_TOKEN must be set}"

python3 -c "
import json, sys, subprocess

image = sys.argv[1]
cve_id = sys.argv[2]
acs_url = sys.argv[3]
acs_token = sys.argv[4]

result = subprocess.run([
    'curl', '-sk',
    '-H', f'Authorization: Bearer {acs_token}',
    f'{acs_url}/v1/images/scan',
    '-X', 'POST',
    '-H', 'Content-Type: application/json',
    '-d', json.dumps({'imageName': image}),
], capture_output=True, text=True)

out = {'image': image, 'cve_id': cve_id, 'source': 'acs_scan'}

if result.returncode != 0:
    out['error'] = 'ACS scan failed'
    out['detail'] = result.stderr
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
scan = d.get('scan', {})

# Overall scan summary
comps = scan.get('components', [])
out['scan_summary'] = {
    'total_vulns': sum(len(c.get('vulns', [])) for c in comps),
    'fixable_cves': d.get('fixableCves', 0),
    'critical': sum(1 for c in comps for v in c.get('vulns', []) if 'CRITICAL' in str(v.get('severity', ''))),
    'important': sum(1 for c in comps for v in c.get('vulns', []) if 'IMPORTANT' in str(v.get('severity', ''))),
    'os': scan.get('operatingSystem', ''),
}

# Find the specific CVE
out['vulnerable_components'] = []
for comp in comps:
    for v in comp.get('vulns', []):
        if v.get('cve') == cve_id:
            out['vulnerable_components'].append({
                'name': comp.get('name', ''),
                'version': comp.get('version', ''),
                'source': comp.get('source', ''),
                'layer_index': comp.get('layerIndex'),
                'fixed_by': v.get('fixedBy', ''),
                'severity': v.get('severity', ''),
            })

out['cve_found'] = len(out['vulnerable_components']) > 0

print(json.dumps(out, indent=2))
" "$IMAGE" "$CVE_ID" "$ACS_CENTRAL_URL" "$ACS_API_TOKEN"
