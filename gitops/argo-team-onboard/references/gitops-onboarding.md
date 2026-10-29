<!-- Loaded on demand by skills/gitops/argo-team-onboard/SKILL.md. This is the RECOMMENDED
     onboarding model: a per-tenant values file in Git, rendered by a shared onboarding
     Helm chart, discovered by an ApplicationSet. -->

# GitOps Onboarding — Per-Tenant Values + Onboarding Chart

The recommended model. Onboarding a tenant means **adding one small values file to the
GitOps repo**. A shared Helm chart renders every object from it; an ApplicationSet
discovers the file and creates the Application that installs it.

Credit: this pattern follows Thomas Jungbauer's
[Project onboarding using GitOps and Helm](https://www.redhat.com/en/blog/project-onboarding-using-gitops-and-helm)
and the [Stormshift/OpenShift bootstrap](https://github.com/tjungbauer) work it comes from.

## Why this over committing rendered manifests

| | Rendered manifests per tenant | Per-tenant values + chart |
|---|---|---|
| Onboarding diff | 150+ lines of YAML to review | ~15 lines of intent |
| Changing the standard for everyone | Edit N tenants | Edit one chart |
| Reviewer burden | Must re-read boilerplate to spot the one odd field | Deviations are the only thing present |
| Drift between tenants | Accumulates silently | Structurally impossible |

Templating beats patching here: tenants genuinely differ in a handful of values
(namespaces, repos, groups, quota size), not in structure.

**When not to use it:** a one-off onboarding, or a team with no appetite for maintaining a
chart. Use `onboarding-guide.md` (rendered manifests) instead — it is a legitimate choice,
just a higher-maintenance one.

## Repository Layout

```
gitops-platform/
├── clusters/
│   └── all/
│       └── project-onboarding/        # Wrapper chart — the ApplicationSet's source
│           ├── Chart.yaml             # Depends on the onboarding chart below
│           └── values.yaml
├── charts/
│   └── helper-proj-onboarding/        # The templating engine
│       ├── Chart.yaml
│       └── templates/                 # Namespace, AppProject, quota, netpol, RBAC...
└── tenant-projects/
    ├── values-global.yaml             # Defaults, cluster list, t-shirt sizes
    ├── payments/
    │   └── cluster-local/
    │       └── values.yaml            # ← onboarding a tenant = adding this file
    └── checkout/
        └── cluster-local/
            └── values.yaml
```

One directory per tenant, one file per tenant-cluster pair. The path encodes *who* and
*where*; the file contents encode *what*.

## The Discovery ApplicationSet

Committed once by the platform team. After that, onboarding never touches it.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: project-onboarding
  namespace: openshift-gitops
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  generators:
    - git:
        repoURL: https://github.com/acme/gitops-platform.git
        revision: main
        files:
          - path: "tenant-projects/**/values.yaml"   # recursive: tenant/cluster/values.yaml
  template:
    metadata:
      name: 'onboarding-{{ index .path.segments 1 }}-{{ .path.basename }}'
    spec:
      project: default
      source:
        repoURL: https://github.com/acme/gitops-platform.git
        targetRevision: main
        path: clusters/all/project-onboarding
        helm:
          valueFiles:
            - /tenant-projects/values-global.yaml    # defaults first
            - /{{ .path.path }}/values.yaml          # tenant overrides second
      destination:
        server: https://kubernetes.default.svc
        namespace: openshift-gitops
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

**The `**` glob is what makes this self-maintaining** — a new
`tenant-projects/<team>/<cluster>/values.yaml` is picked up with no change to the
ApplicationSet. Note `values-global.yaml` is listed first so tenant values win.

> `.path.segments` is 0-indexed: for `tenant-projects/payments/cluster-local`, index 1 is
> `payments`. Verify the generated Application names on your first tenant.

## Global Values

`tenant-projects/values-global.yaml` — platform-wide defaults and the t-shirt sizes.

```yaml
global:
  application_gitops_namespace: gitops-application
  envs:
    - name: in-cluster
      url: https://kubernetes.default.svc
  allowed_source_repos:
    - https://github.com/acme/
  tshirt_sizes:
    - name: S
      quota:
        pods: 10
        requests: {cpu: "1",  memory: 2Gi}
        limits:   {cpu: "2",  memory: 4Gi}
      limitRange:
        default:        {cpu: 500m, memory: 512Mi}
        defaultRequest: {cpu: 100m, memory: 128Mi}
    - name: M
      quota:
        pods: 25
        requests: {cpu: "4",  memory: 8Gi}
        limits:   {cpu: "8",  memory: 16Gi}
      limitRange:
        default:        {cpu: "1", memory: 1Gi}
        defaultRequest: {cpu: 200m, memory: 256Mi}
    - name: L
      quota:
        pods: 60
        requests: {cpu: "12", memory: 24Gi}
        limits:   {cpu: "24", memory: 48Gi}
      limitRange:
        default:        {cpu: "2", memory: 2Gi}
        defaultRequest: {cpu: 500m, memory: 512Mi}
```

## Per-Tenant Values — the whole onboarding

`tenant-projects/payments/cluster-local/values.yaml`:

```yaml
oidc_groups: &oidc-group acme-payments-admins
environment:  &environment in-cluster

namespaces:
  - name: &ns payments-dev
    enabled: true
    project_size: "S"                    # inherit the S t-shirt size
    additional_settings:
      podsecurity_enforce: restricted    # Pod Security Standards
      cluster_monitoring: true           # opt into platform monitoring
    labels:
      team: payments
      environment: dev
    local_admin_group:                   # only when SSO groups are not IdP-synced
      enabled: false
      clusterrole: admin
      users: []
    networkpolicies:
      default_deny_egress: true          # see Default NetworkPolicies below
      allow_from_router: true
      allow_from_monitoring: true
      allow_same_namespace: true

argocd_rbac_setup:
  payments:
    enabled: true
    name: *ns
    sourceRepos:
      - https://github.com/acme/payments-svc.git
    destinations:
      - namespace: payments-dev
        server: https://kubernetes.default.svc
    rbac:
      - name: write
        oidc_groups: [*oidc-group]
        policies:
          - {action: sync, permission: allow}
          - {action: get,  permission: allow}
```

Overriding one value from the t-shirt size, without restating the rest:

```yaml
namespaces:
  - name: payments-prod
    project_size: "M"
    resourceQuotas:
      limits:
        cpu: "16"        # M gives 8; this tenant needs 16. Everything else stays M.
```

YAML anchors (`&ns` / `*ns`) keep the tenant name written once. Worth it — a tenant name
retyped five times is a tenant name that will eventually be typed wrong.

## Default NetworkPolicies

**Generate these for every tenant namespace.** A namespace with no NetworkPolicy accepts
traffic from every pod on the cluster, which silently undoes the AppProject boundary.
The AppProject `namespaceResourceBlacklist` stops *teams* from editing policies — it does
not create them. That is this chart's job.

Default-deny egress plus explicit allows:

```yaml
# 1. Deny all egress by default
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: payments-dev
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    # DNS must be allowed or everything breaks in confusing ways
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-dns
      ports:
        - {protocol: UDP, port: 5353}
        - {protocol: TCP, port: 5353}
---
# 2. Allow traffic within the tenant's own namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-same-namespace
  namespace: payments-dev
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: {}
---
# 3. Allow ingress from the OpenShift router (public routes)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-router
  namespace: payments-dev
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              policy-group.network.openshift.io/ingress: ""
---
# 4. Allow scraping by cluster monitoring
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-monitoring
  namespace: payments-dev
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              network.openshift.io/policy-group: monitoring
```

**Gotchas:**
- **Always allow DNS egress.** A bare default-deny-egress policy breaks name resolution,
  and the resulting failures look like application bugs, not policy bugs.
- Router and monitoring selector labels differ between OpenShift versions and on vanilla
  Kubernetes (where there is no `openshift-dns` or router namespace). Verify the labels on
  the target cluster before committing: `kubectl get ns --show-labels`.
- Egress-heavy tenants (external APIs, databases outside the cluster) need explicit allows
  — collect those during discovery rather than discovering them via an outage.

## Namespace Security Labels

Every tenant namespace should carry Pod Security Standards enforcement:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payments-dev
  labels:
    # Pod Security Standards — restricted is the correct default
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
    # Opt into platform monitoring
    openshift.io/cluster-monitoring: "true"
    app.kubernetes.io/part-of: tenant-onboarding
    team: payments
    environment: dev
```

Start at `restricted` and relax deliberately per tenant if a workload genuinely requires
it. Going the other way — onboarding at `privileged` and tightening later — rarely happens
once workloads depend on the looser setting.

## Two Argo CD Instances

This pattern assumes a split, and it is worth adopting:

| Instance | Scope | Owns |
|----------|-------|------|
| `openshift-gitops` (cluster-scoped) | Platform | The onboarding ApplicationSet, AppProjects, namespaces, quotas, policies |
| `gitops-application` (namespace-scoped) | Tenants | Teams' own Applications, within the boundary the platform instance created |

Teams never get write access to the instance that defines their own boundary — otherwise
the boundary is advisory. Alternatively, use apps-in-any-namespace on a single instance
(see `references/onboarding-guide.md`, *Apps-in-Any-Namespace RBAC*); the two-instance
split is the stronger isolation.

## Onboarding Checklist

1. Create `tenant-projects/<tenant>/<cluster>/values.yaml` from the schema above
2. Set `project_size`, or explicit quotas if the tenant does not fit a t-shirt size
3. Scope `sourceRepos` and `destinations` to exact values — never `*`
4. Confirm `podsecurity_enforce` and the NetworkPolicy toggles
5. `git diff` and walk the user through it
6. Commit / open a PR
7. Watch the ApplicationSet pick it up:
   `argocd app get onboarding-<tenant>-<cluster> --refresh`

## Common Mistakes

1. **Editing the ApplicationSet to add a tenant.** The `**/values.yaml` glob already
   matches. If you are editing the ApplicationSet, the layout is probably wrong.
2. **Listing tenant values before global values.** Helm applies `valueFiles` in order;
   global must come first or defaults overwrite tenant settings.
3. **Default-deny egress with no DNS allow.** See above — the most common self-inflicted
   outage in this pattern.
4. **`missingkey=error` with an incomplete values file.** The ApplicationSet fails to
   render rather than generating a half-configured tenant. That is correct behavior — read
   the applicationset-controller logs rather than removing the option.
5. **Letting the chart create a tenant's Application alongside the AppProject.** The chart
   owns the *boundary*; teams own what runs inside it. Blurring this puts the platform
   team back in the business of deploying tenant workloads.
