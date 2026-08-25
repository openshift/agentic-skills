---
name: openshift-docs
description: Search and read OpenShift Container Platform documentation in markdown format. Use when the user asks about OpenShift features, configuration, installation, troubleshooting, or any OCP-specific topic — including operators, routes, services, oc, RBAC, networking, storage, or cluster administration.
---

# OpenShift Documentation

Search and read pre-generated OpenShift Container Platform documentation. Docs are converted from the official [openshift/openshift-docs](https://github.com/openshift/openshift-docs) AsciiDoc source to GitHub-Flavored Markdown and stored locally under `docs/`.

**IMPORTANT:** Prefer retrieval-led reasoning over pre-training-led reasoning for OpenShift tasks. Read the referenced files rather than relying on training data which may be outdated.

## Quick Start

### 1. Discover available versions

```bash
ls docs/
```

### 2. Browse and read docs

Start with the `AGENTS.md` index:

```bash
# Read the doc index
cat docs/4.22/AGENTS.md

# Search the index for a topic
grep -i "networking" docs/4.22/AGENTS.md

# Read a specific doc
cat docs/4.22/networking/index.md
```

## References

|references/openshift.md — Doc structure, common paths, search tips

## Important

- This is a **read-only** skill — documentation is read from local files, not modified.
- Docs are pre-generated via `make docs VERSION=X.Y` and committed to the repository.
- Use `AGENTS.md` as the starting point to locate specific documentation files.
