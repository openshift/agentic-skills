<!-- Loaded on demand by skills/gitops/argo-app-sync-triage/SKILL.md when
     operationState.phase is Failed or Error. Read-only. -->

# A sync that failed

`Failed` means the operation ran and at least one resource could not be applied.
`Error` means the operation could not be carried out at all. Both leave a message, and
a per-resource result that says exactly which object broke.

Note that a failed sync does **not** make the Application `OutOfSync` on its own — the
status reflects the comparison that followed. An Application reading `Synced` with
phase `Failed` is normal and means the failure did not change the diff.

## 1. Read the per-resource result

The app-level message is a summary. The resource list is the diagnosis.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.status} {.kind}/{.namespace}/{.name}: {.message}{"\n"}{end}' \
  | grep -v -E "^Synced|^Succeeded"
```

| Status | Meaning |
|---|---|
| `SyncFailed` | The apply was rejected. The message is the API server's or the hook's. |
| `PruneSkipped` | Not a failure. The resource was left alone deliberately. |
| `Failed` on a hook | A hook resource failed. The sync stops at that phase. |

Quote the message. Nearly every cause below is identifiable from its text alone, and
the rest of this file is about what to confirm once you have read it.

## 2. Classify the message

| Message contains | Cause | Confirm with |
|---|---|---|
| `forbidden`, `Unauthorized`, `cannot create resource` | RBAC. The controller ServiceAccount may not write that kind in that namespace. | Section 3 |
| `is invalid`, `ValidationError`, `unknown field` | The manifest is wrong, or the CRD schema differs from what it was written against. | Section 4 |
| `conflict`, `Operation cannot be fulfilled`, `field is managed by` | Another writer owns the object or the field. | Section 5 |
| `admission webhook ... denied the request` | A policy engine rejected it. The webhook name is in the message. | Section 6 |
| `the server could not find the requested resource` | The CRD is not installed, or the API version was removed. | Section 7 |
| `exceeded quota` | A ResourceQuota in the destination namespace. | Read the quota directly |
| `namespaces "<ns>" not found` | The destination namespace does not exist and `CreateNamespace=true` is not set. | Section 7 |

## 3. RBAC

Two independent layers, and both can reject a sync. Check both; fixing one while the
other is also broken produces a second identical failure.

**Kubernetes RBAC** — can the controller write this object?

```bash
$KCTL auth can-i <verb> <resource> \
  --as=system:serviceaccount:"$NS":"$CR"-argocd-application-controller \
  -n <destination-namespace>
```

On an operator-managed instance this is almost never fixed by writing a Role. The
operator creates the destination-namespace Role and RoleBinding from the
`argocd.argoproj.io/managed-by` label or a `NamespaceManagement` handshake, and a
hand-written binding will not be adopted. Load `skills/gitops/argo-operator` before
recommending any RBAC manifest.

A `forbidden` on a **cluster-scoped** kind from a namespace-scoped instance is a
different problem and no label fixes it — a Role cannot grant cluster-scoped resources.

**AppProject policy** — is the resource kind allowed at all?

```bash
PROJ=$($KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath='{.spec.project}')
$KCTL get appproject "$PROJ" -n "$NS" -o jsonpath=''\
'clusterResourceWhitelist={.spec.clusterResourceWhitelist}{"\n"}'\
'namespaceResourceBlacklist={.spec.namespaceResourceBlacklist}{"\n"}'\
'namespaceResourceWhitelist={.spec.namespaceResourceWhitelist}{"\n"}'
```

A project rejection reads differently — it names the project and happens before the API
call — so the message distinguishes the two layers for you.

## 4. Invalid manifests

The API server rejected the object's shape.

```bash
$KCTL get crd <plural>.<group> \
  -o jsonpath='{range .spec.versions[*]}{.name} served={.served} storage={.storage}{"\n"}{end}'
