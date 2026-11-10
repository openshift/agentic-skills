<!-- Loaded on demand by skills/gitops/argo-app-health-triage/SKILL.md when the
     Application health status is Progressing. Read-only. -->

# Progressing

`Progressing` means not healthy yet, but still allowed to become healthy. It is the
normal state during a rollout. The symptom here is that it is *sustained* — it has not
resolved on its own.

The judgment this file exists to support is: **wedged, or still working?** Both look
identical in the Application status. Getting it wrong in either direction is costly —
recommending action on a healthy rollout, or reporting "still progressing" about
something that will never finish.

## The timing trap

A failing Deployment reports `Progressing`, not `Degraded`, until its `Progressing`
condition reaches `ProgressDeadlineExceeded`. `progressDeadlineSeconds` defaults to
**600 seconds**. Any automated trigger with a grace period shorter than ten minutes
sees failing Deployments as `Progressing`.

So for the first ten minutes, a Deployment whose pods are in `CrashLoopBackOff` and a
Deployment that is rolling out normally are the same status. Never infer "it is still
working" from `Progressing`. Look at the pods.

If `progressDeadlineSeconds` is set very high, or the workload is a kind with no
deadline concept, the Application can sit `Progressing` indefinitely and will never
reach `Degraded` on its own.

## 1. Identify the progressing resource and its message

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} {.health.status} {.health.message}{"\n"}{end}' \
  | grep -i progressing
```

The message is diagnostic on its own. Match it before running anything else.

| Message | Meaning |
|---|---|
| `Pending deletion` | The object has a `deletionTimestamp`. Go to section 2 — this is the most common sustained case and has nothing to do with the rollout. |
| `Waiting for rollout to finish: N out of M new replicas have been updated...` | New pods have not been created yet |
| `Waiting for rollout to finish: N old replicas are pending termination...` | Old pods are not going away — look for PDBs, finalizers, long `terminationGracePeriodSeconds` |
| `Waiting for rollout to finish: N of M updated replicas are available...` | Pods exist but are not ready — readiness probes, section 3 |
| `observed deployment generation less than desired generation` | The Deployment controller has not acted on the spec at all. Section 4. |

## 2. Stuck terminating

A resource with a `deletionTimestamp` and no hook finalizer is `Progressing` with
message `Pending deletion`, regardless of anything else. A finalizer that never
completes holds this forever.

```bash
$KCTL get <kind> <name> -n <ns> \
  -o jsonpath='deletionTimestamp={.metadata.deletionTimestamp}{"\n"}finalizers={.metadata.finalizers}{"\n"}'
```

If finalizers are present, the owning controller is not removing them. Identify which
controller owns the finalizer and whether it is running. This is not an Argo CD fault
and re-syncing will not clear it.

A namespace stuck `Terminating` produces the same shape across every resource in it,
and is worth checking once before diagnosing resources individually:

```bash
$KCTL get ns <ns> -o jsonpath='phase={.status.phase}{"\n"}finalizers={.spec.finalizers}{"\n"}'
```

## 3. Pods that will not become ready

`Pending` pods are `Progressing`, not `Degraded` — so unschedulable pods, pods blocked
on an unbound PVC, and pods blocked by quota all land here.

```bash
$KCTL get pods -n <ns> -l <selector> \
  -o jsonpath='{range .items[*]}{.metadata.name} {.status.phase} ready={.status.containerStatuses[*].ready} {range .status.conditions[?(@.type=="PodScheduled")]}{.reason}: {.message}{end}{"\n"}{end}'
$KCTL get events -n <ns> --sort-by=.lastTimestamp | tail -25
```

| What you find | Cause |
|---|---|
| `PodScheduled=False`, reason `Unschedulable` | No node fits — resource requests, taints, node selector, affinity. The event message names which |
| Pending with an unbound PVC | Check the PVC; `WaitForFirstConsumer` with an unschedulable pod is a deadlock both sides of |
| Pending, `exceeded quota` event | ResourceQuota in the namespace |
| Running, `ready=false`, no restarts | Readiness probe failing or still in `initialDelaySeconds` |
| Running, `ready=false`, with restarts | This is a crash loop — it belongs in `references/degraded.md`, and the app status should be `Degraded` unless something worse is masking it |

Also check PodDisruptionBudgets when old replicas are pending termination — a PDB that
cannot be satisfied blocks eviction indefinitely.

## 4. The controller never acted

`observed deployment generation less than desired generation` means the spec was
written but `status.observedGeneration` has not caught up. The workload controller is
not processing it. Causes: a failing mutating admission webhook, a wedged
kube-controller-manager, or an unschedulable controller. Check for webhook errors in
the namespace events and confirm the controller is running before blaming the app.

## 5. Kinds that sit Progressing by design

Not every sustained `Progressing` is a fault. Confirm which of these you have before
recommending anything:

| Kind | Why |
|---|---|
| Job | A Job with no `Complete` or `Failed` condition is `Progressing`. A legitimately long job looks identical to a hung one — check the pod's logs and age, not just the Job |
| Pod with `restartPolicy: OnFailure` or `Never` | Running is `Progressing`, not `Healthy`, because these pods are expected to terminate. Hook pods and Job pods are in this class |
| PVC | Pending is `Progressing`. With `WaitForFirstConsumer` this is correct and resolves when a consumer pod is scheduled |
| Rollout paused at a step | An Argo Rollouts canary awaiting promotion is working as configured. `skills/gitops/argo-cluster-debug` has the Rollout workflow |
| Service of type LoadBalancer | Progressing until an ingress IP is assigned; on a cluster with no load balancer provider this never completes |

For these, the correct output is frequently a diagnosis with **no action required**.
Saying "this Job has been running 14 minutes and is still making progress, no action
needed" is a complete and correct answer.

## 6. Decide and report

State which of these you concluded, and the evidence:

- **Wedged.** Something will not complete without intervention — a finalizer, an
  unschedulable pod, a failed webhook, a PDB. Name it.
- **Failing, inside the deadline.** The pods show a real fault and the Deployment has
  simply not hit `ProgressDeadlineExceeded` yet. Diagnose it as the fault it is; it
  will become `Degraded` on its own, and waiting for that adds nothing.
- **Still working.** Progress is observable — replica counts moving, job log advancing,
  a recent transition. Report no action required and say what you would expect to
  change next.

For the last one, check `.status.health.lastTransitionTime` against now. A status that
has not moved in far longer than the workload's normal rollout time is evidence toward
wedged; one that changed a minute ago is evidence toward working.
