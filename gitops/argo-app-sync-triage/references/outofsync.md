<!-- Loaded on demand by skills/gitops/argo-app-sync-triage/SKILL.md when the sync
     status is OutOfSync and no operation is running. Read-only. -->

# OutOfSync

The live state does not match the desired state. Before diagnosing why, establish
which of three very different situations this is — they look identical at app level:

| Situation | Tell | Is it a fault? |
|---|---|---|
| Nobody has synced it | No `automated` policy, and `operationState` is empty or old | No. This is how manual-sync apps work. |
| Auto-sync is configured and declining to run | `automated` is set, no operation running | Yes, usually |
| Sync succeeds and the diff returns | `operationState.phase: Succeeded` with a recent `finishedAt` | Yes, and syncing again will not help |

## 1. Is auto-sync even configured?

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'automated={.spec.syncPolicy.automated}{"\n"}'\
'prune={.spec.syncPolicy.automated.prune}{"\n"}'\
'selfHeal={.spec.syncPolicy.automated.selfHeal}{"\n"}'\
'phase={.status.operationState.phase}{"\n"}'\
'finishedAt={.status.operationState.finishedAt}{"\n"}'
```

If `automated` is empty, the Application is manual-sync and sitting `OutOfSync` is its
normal resting state. Report that and stop. Do not diagnose a fault, and do not
recommend enabling auto-sync — that is a policy decision, frequently deliberate for
production.

If `finishedAt` is within the last few minutes and the status is still `OutOfSync`, go
straight to section 5. The sync is working and something is undoing it.

## 2. What is actually different?

Narrow to the resources before reasoning about causes.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} {.status}{"\n"}{end}' \
  | grep -v Synced
```

Per-resource values and what each means:

| Value | Meaning |
|---|---|
| `OutOfSync` | Desired and live differ, or the resource does not exist live. |
| `PruneSkipped` | Live-only resource that Argo CD declined to delete. Prune is off, or the resource is annotated `Prune=false`. |
| `Unknown` | This resource could not be compared, even though the Application could. |

Read the diff itself if you can. It is the single highest-value piece of evidence and
removes all guesswork about which field differs. This needs the `argocd` CLI and an
authenticated session, neither of which is guaranteed — only `oc` or `kubectl` is:

```bash
command -v argocd >/dev/null 2>&1 && argocd app diff "$APP" --app-namespace "$APP_NS" 2>&1 | head -60
```

When that is unavailable, fall back to the live object and work from the per-resource
status above:

```bash
$KCTL get <kind> <name> -n <ns> -o yaml | head -60
```

Then say in the report that the diff could not be read directly. Every conclusion below
is weaker without it, and a confident cause named from the resource list alone is the
most common way this triage goes wrong.

## 3. Auto-sync is set but nothing runs

The controller logs its reason, and this is the fastest route to the answer:

```bash
$KCTL logs -n "$NS" sts/"$CR"-application-controller --tail=500 \
  | grep -i -E "$APP" | grep -i -E "auto-sync|skipping|sync window|terminated"
```

| Log or condition | Cause |
|---|---|
| `Skipping auto-sync: most recent sync already to <rev>` | Argo CD already attempted this exact revision and the operation failed. It will not retry the same revision automatically. A new commit, a manual sync, or `spec.syncPolicy.retry` is needed. This is the most commonly missed cause. |
| `Skipping auto-sync: sync window` | A deny window is active. Check the AppProject. |
| `Skipping auto-sync: application is deleting` | A `deletionTimestamp` is set. |
| Nothing at all, and the app is never refreshed | The controller is not processing this Application: wrong shard, the app is in a namespace the instance does not watch, or the controller is wedged. |

Sync windows are AppProject-level and easy to forget, because nothing on the
Application says a window exists:

```bash
PROJ=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.project}')
$KCTL get appproject "$PROJ" -n "$NS" -o jsonpath='{.spec.syncWindows}{"\n"}'
```

A `deny` window matching this Application blocks auto-sync for its duration. A window
with `manualSync: false` also blocks a human sync. This is normal configured behavior,
not a fault — report it as "working as configured" and name the window.

