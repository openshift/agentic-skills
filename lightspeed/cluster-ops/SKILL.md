---
name: cluster-ops
description: Execute remediation actions on Kubernetes and OpenShift clusters using oc/kubectl. Use when executing approved remediation actions such as patching resources, deleting pods, scaling deployments, or triggering rollout restarts. This skill is for WRITE operations only — use platform-docs and prometheus skills for read-only investigation.
allowed-tools: Bash(oc:*) Bash(kubectl:*)
---

# Cluster Operations — Write Actions

Execute approved remediation actions on Kubernetes and OpenShift clusters using `oc` or `kubectl`.

## Critical Rules

These rules are non-negotiable. Violating them can cause outages.

1. **Only execute actions explicitly listed in the approved actions set.** Never infer, improvise, or expand scope. If the approved action says "scale deployment/frontend to 3 replicas in namespace production", do exactly that — nothing more.

2. **Verify the resource exists before mutating it.** Always `oc get` the resource first. If it doesn't exist, report an error — do not create it.

3. **Log every write operation.** Before executing, print the exact command. After executing, print the result. This creates an audit trail.

4. **Verify after every write.** After patching, scaling, deleting, or restarting, confirm the change took effect using a read command.

5. **Never delete namespaces, CRDs, or cluster-scoped resources** unless the approved action explicitly names them.

6. **Always use `--namespace` explicitly.** Never rely on the default namespace context.

## Patch Resource

Apply a patch to a Kubernetes resource. Supports strategic-merge (default), merge, and JSON patch types.

```bash
# Strategic merge patch (default) — merges with existing spec
oc patch deployment/frontend --namespace production \
  --type=strategic \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"frontend","resources":{"limits":{"memory":"512Mi"}}}]}}}}'

# Merge patch — replaces at the key level
oc patch deployment/frontend --namespace production \
  --type=merge \
  -p '{"spec":{"replicas":3}}'

# JSON patch — precise path-based operations
oc patch deployment/frontend --namespace production \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}]'
```

### Pre-flight check

```bash
# Verify the resource exists and capture current state
oc get deployment/frontend --namespace production -o json | \
  jq '{replicas: .spec.replicas, containers: [.spec.template.spec.containers[] | {name, resources}]}'
```

### Post-patch verification

```bash
# Verify the patch was applied
oc get deployment/frontend --namespace production -o json | \
  jq '{replicas: .spec.replicas, containers: [.spec.template.spec.containers[] | {name, resources}]}'

# Wait for rollout to complete (if pod template changed)
oc rollout status deployment/frontend --namespace production --timeout=120s
```

## Delete Resource

Delete a specific resource by name.

```bash
# Delete a specific pod
oc delete pod/frontend-abc123 --namespace production

# Delete with grace period (seconds)
oc delete pod/frontend-abc123 --namespace production --grace-period=30

# Delete immediately (force — use only when approved)
oc delete pod/frontend-abc123 --namespace production --grace-period=0 --force
```

### Pre-flight check

```bash
# Verify the resource exists
oc get pod/frontend-abc123 --namespace production -o json | \
  jq '{name: .metadata.name, phase: .status.phase, restarts: [.status.containerStatuses[]? | {name, restartCount}]}'
```

### Post-delete verification

```bash
# Confirm deletion
oc get pod/frontend-abc123 --namespace production 2>&1 || echo "Pod deleted successfully"

# If deleting a pod managed by a deployment, verify replacement pod is running
oc get pods --namespace production -l app=frontend -o json | \
  jq '.items[] | {name: .metadata.name, phase: .status.phase, ready: [.status.conditions[]? | select(.type=="Ready") | .status]}'
```

## Scale Resource

Change the replica count of a deployment, statefulset, or replicaset.

```bash
# Scale a deployment
oc scale deployment/frontend --namespace production --replicas=3

# Scale a statefulset
oc scale statefulset/redis --namespace production --replicas=5
```

### Pre-flight check

```bash
# Check current replicas and available replicas
oc get deployment/frontend --namespace production -o json | \
  jq '{replicas: .spec.replicas, ready: .status.readyReplicas, available: .status.availableReplicas}'
```

### Post-scale verification

```bash
# Wait for all replicas to be ready
oc rollout status deployment/frontend --namespace production --timeout=120s

# Verify final state
oc get deployment/frontend --namespace production -o json | \
  jq '{replicas: .spec.replicas, ready: .status.readyReplicas, available: .status.availableReplicas}'
```

## Rollout Restart

Trigger a rolling restart of a deployment, statefulset, or daemonset. This creates new pods with the current spec (useful for picking up ConfigMap/Secret changes or recovering from a bad state).

```bash
# Restart a deployment
oc rollout restart deployment/frontend --namespace production

# Restart a statefulset
oc rollout restart statefulset/redis --namespace production

# Restart a daemonset
oc rollout restart daemonset/fluentd --namespace kube-system
```

### Post-restart verification

```bash
# Wait for rollout to complete
oc rollout status deployment/frontend --namespace production --timeout=300s

# Verify new pods are running (RESTARTS column should show 0 for new pods)
oc get pods --namespace production -l app=frontend \
  -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,READY:.status.conditions[?\(@.type==\"Ready\"\)].status,AGE:.metadata.creationTimestamp
```

## References

Detailed command references — read on demand for specific operations:

|references/patching.md — Patch types, complex patches, subresource patches
|references/scaling.md — HPA interactions, PDB considerations, statefulset ordering
|references/troubleshooting.md — Common failure modes, RBAC errors, stuck rollouts

## Important

- **Every write action must be in the approved actions list.** No exceptions.
- Always use `--namespace` explicitly — never rely on context defaults.
- After every mutation, verify the change took effect before reporting success.
- If a command fails, report the exact error — do not retry automatically unless the approved action says to.
- RBAC errors (`Forbidden`) mean the service account lacks permissions. Report clearly and stop — do not attempt workarounds.
- Rollout timeouts do not necessarily mean failure — check pod status for details.