```

Causes worth separating, because they lead to different fixes:

- The manifest is genuinely malformed. A render-time templating bug produces this and
  the repo is where it gets fixed.
- The CRD is an older version than the manifest expects. `unknown field` on a CR
  usually means the operator providing the CRD has not been upgraded.
- Dry-run was skipped. `SkipDryRunOnMissingResource=true` defers validation of a kind
  whose CRD is created in the same sync, so a genuine schema error surfaces only at
  apply time.

## 5. Conflicts

Another writer holds the object.

```bash
$KCTL get <kind> <name> -n <ns> \
  -o jsonpath='{range .metadata.managedFields[*]}{.manager} {.operation} {.subresource}{"\n"}{end}'
```

| Shape | Cause |
|---|---|
| Another controller in `managedFields` | A genuine two-writer conflict. One of them has to stop owning the field — `ignoreDifferences` on Argo CD's side if the other writer is authoritative. |
| `Operation cannot be fulfilled ... object has been modified` | An optimistic-concurrency retry. Usually transient; if it repeats every sync, something writes the object continuously. |
| An immutable field | `Replace=true` or deletion and recreation is the only path. Job `spec.selector`, Service `clusterIP`, PVC `resources.requests.storage` downward, and StatefulSet fields other than `replicas` and the pod template. |

The immutable-field case deserves care in the report: recreating a StatefulSet or a PVC
is data-destructive, and triage should name the constraint rather than recommend the
recreation.

## 6. Admission webhooks

The message names the webhook. Find what it is:

```bash
$KCTL get validatingwebhookconfigurations -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
```

A webhook that is *unreachable* rather than *denying* produces a different message —
`failed calling webhook ... connection refused` or `context deadline exceeded` — and is
an infrastructure fault, not a policy rejection. Its `failurePolicy: Fail` turns an
unreachable webhook into a blocked sync for every Application touching that kind.

Measure the blast radius before concluding:

```bash
$KCTL get applications.argoproj.io -A \
  -o jsonpath='{range .items[*]}{.metadata.name} {.status.operationState.phase}{"\n"}{end}' \
  | grep -c -E "Failed|Error"
```

## 7. Missing prerequisites

A sync that fails on the first resource of the first wave is usually a missing
prerequisite rather than a bad manifest.

- **Namespace does not exist.** Argo CD does not create it unless
  `CreateNamespace=true` is in `syncOptions`, or the namespace is in the manifests with
  an earlier sync wave.
- **CRD not installed.** A CRD and its CRs in the same sync need the CRD in an earlier
  wave, or `SkipDryRunOnMissingResource=true`.
- **Namespace terminating.** Every apply into it fails and nothing is wrong with the
  manifests.

```bash
$KCTL get ns <destination-namespace> -o jsonpath='{.status.phase}{"\n"}'
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" \
  -o jsonpath='{.spec.syncPolicy.syncOptions}{"\n"}'
```

## 8. Will it retry?

Whether this failure is self-correcting changes the recommendation entirely.

```bash
$KCTL get applications.argoproj.io "$APP" -n "$APP_NS" -o jsonpath=''\
'retry={.spec.syncPolicy.retry}{"\n"}'\
'retryCount={.status.operationState.retryCount}{"\n"}'
```

With no `retry` block, an auto-sync failure is **terminal for that revision**. The
controller logs `Skipping auto-sync: most recent sync already to <rev>` and will not
try again until a new commit arrives. This is why a transient failure — a webhook
blip, a brief quota breach — leaves an Application stuck `OutOfSync` long after the
cause has cleared. Say so explicitly: the condition is gone and the Application will
not recover on its own.

## 9. Report

Name the resource, quote the API server or hook message, and say which of sections 3
to 7 it falls into. Then state whether it will retry, because "this cleared an hour ago
and the Application will stay broken until someone syncs it" is usually the most
actionable sentence available.

If the cause is RBAC on an operator-managed instance, do not produce a Role or
RoleBinding manifest. Hand off to `skills/gitops/argo-operator`.
