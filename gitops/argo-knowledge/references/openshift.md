# OpenShift GitOps

Reference for running the Argo ecosystem on OpenShift — covers the OpenShift GitOps
Operator, the `ArgoCD` CRD, Routes, SCCs, and platform-specific patterns.

## OpenShift GitOps Operator

OpenShift GitOps is Red Hat's supported distribution of Argo CD, installed via OLM
(Operator Lifecycle Manager). It manages Argo CD instances declaratively through the
`ArgoCD` custom resource.

**Key differences from upstream Argo CD:**
- Installed via OperatorHub, not Helm or raw manifests
- Default namespace is `openshift-gitops` (not `argocd`)
- Managed via `ArgoCD` CRD (not ConfigMaps directly)
- Includes Argo CD Agent Mode (GA in OpenShift GitOps 1.19)
- Integrated with OpenShift OAuth for SSO out of the box
- Uses `Route` objects for UI access (not `Ingress`)

### ArgoCD CRD

The operator watches for `ArgoCD` custom resources and reconciles Argo CD components:

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: argocd
  namespace: openshift-gitops
spec:
  server:
    autoscale:
      enabled: true
    route:
      enabled: true
      tls:
        termination: reencrypt
  controller:
    resources:
      limits:
        cpu: "2"
        memory: 4Gi
      requests:
        cpu: 500m
        memory: 1Gi
  repo:
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
      requests:
        cpu: 250m
        memory: 256Mi
  redis:
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
  ha:
    enabled: false
  rbac:
    defaultPolicy: role:readonly
    policy: |
      g, cluster-admins, role:admin
      g, dev-team, role:readonly
    scopes: '[groups]'
  resourceExclusions: |
    - apiGroups:
      - tekton.dev
      kinds:
      - TaskRun
      - PipelineRun
  applicationSet:
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
  notifications:
    enabled: true
```

### Cluster-Scoped vs Namespace-Scoped Instances

**Cluster-scoped** (default in `openshift-gitops` namespace):
- Can manage resources across all namespaces
- Required for "Applications in any namespace" feature
- The default instance created by the operator is cluster-scoped

**Namespace-scoped** (team instances):
- Created in any namespace by users with appropriate RBAC
- Can only manage resources in explicitly granted namespaces
- Ideal for team-level GitOps isolation

```yaml
apiVersion: argoproj.io/v1beta1
kind: ArgoCD
metadata:
  name: team-argocd
  namespace: team-frontend
spec:
  server:
    route:
      enabled: true
  sourceNamespaces:
    - team-frontend
    - team-frontend-staging
```

To extend a namespace-scoped instance to manage other namespaces, label the target
namespace:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-frontend-staging
  labels:
    argocd.argoproj.io/managed-by: team-frontend
```

## OpenShift-Specific Patterns

### Routes Instead of Ingress

OpenShift uses `Route` objects. When generating Application manifests, prefer `Route`
over `Ingress` unless targeting multi-cloud:

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: frontend
spec:
  to:
    kind: Service
    name: frontend
  port:
    targetPort: 8080
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

When auditing repos, check if Applications deploy both `Route` and `Ingress` — this
is usually redundant.

### SecurityContextConstraints (SCCs)

OpenShift replaces PodSecurityPolicies with SCCs. When deploying Argo Rollouts or
Workflows on OpenShift:

- **Rollout pods** need appropriate SCC. The `restricted-v2` SCC (default) works for
  most containers. If Rollout pods need elevated permissions, create a dedicated
  ServiceAccount and bind it to the required SCC.
- **Workflow pods** often need broader permissions (artifact upload, Docker builds).
  Use a dedicated ServiceAccount with `nonroot-v2` or custom SCC.
- **AnalysisTemplate Job pods** inherit the Rollout's ServiceAccount unless overridden.
  Verify the SA has the right SCC for the analysis container.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: workflow-sa-scc
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:nonroot-v2
subjects:
  - kind: ServiceAccount
    name: workflow-sa
    namespace: argo
