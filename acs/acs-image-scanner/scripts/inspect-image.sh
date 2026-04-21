#!/usr/bin/env bash
# Inspect image metadata via Skopeo without pulling.
# Usage: inspect-image.sh <IMAGE>
# Output: JSON to stdout
# Requires: skopeo, python3
set -euo pipefail

IMAGE="${1:?Usage: inspect-image.sh <IMAGE>}"

python3 -c "
import json, sys, subprocess

image = sys.argv[1]
result = subprocess.run(
    ['skopeo', 'inspect', '--override-os', 'linux', '--override-arch', 'amd64',
     f'docker://{image}'],
    capture_output=True, text=True
)

out = {'image': image, 'source': 'skopeo_inspect'}

if result.returncode != 0:
    out['error'] = 'Skopeo inspect failed'
    out['detail'] = result.stderr.strip()
    print(json.dumps(out, indent=2))
    sys.exit(0)

d = json.loads(result.stdout)
labels = d.get('Labels', {})

out['digest'] = d.get('Digest', '')
out['architecture'] = d.get('Architecture', '')
out['created'] = d.get('Created', '')[:10]
out['labels'] = {
    'name': labels.get('name', ''),
    'version': labels.get('version', ''),
    'release': labels.get('release', ''),
    'component': labels.get('com.redhat.component', ''),
    'build_host': labels.get('com.redhat.build-host', ''),
}

print(json.dumps(out, indent=2))
" "$IMAGE"