If the controller logs nothing about the Application at all, confirm it is being
watched. On an operator-managed instance an Application in a tenant namespace is
ignored entirely unless the namespace is in `sourceNamespaces` — see
`skills/gitops/argo-operator`.

## 4. The revision is not what you think

A change pushed to git that never appears is often a revision mismatch rather than a
sync problem.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'target={.spec.source.targetRevision}{"\n"}'\
'synced={.status.sync.revision}{"\n"}'\
'observedAt={.status.reconciledAt}{"\n"}'
```

- `targetRevision` pinned to a tag or SHA does exactly what it says. A moved tag is not
  re-resolved until the cache expires.
- `reconciledAt` far in the past means no refresh has happened. Default polling is
  `timeout.reconciliation`, 180s. If a webhook was expected to trigger it, the webhook
  is the thing to check.
- The repo-server caches manifests. A push that is genuinely in the repo but not
  visible to Argo CD appears as a stale `status.sync.revision` while the branch head
  has moved.

## 5. Sync succeeds and the diff comes straight back

The hardest shape, and the one where repeated syncing wastes the most time. The sync
reports success, the comparison immediately finds a difference again, and the
Application flaps between `Synced` and `OutOfSync`. Something other than Argo CD is
writing the field.

Four causes, in rough order of frequency:

**A mutating admission webhook or another controller writes the field.** Anything that
injects a sidecar, a label, a default resource limit, or a CA bundle. Argo CD applies
the manifest, the webhook rewrites it, the next comparison sees the rewrite.

```bash
$KCTL get mutatingwebhookconfigurations -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
```

The fix is `ignoreDifferences` for the specific path, never a sync loop. On an
operator-managed instance that is `.spec.resourceIgnoreDifferences` on the `ArgoCD` CR,
because an `argocd-cm` edit will be reverted.

**A server-side-apply field ownership conflict.** With `ServerSideApply=true`, another
field manager owning a field Argo CD also sets produces a conflict that leaves the
field unchanged. Check who owns it:

```bash
$KCTL get <kind> <name> -n <ns> -o jsonpath='{range .metadata.managedFields[*]}{.manager} {.operation}{"\n"}{end}'
```

**`ignoreDifferences` is honored by the diff but not by the sync.** The resource stops
showing as `OutOfSync` in the UI but sync still overwrites the field, so the other
controller rewrites it. `RespectIgnoreDifferences=true` in `syncOptions` is what makes
sync honor them too. Its absence is the classic cause of a flapping Application that
looks correctly configured.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'syncOptions={.spec.syncPolicy.syncOptions}{"\n"}'\
'ignoreDifferences={.spec.ignoreDifferences}{"\n"}'
```

**A generated field.** A manifest containing a timestamp, a random suffix, or a
`helm.sh/hook` object that changes every render is `OutOfSync` by construction. Every
comparison produces a genuine difference and no sync can converge.

## 6. Prune and PruneSkipped

`PruneSkipped` is not a failure. It means a resource exists live, is no longer in git,
and Argo CD was told not to delete it:

- `spec.syncPolicy.automated.prune` is `false`, the default. Auto-sync never deletes
  unless this is explicitly enabled.
- The resource is annotated `argocd.argoproj.io/sync-options: Prune=false`.
- The resource is annotated `argocd.argoproj.io/compare-options: IgnoreExtraneous`,
  which excludes it from the diff entirely.

Report which of the three applies. Recommending `prune: true` is a destructive change
with a blast radius beyond this Application — state that it deletes every live resource
no longer in git, and leave the decision to a human.

## 7. Report

Name which section produced the answer, and state plainly whether the `OutOfSync` is a
fault at all. A manual-sync Application, a closed sync window, and a deliberately
unpruned resource are all expected states, and reporting them as problems trains people
to ignore the diagnosis.

If the cause is section 5, say so explicitly and say that syncing again will not resolve
it. That one sentence is usually the most useful output of the whole triage.
