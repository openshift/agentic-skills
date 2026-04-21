# Kubernetes Documentation Reference

Repository: `kubernetes/website`
Docs path: `content/en/docs/`
Versioning: Git branches (`release-X.Y`). Use `?ref=$VERSION` in all API calls.

## Discovering Available Versions

```bash
# List recent release branches
gh api repos/kubernetes/website/branches --paginate --jq '.[].name' \
  | grep "^release-" | sort -V | tail -5

# Get the latest release branch into a variable
VERSION=$(gh api repos/kubernetes/website/branches --paginate --jq '.[].name' \
  | grep "^release-" | sort -V | tail -1)
```

Use the highest release branch by default unless the user specifies one. The `main` branch tracks the next upcoming release.

## Navigating the Doc Tree

There is no index file — navigate by listing directories:

```bash
# List top-level sections
gh api "repos/kubernetes/website/contents/content/en/docs?ref=$VERSION" \
  --jq '.[] | select(.type=="dir") | .name'

# List contents of a section
gh api "repos/kubernetes/website/contents/content/en/docs/concepts?ref=$VERSION" \
  --jq '.[] | "\(.type)\t\(.name)"'

# Drill into a subsection
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/workloads/pods?ref=$VERSION" \
  --jq '.[] | "\(.type)\t\(.name)"'
```

## Reading Documentation Files

```bash
# Always include the raw content header
gh api "repos/kubernetes/website/contents/content/en/docs/{path}?ref=$VERSION" \
  -H "Accept: application/vnd.github.raw+json"
```

### Common Paths

```bash
# Pods
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/workloads/pods/_index.md?ref=release-1.34" \
  -H "Accept: application/vnd.github.raw+json"

# Services
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/services-networking/service.md?ref=release-1.34" \
  -H "Accept: application/vnd.github.raw+json"

# Ingress
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/services-networking/ingress.md?ref=release-1.34" \
  -H "Accept: application/vnd.github.raw+json"

# Network Policies
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/services-networking/network-policies.md?ref=release-1.34" \
  -H "Accept: application/vnd.github.raw+json"

# Persistent Volumes
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/storage/persistent-volumes.md?ref=release-1.34" \
  -H "Accept: application/vnd.github.raw+json"

# Tasks — configure pods
gh api "repos/kubernetes/website/contents/content/en/docs/tasks/configure-pod-container?ref=release-1.34" \
  --jq '.[] | .name'

# RBAC
gh api "repos/kubernetes/website/contents/content/en/docs/reference/access-authn-authz?ref=release-1.34" \
  --jq '.[] | .name'
```

## Searching for Topics

```bash
# Search for files matching a keyword (GitHub search API)
gh api "search/code?q=repo:kubernetes/website+path:content/en/docs+filename:network" \
  --jq '.items[:10] | .[] | .path'

# List and grep filenames in a section
gh api "repos/kubernetes/website/contents/content/en/docs/tasks?ref=$VERSION" \
  --jq '.[].name' | grep -i "network\|dns\|ingress"
```

## Doc Structure

```
content/en/docs/
├── concepts/          # Core Kubernetes concepts
│   ├── architecture/
│   ├── cluster-administration/
│   ├── configuration/
│   ├── containers/
│   ├── extend-kubernetes/
│   ├── overview/
│   ├── policy/
│   ├── scheduling-eviction/
│   ├── security/
│   ├── services-networking/
│   ├── storage/
│   ├── windows/
│   └── workloads/
├── tasks/             # Step-by-step how-tos
│   ├── access-application-cluster/
│   ├── administer-cluster/
│   ├── configure-pod-container/
│   ├── debug/
│   ├── manage-kubernetes-objects/
│   ├── network/
│   ├── run-application/
│   └── tls/
├── tutorials/         # Guided walkthroughs
│   ├── kubernetes-basics/
│   ├── stateful-application/
│   ├── stateless-application/
│   └── services/
├── reference/         # API, kubectl, config references
│   ├── access-authn-authz/
│   ├── command-line-tools-reference/
│   ├── kubectl/
│   ├── kubernetes-api/
│   ├── networking/
│   └── setup-tools/
└── setup/             # Installation & cluster setup
    ├── best-practices/
    ├── learning-environment/
    └── production-environment/
```

**File naming:** Sections use `_index.md` for the overview page. Individual topics are named descriptively (e.g., `pod-lifecycle.md`, `service.md`).

## Section Guide

| Section | Path | Description |
|---------|------|-------------|
| **Concepts** | `concepts/` | Core k8s concepts: workloads, networking, storage, security |
| **Tasks** | `tasks/` | Step-by-step how-tos: configure pods, debug, administer cluster |
| **Tutorials** | `tutorials/` | Guided walkthroughs: basics, stateful/stateless apps |
| **Reference** | `reference/` | API reference, kubectl commands, RBAC, config |
| **Setup** | `setup/` | Cluster installation and configuration |

### Key Subsections

| Topic | Path |
|-------|------|
| Pods | `concepts/workloads/pods/` |
| Deployments | `concepts/workloads/controllers/` |
| Services | `concepts/services-networking/service.md` |
| Ingress | `concepts/services-networking/ingress.md` |
| Network Policies | `concepts/services-networking/network-policies.md` |
| Persistent Volumes | `concepts/storage/persistent-volumes.md` |
| ConfigMaps/Secrets | `concepts/configuration/` |
| RBAC | `reference/access-authn-authz/` |
| Scheduling | `concepts/scheduling-eviction/` |
| Security | `concepts/security/` |
| Debugging | `tasks/debug/` |
| kubectl reference | `reference/kubectl/` |

## Tips

- **Start with directory listings**: No index file exists, so list directories to find files.
- **Use `_index.md` for overviews**: Each section/subsection has an `_index.md` overview — start there.
- **Hugo shortcodes**: Docs contain `{{< glossary_tooltip >}}` or `{{< note >}}`. Ignore these.
- **Version via `ref`**: Always include `?ref=$VERSION` in API calls.
- **`main` branch**: Tracks the next upcoming release. Use release branches for stable docs.
- **Large sections**: `tasks/administer-cluster/` and `reference/` are very large. List contents first.
