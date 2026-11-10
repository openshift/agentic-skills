<!-- Loaded on demand by skills/gitops/argo-operator/SKILL.md.
     Run the workflow in order. Read-only. Do not create Role or RoleBinding objects. -->

# Destination namespace RBAC

The OpenShift GitOps operator creates the Kubernetes permission that lets an Argo CD
instance manage a destination namespace. The permission is a Role and a RoleBinding in
that namespace. Creating them by hand is the wrong fix: the operator will not adopt a
hand-written object, and a later reconcile or instance deletion removes only the
objects it owns.

## Objects the operator creates

In the destination namespace, for Argo CD CR name `<argocd-name>`:

| Name | Kind | Subject |
|------|------|---------|
| `<argocd-name>-argocd-application-controller` | Role and RoleBinding | ServiceAccount `<argocd-name>-argocd-application-controller` in the instance namespace |
| `<argocd-name>-argocd-server` | Role and RoleBinding | ServiceAccount `<argocd-name>-argocd-server` in the instance namespace |

The controller binding is what a sync uses. The server binding is what the UI, API,
and CLI use to read and manage resources in that namespace. Check both. A sync can
fail while the UI still looks healthy, and the reverse.

The two Roles are not the same, and neither matches the `admin` ClusterRole. The
controller Role is every verb on every resource in every API group, plus
`impersonate` on `serviceaccounts` — broader than `admin`, which cannot write
`resourcequotas` and cannot impersonate. The server Role is narrower: `get`, `patch`,
and `delete` on everything, full CRUD on `secrets` and `configmaps`, and the
`argoproj.io` kinds. Neither covers cluster-scoped kinds; a Role cannot grant them.

If the operator environment sets `CONTROLLER_CLUSTER_ROLE` or `SERVER_CLUSTER_ROLE`
(read them from the operator Deployment, step 1), the operator does **not** create
the default Role. It
creates only a RoleBinding whose `roleRef` is that ClusterRole. The ClusterRole
itself is the administrator's to create. It must allow `get`, `list`, and `watch`,
or the Argo CD CR must limit what the controller touches with `resourceInclusions`
or `resourceExclusions`. A RoleBinding to a ClusterRole that does not exist looks
like "RBAC is missing" and is fixed by creating that ClusterRole, not a second Role.

The cluster secret is `<argocd-name>-default-cluster-config`, and it lives in the
**instance** namespace, not the destination. `NamespaceManagement` adds the
destination namespace to its `namespaces` key, a comma-joined list:

```bash
$KCTL get secret "${CR}-default-cluster-config" -n "$NS" \
  -o jsonpath='{.data.namespaces}' | base64 -d; echo
```

A read-only run may not hold secret access — a cluster-wide reader role commonly
excludes `secrets`. Distinguish the two failures, because they mean opposite things:
`forbidden` is a gap in **your** permissions and leaves the handshake unverified, while
`NotFound` is evidence about the cluster. Check which you got:

```bash
$KCTL get secret "${CR}-default-cluster-config" -n "$NS" -o name 2>&1
```

If it is `forbidden`, say that this check was unavailable and fall back to the Role and
RoleBinding in the destination namespace, which are readable and prove the same
handshake. Do not report an unverified handshake as a missing one.

Do not read `<argocd-name>-cluster` for this. That is the admin password secret and
never has a `namespaces` key; finding none there says nothing about the handshake.

The operator does not create `-default-cluster-config` at all for a cluster-scoped
instance, so its absence alongside the default `openshift-gitops` instance is
expected and is not a finding.

Cluster-scoped instances are a different object, and the label is not how they get
their rights. The operator creates:

| Name | Kind |
|------|------|
| `<argocd-name>-<instance-namespace>-argocd-application-controller` | ClusterRole and ClusterRoleBinding |
| `<argocd-name>-<instance-namespace>-argocd-server` | ClusterRole and ClusterRoleBinding |

The default instance in `openshift-gitops` is cluster-scoped. It can read broadly and
deploy only a limited set of kinds. Do not send an application team to add
`managed-by` on the default instance. Application delivery belongs on a separate
namespace-scoped instance.

## Workflow

Set these from the live objects before judging anything. `$NS` is the namespace of
the Argo CD instance. `$CR` is the ArgoCD CR name. They are often both
`openshift-gitops`, which hides the fact that the label value is the namespace.

