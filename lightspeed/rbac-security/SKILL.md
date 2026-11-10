---
name: rbac-security
description: Map proposed remediation actions to minimum-privilege Kubernetes RBAC rules. Given a proposal (what to fix, which resources), output the exact namespace, apiGroups, resources, resourceNames, and verbs needed for execution.
allowed-tools: Bash(oc:*) Bash(kubectl:*)
---

# RBAC Security — Minimum Privilege Permission Mapper

Given a proposal from the analysis agent, determine the least-privilege RBAC permissions the execution agent needs.

**Input:** Proposed actions (what to do, which resources to modify)
**Output:** `rbac` block with `namespaceScoped` and `clusterScoped` permission rules

## Rules

1. **Minimum privilege.** Request the narrowest verbs, resources, and scope possible.
   - Always use `resourceNames` when the target resource is known.
   - Always specify the target `namespace` for namespace-scoped rules.
   - Do NOT request access to child resources managed by controllers (e.g. ReplicaSets/Pods for a Deployment). Verify via the parent's `status.conditions`.
   - When in doubt, request less — insufficient permissions retry with enriched context; over-granted permissions are a security risk.

2. **Never request denied permissions.** The operator rejects these regardless:
   - `rbac.authorization.k8s.io/*` — RBAC manipulation
   - `apiextensions.k8s.io/*` — CRD creation
   - `admissionregistration.k8s.io/*` — webhook creation
   - `ols.openshift.io/*` — self-modification
   - `pods/exec`, `pods/attach` — container escape
   - `serviceaccounts/token` — token generation
   - `authentication.k8s.io/*` — impersonation

3. **Never target protected namespaces:** `kube-system`, `kube-public`, `kube-node-lease`, `openshift-*`, `default`

4. **No wildcards.** Never use `"*"` in verbs or resources.

## Operation-to-RBAC Map

| Operation | apiGroups | Resources | Verbs |
|-----------|-----------|-----------|-------|
| Patch deployment | `apps` | `deployments` | `get`, `patch` |
| Scale deployment | `apps` | `deployments/scale` | `get`, `patch` |
| Rollout restart | `apps` | `deployments` | `get`, `patch` |
| Delete pod | `""` | `pods` | `delete` |
| Read/update configmap | `""` | `configmaps` | `get`, `update` |
| Read/update secret | `""` | `secrets` | `get`, `update` |
| Create service | `""` | `services` | `create` |
| Create route (OCP) | `route.openshift.io` | `routes` | `create` |
| Cordon/uncordon node | `""` | `nodes` | `get`, `patch` |
| Install operator | `operators.coreos.com` | `subscriptions` | `create`, `get` |
| Create PVC | `""` | `persistentvolumeclaims` | `create` |

Same patterns apply to `statefulsets`, `daemonsets` in `apps`.

**Namespace vs Cluster scope:** Deployments, Pods, Services, ConfigMaps, Secrets, PVCs → Namespace. Nodes, PVs, Namespaces, StorageClasses → Cluster.

## Watch For

- `create pods` — can hijack SAs in the namespace (check SCC/PSA enforcement)
- `get/list secrets` — exposes all secret data in namespace
- `create pods` + `anyuid/privileged SCC` — container escape
- `patch namespaces` — can weaken PSA labels
- `create persistentvolumes` with hostPath — host filesystem access

## Example

Proposal: "Patch deployment/frontend in namespace app-prod to fix OOMKill by increasing memory limit."

```json
{
  "rbac": {
    "namespaceScoped": [
      {
        "namespace": "app-prod",
        "apiGroups": ["apps"],
        "resources": ["deployments"],
        "resourceNames": ["frontend"],
        "verbs": ["get", "patch"],
        "justification": "Read current spec and patch resource limits on deployment/frontend"
      }
    ],
    "clusterScoped": []
  }
}
```

One rule. Scoped to one resource in one namespace. No child resource access.
