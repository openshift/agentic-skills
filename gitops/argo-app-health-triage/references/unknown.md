<!-- Loaded on demand by skills/gitops/argo-app-health-triage/SKILL.md when the
     Application health status is Unknown. Read-only. -->

# Unknown

Health could not be computed. This is almost always a broken **health check**, not a
broken workload — and it is the single most misdiagnosed Argo CD status, because the
natural reading ("something is wrong with my app") is usually false.

## Why this status is special

`Unknown` is the **worst** status in the rollup order:

`Healthy` → `Suspended` → `Progressing` → `Missing` → `Degraded` → `Unknown`

So one resource whose health check errors makes the entire Application `Unknown` and
masks every other problem in it. An Application can be `Unknown` while a Deployment
inside it is in `CrashLoopBackOff`; the crash loop is invisible at app level.

Two implications for triage:

1. Find the resource that is `Unknown` and fix the assessment first. Until then you
   cannot trust the app-level status for anything else.
2. Always re-read the full resource list afterwards. There is frequently a real fault
   hiding behind the `Unknown`.

A child `Application` that is `Unknown` is excluded from its parent in an app-of-apps,
so a parent reporting `Unknown` has its own unknown resource.

## 1. Find the resource and read its message

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.namespace}/{.name} {.health.status} {.health.message}{"\n"}{end}' \
  | grep -i unknown
```

**The health message carries the error text.** When a custom Lua script fails, Argo CD
sets the status to `Unknown` and puts the script's error in the message — a Lua
runtime error, a nil index, a type error. That message is the diagnosis; quote it.

If the Application itself is `Unknown` but no individual resource is, read the
app-level message:

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{.status.health.status}: {.status.health.message}{"\n"}'
```

A message of the form `see application-controller logs for N other errors; most recent
error was: ...` means several resources failed assessment at once. That pattern points
at the controller or a shared override, not at one workload.

## 2. Custom health script errors

The most common cause. Check whether an override exists for the kind:

```bash
$KCTL get cm argocd-cm -n "$NS" -o yaml | grep -n "resource.customizations" -A 20
```

The key is `resource.customizations.health.<group>_<Kind>`. For a core-group kind the
group is empty, giving a leading underscore.

A script errors rather than returning a verdict when it indexes a field that does not
exist on this particular CR — a status subresource that has not been populated yet, a
conditions array that is absent on a freshly created object, or an API version change
that moved a field. The giveaway is that the same kind is healthy elsewhere and only
the new or just-created instances are `Unknown`.

Compare the script's assumptions against the live object:

```bash
$KCTL get <kind> <name> -n <ns> -o jsonpath='{.status}' | head -c 2000
```

The remediation lives in `argocd-cm`, not in the workload. Note that editing
`argocd-cm` on an operator-managed instance will be reverted — the override belongs in
the `ArgoCD` CR's `resourceHealthChecks`. Say so rather than suggesting a direct edit.

## 3. The controller cannot reach the destination cluster

If every resource in an Application is `Unknown`, or whole Applications pointing at one
destination are `Unknown`, the cluster connection is the suspect rather than any
script.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='server={.spec.destination.server}{"\n"}name={.spec.destination.name}{"\n"}'

$KCTL get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster \
  -o jsonpath='{range .items[*]}{.metadata.name} {.data.server}{"\n"}{end}'

$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'
```

An expired or rotated cluster credential shows up as `ComparisonError` or
`UnknownError` conditions on every Application using that destination. Check whether
the blast radius is one Application or all of them before diagnosing — that one
observation separates a script bug from a credential problem.

## 4. The kind disappeared

If a CRD was uninstalled while its CRs still exist, or an API version was removed in a
cluster upgrade, assessment of those objects fails.

```bash
$KCTL api-resources 2>&1 | grep -i <kind>
$KCTL get crd <plural>.<group> -o jsonpath='{range .spec.versions[*]}{.name} served={.served}{"\n"}{end}'
```

A version that is no longer `served` while manifests still request it produces errors
on every reconcile.

## 5. Controller health

Assessment also fails when the application controller is itself unhealthy — out of
memory, wedged, or failing to build the cluster cache.

```bash
$KCTL get pods -n "$NS" -l app.kubernetes.io/name="$CR"-application-controller
$KCTL logs -n "$NS" sts/"$CR"-application-controller --tail=100 | grep -i -E "error|failed to get resource health"
```

The log line `failed to get resource health for "<Kind>" with name "<name>" in
namespace "<ns>"` is emitted for exactly this case and names the resource directly.

If the controller is restarting or OOMKilled, every Application it manages is affected
and the per-Application diagnosis is a distraction. `skills/gitops/argo-performance-tuning`
covers controller sizing.

## 6. Report

Name which of the five it is and quote the error text you found. Then state explicitly
what the `Unknown` was hiding:

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.name} {.health.status}{"\n"}{end}' \
  | grep -v -E "Healthy|Unknown"
```

If that returns nothing, say so — it is a real finding that the only problem is the
assessment. If it returns degraded or missing resources, report them as a second
finding and note that they were masked, because they will become the Application's
status as soon as the `Unknown` is resolved.
