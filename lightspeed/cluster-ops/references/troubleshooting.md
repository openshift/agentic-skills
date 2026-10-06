# Troubleshooting Reference

Common failure modes when executing cluster operations and how to diagnose them.

## RBAC Errors

### Symptom

```
Error from server (Forbidden): deployments.apps "frontend" is forbidden:
User "system:serviceaccount:openshift-lightspeed:lightspeed-exec-abc123" cannot patch resource "deployments" in API group "apps" in the namespace "production"
```

### Diagnosis

```bash
# Check what the SA can do
oc auth can-i --list --as=system:serviceaccount:openshift-lightspeed:lightspeed-exec-abc123 \
  --namespace production

# Check specific permission
oc auth can-i patch deployments.apps --namespace production \
  --as=system:serviceaccount:openshift-lightspeed:lightspeed-exec-abc123

# List roles/rolebindings for the SA
oc get rolebindings --namespace production -o json | \
  jq '.items[] | select(.subjects[]?.name=="lightspeed-exec-abc123") | {name: .metadata.name, role: .roleRef.name}'
```

### Resolution

Report the RBAC error clearly. Do NOT attempt workarounds. The operator creates dynamic RBAC — if permissions are missing, the operator needs to fix the role.

## Stuck Rollouts

### Symptom

`oc rollout status` hangs or reports `Waiting for deployment "frontend" rollout to finish`.

### Diagnosis

```bash
# Check rollout conditions
oc get deployment/frontend --namespace production -o json | \
  jq '.status.conditions[] | {type, status, reason, message}'

# Check for failed pods
oc get pods --namespace production -l app=frontend -o json | \
  jq '.items[] | select(.status.phase != "Running") | {name: .metadata.name, phase: .status.phase, reason: .status.containerStatuses[]?.state | to_entries[] | {state: .key, reason: .value.reason, message: .value.message}}'

# Check events for the deployment
oc get events --namespace production --sort-by=.lastTimestamp \
  --field-selector involvedObject.name=frontend | tail -20

# Check ReplicaSet status
oc get rs --namespace production -l app=frontend -o json | \
  jq '.items[] | {name: .metadata.name, desired: .spec.replicas, ready: .status.readyReplicas, available: .status.availableReplicas}'
```

### Common causes

- **ImagePullBackOff** — wrong image tag or registry auth
- **CrashLoopBackOff** — application crashes on startup
- **Insufficient resources** — no node has enough CPU/memory
- **PDB violation** — PodDisruptionBudget prevents old pods from terminating

## Resource Not Found

### Symptom

```
Error from server (NotFound): deployments.apps "frontend" not found
```

### Diagnosis

```bash
# Check if the resource exists with a different name
oc get deployments --namespace production

# Check if the namespace exists
oc get namespace production

# Check if it's a different resource kind
oc get all --namespace production | grep frontend
```

### Resolution

Report the exact error. The approved action references a resource that doesn't exist — this is either a stale proposal or a typo in the approved action.

## Conflict Errors

### Symptom

```
Error from server (Conflict): Operation cannot be fulfilled on deployments.apps "frontend":
the object has been modified; please apply your changes to the latest version
```

### Diagnosis

Another actor modified the resource between the read and the write. This is rare but can happen in active clusters.

```bash
# Get the current state
oc get deployment/frontend --namespace production -o json | jq '.metadata.resourceVersion'
```

### Resolution

Retry the patch once. If it fails again, report the conflict — do not loop.

## Pod Eviction / Preemption

### Symptom

Pods are terminated unexpectedly after scaling or patching.

### Diagnosis

```bash
# Check for eviction events
oc get events --namespace production --sort-by=.lastTimestamp \
  --field-selector reason=Evicted

# Check node conditions
oc get nodes -o json | \
  jq '.items[] | {name: .metadata.name, conditions: [.status.conditions[] | select(.status=="True") | .type]}'

# Check resource pressure
oc describe node <node-name> | grep -A5 "Allocated resources"
```

## Timeout Handling

If `oc rollout status --timeout=Ns` exits with a timeout:

1. The rollout is NOT necessarily failed — it's just slow
2. Check pod status to determine if progress is being made
3. Report the timeout with current pod status — let the operator decide next steps

```bash
# After a timeout, gather diagnostic info
oc get deployment/frontend --namespace production -o json | \
  jq '{replicas: .spec.replicas, ready: .status.readyReplicas, updated: .status.updatedReplicas, conditions: [.status.conditions[] | {type, status, reason}]}'
```
