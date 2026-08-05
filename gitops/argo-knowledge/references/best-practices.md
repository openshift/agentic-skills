# Argo Best Practices Reference

## Sync Policy Recommendations

### Production Applications

```yaml
syncPolicy:
  automated:
    prune: true                         # Enable — but only after testing in lower envs
    selfHeal: true                      # Prevent manual drift
    allowEmpty: false                   # Safety: never sync zero manifests
  syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true              # Handles large CRDs, avoids annotation limits
    - PruneLast=true                    # Delete removed resources after new ones are healthy
    - RespectIgnoreDifferences=true     # Don't revert fields you explicitly ignore
  retry:
    limit: 5
    backoff:
      duration: 5s
      factor: 2
      maxDuration: 3m
```

### Checklist

- [ ] `prune: true` tested in dev/staging before production
- [ ] `selfHeal: true` enabled to prevent drift
- [ ] `allowEmpty: false` (default) — never disable in production
- [ ] `retry` configured to handle transient failures
- [ ] `PruneLast=true` to avoid downtime during resource replacement
- [ ] `ServerSideApply=true` for CRDs and large resources
- [ ] `targetRevision` pinned to a tag or SHA in production (never `HEAD`)
- [ ] `ignoreDifferences` configured for controller-managed fields (e.g., replicas with HPA)
- [ ] `RespectIgnoreDifferences=true` if using `ignoreDifferences`

## Resource Tracking Method Selection

| Method | When to Use |
|--------|------------|
| `annotation` (default) | Most cases. No conflicts with other tools. |
| `label` | You need to query Argo-managed resources via label selectors. |
| `annotation+label` | Migrating from label to annotation tracking. Both tools need to find the resources. |

**Recommendation:** Use `annotation` (default). Only use `label` or `annotation+label` if you have a specific need.

Configured in `argocd-cm`:
```yaml
data:
  resource.trackingMethod: annotation
```

## Health Check Customization

### When to Add Custom Health Checks

- CRDs that Argo CD doesn't know about (custom operators, third-party CRDs)
- Override default health logic (e.g., treat a specific condition as healthy)
- Rollout, AnalysisRun, and other Argo CRDs (built-in support, but you may need to tune)

### Best Practices

- [ ] Custom health checks for all CRDs your Applications manage
- [ ] Health checks should be conservative — prefer `Progressing` over `Healthy` when uncertain
- [ ] Test health check Lua scripts against real resource states
- [ ] Document custom health checks in your platform runbook

### Example: Custom Health Check for a CRD

```yaml
# argocd-cm ConfigMap
data:
  resource.customizations.health.myorg.io_MyResource: |
    hs = {}
    if obj.status ~= nil and obj.status.conditions ~= nil then
      for _, condition in ipairs(obj.status.conditions) do
        if condition.type == "Ready" then
          if condition.status == "True" then
            hs.status = "Healthy"
            hs.message = condition.message
          elseif condition.status == "False" then
            hs.status = "Degraded"
            hs.message = condition.message
          else
            hs.status = "Progressing"
            hs.message = "Waiting for Ready condition"
          end
          return hs
        end
      end
    end
    hs.status = "Progressing"
    hs.message = "No status available"
    return hs
```

## RBAC Layering

### Architecture

```
SSO Provider (OIDC/SAML)
  └── Groups (org:team-a, org:platform-admins)
        └── Argo CD RBAC (argocd-rbac-cm)
              └── AppProject Roles
                    └── Source/Destination Restrictions
```

### Layer 1: Global RBAC (argocd-rbac-cm)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly         # Default for authenticated users
  policy.csv: |
    # Platform admins — full access
    g, org:platform-admins, role:admin

    # Team roles — scoped to projects
    p, role:team-deployer, applications, sync, */*, allow
    p, role:team-deployer, applications, get, */*, allow
    p, role:team-deployer, applications, action/*, */*, allow
    g, org:deployers, role:team-deployer

    # Read-only for everyone else
    p, role:readonly, applications, get, */*, allow
    p, role:readonly, logs, get, */*, allow
  scopes: '[groups, email]'