```

### DeploymentConfig Considerations

Legacy OpenShift workloads may use `DeploymentConfig` instead of `Deployment`. Argo CD
can manage DeploymentConfigs, but:

- **Health checks** — Argo CD has a built-in health check for DeploymentConfig
- **Rollouts** — Argo Rollouts does NOT support DeploymentConfig. Migrate to
  `Deployment` before adopting Rollouts
- **Resource tracking** — DeploymentConfig uses a different rollout mechanism
  (`oc rollout`) that can conflict with Argo CD sync

### OAuth Integration

OpenShift GitOps integrates with OpenShift OAuth by default. The ArgoCD CR can configure
Dex with OpenShift as an OIDC provider:

```yaml
spec:
  dex:
    openShiftOAuth: true
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
  rbac:
    defaultPolicy: role:readonly
    policy: |
      g, cluster-admins, role:admin
    scopes: '[groups]'
```

Groups from OpenShift are passed through to Argo CD RBAC policies via the `scopes`
field. Map OpenShift groups to Argo CD roles in the `policy` field.

### Resource Exclusions

OpenShift clusters have many operator-managed resources that create noise in Argo CD.
Common exclusions:

```yaml
spec:
  resourceExclusions: |
    - apiGroups:
      - tekton.dev
      kinds:
      - TaskRun
      - PipelineRun
    - apiGroups:
      - compliance.openshift.io
      kinds:
      - ComplianceCheckResult
      - ComplianceRemediation
    - apiGroups:
      - operators.coreos.com
      kinds:
      - InstallPlan
      - CatalogSource
```

### Managed Namespaces

The OpenShift GitOps operator creates managed namespaces by default:
- `openshift-gitops` — cluster-scoped Argo CD instance
- The operator automatically grants the Argo CD instance permissions over namespaces
  labeled with `argocd.argoproj.io/managed-by`

When auditing, check that:
- Production namespaces have the `managed-by` label pointing to the correct ArgoCD instance
- No namespace is managed by multiple ArgoCD instances (causes conflicts)
- The `openshift-gitops` namespace is not used for team Applications (use separate namespaces)

## OpenShift GitOps Agent (GA in 1.19)

The Argo CD Agent is GA in OpenShift GitOps 1.19. OpenShift-specific considerations:

- **Installation:** Deployed via the OpenShift GitOps operator on both hub and spoke clusters
- **Hub cluster:** Runs the principal component alongside the ArgoCD instance
- **Spoke clusters:** Run the agent component with a local Argo CD stack
- **Authentication:** Uses OpenShift certificate infrastructure for mTLS
- **Network:** Agent initiates outbound connections — works with OpenShift's default
  network policies and egress controls

See `references/agent-mode.md` for the full agent architecture.

## Audit Checklist for OpenShift

When auditing Argo CD repos targeting OpenShift:

- [ ] **ArgoCD CRD used** — check for `apiVersion: argoproj.io/v1beta1 kind: ArgoCD` (operator-managed)
- [ ] **Route configured** — ArgoCD CR has `spec.server.route.enabled: true`
- [ ] **TLS termination** — Route uses `reencrypt` or `edge`, not `passthrough` without good reason
- [ ] **OAuth enabled** — `spec.dex.openShiftOAuth: true` for SSO
- [ ] **Resource exclusions** — Tekton, compliance, OLM resources excluded to reduce noise
- [ ] **No DeploymentConfig with Rollouts** — flag DeploymentConfig in repos using Argo Rollouts
- [ ] **SCC bindings for Workflow ServiceAccounts** — verify pods won't fail due to SCC restrictions
- [ ] **Managed-by labels** — target namespaces labeled for the correct ArgoCD instance
- [ ] **No conflicting management** — no namespace managed by multiple ArgoCD instances
- [ ] **RBAC maps OpenShift groups** — ArgoCD RBAC `policy` references actual OpenShift groups
