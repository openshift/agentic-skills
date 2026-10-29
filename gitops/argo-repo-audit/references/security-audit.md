# Argo CD Security Audit Checklist

Audit the repository against each category. Use the scanning commands to find specific issues.

---

## AppProject Restrictions

- [ ] No wildcard `*` in `spec.sourceRepos` for production projects
- [ ] No wildcard `*` in `spec.destinations[].server` for production projects
- [ ] No wildcard `*` in `spec.destinations[].namespace` for production projects
- [ ] `spec.clusterResourceWhitelist` explicitly scoped (not `group: '*', kind: '*'`)
- [ ] `spec.namespaceResourceBlacklist` configured to deny sensitive resources:
  - `kind: Secret` (if secrets should only come from sealed-secrets/external-secrets)
  - `kind: ResourceQuota` (if managed by platform team)
  - `kind: LimitRange` (if managed by platform team)
- [ ] `spec.orphanedResources.warn: true` enabled to detect resources not tracked by any Application
- [ ] `spec.sourceNamespaces` restricted if multi-tenant (Argo CD 2.5+)
- [ ] `spec.permitOnlyProjectScopedClusters: true` where applicable (Argo CD 2.12+)

### Scanning: Find wildcard sourceRepos

```bash
grep -rn "sourceRepos" <repo-root> --include="*.yaml" --include="*.yml" | grep -E "'\*'|\"\\*\""
```

### Scanning: Find wildcard destinations

```bash
grep -rn -A5 "destinations:" <repo-root> --include="*.yaml" --include="*.yml" | grep -E "server:.*'\*'|namespace:.*'\*'|server:.*\"\\*\"|namespace:.*\"\\*\""
```

### Scanning: Find unrestricted clusterResourceWhitelist

```bash
grep -rn -A3 "clusterResourceWhitelist" <repo-root> --include="*.yaml" --include="*.yml" | grep -E "group:.*'\*'|kind:.*'\*'"
```

### Scanning: Find *enumerated* but privilege-escalating clusterResourceWhitelist

**The wildcard scan above is not sufficient, and this is the more common real-world case.**
An explicitly enumerated whitelist that grants cluster-scoped RBAC or admission kinds
contains no `*`, passes every wildcard grep, and reads as careful least-privilege in
review — while voiding the AppProject's `destinations` scoping entirely.

A team allowed to commit a `ClusterRoleBinding` can bind themselves `cluster-admin`, and
the Argo CD controller — which runs privileged — will apply it. Namespace scoping is
irrelevant at that point.

```bash
# Escalation-capable kinds that should essentially never be team-whitelisted
grep -rn -A20 "clusterResourceWhitelist" <repo-root> --include="*.yaml" --include="*.yml" | \
  grep -E "kind:[[:space:]]*(ClusterRole|ClusterRoleBinding|RoleBinding|CustomResourceDefinition|MutatingWebhookConfiguration|ValidatingWebhookConfiguration|SecurityContextConstraints|PodSecurityPolicy|APIService|StorageClass|PriorityClass)"
```

| Kind | Why it is an escalation |
|------|------------------------|
| `ClusterRole`, `ClusterRoleBinding` | Self-grant any permission cluster-wide, including cluster-admin |
| `RoleBinding` | Bind existing powerful ClusterRoles into any namespace in reach |
| `CustomResourceDefinition` | Cluster-scoped; can shadow or conflict with platform CRDs |
| `MutatingWebhookConfiguration`, `ValidatingWebhookConfiguration` | Intercept and rewrite *all* cluster API traffic |
| `SecurityContextConstraints` (OpenShift), `PodSecurityPolicy` | Grant themselves privileged pod execution |
| `APIService` | Hijack aggregated API endpoints |
| `StorageClass`, `PriorityClass` | Cluster-wide resource and scheduling impact |

Report any hit as **Critical**, even with no wildcard present. Expected safe entries are
narrow and app-shaped — the team's own CRDs, or `Namespace` when they self-provision.

### Scanning: Find scoped-but-dangerous project role policies

The triple-wildcard RBAC grep further down misses project-scoped grants that are still too
broad: a wildcard *action* on a narrowly scoped resource, and any `exec` grant.

```bash
# Wildcard action (applications, *) even when the project/app scope is narrow
grep -rn -E "p,[^,]+,[[:space:]]*applications[[:space:]]*,[[:space:]]*\*" <repo-root> --include="*.yaml" --include="*.yml" --include="*.csv"

# Any exec grant, at any scope — not just */*
grep -rn -E "p,[^,]+,[[:space:]]*exec[[:space:]]*,[[:space:]]*create" <repo-root> --include="*.yaml" --include="*.yml" --include="*.csv"
```

`applications, *` includes `delete` and `override`, and lets the holder edit the
Application spec — including repointing `source` outside the intended repo. `exec, create`
gives a shell in any pod in scope, which exposes mounted ServiceAccount tokens and bypasses
Kubernetes audit attribution. Scope to `get`, `sync`, and at most `override`.

