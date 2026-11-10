<!-- Loaded on demand by skills/gitops/argo-app-health-triage/SKILL.md when the
     Application health status is Degraded. Read-only. -->

# Degraded

A health check ran and reported failure. Something is wrong now, as opposed to not
finished yet. `Degraded` outranks `Missing` in the rollup, so a `Degraded` Application
may also contain missing resources that the status is hiding — check for both.

`Degraded` with sync status `Synced` means the live state matches git. Drift is not the
cause and syncing again changes nothing. Say that explicitly when you see it; it is the
most common wrong recommendation for this status.

## 1. Find the resource that produced the status

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} {.health.status} {.health.message}{"\n"}{end}' \
  | grep -i degraded
```

The health message is the check's own words. Quote it in the report — it usually names
the cause, and inventing a different one when the message disagrees is a failed
diagnosis.

If several resources are `Degraded`, the owning workload is usually the cause and the
rest are consequences. A Deployment, its ReplicaSet, and its Pods all going `Degraded`
together is one fault, not three.

## 2. Match the message to the check that produced it

### Deployment: `exceeded its progress deadline`

The Deployment's `Progressing` condition reached `ProgressDeadlineExceeded`. This is a
timeout, not a diagnosis — it says the rollout did not finish within
`progressDeadlineSeconds` (default 600). The real cause is in the pods.

```bash
$KCTL get deploy <name> -n <ns> \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{"\n"}{end}'
$KCTL get pods -n <ns> -l <selector> \
  -o jsonpath='{range .items[*]}{.metadata.name} {.status.phase} {range .status.containerStatuses[*]}{.state.waiting.reason}{" "}{.lastState.terminated.reason}{end}{"\n"}{end}'
```

Do not stop at the deadline message. Report what the pods are doing.

### Pod-backed Degraded

A Pod is `Degraded` in exactly these cases:

| Condition | Note |
|---|---|
| A container is waiting with a reason starting `Err`, or ending `Error` or `BackOff` | `CrashLoopBackOff`, `ImagePullBackOff`, `ErrImagePull`, `CreateContainerConfigError`, `InvalidImageName`. **Only when `restartPolicy: Always`.** |
| Pod phase `Failed` | Message is the pod message, else a container's termination message, else `OOMKilled`, else the non-zero exit code |
| Pod phase `Running`, not ready, and some container has a previous termination | A restart loop that has not yet reached backoff |

Two exclusions that change the diagnosis:

- **`Pending` is `Progressing`, not `Degraded`.** An unschedulable pod, one blocked on
  an unbound PVC, or one waiting on quota does not produce `Degraded`. If the status is
  `Degraded`, a pending pod is not the cause.
- **Pods with `restartPolicy: OnFailure` or `Never` never take the waiting-reason
  path.** This is deliberate, so a hook pod with `ImagePullBackOff` does not fail its
  sync prematurely. A Job's pod in `ImagePullBackOff` leaves the Job `Progressing`.

Get the evidence directly:

```bash
$KCTL get pod <pod> -n <ns> \
  -o jsonpath='phase={.status.phase}{"\n"}restartPolicy={.spec.restartPolicy}{"\n"}{range .status.containerStatuses[*]}{.name} ready={.ready} restarts={.restartCount} waiting={.state.waiting.reason} lastTerm={.lastState.terminated.reason}:{.lastState.terminated.exitCode}{"\n"}{end}'
$KCTL logs <pod> -n <ns> --previous --tail=50
$KCTL get events -n <ns> --field-selector involvedObject.name=<pod> \
  --sort-by=.lastTimestamp | tail -20
```

`--previous` is the important one for a crash loop: the current container has not
failed yet, so its log shows nothing useful.

Common causes and the evidence that confirms each:

| Cause | Confirmed by |
|---|---|
| Bad image or tag | `ErrImagePull` / `InvalidImageName`, event text naming the registry |
| Registry auth or rate limit | `ImagePullBackOff` with `401`, `403`, or `toomanyrequests` in the event |
| Application crash on startup | `CrashLoopBackOff`, non-zero exit code, stack trace in `logs --previous` |
| OOM | `lastState.terminated.reason: OOMKilled`; compare to `resources.limits.memory` |
| Missing ConfigMap or Secret | `CreateContainerConfigError`, event naming the object. Note the object being missing does **not** itself make the app `Missing` |
| Failing readiness probe | Running, `ready=false`, no termination; probe failure events |

### Job: `Degraded`

The Job has a `Failed` condition; the message is that condition's message. Inspect the
pods it created, with `--previous` as above. A Job that is merely incomplete is
`Progressing`, not `Degraded`.

### A custom Lua script returned Degraded

If the kind is a CRD, or the message does not look like any built-in check, the status
may come from `resource.customizations.health.<group>_<Kind>` in `argocd-cm`:

```bash
$KCTL get cm argocd-cm -n "$NS" -o yaml | grep -n "resource.customizations" -A 20
```

Then the question is whether the script is right about the resource. Read the CR's own
status and compare. A script asserting `Degraded` on a CR that looks healthy is a bug
in the script, and the remediation is in `argocd-cm`, not in the workload.

## 3. Check what the status is hiding

`Degraded` outranks `Missing`, so re-read the resource list for anything missing or
unhealthy that did not drive the status:

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.name} {.health.status} {.status}{"\n"}{end}' \
  | grep -v Healthy
```

Report those as additional findings. Do not fold them into the one root cause.

## 4. Before suggesting anything

Read the sync policy. With `selfHeal: true`, any manual cluster change is reverted
within seconds, so a `kubectl` fix is not a fix:

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='automated={.spec.syncPolicy.automated}{"\n"}selfHeal={.spec.syncPolicy.automated.selfHeal}{"\n"}prune={.spec.syncPolicy.automated.prune}{"\n"}'
```

If the cause is in the manifests — a bad image tag, a wrong limit, a missing env var —
the correction belongs in git. Say that, and say that a cluster-side edit will be
reverted. Report it as the cause; do not dress it up as a command.
