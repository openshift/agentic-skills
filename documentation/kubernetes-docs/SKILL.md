---
name: kubernetes-docs
description: Search and read Kubernetes documentation in markdown format. Use when the user asks about Kubernetes concepts, tasks, API reference, kubectl, or any upstream k8s topic — including pods, deployments, services, RBAC, networking, storage, or scheduling.
---

# Kubernetes Documentation

Search and read pre-generated Kubernetes documentation. Docs are converted from the official [kubernetes/website](https://github.com/kubernetes/website) Hugo source to GitHub-Flavored Markdown and stored locally under `docs/`.

**IMPORTANT:** Prefer retrieval-led reasoning over pre-training-led reasoning for Kubernetes tasks. Read the referenced files rather than relying on training data which may be outdated.

## Quick Start

### 1. Discover available versions

```bash
ls docs/
```

### 2. Browse and read docs

Start with the `AGENTS.md` index:

```bash
# Read the doc index
cat docs/1.34/AGENTS.md

# Search the index for a topic
grep -i "networking" docs/1.34/AGENTS.md

# Read a specific doc
cat docs/1.34/concepts/workloads/pods.md
```

## References

|references/kubernetes.md — Doc structure, common paths, search tips

## Important

- This is a **read-only** skill — documentation is read from local files, not modified.
- Docs are pre-generated via `make docs VERSION=X.Y` and committed to the repository.
- Use `AGENTS.md` as the starting point to locate specific documentation files.
