#!/usr/bin/env bash
# List available tags for a Red Hat container repository via Pyxis.
# Usage: list-tags.sh <REGISTRY> <REPOSITORY>
# Example: list-tags.sh registry.access.redhat.com ubi9/nginx-124
# Output: JSON to stdout
# Requires: curl, python3
# Auth: none (public API)
set -euo pipefail

REGISTRY="${1:?Usage: list-tags.sh <REGISTRY> <REPOSITORY>}"
REPO="${2:?Usage: list-tags.sh <REGISTRY> <REPOSITORY>}"

python3 -c "
import json, sys, subprocess

registry = sys.argv[1]
repo = sys.argv[2]
url = f'https://catalog.redhat.com/api/containers/v1/repositories/registry/{registry}/repository/{repo}/images?page_size=50'

result = subprocess.run(['curl', '-sf', url], capture_output=True, text=True)

out = {'registry': registry, 'repository': repo, 'source': 'pyxis_images'}

if result.returncode != 0:
    out['error'] = 'Failed to list tags'
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
out['total_builds'] = d.get('total', 0)
out['tags'] = []

seen = set()
for img in d.get('data', []):
    arch = img.get('architecture', '')
    if arch != 'amd64':
        continue
    created = img.get('creation_date', '')[:10]
    digest = img.get('docker_image_digest', '')
    tags = []
    for r in img.get('repositories', []):
        for t in r.get('tags', []):
            name = t.get('name', '')
            if name and name not in tags:
                tags.append(name)
    tag_key = tuple(sorted(tags))
    if tag_key in seen:
        continue
    seen.add(tag_key)
    out['tags'].append({
        'names': tags,
        'created': created,
        'digest': digest[:20] + '...' if len(digest) > 20 else digest,
    })

print(json.dumps(out, indent=2))
" "$REGISTRY" "$REPO"