```

### Layer 2: Project-Level RBAC

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
spec:
  roles:
    - name: admin
      policies:
        - p, proj:team-a:admin, applications, *, team-a/*, allow
      groups:
        - org:team-a-leads
    - name: deployer
      policies:
        - p, proj:team-a:deployer, applications, get, team-a/*, allow
        - p, proj:team-a:deployer, applications, sync, team-a/*, allow
      groups:
        - org:team-a
```

### Layer 3: Source/Destination Restrictions

```yaml
spec:
  sourceRepos:
    - https://github.com/org/team-a-*.git
  destinations:
    - server: https://kubernetes.default.svc
      namespace: team-a-*
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
```

### Checklist

- [ ] SSO configured with group claims
- [ ] `policy.default: role:readonly` in `argocd-rbac-cm`
- [ ] Platform admins mapped to `role:admin`
- [ ] Per-team AppProjects with source/destination restrictions
- [ ] Project roles mapped to SSO groups
- [ ] Sync windows for production projects
- [ ] No team has `clusterResourceWhitelist: [{group: '*', kind: '*'}]` unless justified

## ApplicationSet vs App-of-Apps Selection

| Criteria | Use ApplicationSet | Use App-of-Apps |
|----------|-------------------|----------------|
| # Applications | > 20 | < 20 |
| Pattern-based | Yes (all apps look similar) | No (each app is unique) |
| Auto-discovery needed | Yes | No |
| Multi-cluster | Yes (cluster generator) | Manual per cluster |
| Progressive rollout | Yes (rollingSync) | Manual (sync waves) |
| Per-app customization | Limited (template + patch) | Full (each is a manifest) |
| Bootstrap | No (needs Argo CD running) | Yes (root app bootstraps) |

**Common pattern:** Use app-of-apps to bootstrap the cluster (install Argo CD, CRDs, platform components) and ApplicationSets for application workloads.

## Rollout Adoption Strategy

### Migration Path: Deployment to Rollout

1. **Start with `Rollout` that mirrors your current `Deployment`:**
   ```yaml
   apiVersion: argoproj.io/v1alpha1
   kind: Rollout
   spec:
     strategy:
       canary:
         steps:
           - setWeight: 100             # Immediate 100% — same as Deployment
   ```

2. **Add a simple canary step:**
   ```yaml
   steps:
     - setWeight: 20
     - pause: { duration: 5m }
     - setWeight: 100
   ```

3. **Add analysis:**
   ```yaml
   steps:
     - setWeight: 20
     - analysis:
         templates:
           - templateName: success-rate
     - setWeight: 100
   ```

4. **Add traffic routing (if using service mesh/ingress controller).**

### Checklist

- [ ] Install Argo Rollouts controller
- [ ] Create canary and stable Services
- [ ] Replace `Deployment` with `Rollout` (same pod template)
- [ ] Start with simple weight-based steps, no analysis
- [ ] Add AnalysisTemplates with `dryRun` first to validate metrics without blocking rollouts
- [ ] Remove `dryRun` once metrics are validated
- [ ] Configure traffic routing if available
- [ ] Set up Rollouts dashboard/notifications

## Workflow Resource Management

### Checklist

- [ ] **Always set `activeDeadlineSeconds`** — stuck workflows consume resources forever
- [ ] **Configure `podGC`** — completed pods accumulate without it
- [ ] **Set `ttlStrategy`** — auto-delete completed workflow CRs
- [ ] **Use `retryStrategy`** with `backoff` for transient failures
- [ ] **Limit `parallelism`** — prevent thundering herd
- [ ] **Use `resourceQuota`** in the workflow namespace
- [ ] **Archive workflows** to PostgreSQL/MySQL for long-term storage
- [ ] **Use `workflowTemplateRef`** — avoid duplicating templates
- [ ] **Set `podPriorityClassName`** for production workflows

