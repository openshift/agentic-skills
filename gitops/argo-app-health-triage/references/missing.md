<!-- Loaded on demand by skills/gitops/argo-app-health-triage/SKILL.md when the
     Application health status is Missing. Read-only. -->

# Missing

A resource is in the Application's desired state and has no live object on the cluster.
Argo CD knows what should exist and cannot find it.

## What Missing already tells you

A missing resource only affects Application health when Argo CD can health-assess its
kind — a built-in check, a bundled Lua script, or a user override. A missing resource
of any other kind is skipped and leaves the Application `Healthy`.

Built-in Go checks exist for exactly these:

| Group | Kinds |
|---|---|
| `apps` | Deployment, StatefulSet, ReplicaSet, DaemonSet |
| core | Pod, Service, PersistentVolumeClaim |
| `batch` | Job |
| `autoscaling` | HorizontalPodAutoscaler |
| `networking.k8s.io`, `extensions` | Ingress |
| `apiregistration.k8s.io` | APIService |
| `argoproj.io` | Workflow |

Argo CD also bundles Lua health scripts for a couple of hundred other kinds, including
`route.openshift.io/Route` and many operator CRDs, and those count too.

There is **no** health assessment for ConfigMap, Secret, or ServiceAccount. If one of
those is missing, it is not what made the Application `Missing` — keep looking. It may
still be the cause of a *Degraded* workload that cannot start without it.

`Missing` ranks below `Degraded`. If any resource is degraded, the Application reports
`Degraded` and the missing one is invisible at app level. Seeing `Missing` therefore
means nothing is degraded, which narrows things usefully.

Finally, a child `Application` that is `Missing` is excluded from its parent in an
app-of-apps. A parent reporting `Missing` is missing something other than a child app.

## 1. Which resources are missing

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} health={.health.status} sync={.status}{"\n"}{end}' \
  | grep -i missing
```

Then confirm against the cluster, because "missing" is relative to where Argo CD looked:

```bash
$KCTL get <kind> <name> -n <ns>
```

If the object exists but Argo CD reports it missing, the problem is what Argo CD can
see, not what exists — go to section 5.

## 2. Did a sync ever run, and did it succeed?

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='phase={.status.operationState.phase}{"\n"}message={.status.operationState.message}{"\n"}finishedAt={.status.operationState.finishedAt}{"\n"}revision={.status.sync.revision}{"\n"}'

$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.kind}/{.namespace}/{.name} {.status} {.hookPhase} {.message}{"\n"}{end}'
```

| What you see | Cause |
|---|---|
| No `operationState` at all | The Application has never synced. Check `syncPolicy` — a manual-sync app that nobody synced is `Missing` by design, not by fault |
| `phase: Failed` with `forbidden` or `Unauthorized` in a resource message | RBAC. The Argo CD instance may not be permitted in the destination namespace. Load `skills/gitops/argo-operator` — the operator owns that grant and it must not be hand-written |
| `phase: Failed`, message naming a kind | Often a CRD that is not installed. Section 3 |
| `phase: Error` on a hook | A `PreSync` hook failed and the sync never reached the resources. The hook itself is excluded from health, so it will not show as unhealthy anywhere |
| `phase: Succeeded`, resource still absent | The object was created and then removed. Section 4 |

## 3. Does the kind exist on the cluster?

A manifest for a kind with no CRD cannot be applied.

```bash
$KCTL api-resources | grep -i <kind>
$KCTL get crd | grep -i <group>
```

A sync that fails only for the CRs, while the operator's own resources are fine, is
usually ordering: the CRD and its CRs went in the same sync wave. Confirm with the
sync result messages rather than assuming.

Also confirm the destination namespace exists — resources cannot be created in a
namespace that is absent or terminating:

```bash
$KCTL get ns <dest> -o jsonpath='phase={.status.phase}{"\n"}deletionTimestamp={.metadata.deletionTimestamp}{"\n"}'
```

## 4. Was it created and then removed?

```bash
$KCTL get events -n <ns> --sort-by=.lastTimestamp | grep -i -E "delete|evict|prune" | tail -20
```

Candidates:

- Someone or something deleted it outside Argo CD. With `selfHeal: false` Argo CD
  reports the drift and leaves it missing.
- An owner was deleted and garbage collection removed this object with it.
- A namespace is terminating.
- Another Application manages the same resource and pruned it. Two Applications
  fighting over one object show as alternating sync and missing states; check whether
  another Application lists the same resource:

```bash
$KCTL get applications.argoproj.io -A \
  -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'
```

Note that `prune` only removes what is no longer in git. A resource still in the
desired state is not pruned, so pruning does not explain a resource that Argo CD still
expects.

## 5. Argo CD cannot see it

If the object exists on the cluster but the Application calls it missing, the cause is
visibility rather than existence:

- **Cluster cache is stale.** A hard refresh re-reads live state. Diagnose it by
  comparing the object's `creationTimestamp` to `.status.reconciledAt`.
- **The destination is a different cluster** than you are inspecting. Check
  `.spec.destination.server` before concluding anything from a local lookup.
- **`ignoreDifferences` or a resource exclusion** hides the object from the diff.
  Instance-wide exclusions live in `resource.exclusions` in `argocd-cm`.
- **Namespace mismatch.** The manifest has no namespace and the destination differs
  from where you looked.

## 6. Report

State which of the five it is, with the sync result or event that shows it. The two
most common correct conclusions:

- The sync failed, and the resource is missing *because* of that failure. The root
  cause is the sync error; the missing resource is the symptom. Do not report them as
  two findings.
- The app has never been synced. There is no fault at all. Say that plainly rather
  than constructing a cause.