```bash
APP=<application-name>
APP_NS=<namespace-of-the-application-object>

$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='project={.spec.project}{"\n"}server={.spec.destination.server}{"\n"}dest={.spec.destination.namespace}{"\n"}'
DEST=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.destination.namespace}')

$KCTL get argocd -A
```

Every command below interpolates `$NS` and `$CR`. Set them from that listing before
going on; unset, the commands silently query names like `--argocd-server`.

```bash
NS=<namespace-of-the-argocd-cr>     # usually $APP_NS
CR=$($KCTL get argocd -n "$NS" -o jsonpath='{.items[0].metadata.name}')
echo "NS=$NS CR=$CR DEST=$DEST"
```

The `[0]` picks arbitrarily. If `$KCTL get argocd -n "$NS"` returned more than one
CR, run the workflow once per CR rather than accepting that pick.

If the Application is not in `$APP_NS`, search with
`$KCTL get applications.argoproj.io -A`. Then identify which instance owns it: the
Application's namespace is the usual instance namespace. When several `ArgoCD` CRs
exist, report each candidate. Do not collapse them into one finding.

### 1. Is this instance namespace-scoped?

Read the environment from the operator **Deployment**, not the Subscription. The
defaults ship in the CSV, and `Subscription.spec.config.env` exists only where an
admin added one. On a default install it is absent, so a Subscription-only read
returns nothing and is not evidence that the variables are unset.

```bash
$KCTL get deploy -n openshift-gitops-operator \
  -o jsonpath='{range .items[*].spec.template.spec.containers[?(@.name=="manager")].env[*]}{.name}={.value}{"\n"}{end}'
```

A Subscription entry **replaces** the CSV default rather than adding to it. An admin
who set `ARGOCD_CLUSTER_CONFIG_NAMESPACES=team-a` and dropped `openshift-gitops` made
the default instance namespace-scoped without intending to. The Deployment shows the
merged result; read the Subscription only to attribute a value to someone:

```bash
$KCTL get subscriptions.operators.coreos.com -n openshift-gitops-operator \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .spec.config.env[*]}  {.name}={.value}{"\n"}{end}{end}'
```

Record:

- `ARGOCD_CLUSTER_CONFIG_NAMESPACES` — namespaces whose Argo CD instances are
  cluster-scoped. The CSV default is `openshift-gitops`, which is why that instance
  is cluster-scoped. A first entry of `*` means every namespace. An empty value means
  none, including `openshift-gitops`. Confirm against the ClusterRole below rather
  than the variable alone.
- `ALLOW_NAMESPACE_MANAGEMENT_IN_NAMESPACE_SCOPED_INSTANCES` — must be `"true"` or
  `NamespaceManagement` is inert and the operator cleans the related RBAC up.
- `CONTROLLER_CLUSTER_ROLE` and `SERVER_CLUSTER_ROLE` — when set, expect a
  RoleBinding and no default Role.

```bash
$KCTL get clusterrole "${CR}-${NS}-argocd-application-controller" \
  "${CR}-${NS}-argocd-server"
$KCTL get clusterrolebinding "${CR}-${NS}-argocd-application-controller" \
  "${CR}-${NS}-argocd-server"
```

Those ClusterRoles existing means this instance is cluster-scoped. Stop using the
label as the explanation. Inspect that ClusterRole against the kind that failed, and
say the default instance is the wrong place for application delivery when `$NS` is
`openshift-gitops`.

A namespace-scoped instance with no ClusterRole is the case the rest of this
workflow is for.

### 2. Where is the Application trying to deploy?

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{.status.operationState.phase}{" "}{.status.operationState.message}{"\n"}'
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.kind}/{.namespace}/{.name} {.status} {.message}{"\n"}{end}'
```

Note the kind. If it is cluster-scoped (Namespace, CustomResourceDefinition,
ClusterRole, ClusterRoleBinding, StorageClass, and the like), a namespace-scoped
instance cannot manage it. The label will not change that. Say so and stop
recommending RBAC in the destination namespace.

If `spec.destination.server` is not `https://kubernetes.default.svc`, the target is
another cluster. The `managed-by` label on this cluster does nothing there. Say that
the Role and RoleBinding have to be created on the remote cluster, and do not
recommend labeling the local namespace.

If `DEST` equals `$NS`, the instance already has rights in its own namespace. A
forbidden error there is not a missing managed-namespace grant. Check the AppProject
and `auth can-i` in step 6.

### 3. Label path

