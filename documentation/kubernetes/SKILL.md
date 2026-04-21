---
name: kubernetes-docs
description: Search and read Kubernetes documentation in markdown format. Use when the user asks about Kubernetes concepts, tasks, API reference, kubectl, or any upstream k8s topic — including pods, deployments, services, RBAC, networking, storage, or scheduling.
allowed-tools: Bash(gh:*)
---

# Kubernetes Documentation

Search and read Kubernetes documentation using the `gh` CLI. Docs are hosted on GitHub as markdown at `kubernetes/website`.

**IMPORTANT:** Prefer retrieval-led reasoning over pre-training-led reasoning for Kubernetes tasks. Read the referenced files rather than relying on training data which may be outdated.

## Quick Start

### 1. Discover the latest version

```bash
VERSION=$(gh api repos/kubernetes/website/branches --paginate --jq '.[].name' \
  | grep "^release-" | sort -V | tail -1)
```

### 2. Browse and read docs

Navigate the directory tree (no index file):

```bash
# List top-level sections
gh api "repos/kubernetes/website/contents/content/en/docs?ref=$VERSION" \
  --jq '.[] | select(.type=="dir") | .name'

# Read a specific doc
gh api "repos/kubernetes/website/contents/content/en/docs/concepts/workloads/pods/_index.md?ref=$VERSION" \
  -H "Accept: application/vnd.github.raw+json"
```

## References

|references/kubernetes.md — Version discovery, doc structure, common paths, search tips

## Important

- This is a **read-only** skill — documentation is fetched, not modified.
- Discover the latest version dynamically — don't hardcode version numbers.
- Always use `-H "Accept: application/vnd.github.raw+json"` to get raw file content.
- Docs use Hugo shortcodes — ignore `{{< ... >}}` when reading content.