### Resource Defaults

Configure defaults in the Workflow Controller ConfigMap:

```yaml
# workflow-controller-configmap
data:
  workflowDefaults: |
    spec:
      activeDeadlineSeconds: 7200
      ttlStrategy:
        secondsAfterCompletion: 86400
        secondsAfterSuccess: 3600
        secondsAfterFailure: 259200
      podGC:
        strategy: OnPodSuccess
        deleteDelayDuration: 120s
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
```

## Secret Management Approaches

### Option 1: Sealed Secrets (Bitnami)

```yaml
# Encrypt secrets client-side, store encrypted SealedSecret in Git
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: my-secret
  namespace: my-app
spec:
  encryptedData:
    password: AgByz+...  # Encrypted with cluster's public key
```

- **Pro:** Secrets stored in Git (encrypted). Works with any GitOps workflow.
- **Con:** Cluster-specific encryption. Re-seal needed for each cluster.

### Option 2: External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: my-secret
  namespace: my-app
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: my-secret
  data:
    - secretKey: password
      remoteRef:
        key: secret/my-app
        property: password
```

- **Pro:** Secrets live in a vault (Vault, AWS SM, GCP SM, Azure KV). Git only has references.
- **Con:** Requires External Secrets Operator + secret store infrastructure.

### Option 3: Vault CSI Provider

```yaml
# Mount secrets as volumes via CSI driver
spec:
  volumes:
    - name: secrets
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: vault-secrets
```

- **Pro:** No Kubernetes Secret objects created. Secrets injected directly.
- **Con:** Requires CSI driver + Vault Agent. More complex setup.

### Option 4: SOPS + Kustomize/Helm Secrets Plugin

Encrypt values in-place within YAML files using SOPS:

```bash
sops --encrypt --in-place secrets.yaml
```

Use Argo CD config management plugin to decrypt during sync.

- **Pro:** Encrypted files in Git. Works with existing tooling.
- **Con:** Requires config management plugin setup. Key management complexity.

### Recommendation

| Team Size | Infrastructure | Recommendation |
|-----------|---------------|---------------|
| Small | Simple | Sealed Secrets |
| Medium | Cloud-native | External Secrets Operator |
| Large | Enterprise | Vault + External Secrets or CSI |
| Any | Already using SOPS | SOPS plugin |

### Checklist

- [ ] Never store plaintext secrets in Git
- [ ] Choose one approach and standardize across all teams
- [ ] Automate secret rotation
- [ ] Audit secret access
- [ ] Test secret sync with Argo CD (ensure CMP or operator is healthy before Application sync)

## Argo CD High Availability

### Checklist

- [ ] Run at least 2 replicas of `argocd-server`
- [ ] Run at least 2 replicas of `argocd-repo-server`
- [ ] Run single `argocd-application-controller` with sharding for large-scale
- [ ] Redis HA (Sentinel or Redis Cluster) for caching
- [ ] Increase `--repo-server-timeout-seconds` for large repos
- [ ] Configure `resource.exclusions` to skip resources you don't need to track
- [ ] Set `--app-resync` interval based on scale (default 180s may be too frequent at scale)
- [ ] Monitor Argo CD metrics (Prometheus endpoint at `:8082/metrics`)

## Multi-Tenancy Checklist

- [ ] One AppProject per team/tenant
- [ ] Source repos restricted per project
- [ ] Destination namespaces restricted per project
- [ ] Cluster-scoped resource access denied by default
- [ ] SSO groups mapped to project roles
- [ ] Sync windows for production namespaces
- [ ] Network policies between tenant namespaces
- [ ] Resource quotas per namespace
- [ ] Separate Argo CD instances for hard multi-tenancy (if needed)
