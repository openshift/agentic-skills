<!-- Loaded on demand by skills/gitops/argo-operator/SKILL.md when a human user cannot
     see or act on Applications in the UI or CLI. Read-only. -->

# UI and CLI RBAC

A user logs in successfully and sees no Applications, or gets `permission denied` from
`argocd app get`. This is Argo CD's **own** authorization layer, which has nothing to
do with the Kubernetes RBAC in `destination-namespace-rbac.md`.

Keep the two apart from the first sentence of the report:

| | This file | `destination-namespace-rbac.md` |
|---|---|---|
| Who is denied | A human, in the UI or `argocd` CLI | The application-controller ServiceAccount |
| Enforced by | argocd-server, from `argocd-rbac-cm` | The Kubernetes API server |
| Symptom | Empty Application list, `permission denied` | Sync fails `forbidden` |

A user seeing nothing while syncs work normally is always this file. The reverse is
always the other one.

## The operator owns the config

`argocd-rbac-cm` and the SSO configuration are rendered by the operator from the
`ArgoCD` CR. A direct edit to the ConfigMap is reverted on the next reconcile, which
presents as a permission fix that works for a minute and then stops.

| Setting | `ArgoCD` CR field |
|---|---|
| Policy rules | `.spec.rbac.policy` |
| What an unmatched user gets | `.spec.rbac.defaultPolicy` |
| Which OIDC claims become subjects | `.spec.rbac.scopes` |
| Identity provider | `.spec.sso` |
| Built-in admin account | `.spec.disableAdmin` |

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.rbac}{"\n"}'
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.sso}{"\n"}'
```

Always compare the CR against what is live. A difference between the two means the
operator has not reconciled, or something is writing the ConfigMap directly:

```bash
$KCTL get cm argocd-rbac-cm -n "$NS" -o jsonpath='{.data.policy\.csv}{"\n"}'
$KCTL get cm argocd-rbac-cm -n "$NS" -o jsonpath='{.data.policy\.default}{"\n"}'
$KCTL get cm argocd-rbac-cm -n "$NS" -o jsonpath='{.data.scopes}{"\n"}'
```

## 1. Who does Argo CD think the user is?

Nothing else matters until the subject is known. A policy that is correct for
`user@example.com` does nothing if the token's subject is a group, a numeric ID, or
absent.

You cannot log in as that user, and `argocd account get-user-info` would only describe
whatever session you already hold. Read the subject from the server instead — the
denial is logged with it:

```bash
$KCTL logs -n "$NS" deploy/"$CR"-server --tail=500 \
  | grep -i -E "permission denied|rbac|forbidden"
```

Those lines carry the subject argocd-server evaluated and the resource and action it
refused. That string is the diagnosis: compare it against the policy, not against the
username someone expects to have.

If the logs have rotated past the event, derive the subject instead of guessing at it.
An empty `groups` list against a group-based policy is the single most common cause of
"I see nothing", and group membership is readable from the cluster — see the end of
this section.

`scopes` controls which claims become subjects. The default is `[groups]`. If the
identity provider puts group membership in a different claim, the policy never matches
anything:

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.rbac.scopes}{"\n"}'
```

On OpenShift with the default Dex OpenShift OAuth connector, groups arrive as
OpenShift group names. A user who belongs to no OpenShift group matches no group rule
regardless of how the policy is written — check the user's groups on the cluster side
before concluding the policy is wrong:

```bash
$KCTL get groups.user.openshift.io -o jsonpath='{range .items[*]}{.metadata.name}: {.users}{"\n"}{end}'
```

## 2. Read the default policy

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.rbac.defaultPolicy}{"\n"}'
```

An empty or absent `defaultPolicy` means an authenticated user with no matching rule
gets **nothing** — a working login and a blank UI. This is the intended secure default
and is constantly reported as a broken installation.

`role:readonly` gives every authenticated user read access to everything. If it is set,
a user who sees nothing is not failing authorization, and the problem is section 1.

## 3. Read the policy rules

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.rbac.policy}{"\n"}'
```

Two line forms:

```
p, <subject>, <resource>, <action>, <object>, allow|deny
g, <subject>, <role>
```

Checks that find most faults:

- **Subject spelling.** `g, my-group, role:admin` matches a group named exactly
  `my-group`. Case and any provider prefix matter.
- **Role must exist.** A `g` line granting `role:developer` does nothing unless `p`
  lines define `role:developer`. Only `role:admin` and `role:readonly` are built in.
- **`deny` beats `allow`**, regardless of order. One broad deny can silence a correct
  allow further down.
- **Resource names are specific.** `applications`, `applicationsets`, `clusters`,
  `projects`, `repositories`, `logs`, `exec`, `accounts`. `logs` and `exec` are
  separate from `applications`: a user with full application access still cannot read
  pod logs in the UI without a `logs` rule.

### The object field changes with apps-in-any-namespace

For `applications`, the object is normally `<project>/<application>`. Once
`.spec.sourceNamespaces` is in use it becomes
`<project>/<namespace>/<application>` for Applications outside the instance namespace.

Two-part rules keep working for Applications in the instance namespace and silently
stop matching the ones that moved. A policy that was correct before the feature was
enabled narrows the moment it is turned on, and nothing reports an error. If
`sourceNamespaces` is set and some Applications are visible while others are not, check
this before anything else — see `apps-in-any-namespace.md`.

## 4. SSO itself

If login fails rather than returning an empty list, the problem is authentication, not
authorization.

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.sso.provider}{"\n"}'
$KCTL get pods -n "$NS" | grep -E "dex|keycloak"
$KCTL logs -n "$NS" deploy/"$CR"-dex-server --tail=100
```

- `.spec.sso` is the current field. The older top-level `.spec.dex` is deprecated, and
  setting both makes the operator reject the CR — check the `ArgoCD` CR status if the
  operator appears to be ignoring a change.
- `.spec.sso.dex.openShiftOAuth: true` wires Dex to the cluster's OAuth. It needs the
  Dex ServiceAccount to have an OAuth redirect annotation, which the operator manages.
- A redirect URI mismatch after a Route hostname change fails at login with an error
  from the provider, not from Argo CD.

Read the `ArgoCD` CR status for operator-level complaints before digging into the
provider:

```bash
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.status}{"\n"}'
```

## 5. AppProject roles are a separate system

An AppProject can carry its own roles and tokens in `.spec.roles`. These are not in
`argocd-rbac-cm` and not operator-owned:

```bash
# List the projects, or derive the one behind a named Application.
$KCTL get appproject -n "$NS" -o name
PROJ=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.project}')

$KCTL get appproject "$PROJ" -n "$NS" -o jsonpath='{.spec.roles}{"\n"}'
```

A project role grants access only within that project. If a user has access through a
project role, changing the global policy will not affect them — and an edit here is an
ordinary change that the operator will not revert.

## 6. Report

Name the layer: authentication (section 4), subject extraction (section 1), default
policy (section 2), or a rule (section 3). Quote the subject Argo CD actually saw and
the rule you expected to match it, side by side. A policy diagnosis without the
observed subject is a guess.

Give the fix as an `ArgoCD` CR field. Never recommend editing `argocd-rbac-cm` directly
— it is reverted, and the resulting intermittent behavior is harder to diagnose than
the original problem. If the change belongs to an AppProject role instead, say so
explicitly, because that one is a normal edit.
