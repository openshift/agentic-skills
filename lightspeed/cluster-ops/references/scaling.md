# Scaling Reference

Detailed reference for `oc scale` / `kubectl scale` operations.

## Basic Scaling

```bash
# Scale deployment
oc scale deployment/frontend --namespace production --replicas=3

# Scale statefulset
oc scale statefulset/redis --namespace production --replicas=5

# Scale replicaset (rare — usually scale the deployment instead)
oc scale replicaset/frontend-7d4b8c6f --namespace production --replicas=3
```

## Conditional Scaling

Scale only if the current replica count matches an expected value (optimistic concurrency):

```bash
# Only scale if currently at 1 replica
oc scale deployment/frontend --namespace production \
  --replicas=3 --current-replicas=1
```

This prevents accidental double-scaling if another actor already changed the count.

## HPA Interactions

If a Horizontal Pod Autoscaler (HPA) manages the deployment, manual scaling may be overridden.

### Check for HPA

```bash
# List HPAs in the namespace
oc get hpa --namespace production

# Check if an HPA targets this deployment
oc get hpa --namespace production -o json | \
  jq '.items[] | select(.spec.scaleTargetRef.name=="frontend") | {name: .metadata.name, min: .spec.minReplicas, max: .spec.maxReplicas, current: .status.currentReplicas}'
```

### Scaling with HPA present

- Scaling **above** `maxReplicas` → HPA will scale back down
- Scaling **below** `minReplicas` → HPA will scale back up
- To persistently change scale, update the HPA's `minReplicas`/`maxReplicas`:

```bash
# Update HPA min/max (use patch, not scale)
oc patch hpa/frontend --namespace production \
  --type=merge \
  -p '{"spec":{"minReplicas":3,"maxReplicas":10}}'
```

## PodDisruptionBudget Considerations

PDBs limit how many pods can be unavailable during voluntary disruptions (including scale-down).

```bash
# Check PDBs in the namespace
oc get pdb --namespace production

# Check if a PDB affects the target pods
oc get pdb --namespace production -o json | \
  jq '.items[] | {name: .metadata.name, minAvailable: .spec.minAvailable, maxUnavailable: .spec.maxUnavailable, currentHealthy: .status.currentHealthy, disruptionsAllowed: .status.disruptionsAllowed}'
```

Scaling **up** is never blocked by PDBs. Scaling **down** may be blocked if it would violate the PDB.

## StatefulSet Ordering

StatefulSets scale pods in order:
- **Scale up**: pods are created in order (0, 1, 2, ...)
- **Scale down**: pods are terminated in reverse order (..., 2, 1)

```bash
# Scale up — new pods appear sequentially
oc scale statefulset/redis --namespace production --replicas=5

# Monitor scale-up progress
oc get pods --namespace production -l app=redis --sort-by=.metadata.name \
  -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,READY:.status.conditions[?\(@.type==\"Ready\"\)].status
```

## Verification

```bash
# Check deployment scale status
oc get deployment/frontend --namespace production -o json | \
  jq '{desired: .spec.replicas, ready: .status.readyReplicas, available: .status.availableReplicas, unavailable: .status.unavailableReplicas}'

# Wait for all replicas to be ready
oc rollout status deployment/frontend --namespace production --timeout=120s

# List all pods with their status
oc get pods --namespace production -l app=frontend \
  -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,READY:.status.conditions[?\(@.type==\"Ready\"\)].status,NODE:.spec.nodeName
```
