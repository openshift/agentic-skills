<!-- Loaded on demand by skills/gitops/argo-app-sync-triage/SKILL.md when
     operationState.phase is Running or Terminating. Read-only. -->

# A sync that will not finish

Phase `Running` with no end in sight. Argo CD is waiting for something, and a sync
operation waits indefinitely by default — there is no overall timeout unless
`spec.syncPolicy.retry` or a `--timeout` was set on a manual sync.

First, confirm it is actually stuck rather than slow.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'phase={.status.operationState.phase}{"\n"}'\
'message={.status.operationState.message}{"\n"}'\
'startedAt={.status.operationState.startedAt}{"\n"}'\
'retryCount={.status.operationState.retryCount}{"\n"}'
date -u +%Y-%m-%dT%H:%M:%SZ
```

A sync with hooks and several waves legitimately takes as long as the slowest workload
in each wave. Under a few minutes with waves in play is not stuck.

## 1. Find the wave or hook it is waiting on

A sync runs in phases — `PreSync`, `Sync`, `PostSync` — and within each phase in wave
order. Argo CD applies a wave, waits for every resource in it to become **healthy**,
then moves on. One resource that never becomes healthy stops the operation there
forever.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.hookPhase} {.status} {.kind}/{.name} {.message}{"\n"}{end}'
```

The resource with an empty or `Running` status, where the ones before it are
`Synced` or `Succeeded`, is the blocker. Then find its wave:

```bash
$KCTL get <kind> <name> -n <ns> \
  -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/sync-wave}{"\n"}'
```

This is the critical point: **the wave gate is health, not existence.** A Deployment
that is applied successfully but whose pods never become ready blocks the wave
indefinitely, and the sync looks stuck while the apply itself worked perfectly. When
the blocker is a workload, the real question is why it is unhealthy —
`skills/gitops/argo-app-health-triage` owns that, and it is usually the faster path.

## 2. Hooks

A `PreSync` hook Job that never completes blocks everything after it, and hook failures
do not show up in Application health at all — hooks are excluded from the health
rollup, so the only evidence is here.

```bash
$KCTL get jobs -n <ns> -o jsonpath='{range .items[*]}{.metadata.name} active={.status.active} succeeded={.status.succeeded} failed={.status.failed}{"\n"}{end}'
$KCTL get pods -n <ns> --sort-by=.metadata.creationTimestamp | tail -20
```

| Shape | Cause |
|---|---|
| Job exists, pod `Pending` | Unschedulable, missing PVC, missing image pull secret. Read the pod events. |
| Job exists, pod running forever | The hook command does not terminate. A migration waiting on a lock is the classic case. |
| Job absent entirely | The hook could not be created. Read `operationState.message` — usually RBAC or a quota. |
| Job from a previous run still present | `hook-delete-policy` is unset, so the old Job was never cleaned up and the new one collides on name. |

A hook Job with a `backoffLimit` that keeps retrying holds the sync for
`backoffLimit × pod runtime`, which can be very long without ever reporting failure.

## 3. Resources that can never become healthy

Some resources never reach `Healthy` by design, and putting one in an early wave wedges
every sync permanently:

- A `Job` that is meant to run forever, or a `CronJob`'s spawned Job.
- A PVC in `Pending` because no volume can be bound — `WaitForFirstConsumer` with no
  consumer in that wave is a self-deadlock.
- A `Service` of type `LoadBalancer` with no controller to assign an address.
- A custom resource whose operator is not installed, so nothing ever updates its
  status.

```bash
$KCTL get pvc -n <ns>
$KCTL get events -n <ns> --sort-by=.lastTimestamp | tail -30
```

The tell is that the resource is applied, unchanged, and quiet — no errors anywhere,
the sync simply never advances.

## 4. Terminating

Phase `Terminating` means a sync was asked to stop. If it persists, the operation is
waiting on a resource it cannot finish with.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{.status.operationState.message}{"\n"}'
```

A sync stuck `Terminating` together with a `deletionTimestamp` on the Application is
the Argo CD finalizer waiting for cascade deletion of children — almost always a child
resource with its own finalizer that nothing will clear:

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='deletionTimestamp={.metadata.deletionTimestamp}{"\n"}finalizers={.metadata.finalizers}{"\n"}'
```

Report the finalizer and which object holds it. Do not strip a finalizer as part of
triage: it orphans live resources and is the kind of action that needs a human who
understands what will be left behind.

## 5. The controller stopped working on it

A sync can also appear stuck because nothing is driving it.

```bash
$KCTL get pods -n "$NS" -l app.kubernetes.io/name="$CR"-application-controller
$KCTL logs -n "$NS" sts/"$CR"-application-controller --tail=200 | grep -i -E "$APP|panic|OOM|leader"
```

If the controller restarted mid-sync, the operation is left in `Running` with a
`startedAt` that predates the restart. Compare the two timestamps — a `startedAt`
earlier than the controller pod's start time is conclusive, and the diagnosis is the
controller, not this Application.

When the controller is OOMKilled or restarting repeatedly, every Application it manages
is affected and per-Application triage is a distraction.
`skills/gitops/argo-performance-tuning` covers controller sizing and sharding.

## 6. Report

Name the exact resource the operation is waiting on, its phase and wave, and why it
cannot progress. "The sync is stuck" is not a diagnosis; "the sync is in `PreSync`
waiting on Job `db-migrate`, whose pod has been `Pending` for 40 minutes with
`FailedScheduling: insufficient memory`" is.

State whether the blocker is the sync machinery or an unhealthy workload. If it is a
workload, say that the sync is behaving correctly and hand off to
`skills/gitops/argo-app-health-triage`.
