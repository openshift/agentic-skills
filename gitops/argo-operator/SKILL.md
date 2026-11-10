---
name: argo-operator
description: >
  Diagnose behavior that the Red Hat OpenShift GitOps operator owns on a live cluster,
  where the fix is an operator input — a label, an ArgoCD CR field, an operator
  environment variable — rather than the reconciled object itself. Two topics.
  Destination-namespace RBAC: the operator writes the Role and RoleBinding from the
  argocd.argoproj.io/managed-by label or a completed NamespaceManagement handshake, so
  use it when a sync fails forbidden or Unauthorized. Apps in any namespace: an
  Application object outside the Argo CD namespace is ignored with no status, driven by
  sourceNamespaces. Read-only, and written for an automated
  run with no human available — it never writes the object the operator owns, and it
  never asks a question. Not for sync or health status triage.
license: MIT
compatibility: Requires oc or kubectl
---

# Argo CD operator

Operator-owned behavior for an Argo CD instance installed by the Red Hat OpenShift
GitOps operator. Upstream Argo CD does not create these objects, so the fix is always
an operator input — a label, a CR field, an operator environment variable — never the
reconciled object itself.

This skill is read-only. Show the operator input that would fix the problem, and stop
there. Applying it belongs to `argo-operations`, and only after a dry-run and an
explicit confirmation.

## You are probably running non-interactively

This skill is written to be usable by an automated diagnosis run with no human in the
loop. If no one can answer a question, do not ask one. Gather the evidence you can
reach, name the most probable cause, and state your confidence and what you could not
check. An honest `Low` confidence diagnosis is useful. A question is not.

Related skills, so this one stays narrow:

| Need | Skill |
|------|-------|
| Operator CRD field reference — RolloutManager, NotificationsConfiguration, NamespaceManagement, ImageUpdater, GitopsService | `skills/gitops/argo-knowledge/references/openshift-gitops-operator.md` |
| Installing or changing an operator-managed instance | `skills/gitops/argo-operations` |
| Sync, health, and controller-log debugging that is not operator-owned | `skills/gitops/argo-cluster-debug` |

## Before any check

Resolve the CLI. On OpenShift, `oc` is the default.

```bash
if command -v oc >/dev/null 2>&1 && oc api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes; then
  KCTL=oc
elif command -v kubectl >/dev/null 2>&1; then
  KCTL=kubectl
elif command -v oc >/dev/null 2>&1; then
  KCTL=oc
else
  echo "ERROR: no cluster CLI found — install kubectl or oc" >&2; exit 1
fi
```

Confirm the cluster context with `$KCTL config current-context`. Use
`applications.argoproj.io`, never the short name `application`: on Open Cluster
Management clusters the short name is `applications.app.k8s.io` and a miss looks
like the Application does not exist.

Identify the instance before anything else. Most of these topics have a different
answer for a cluster-scoped instance than for a namespace-scoped one:

```bash
NS=<namespace-of-the-ArgoCD-CR>
CR=<name-of-the-ArgoCD-CR>

# Set these two as well whenever the symptom names a specific Application.
APP=<application-name>
APP_NS=<namespace-of-the-application-object>

$KCTL get argocd -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'
```

## Route by symptom

Load exactly one topic. These look alike at a distance and have unrelated fixes.

| Symptom | Topic | Reference |
|---|---|---|
| Sync fails `forbidden` or `Unauthorized`; the controller cannot write to the destination namespace | Destination-namespace RBAC | `references/destination-namespace-rbac.md` |
| An `Application` object outside the Argo CD namespace is ignored — no status at all | Apps in any namespace | `references/apps-in-any-namespace.md` |

Each is a different "permission denied", and the distinguishing evidence is cheap: an
empty `.status` means the Application is not being watched, while a `forbidden` sync
means the controller lacks Kubernetes rights. Establish which before loading a
reference.

If the symptom is not operator-owned, hand off rather than guessing. Sync state is
`skills/gitops/argo-app-sync-triage`, health is `skills/gitops/argo-app-health-triage`.

## Topic: destination-namespace RBAC

Diagnose whether an instance is allowed to manage resources in an Application's
destination namespace.

### What the operator owns

A namespace-scoped Argo CD instance can deploy only in its own namespace until a
destination namespace is granted to it. The OpenShift GitOps operator creates that
grant. Do not write a Role or RoleBinding for it.

Two paths produce the same objects in the destination namespace:

| Path | Who does it | Operator then creates |
|------|-------------|------------------------|
| Label `argocd.argoproj.io/managed-by: <instance-namespace>` | A cluster admin labels the destination namespace. The value is the namespace the `ArgoCD` CR lives in, not the CR name. | Role and RoleBinding `<argocd-name>-argocd-application-controller` and `<argocd-name>-argocd-server` |
| `NamespaceManagement` | A tenant creates the CR in the destination namespace, after an admin has enabled the feature and the `ArgoCD` CR has opted in. | The same Role and RoleBinding, and the destination namespace is added to the instance cluster secret `<argocd-name>-default-cluster-config` |

