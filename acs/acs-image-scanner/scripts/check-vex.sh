#!/usr/bin/env bash
# Check Red Hat VEX/CSAF applicability for a CVE.
# Usage: check-vex.sh <CVE-ID>
# Output: JSON to stdout
# Requires: curl, python3
# Auth: none (public API)
set -euo pipefail

CVE_ID="${1:?Usage: check-vex.sh <CVE-ID>}"

python3 -c "
import json, sys, subprocess

cve_id = sys.argv[1]
year = cve_id.split('-')[1]
cve_lower = cve_id.lower()
url = f'https://security.access.redhat.com/data/csaf/v2/vex/{year}/{cve_lower}.json'

result = subprocess.run(['curl', '-sf', url], capture_output=True, text=True)

out = {'cve_id': cve_id, 'source': 'redhat_vex_csaf'}

if result.returncode != 0:
    out['available'] = False
    out['note'] = 'No VEX document published. Fall back to Security Data API package_state for status.'
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
out['available'] = True

# Build product ID -> name mapping
products = {}
def walk_branches(branches, prefix=''):
    for b in branches:
        name = prefix + b.get('name', '')
        if 'product' in b:
            products[b['product']['product_id']] = b['product'].get('name', name)
        if 'branches' in b:
            walk_branches(b['branches'], name + ' / ')

tree = d.get('product_tree', {})
walk_branches(tree.get('branches', []))

out['products_by_status'] = {}
for vuln in d.get('vulnerabilities', []):
    status = vuln.get('product_status', {})
    for category in ['known_not_affected', 'fixed', 'known_affected', 'under_investigation']:
        ids = status.get(category, [])
        if ids:
            out['products_by_status'][category] = [
                {'product_id': pid, 'name': products.get(pid, pid)}
                for pid in ids
            ]

    # Include remediations if present
    remediations = vuln.get('remediations', [])
    if remediations:
        out['remediations'] = [
            {
                'category': r.get('category', ''),
                'details': r.get('details', ''),
                'product_ids': r.get('product_ids', []),
            }
            for r in remediations[:10]
        ]

print(json.dumps(out, indent=2))
" "$CVE_ID"
