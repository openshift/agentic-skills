<!-- Loaded on demand by skills/gitops/argo-app-sync-triage/SKILL.md when the sync
     status is Unknown or there is a ComparisonError or InvalidSpecError condition.
     Read-only. -->

# Comparison failed

Sync status `Unknown` means Argo CD never produced a diff. Either it could not build
the desired state, or it could not read the live state. Nothing downstream is
trustworthy: the resource list may be stale from the last successful comparison, and
`OutOfSync` counts mean nothing.

Check this before any other sync symptom. An Application that cannot be compared cannot
be meaningfully `OutOfSync`.

## 1. Read the condition, not the status

The status is one word. The condition carries the error.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'
```

| Condition | What failed |
|---|---|
| `ComparisonError` | The desired state could not be built, or the destination could not be read. Repo, revision, render, or cluster. |
| `InvalidSpecError` | The Application spec itself is rejected. The project, destination, or source is not permitted or does not exist. Nothing was attempted. |
| `UnknownError` | Everything else. Read the message verbatim. |

`InvalidSpecError` is a policy problem and never a repo problem. Go to section 5.

Quote the message in your report. Most of the diagnosis is in that one string, and
paraphrasing it loses the part that identifies the cause.

## 2. Repo and revision

The most common `ComparisonError`. Message text points at it directly — `repository
not accessible`, `authentication required`, `unable to resolve <ref> to a commit SHA`,
`Unable to resolve 'HEAD' to a commit SHA`.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'repoURL={.spec.source.repoURL}{"\n"}'\
'path={.spec.source.path}{"\n"}'\
'targetRevision={.spec.source.targetRevision}{"\n"}'\
'chart={.spec.source.chart}{"\n"}'
```

For a multi-source Application read `.spec.sources[*]` instead — a single-source
jsonpath returns empty and reads as a missing field rather than a different shape.

Then check the credential actually exists and matches the URL:

```bash
$KCTL get secrets -n "$NS" -l argocd.argoproj.io/secret-type=repository \
  -o jsonpath='{range .items[*]}{.metadata.name} {.data.url}{"\n"}{end}' 2>&1 \
  | while read n u; do echo "$n $(echo "$u" | base64 -d)"; done
```

A read-only run may not hold secret access — a cluster-wide reader role commonly
excludes `secrets`. On `forbidden`, say the credential could not be inspected and
diagnose from the condition message alone; `authentication required` against a
configured repo still points here. Do not report a credential as missing when you were
only unable to read it.

Never print the decoded contents of these secrets beyond the `url` key. The diagnosis
needs the URL to compare against `spec.source.repoURL`; the token, SSH key, and
password are not evidence for anything, and an `AnalysisResult` is a cluster object
that others can read.

Matching is by URL prefix, and it is literal. `https://github.com/org/repo` and
`https://github.com/org/repo.git` are different strings, and an SSH URL never matches
an HTTPS credential. A near-miss here presents as `authentication required` on a repo
that is genuinely configured.

Causes that produce this condition without anything being misconfigured: a rotated or
expired token, a deleted branch or tag, a force-push that removed the pinned SHA, and a
private repo reachable from the user's laptop but not from the repo-server pod. For
the last one, check egress from the pod rather than assuming credentials:

```bash
$KCTL logs -n "$NS" deploy/"$CR"-repo-server --tail=100 | grep -i -E "error|failed|denied|timeout"
```

## 3. Render failures

The repo is reachable and the tool failed. The message contains the tool's own output —
`Helm`, `kustomize build`, `rpc error`, `plugin`.

```bash
$KCTL logs -n "$NS" deploy/"$CR"-repo-server --tail=200 | grep -i -E "helm|kustomize|plugin|manifest generation"
```

| Tool | What to confirm |
|---|---|
| Helm | The chart dependency is vendored or the repo is reachable from repo-server. `helm dependency update` output is not available at render time — a missing `charts/` directory or an unreachable dependency repo fails here. Also check `valueFiles` paths; one that does not exist fails the whole render. |
| Kustomize | A `resources:` entry pointing outside the path, or a remote base that needs egress. Remote bases need the same network access as the repo itself. |
| Plugin | The plugin sidecar is running and its name matches `.spec.source.plugin.name`. A renamed or removed plugin fails every Application using it. |

The blast radius separates a manifest bug from an infrastructure problem. If several
unrelated Applications are `Unknown` at once, suspect repo-server, egress, or a shared
credential rather than this Application's manifests.

```bash
$KCTL get applications.argoproj.io -A \
  -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.status.sync.status}{"\n"}{end}' \
  | grep -c Unknown
```

## 4. The destination cluster

If the desired state renders but the live state cannot be read, the destination is the
problem. Every Application pointing at that destination is affected at once — the same
tell as section 3, pointing somewhere else.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='server={.spec.destination.server}{"\n"}name={.spec.destination.name}{"\n"}'

$KCTL get secrets -n "$NS" -l argocd.argoproj.io/secret-type=cluster \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
```

`spec.destination` accepts either `server` or `name`, not both. A `name` that no cluster
secret declares produces `InvalidSpecError`, not `ComparisonError` — a useful
discriminator when both fields look plausible.

An expired cluster token shows as `ComparisonError` on every Application using that
destination, and the app-controller log names it:

```bash
$KCTL logs -n "$NS" sts/"$CR"-application-controller --tail=200 | grep -i -E "cluster|unauthorized|x509|connection refused"
```

For the in-cluster destination on an operator-managed namespace-scoped instance, a
comparison that fails with `forbidden` is a missing destination-namespace grant, not a
credential. That is `skills/gitops/argo-operator`.

## 5. InvalidSpecError

The spec was rejected before anything ran. Four causes, all policy:

```bash
PROJ=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.project}')
$KCTL get appproject "$PROJ" -n "$NS" -o jsonpath=''\
'destinations={.spec.destinations}{"\n"}'\
'sourceRepos={.spec.sourceRepos}{"\n"}'\
'sourceNamespaces={.spec.sourceNamespaces}{"\n"}'
```

| Message shape | Cause |
|---|---|
| `Application referencing project <p> which does not exist` | The AppProject is absent, or lives in a different namespace from the instance. |
| `application destination ... is not permitted in project` | The destination server or namespace is not in `spec.destinations`. Both fields are matched, and `*` in one does not cover the other. |
| `application repo ... is not permitted in project` | `sourceRepos` does not list the repo. Matching is glob, and is literal about the `.git` suffix. |
| `Application is not allowed in namespace` | The Application object lives in a namespace the instance does not watch. This is apps-in-any-namespace, and on an operator-managed instance the fix is a CR field — see `skills/gitops/argo-operator`. |

An AppProject rejection and a missing Kubernetes RoleBinding are independent, and both
can be true. Fixing one leaves the other. Say which you checked.

## 6. Report

Name which of the four it is — repo, render, destination, or spec policy — and quote
the condition message. State the blast radius you measured, because "only this
Application" and "every Application on this instance" lead to different fixes even for
an identical message.

Then say explicitly that the `OutOfSync`/`Synced` reading and the resource list are
stale and were not used in the diagnosis. A comparison error invalidates them, and
reporting a resource count from a failed comparison is how a second wrong diagnosis
gets built on the first.