The two Roles differ, and neither matches the `admin` ClusterRole. The controller
Role is every verb on every namespaced resource, plus `impersonate` on
ServiceAccounts — broader than `admin`. The server Role is narrower: read, patch, and
delete, with full CRUD on Secrets and ConfigMaps. Neither grants cluster-scoped
resources (Namespace, CRD, ClusterRole). A hand-written binding is not part of this
reconcile and will not be repaired by the operator.

The label works only for namespaces on the same cluster as the operator. A remote
cluster destination needs RBAC created on that cluster. Say so; do not recommend the
label there.

### Labels that are not this grant

| Label or field | What it actually is |
|----------------|---------------------|
| `argocd.argoproj.io/managed-by` | Destination-namespace grant. Value is the Argo CD **namespace**. |
| `argocd.argoproj.io/managed-by-cluster-argocd` | Apps-in-any-namespace. The operator sets it from `sourceNamespaces`. It is where Application objects may live, not permission to deploy workloads. |
| `app.kubernetes.io/managed-by: applicationset-controller` | Marks an Application generated by an ApplicationSet. |
| `argocd.argoproj.io/managed-by-url` | Annotation on an Application that points its UI link at an instance. Not RBAC. |
| AppProject `destinations` | Argo CD policy. Independent of the Kubernetes RoleBinding. Both can fail a sync. |

A namespace should be managed by one instance. If `managed-by` is already set, the
operator will not also create the source-namespace roles for `managed-by-cluster-argocd`.

### Running this topic

Load `references/destination-namespace-rbac.md` and run that workflow in order. Do not
stop at the first missing object. A missing label and an AppProject rejection often sit
on the same Application.

### Scope check comes first

The label and `NamespaceManagement` extend a **namespace-scoped** instance. They are
the wrong fix when:

- The instance is cluster-scoped. Those instances get a ClusterRole and
  ClusterRoleBinding named `<argocd-name>-<argocd-namespace>-argocd-application-controller`
  and `<argocd-name>-<argocd-namespace>-argocd-server`. Which namespaces host a
  cluster-scoped instance is `ARGOCD_CLUSTER_CONFIG_NAMESPACES`, read from the
  operator **Deployment** — the CSV default is `openshift-gitops`, and a Subscription
  entry replaces that default rather than extending it. So the default
  `openshift-gitops` instance is cluster-scoped and is for
  cluster configuration, not application delivery. A forbidden sync there is usually
  the limited default ClusterRole, not a missing label.
- The resource that failed is cluster-scoped. A namespace-scoped instance cannot
  manage it, even with `managed-by` set.
- The destination server is a remote cluster.

### Report

Every destination-namespace RBAC session ends with this report. Quote the field or
object that establishes each claim. A cause with no supporting output fails the
diagnosis.

#### 1. Instance

| Field | Value |
|-------|-------|
| Context | current context |
| ArgoCD | `<namespace>/<name>` |
| Scope | namespace-scoped or cluster-scoped, and the evidence |
| Application | `<namespace>/<name>` |
| Destination | server and namespace from `spec.destination` |

When more than one Argo CD instance exists, repeat the report per instance that could
own the Application. Do not pick one silently.

#### 2. Grant

State which path is in effect, or that neither is:

- Label value on the destination namespace, and whether it equals the instance namespace.
- `NamespaceManagement` in that namespace: `.spec.managedBy`, its
  `.status.conditions`, whether the feature environment is set on the operator
  Deployment, and whether `ArgoCD.spec.namespaceManagement` allows that name. Quote
  the condition, or state that there is none — both are evidence.
- Role and RoleBinding names found or missing.
- `kubectl auth can-i` result for the application-controller ServiceAccount. The
  account is `<argocd-name>-argocd-application-controller` in the **instance**
  namespace. `can-i` against a ServiceAccount that does not exist returns "no" and
  is not evidence that RBAC was denied.

#### 3. Separate checks

AppProject destination and resource restrictions, and whether the failing object is
cluster-scoped. Say explicitly when Kubernetes RBAC is fine and the project is what
rejected the sync, or the reverse.

#### 4. Root cause and recommendation

Name one root cause. If the grant is missing, the recommendation is the label or the
`NamespaceManagement` handshake. It is not a Role or RoleBinding manifest.

State the impact of the recommendation:

- The label gives that instance every verb on every namespaced resource in the
  destination namespace, including `impersonate` on the ServiceAccounts in it. Every
  Application on that instance can deploy there, still subject to the AppProject.
- Do not put the label on a namespace whose `managed-by` value is a different instance.
- `NamespaceManagement` does nothing until the operator environment is true and the
  `ArgoCD` CR allows the namespace. `status.conditions` on the `NamespaceManagement`
  CR distinguishes those two, and an absent condition points at the environment.

## Topic: apps in any namespace

