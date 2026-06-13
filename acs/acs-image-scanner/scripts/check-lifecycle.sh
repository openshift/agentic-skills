#!/usr/bin/env bash
# Check Red Hat product lifecycle status.
# Usage: check-lifecycle.sh <PRODUCT_NAME> [VERSION_PREFIX]
# Example: check-lifecycle.sh "Red Hat Enterprise Linux" 9
# Output: JSON to stdout
# Requires: curl, python3
# Auth: none (public API)
set -euo pipefail

PRODUCT="${1:?Usage: check-lifecycle.sh <PRODUCT_NAME> [VERSION_PREFIX]}"
VERSION_PREFIX="${2:-}"

python3 -c "
import json, sys, subprocess
from datetime import datetime

product = sys.argv[1]
version_prefix = sys.argv[2] if len(sys.argv) > 2 else ''

encoded = product.replace(' ', '+')
url = f'https://access.redhat.com/product-life-cycles/api/v1/products?name={encoded}'
result = subprocess.run(['curl', '-sf', url], capture_output=True, text=True)

out = {'product': product, 'source': 'redhat_lifecycle_api'}

if result.returncode != 0:
    out['error'] = 'Product not found'
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
today = datetime.now()
today_str = today.strftime('%Y-%m-%d')

out['versions'] = []
for prod in d.get('data', []):
    for ver in prod.get('versions', []):
        name = ver.get('name', '')
        if version_prefix and not name.startswith(version_prefix):
            continue
        phases = ver.get('phases', [])
        current_phase = 'Unknown'
        phase_end = None
        for phase in phases:
            start = phase.get('date_start', '')
            end = phase.get('date_end', '')
            if start <= today_str and (not end or end >= today_str):
                current_phase = phase.get('name', 'Unknown')
                phase_end = end
        eol_date = ''
        for phase in phases:
            if phase.get('name') == 'End of life':
                eol_date = phase.get('date_start', '')

        entry = {
            'version': name,
            'current_phase': current_phase,
            'eol_date': eol_date or None,
        }
        if phase_end:
            try:
                days_left = (datetime.strptime(phase_end, '%Y-%m-%d') - today).days
                entry['current_phase_ends'] = phase_end
                entry['days_remaining'] = days_left
            except ValueError:
                pass
        out['versions'].append(entry)

print(json.dumps(out, indent=2))
" "$PRODUCT" "$VERSION_PREFIX"
