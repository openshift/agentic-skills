#!/usr/bin/env bash
# Scan an image via ACS Central and run policy check.
# Usage: scan-image.sh <IMAGE>
# Output: JSON to stdout (scan summary + policy result)
# Requires: curl, python3, ACS_CENTRAL_URL, ACS_API_TOKEN
set -euo pipefail

IMAGE="${1:?Usage: scan-image.sh <IMAGE>}"

: "${ACS_CENTRAL_URL:?ACS_CENTRAL_URL must be set}"
: "${ACS_API_TOKEN:?ACS_API_TOKEN must be set}"

python3 -c "
import json, sys, subprocess

image = sys.argv[1]
acs_url = sys.argv[2]
acs_token = sys.argv[3]

out = {'image': image, 'source': 'acs_scan_and_check'}

# Scan
scan_result = subprocess.run([
    'curl', '-sk',
    '-H', f'Authorization: Bearer {acs_token}',
    f'{acs_url}/v1/images/scan',
    '-X', 'POST', '-H', 'Content-Type: application/json',
    '-d', json.dumps({'imageName': image}),
], capture_output=True, text=True)

if scan_result.returncode != 0:
    out['error'] = 'ACS scan failed'
    out['detail'] = scan_result.stderr
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(scan_result.stdout)
scan = d.get('scan', {})
comps = scan.get('components', [])

out['scan'] = {
    'total_vulns': sum(len(c.get('vulns', [])) for c in comps),
    'fixable_cves': d.get('fixableCves', 0),
    'critical': sum(1 for c in comps for v in c.get('vulns', []) if 'CRITICAL' in str(v.get('severity', ''))),
    'important': sum(1 for c in comps for v in c.get('vulns', []) if 'IMPORTANT' in str(v.get('severity', ''))),
    'moderate': sum(1 for c in comps for v in c.get('vulns', []) if 'MODERATE' in str(v.get('severity', ''))),
    'low': sum(1 for c in comps for v in c.get('vulns', []) if 'LOW' in str(v.get('severity', ''))),
    'os': scan.get('operatingSystem', ''),
    'total_components': len(comps),
}

# Policy check
check_result = subprocess.run([
    'curl', '-sk',
    '-H', f'Authorization: Bearer {acs_token}',
    f'{acs_url}/v1/images/check',
    '-X', 'POST', '-H', 'Content-Type: application/json',
    '-d', json.dumps({'imageName': image}),
], capture_output=True, text=True)

if check_result.returncode == 0:
    cd = json.loads(check_result.stdout)
    alerts = cd.get('alerts', [])
    out['policy'] = {
        'pass': len(alerts) == 0,
        'violation_count': len(alerts),
        'violations': [
            {
                'name': a.get('policy', {}).get('name', ''),
                'severity': a.get('policy', {}).get('severity', ''),
            }
            for a in alerts
        ],
    }
else:
    out['policy'] = {'error': 'Policy check failed'}

print(json.dumps(out, indent=2))
" "$IMAGE" "$ACS_CENTRAL_URL" "$ACS_API_TOKEN"