An `Application` object created outside the Argo CD namespace is ignored — not
rejected, not errored, simply never read. An entirely empty `.status` is the tell.

The operator owns this through `.spec.sourceNamespaces` on the `ArgoCD` CR, from which
it derives the `argocd.argoproj.io/managed-by-cluster-argocd` label on each permitted
namespace, the Role and RoleBinding granting rights on `applications.argoproj.io`
there, and the `--application-namespaces` arguments. All four are reconciled. Do not
set the label, write the RBAC, or edit the flag.

Two layers must agree, and they fail differently — which tells you which is missing
without reading either:

| Missing | Symptom |
|---|---|
| The namespace is not in `ArgoCD.spec.sourceNamespaces` | No `.status` at all |
| The namespace is not in the AppProject's `spec.sourceNamespaces` | A status with `InvalidSpecError: Application is not allowed in namespace` |

The AppProject is not operator-owned, so that half is an ordinary edit. Say which layer
you are recommending a change to.

Load `references/apps-in-any-namespace.md`.

## If the run writes a structured result

When the output is an `AnalysisResult`, each topic's Report maps onto its fields:
`diagnosis.summary` and `diagnosis.rootCause` for the finding, `diagnosis.confidence`
for how far the evidence reached — the enum is exactly `Low`, `Medium`, `High` — and
`actionRequired` for whether anything should change.

Use `actionRequired: "False"` where the finding is working-as-configured: a
cluster-scoped instance that does not need a `managed-by` label, an AppProject
deliberately restricting a destination, a `defaultPolicy` that is empty on purpose.
That ends the run as Completed instead of manufacturing a remediation.

When `actionRequired` is `"True"`, `remediationPlan.actions[].command` must be an exact
executable command. So the rule is not "never produce a command" — it is that the
command must be the **operator input**, never the object the operator reconciles:

| Recommend | Never |
|---|---|
| `oc label namespace <dest> argocd.argoproj.io/managed-by=<argocd-ns>` | A `Role` or `RoleBinding` in the destination namespace |
| `oc patch argocd <cr> -n <ns> --type merge -p '{"spec":{"sourceNamespaces":[...]}}'` | Editing `--application-namespaces` on the Deployment or StatefulSet |
| `oc patch argocd <cr> -n <ns> --type merge -p '{"spec":{"rbac":{"policy":"..."}}}'` | Editing `argocd-cm` or `argocd-rbac-cm` |

A command in the right-hand column appears to succeed and is reverted on the next
reconcile, which is worse than proposing nothing: it consumes an approval and an
execution step to produce a regression.

Declare RBAC to match the command you actually proposed, with a `justification`.
**Your declaration is the only source of execution permissions.** Nothing in the run
scopes you to a namespace and nothing widens the grant later, so a namespace you leave
out is a namespace the execution step cannot touch — and it fails there, after an
approval has already been spent.

| Command | Needs |
|---|---|
| Labelling a namespace | `patch` on `namespaces`, **cluster-scoped** — a Namespace is not a namespaced resource, so a namespace-scoped rule will not grant it |
| Patching the `ArgoCD` CR | `patch` on `argocds.argoproj.io`, namespace-scoped to the **instance** namespace |
| Editing an AppProject | `patch` on `appprojects.argoproj.io`, namespace-scoped to the **instance** namespace |

The Argo-specific trap is that an Application's own namespace and its destination
namespace are usually different, and both may be in scope for one fix. Enumerate the
namespaces from the objects you actually named in the diagnosis rather than defaulting
to the Argo CD namespace.

Size the `risk` and the justification to the real grant:

- Patching the `ArgoCD` CR restarts Argo CD components, so `risk` is at least `Medium`.
- Granting `managed-by` gives that instance every verb on every namespaced resource in
  the destination, including `impersonate` on its ServiceAccounts. Scope the
  justification to that, and do not call it admin-equivalent — that understates it.

Put the read-back that proves the operator acted — the Role appearing, the label being
present, `observedGeneration` catching up — in a `post-check` action. The operator is
eventually consistent, so a `mutation` with no `post-check` cannot be verified.

## Reference

| Topic | File | When to load |
|-------|------|----------------|
| Destination-namespace RBAC — decision order, commands, and the two grant paths | `references/destination-namespace-rbac.md` | The symptom is a `forbidden` or `Unauthorized` sync, or a question about `managed-by` or `NamespaceManagement` |
| Apps in any namespace — `sourceNamespaces`, the two layers, and addressing Applications afterwards | `references/apps-in-any-namespace.md` | An Application outside the instance namespace has no status, or `Application is not allowed in namespace` |
| Application **sync** state triage | `skills/gitops/argo-app-sync-triage` | The symptom is `OutOfSync`, a failed or stuck sync, or `Synced` while the cluster is wrong |
| Application **health** status triage | `skills/gitops/argo-app-health-triage` | The symptom is `Degraded`, `Progressing`, `Missing`, or health `Unknown` |