---

## RBAC and Authentication

- [ ] SSO configured (OIDC, SAML, or Dex connector) — not relying solely on local admin account
- [ ] RBAC policies in `argocd-rbac-cm` ConfigMap restrict access by project/application:
  - `p, <role>, applications, <action>, <project>/<app>, allow`
  - NOT `p, <role>, applications, *, */*, allow`
- [ ] Default policy is read-only or deny:
  - `policy.default: role:readonly` (safe default)
  - NOT `policy.default: role:admin`
- [ ] Admin access limited:
  - `admin.enabled: "false"` in `argocd-cm` for production
  - No broad `p, *, *, *, *, allow` rules
- [ ] `exec` resource disabled for production:
  - No `p, <role>, exec, create, */*, allow` (prevents terminal access to pods)
- [ ] Project-scoped roles use JWTs with expiration (`spec.roles[].jwtTokens`)
- [ ] `g, <sso-group>, role:admin` mappings limited to platform team groups

### Scanning: Find overly permissive RBAC

```bash
grep -rn "p,.*\*.*\*.*\*.*allow" <repo-root> --include="*.yaml" --include="*.yml" --include="*.csv"
```

### Scanning: Find admin access

```bash
grep -rn "role:admin" <repo-root> --include="*.yaml" --include="*.yml"
```

---

## Secrets Management

- [ ] No plain-text `kind: Secret` manifests committed to Git
- [ ] Secrets managed via one of:
  - **SealedSecret** (`kind: SealedSecret`, bitnami-labs/sealed-secrets)
  - **ExternalSecret** (`kind: ExternalSecret`, external-secrets/external-secrets)
  - **SOPS** (`.sops.yaml` config, encrypted `data`/`stringData` in Secret manifests)
  - **Vault** (Vault Agent injector annotations or Vault Secrets Operator)
  - **Argo CD Vault Plugin** (AVP `<path:...>` placeholders)
- [ ] Cluster credentials (`kind: Secret` with `argocd.argoproj.io/secret-type: cluster`) not stored in plain text
- [ ] Repository credentials managed via:
  - `argocd-repo-creds` pattern (credential templates)
  - External secret management
  - NOT plain `kind: Secret` with `argocd.argoproj.io/secret-type: repository`
- [ ] SSH private keys not committed in plain text (check for `sshPrivateKey:` fields)
- [ ] `.sops.yaml` present if SOPS is used, with appropriate key configuration
- [ ] No `stringData:` or `data:` in Secret manifests with base64 values (unless SOPS-encrypted)

### Scanning: Find plain-text secrets

```bash
# Find Secret manifests (excluding SealedSecret, ExternalSecret)
grep -rn "kind: Secret" <repo-root> --include="*.yaml" --include="*.yml" -l | while read f; do
  if ! grep -q "kind: SealedSecret\|kind: ExternalSecret\|sops:" "$f" 2>/dev/null; then
    echo "PLAIN-TEXT SECRET: $f"
  fi
done
```

### Scanning: Find hardcoded credentials and keys

```bash
<repo-root>/scripts/scan-credentials.sh <repo-root>
```

**Use the script, not a bare `grep`.** The obvious one-liner —

```bash
grep -rn -iE "(password|token|secret):" <repo-root>    # DO NOT
```

— prints the whole matching line, which puts the credential itself into the
conversation. An audit that leaks the thing it is auditing for is worse than no audit.
The finding is the **location**, never the value.

`scan-credentials.sh` reports file, line, key name and value *length*, which is enough
to triage severity and find the string yourself. It also separates three cases a plain
grep conflates:

| Classified as | Meaning |
|---|---|
| `PLAINTEXT` | a real finding — treat as compromised, it is in git history |
| `encrypted at rest` | SOPS or SealedSecret ciphertext in the same key — **not** a finding |
| `marked synthetic / templated` | `# notsecret`, `EXAMPLE-`, `CHANGEME`, `${VAR}`, `{{ }}` |

That last distinction matters: flagging SealedSecret ciphertext as a plaintext password
is the false positive that teaches people to ignore the scanner.

If you must inspect a value to judge severity, say so and ask first — do not print it
unprompted.

**Known limits of the scanner — read the Secret yourself as well.**

- It keys off credential-ish *key names*, so it does not flag `username:`, `user:` or
  `host:` even when they sit in the same committed Secret as a password it did flag.
  Those are part of the same exposure. When a hit lands inside a `kind: Secret`, treat
  every key in that object's `data`/`stringData` as exposed and say so — by key name,
  not by value.
- A value marked `EXAMPLE-` or `# notsecret` is classified synthetic and excluded from
  the plaintext count. That is right for severity and wrong for the *pattern*: a marker
  inside a `values: |` block scalar is passed to Helm verbatim, so a placeholder still
  becomes the live credential. Report the anti-pattern even when the value is synthetic.
