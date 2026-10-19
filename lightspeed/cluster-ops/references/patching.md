# Patching Reference

Detailed reference for `oc patch` / `kubectl patch` operations.

## Patch Types

| Type | Flag | Behavior | Best For |
|------|------|----------|----------|
| Strategic Merge | `--type=strategic` (default) | Merges lists by key field (e.g., container name) | Adding/updating containers, env vars, volumes |
| Merge | `--type=merge` | Replaces entire keys | Simple field updates (replicas, labels) |
| JSON Patch | `--type=json` | Array of operations (add, remove, replace, move, copy, test) | Precise path-based changes, removing fields |

## Strategic Merge Patch

The default for `oc patch`. Merges lists using the list's merge key (usually `name`).

```bash
# Update a specific container's memory limit (merges by container name)
oc patch deployment/frontend --namespace production \
  --type=strategic \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"frontend","resources":{"limits":{"memory":"512Mi"}}}]}}}}'

# Add an environment variable to a specific container
oc patch deployment/frontend --namespace production \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"frontend","env":[{"name":"LOG_LEVEL","value":"debug"}]}]}}}}'

# Add a label to the pod template
oc patch deployment/frontend --namespace production \
  -p '{"spec":{"template":{"metadata":{"labels":{"version":"v2"}}}}}'

# Add a volume and volume mount
oc patch deployment/frontend --namespace production \
  -p '{"spec":{"template":{"spec":{"volumes":[{"name":"config","configMap":{"name":"frontend-config"}}],"containers":[{"name":"frontend","volumeMounts":[{"name":"config","mountPath":"/etc/config"}]}]}}}}'
```

## Merge Patch

Replaces the value at each key. Does NOT merge lists — it replaces them entirely.

```bash
# Update replicas (simple field — merge and strategic are equivalent here)
oc patch deployment/frontend --namespace production \
  --type=merge \
  -p '{"spec":{"replicas":3}}'

# Update annotations
oc patch deployment/frontend --namespace production \
  --type=merge \
  -p '{"metadata":{"annotations":{"lightspeed.openshift.io/remediated":"true"}}}'

# WARNING: this REPLACES all containers, not just the named one
# Use strategic merge for container updates instead
```

## JSON Patch (RFC 6902)

Array of operations for precise mutations.

```bash
# Replace a specific field by path
oc patch deployment/frontend --namespace production \
  --type=json \
  -p '[{"op":"replace","path":"/spec/replicas","value":3}]'

# Replace container resource limits (first container, index 0)
oc patch deployment/frontend --namespace production \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}]'

# Add a field
oc patch deployment/frontend --namespace production \
  --type=json \
  -p '[{"op":"add","path":"/metadata/annotations/lightspeed.openshift.io~1remediated","value":"true"}]'
# Note: "/" in keys must be escaped as "~1", "~" as "~0"

# Remove a field
oc patch deployment/frontend --namespace production \
  --type=json \
  -p '[{"op":"remove","path":"/spec/template/spec/containers/0/resources/limits/cpu"}]'

# Test + replace (atomic: fails if test doesn't match)
oc patch deployment/frontend --namespace production \
  --type=json \
  -p '[{"op":"test","path":"/spec/replicas","value":1},{"op":"replace","path":"/spec/replicas","value":3}]'
```

## Subresource Patches

```bash
# Patch the scale subresource directly
oc patch deployment/frontend --namespace production \
  --subresource=scale \
  --type=merge \
  -p '{"spec":{"replicas":3}}'

# Patch status (requires appropriate RBAC)
oc patch deployment/frontend --namespace production \
  --subresource=status \
  --type=merge \
  -p '{"status":{"conditions":[{"type":"Available","status":"True"}]}}'
```

## Common Patterns

### Update container image
```bash
oc set image deployment/frontend --namespace production \
  frontend=registry.example.com/frontend:v2.1.0
```

### Update resource limits for a container
```bash
oc set resources deployment/frontend --namespace production \
  -c frontend --limits=memory=512Mi,cpu=500m --requests=memory=256Mi,cpu=250m
```

### Add/update annotations
```bash
oc annotate deployment/frontend --namespace production \
  lightspeed.openshift.io/remediated="true" --overwrite
```

### Add/update labels
```bash
oc label deployment/frontend --namespace production \
  version=v2 --overwrite
```