```bash
$KCTL get ns "$DEST" -o go-template='managed-by={{with .metadata.labels}}{{index . "argocd.argoproj.io/managed-by"}}{{end}}{{"\n"}}source={{with .metadata.labels}}{{index . "argocd.argoproj.io/managed-by-cluster-argocd"}}{{end}}{{"\n"}}deleting={{.metadata.deletionTimestamp}}{{"\n"}}'
$KCTL get argocd -n "$NS" --no-headers
```

Judge the label against these rules:

- The value must equal `$NS`. When the CR name and the namespace differ, a value
  equal to the CR name is wrong.
- Empty or absent, on a namespace-scoped instance whose destination is another
  namespace, means this path was not used. Go to step 4 before calling it missing.
- A value equal to some other namespace means a different instance owns the
  namespace. Do not recommend changing it to `$NS`. Say which instance holds it.
- `deletionTimestamp` set: the operator removes `managed-by` from a terminating
  namespace and skips reconcile, which deletes the Role and RoleBinding. The
  missing RBAC is a consequence. Do not recommend putting the label back.
- More than one `ArgoCD` CR in `$NS`: the label names a namespace, not one CR.
  Both instances reconcile their own Role names into `DEST`. Report that; do not
  pretend the label selected one of them.
- `managed-by-cluster-argocd` without `managed-by` is the source-namespace label.
  It does not grant destination admin. Do not treat it as the grant.

### 4. NamespaceManagement path

This is the tenant path. It is off by default. All three of the following have to be
true, and `status.conditions` on the `NamespaceManagement` CR usually tells you which
one is missing — read it before reasoning about the rest:

1. Operator **Deployment** env `ALLOW_NAMESPACE_MANAGEMENT_IN_NAMESPACE_SCOPED_INSTANCES=true`,
   read as in section 1. Do not read the Subscription for this: on a default install
   it carries no `spec.config.env` and an absent entry is not evidence the flag is off.
2. The ArgoCD CR allows the namespace:

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: team-argocd
  namespace: team-frontend
spec:
  namespaceManagement:
    - name: payments-*          # both fields required; globs are allowed
      allowManagedBy: true
```

3. The destination namespace contains a `NamespaceManagement` whose
   `spec.managedBy` is exactly `$NS`:

```yaml
apiVersion: argoproj.io/v1beta1
kind: NamespaceManagement
metadata:
  name: managed
  namespace: payments-dev        # the destination namespace
spec:
  managedBy: team-frontend       # the Argo CD instance namespace
```

```bash
$KCTL get namespacemanagements.argoproj.io -n "$DEST" -o yaml
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='{.spec.namespaceManagement}{"\n"}'

$KCTL get namespacemanagements.argoproj.io -n "$DEST" \
  -o jsonpath='{range .items[*]}{.metadata.name} managedBy={.spec.managedBy} {.status.conditions}{"\n"}{end}'
```

The operator writes a condition on every `NamespaceManagement` whose `spec.managedBy`
matches an instance namespace, and only while the feature is enabled. Read it as:

| `status.conditions` | What it means |
|---------------------|----------------|
| Absent | The operator never evaluated this CR. Either `ALLOW_NAMESPACE_MANAGEMENT_IN_NAMESPACE_SCOPED_INSTANCES` is not `"true"`, or `spec.managedBy` names a namespace with no Argo CD instance, or the `ArgoCD` CR is not reconciling at all. Check the Deployment environment from step 1 first. |
| `reason: ErrorOccurred`, message `Namespace <ns> is not permitted for management by ArgoCD instance <ns> based on NamespaceManagement rules` | The feature is on and the request reached the operator. `ArgoCD.spec.namespaceManagement` has no entry matching this namespace with `allowManagedBy: true`. The fix is on the `ArgoCD` CR, not the tenant CR. |
| `reason: Success` | The handshake is complete. A missing Role is then an operator problem (step 7), not a missing opt-in. |

Because the condition is only written while the feature environment is `"true"`, its
absence is itself evidence about that variable. Quote the condition, or quote that
there is none.

On create, the operator writes the Role and RoleBinding from the table above and
adds `DEST` to secret `$CR-default-cluster-config` in `$NS`. On a change of `.spec.managedBy`, it
moves that RBAC. On delete, it removes the RBAC and the cluster-secret entry.
Disabling the Subscription env cleans all of it up. A grant that vanished after an
operator change is often this env flipping back to unset, not a deleted Application.

`spec.managedBy` is the only field on `NamespaceManagement`, and it is required.
Each `ArgoCD.spec.namespaceManagement` entry requires both `name` and
`allowManagedBy`.

### 5. Did the operator actually create the RBAC?

```bash
$KCTL get role -n "$DEST" \
  "${CR}-argocd-application-controller" \
  "${CR}-argocd-server"