- It reads YAML and JSON only. Credentials in a `.env`, a shell script or a Dockerfile
  committed alongside the manifests are not scanned.

A clean scan means "no credential-shaped key matched", not "this repo holds no
secrets". Say which of those you are reporting.

### Scanning: Find cluster secrets

```bash
grep -rn "argocd.argoproj.io/secret-type: cluster" <repo-root> --include="*.yaml" --include="*.yml" -l
```

---

## Cluster Security

- [ ] In-cluster Argo CD permissions scoped appropriately:
  - `argocd-application-controller` ServiceAccount not bound to `cluster-admin` if possible
  - Namespace-scoped installation considered for single-namespace deployments
- [ ] External clusters added with minimal RBAC:
  - Service account token with scoped ClusterRole/Role
  - NOT using `cluster-admin` bearer token
- [ ] TLS verification enabled for external clusters:
  - `tlsClientConfig.insecure: false` (or field absent, which defaults to false)
  - `tlsClientConfig.caData` populated for self-signed CAs
- [ ] Cluster credentials rotated (short-lived tokens or automated rotation)

### Scanning: Find insecure TLS config

```bash
# Matches both YAML (insecure: true) and the quoted-JSON form that appears inside an
# Argo CD cluster Secret's embedded `config` blob ("insecure": true) — the latter is how
# it actually shows up in practice and the plain YAML pattern misses it entirely.
grep -rniE '"?insecure"?[[:space:]]*:[[:space:]]*"?true' <repo-root> --include="*.yaml" --include="*.yml"
```

---

## Network and Access

- [ ] Argo CD server exposed behind ingress with TLS termination
- [ ] GRPC configured properly:
  - Single port with `--insecure` flag + TLS at ingress, OR
  - Separate GRPC ingress with HTTP/2 support
- [ ] Rate limiting configured on API server (via ingress annotations or Argo CD flags)
- [ ] Dex/OIDC callback URLs restricted to known domains
- [ ] Web UI CSP headers configured if using reverse proxy
- [ ] `server.rootpath` set if behind a subpath reverse proxy

### Scanning: Find ingress without TLS

```bash
grep -rn -A10 "kind: Ingress" <repo-root> --include="*.yaml" --include="*.yml" | grep -B5 "host:" | grep -v "tls:"
```

---

## Supply Chain

- [ ] Image tags pinned to digests or immutable tags (not `latest`) in deployed manifests
- [ ] Repository webhooks use shared secrets for authentication
- [ ] Argo CD notifications configured for sync failures (Slack, email, webhook)
- [ ] Git commit signing verification enabled if available (`gpg.enabled: "true"` in argocd-cm)
- [ ] `kustomize.buildOptions` does not include `--enable-exec` or `--enable-alpha-plugins` without review

---

## OpenShift-Specific Security

When the repo targets OpenShift (look for `Route`, `ArgoCD` CRD, `DeploymentConfig`,
or `SecurityContextConstraints` resources):

- [ ] **ArgoCD CRD uses `argoproj.io/v1beta1`** — not the older `v1alpha1` ArgoCD CRD
- [ ] **Route TLS termination** — should be `reencrypt` or `edge`, flag `passthrough` without justification
- [ ] **OAuth enabled** — `spec.dex.openShiftOAuth: true` for SSO integration
- [ ] **Resource exclusions configured** — exclude Tekton TaskRun/PipelineRun, compliance, OLM resources
- [ ] **No DeploymentConfig with Rollouts** — Argo Rollouts does not support DeploymentConfig
- [ ] **SCC bindings for Workflow ServiceAccounts** — workflow pods need appropriate SCC
- [ ] **Managed-by labels on target namespaces** — `argocd.argoproj.io/managed-by` points to correct instance
- [ ] **No namespace managed by multiple ArgoCD instances** — causes reconciliation conflicts
- [ ] **Namespace-scoped instances not elevated** — team instances should NOT be cluster-scoped (security risk)
- [ ] **RBAC maps actual OpenShift groups** — `policy` in ArgoCD CR references real group names from OAuth

### Scanning: Find OpenShift-specific issues

```bash
# Find ArgoCD CRDs
grep -rn "kind: ArgoCD" <repo-root> --include="*.yaml" --include="*.yml"

# Find DeploymentConfig (flag if Rollouts also present)
grep -rn "kind: DeploymentConfig" <repo-root> --include="*.yaml" --include="*.yml"

# Find Routes without TLS
grep -rn -A5 "kind: Route" <repo-root> --include="*.yaml" --include="*.yml" | grep -L "tls:"

# Find namespace-scoped instances with cluster permissions
grep -rn -B2 -A10 "kind: ArgoCD" <repo-root> --include="*.yaml" --include="*.yml" | grep -A10 "namespace:" | grep "clusterScoped\|cluster-admin"
```

---

### Scanning: Find mutable image tags

```bash
grep -rn "image:" <repo-root> --include="*.yaml" --include="*.yml" | grep -E ":latest\"|:latest$" | grep -v "#"
```
