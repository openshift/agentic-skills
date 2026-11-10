<!-- Loaded on demand by skills/gitops/argo-operator/SKILL.md when an Application
     object outside the Argo CD namespace is ignored. Read-only. Do not create Role or
     RoleBinding objects. -->

# Apps in any namespace

By default an Argo CD instance only reads `Application` objects in its own namespace.
An Application created anywhere else is not rejected and not errored — it is **not
looked at**. That is the signature of this problem: the object exists, `kubectl get`
returns it, and it has no status at all.

Letting Applications live elsewhere is the `sourceNamespaces` feature. The operator
owns every part of it, so the fix is a CR field, never a flag or a RoleBinding.

## This is not the `managed-by` grant

The two are routinely confused because both involve a namespace and both produce RBAC.
They answer different questions, and a deployment into another team's namespace needs
**both**:

| | `sourceNamespaces` | `argocd.argoproj.io/managed-by` |
|---|---|---|
| Question | Where may `Application` **objects** live? | Where may **workloads** be deployed? |
| Set by | `.spec.sourceNamespaces` on the `ArgoCD` CR | A label on the destination namespace |
| Operator then | Grants the instance rights on `applications.argoproj.io` in that namespace, and labels it `argocd.argoproj.io/managed-by-cluster-argocd` | Creates the destination Role and RoleBinding for the controller and server |
| Symptom when missing | The Application is ignored entirely — no status, not in the UI | The Application syncs and fails `forbidden` |

If the Application has no status, you are in this file. If it has a status and the sync
is `forbidden`, you are in `destination-namespace-rbac.md`.

## 1. Confirm the Application is being ignored

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'sync={.status.sync.status}{"\n"}'\
'health={.status.health.status}{"\n"}'\
'reconciledAt={.status.reconciledAt}{"\n"}'\
'conditions={.status.conditions}{"\n"}'
```

An entirely empty `.status` is the tell. An Application that the instance has looked at
always has something — a sync status, a condition, a `reconciledAt`.

Distinguish from the near-identical case where the instance *is* watching the namespace
but the AppProject refuses the Application: that produces a status with an
`InvalidSpecError` condition reading `Application is not allowed in namespace`. Section
3 covers it, and it is the step most often missed.

## 2. Is the namespace in `sourceNamespaces`?

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.sourceNamespaces}{"\n"}'
```

Glob patterns are allowed, so `team-*` covers `team-frontend`. Matching is against the
namespace the **Application object** lives in, not the destination namespace.

Then verify the operator acted on it. Two observable consequences — if the field is set
and these are absent, the operator has not reconciled, and that is a different problem
from a missing field:

```bash
# The operator labels each permitted namespace.
$KCTL get ns "$APP_NS" \
  -o jsonpath='{.metadata.labels.argocd\.argoproj\.io/managed-by-cluster-argocd}{"\n"}'

# And grants the instance rights on Application objects there.
$KCTL get role,rolebinding -n "$APP_NS" | grep -i argocd
```

The label value is the Argo CD **namespace**. Do not set this label by hand — the
operator derives it from `sourceNamespaces` and will remove a hand-written one that
does not correspond to a CR entry.

Confirm the flag reached the workloads. The operator renders `sourceNamespaces` into
the controller and server arguments, and a CR that was edited but never reconciled is
visible here:

```bash
$KCTL get statefulset "$CR"-application-controller -n "$NS" \
  -o jsonpath='{.spec.template.spec.containers[0].command}{"\n"}' | tr ',' '\n' | grep -i namespaces
$KCTL get deploy "$CR"-server -n "$NS" \
  -o jsonpath='{.spec.template.spec.containers[0].command}{"\n"}' | tr ',' '\n' | grep -i namespaces
```

Do not edit `--application-namespaces` on the Deployment or StatefulSet. The operator
rewrites it on the next reconcile, which makes the fix appear to work and then regress.

### The CR is set and nothing was created

If `sourceNamespaces` contains the namespace but the label, the RBAC, and the flag are
all absent, the setting is already in the right place and the operator has not acted on
it. Stop here: that is an operator fault, not a configuration one, and repeating the CR
field as a recommendation is useless.

```bash
$KCTL get argocd "$CR" -n "$NS" \
  -o jsonpath='generation={.metadata.generation}{"\n"}observedGeneration={.status.observedGeneration}{"\n"}'
```

A `generation` ahead of `observedGeneration` confirms it. Report that and hand off to
Workflow 6 in `skills/gitops/argo-cluster-debug`, which owns operator and OLM triage —
pod restarts, CSV phase, InstallPlan, and the conversion webhook.

One cause is worth checking before you hand off, because it looks identical and is not
an operator fault: if the installed operator version does not know the field, the API
server silently prunes it on write. Read the CR back and confirm the value is still
there.

## 3. The AppProject must permit the namespace too

This is the second half of the feature and the most common reason a correct
`sourceNamespaces` still does not work. The project the Application references must
list the namespace in **its own** `sourceNamespaces`:

```bash
PROJ=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.project}')
$KCTL get appproject "$PROJ" -n "$NS" -o jsonpath=''\
'sourceNamespaces={.spec.sourceNamespaces}{"\n"}'\
'destinations={.spec.destinations}{"\n"}'
```

The `default` project does **not** permit other namespaces out of the box. An
Application that lands in a tenant namespace and uses `project: default` fails here
with `Application is not allowed in namespace`, which reads like an instance problem
and is not.

Both lists are evaluated. A namespace in the `ArgoCD` CR but not in the AppProject
gives the Application a status and an `InvalidSpecError`; a namespace in neither gives
it no status at all. Use that difference to tell which of the two is missing without
reading either list.

AppProjects are not operator-owned — they are ordinary Argo CD objects, so editing one
is a normal change and will not be reverted. Say which of the two layers you are
recommending a change to, because one is a CR edit and the other is not.

## 4. Addressing the Application afterwards

Once it works, the Application is referenced by namespace everywhere:

Addressing syntax only — this skill is read-only and runs neither of these. Report
the form the team should use; do not sync a cluster you were asked to diagnose.

```text
argocd app get <namespace>/<application>
argocd app sync <application> --app-namespace <namespace>
```

A plain `argocd app get <name>` looks only in the instance namespace and reports the
Application as not found, which looks like the feature is still broken.

This also changes RBAC policy strings. With `sourceNamespaces` in play, the object in
an `applications` policy rule becomes `<project>/<namespace>/<application>` instead of
`<project>/<application>`. Existing two-part rules stop matching the Applications that
moved, so a working RBAC policy silently narrows at the moment this feature is enabled.
Nothing logs an error, because a non-match is not a failure. The fix is
`.spec.rbac.policy` on the `ArgoCD` CR — the operator renders `argocd-rbac-cm` from it,
so a direct ConfigMap edit is reverted on the next reconcile.

## 5. Report

State which layer is missing — the `ArgoCD` CR, the AppProject, or neither — and quote
the evidence that distinguished them: an empty `.status` for the instance layer, an
`InvalidSpecError` condition for the project layer.

Give the `ArgoCD` CR field and the AppProject field as the recommendation. Do not
recommend the `managed-by-cluster-argocd` label, a Role, a RoleBinding, or an edit to
`--application-namespaces`. All four are operator-reconciled, and all four will be
reverted.

Finally, note whether the destination namespace is also granted. Applications in a
tenant namespace nearly always deploy into that same namespace, and fixing only
`sourceNamespaces` moves the symptom from "ignored" to "forbidden" rather than
resolving it. `destination-namespace-rbac.md` is the next step when it is not granted.