$KCTL get rolebinding -n "$DEST" \
  "${CR}-argocd-application-controller" \
  "${CR}-argocd-server"

$KCTL get rolebinding "${CR}-argocd-application-controller" -n "$DEST" \
  -o jsonpath='roleRef={.roleRef.kind}/{.roleRef.name}{"\n"}subject={.subjects[0].kind}/{.subjects[0].namespace}/{.subjects[0].name}{"\n"}'
```

Read the result as follows:

| What you see | What it means |
|--------------|----------------|
| Both Roles and both RoleBindings exist, subjects point at `$NS` | The grant is in place. A forbidden sync is not a missing managed-namespace. Continue to step 6. |
| RoleBindings exist, Roles do not, and `CONTROLLER_CLUSTER_ROLE` or `SERVER_CLUSTER_ROLE` is set | Expected shape. Check that the named ClusterRole exists and can `get`/`list`/`watch`. |
| Label or a completed handshake is present, and these objects are absent | The operator has not reconciled. Check operator health in step 7. Do not create the Role. |
| A RoleBinding with a different name exists | Someone created RBAC by hand. It is not the operator grant. Do not extend it. Recommend the label or `NamespaceManagement`, and say the hand-written object will be left behind. |
| Label value is wrong or points at another instance | Fixing names here will not help. The label decides which instance reconciles. |

Also confirm the ServiceAccount exists before trusting `auth can-i`:

```bash
$KCTL get sa "${CR}-argocd-application-controller" -n "$NS"
$KCTL auth can-i create deployment \
  --as="system:serviceaccount:${NS}:${CR}-argocd-application-controller" \
  -n "$DEST"
```

Use the kind from the sync error in place of `deployment`. `no` with the SA present
and the RoleBinding present means the rules do not allow that kind. `no` with the SA
absent means the account name is wrong or the instance is not installed. Say which
one you observed.

### 6. AppProject, only after the grant is known

Kubernetes RBAC and the AppProject both have to allow the destination. Check the
project even when the Role is missing, so the report does not hide a second cause.

```bash
PROJECT=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.project}')
$KCTL get appprojects.argoproj.io "$PROJECT" -n "$NS" \
  -o jsonpath='{.spec.destinations}{"\n"}{.spec.namespaceResourceBlacklist}{"\n"}{.spec.clusterResourceWhitelist}{"\n"}'
```

The `default` project allows every destination. A team project that omits `DEST`, or
a blacklist that names the failing kind, rejects the sync with a message that looks
like RBAC. Quote the project field. Recommend a project change only when that field
is what excludes the destination. Do not recommend the `default` project as the fix.

### 7. Operator health, when the spec is right and the objects are absent

A correct label with no Role means the operator is not reconciling. Check that
before telling anyone to re-apply the label.

```bash
$KCTL get pods -n openshift-gitops-operator
$KCTL get csv -n openshift-gitops-operator \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
$KCTL get argocd "$CR" -n "$NS" -o jsonpath='phase={.status.phase}{"\n"}'
```

A CSV that is not `Succeeded`, or an operator pod that is not `Running`, is the
blocker. Fixing the Application will not create the Role.

Also re-read step 3: a terminating destination namespace is the operator behaving
correctly, not a stuck reconcile.

## What to recommend

Recommend one of these, and only when the workflow showed it is the missing piece.

Label, applied by a cluster admin to the destination namespace:

```bash
oc label ns <destination> argocd.argoproj.io/managed-by=<instance-namespace>
```

Or the `NamespaceManagement` handshake in step 4, when the tenant should not need
cluster-admin and the Subscription env is already true or the user is willing to
have an admin set it.

Say the impact with the recommendation. The grant is admin-equivalent for every
namespaced resource in that namespace, for every Application on that instance, still
limited by the AppProject. It does not extend to cluster-scoped kinds or to a remote
cluster.

Do not recommend:

- A Role or RoleBinding manifest for the application-controller ServiceAccount.
- `managed-by-cluster-argocd` as a substitute for `managed-by`.
- Adding the label on a namespace that already names a different instance.
- Using this grant so a namespace-scoped instance can create Namespaces or CRDs.
- Pointing an application team at the default `openshift-gitops` instance.
