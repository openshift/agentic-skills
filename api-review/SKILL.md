---
name: api-review
description: Review Kubernetes and OpenShift CRD API types for compliance with upstream conventions. Use when designing, reviewing, or validating Go API types (typically in api/v1alpha1/), CRD schemas, or PR diffs that add or modify Custom Resource Definitions.
allowed-tools: Bash(grep:*), Bash(find:*), Bash(cat:*), Bash(wc:*), Bash(go:*), WebFetch
---

# Kubernetes / OpenShift API Review

Review Go API types for compliance with the Kubernetes API conventions and
OpenShift API review requirements.

## Reference Documents

Fetch and apply rules from these two authoritative sources. Do NOT guess the
rules from memory -- always fetch the latest version before reviewing.

### 1. Kubernetes API Conventions (upstream)

```
https://raw.githubusercontent.com/kubernetes/community/main/contributors/devel/sig-architecture/api-conventions.md
```

Fetch this document and check every rule against the API types under review.

### 2. OpenShift API Review (downstream)

```
https://raw.githubusercontent.com/openshift/api/master/.claude/commands/api-review.md
```

Fetch this document and apply its review workflow on top of the K8s conventions.

## Review Procedure

1. **Fetch both reference documents** using WebFetch.
2. **Identify API files** to review. Look for Go files in paths matching
   `api/*/` or `pkg/apis/*/` with struct types that embed `metav1.TypeMeta`.
3. **Check every struct, field, type, and marker** against the rules from
   both documents. Be exhaustive — check every field, not a sample.

## Output Format

Report findings using this format for each issue:

```
+LineNumber: Brief description
**Current code:**
` `` go
[exact code]
` ``

**Suggested fix:**
` `` diff
- [old]
+ [new]
` ``

**Rule:** [Which convention document and which specific rule]
```

Group findings by file. At the end, provide a summary table:

```
| Category | Count | Source |
|----------|-------|--------|
| ...      | ...   | K8s conventions / OpenShift API review |
```
