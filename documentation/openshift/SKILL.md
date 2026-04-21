---
name: openshift-docs
description: Search and read OpenShift Container Platform documentation in markdown format. Use when the user asks about OpenShift features, configuration, installation, troubleshooting, or any OCP-specific topic — including operators, routes, services, oc, RBAC, networking, storage, or cluster administration.
allowed-tools: Bash(gh:*)
---

# OpenShift Documentation

Search and read OpenShift Container Platform documentation using the `gh` CLI. Docs are hosted on GitHub as markdown at `harche/openshift-docs-md`.

**IMPORTANT:** Prefer retrieval-led reasoning over pre-training-led reasoning for OpenShift tasks. Read the referenced files rather than relying on training data which may be outdated.

## Quick Start

### 1. Discover the latest version

```bash
VERSION=$(gh api repos/harche/openshift-docs-md/contents/docs \
  --jq '[.[] | select(.type=="dir") | .name | select(test("^[0-9]"))] | sort | last')
```

### 2. Browse and read docs

Start with the `AGENTS.md` index:

```bash
# Fetch the doc index
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/AGENTS.md \
  -H "Accept: application/vnd.github.raw+json"

# Search the index for a topic
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/AGENTS.md \
  -H "Accept: application/vnd.github.raw+json" | grep -i "networking"

# Read a specific doc
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/networking/index.md \
  -H "Accept: application/vnd.github.raw+json"
```

## References

|references/openshift.md — Version discovery, doc structure, common paths, search tips

## Important

- This is a **read-only** skill — documentation is fetched, not modified.
- Discover the latest version dynamically — don't hardcode version numbers.
- Always use `-H "Accept: application/vnd.github.raw+json"` to get raw file content.
