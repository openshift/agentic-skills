#!/usr/bin/env bash
# Search Red Hat Container Catalog (Pyxis) for candidate images.
# Usage: search-candidates.sh <APP_NAME> [ubi9|ubi8]
# Output: JSON to stdout
# Requires: curl, python3
# Auth: none (public API)
set -euo pipefail

APP="${1:?Usage: search-candidates.sh <APP_NAME> [ubi9|ubi8]}"
UBI_VERSION="${2:-ubi9}"

python3 -c "
import json, sys, subprocess

app = sys.argv[1]
ubi = sys.argv[2]
base_url = 'https://catalog.redhat.com/api/containers/v1/repositories'

# Search the specified UBI version
url = f'{base_url}?page_size=20&sort_by=repository&filter=repository%3E%3D{ubi}/{app};repository%3C%3D{ubi}/{app}z'
result = subprocess.run(['curl', '-sf', url], capture_output=True, text=True)

out = {'app': app, 'ubi_version': ubi, 'source': 'pyxis_catalog'}

if result.returncode != 0:
    out['error'] = 'Catalog search failed'
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
out['total'] = d.get('total', 0)
out['candidates'] = []

for r in d.get('data', []):
    eol = r.get('eol_date', '')
    grade = ''
    grades = r.get('content_stream_grades', [])
    if grades:
        grade = grades[0].get('grade', '')

    out['candidates'].append({
        'repository': r.get('repository', ''),
        'registry': r.get('registry', ''),
        'description': r.get('display_data', {}).get('short_description', ''),
        'eol_date': eol or None,
        'status': 'EOL' if eol else 'Active',
        'content_grade': grade,
        'auto_rebuild': bool(r.get('auto_rebuild_tags')),
    })

print(json.dumps(out, indent=2))
" "$APP" "$UBI_VERSION"
