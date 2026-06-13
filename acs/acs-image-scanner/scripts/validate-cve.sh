#!/usr/bin/env bash
# Validate a CVE via Red Hat Security Data API and check CISA KEV.
# Usage: validate-cve.sh <CVE-ID>
# Output: JSON to stdout
# Requires: curl, python3
# Auth: none (public APIs)
set -euo pipefail

CVE_ID="${1:?Usage: validate-cve.sh <CVE-ID>}"

python3 -c "
import json, sys, subprocess, os

cve_id = sys.argv[1]

# Red Hat Security Data API
result = subprocess.run(
    ['curl', '-sf', f'https://access.redhat.com/hydra/rest/securitydata/cve/{cve_id}.json'],
    capture_output=True, text=True
)

out = {'cve_id': cve_id, 'source': 'redhat_security_data'}

if result.returncode != 0:
    out['error'] = 'CVE not found in Red Hat Security Data'
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
out['severity'] = d.get('threat_severity', 'Unknown')
out['cvss3_score'] = d.get('cvss3', {}).get('cvss3_base_score')
out['cvss3_vector'] = d.get('cvss3', {}).get('cvss3_scoring_vector')
out['cwe'] = d.get('cwe')
out['description'] = d.get('bugzilla', {}).get('description', '')

out['fixed_in'] = []
for r in d.get('affected_release', []):
    out['fixed_in'].append({
        'product': r.get('product_name', ''),
        'package': r.get('package', ''),
        'advisory': r.get('advisory', ''),
        'cpe': r.get('cpe', ''),
    })

out['unfixed_in'] = []
for s in d.get('package_state', []):
    out['unfixed_in'].append({
        'product': s.get('product_name', ''),
        'package': s.get('package_name', ''),
        'fix_state': s.get('fix_state', ''),
        'cpe': s.get('cpe', ''),
    })

# CISA KEV check
kev_result = subprocess.run(
    ['curl', '-sfL', 'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'],
    capture_output=True, text=True
)

out['in_kev'] = False
out['kev_detail'] = None
if kev_result.returncode == 0:
    try:
        kev = json.loads(kev_result.stdout)
        matches = [v for v in kev.get('vulnerabilities', []) if v.get('cveID') == cve_id]
        if matches:
            v = matches[0]
            out['in_kev'] = True
            out['kev_detail'] = {
                'vendor': v.get('vendorProject', ''),
                'product': v.get('product', ''),
                'required_action': v.get('requiredAction', ''),
                'due_date': v.get('dueDate', ''),
            }
    except json.JSONDecodeError:
        pass

print(json.dumps(out, indent=2))
" "$CVE_ID"
