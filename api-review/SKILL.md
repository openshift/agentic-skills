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

Fetch this document and extract the rules. Key sections to check:

- **Naming**: PascalCase Go fields, camelCase JSON, no underscores/dashes,
  acronym casing, `fooRef` for references, `fooSeconds` for durations,
  `somethingTime` for timestamps, no abbreviations
- **Types**: `int32`/`int64` only (never `int`), no unsigned ints, no floats
  in spec, `bool` must be `*bool` with `omitempty`
- **Enums**: CamelCase string values with initial uppercase (e.g., `ClientIP`,
  `ClusterFirst`), never numeric enums
- **Optional fields**: must have `+optional` tag, pointer or nil-able type,
  `omitempty` json tag, document what happens when omitted
- **Required fields**: must have `+required` tag, typically non-pointer
- **Lists**: prefer named subobject lists over maps, all lists must have
  `+listType` tag (`atomic`, `map`, or `set`), all lists must have `MaxItems`
- **Strings**: all string fields must have `MaxLength`
- **Maps**: all maps must have max size
- **Conditions**: use `[]metav1.Condition` with `+listType=map`,
  `+listMapKey=type`, `+patchStrategy=merge`, `+patchMergeKey=type`,
  condition types are PascalCase adjectives or past-tense verbs
- **Phase is deprecated**: newer APIs must use conditions, not a `phase` enum
- **Spec/Status**: objects with mutable state need both, status subresource
  must be enabled, no extra top-level fields beyond spec/status/metadata
- **Validation**: use CEL (`XValidation`) for cross-field constraints,
  bounds-check all numeric fields

### 2. OpenShift API Review (downstream)

```
https://raw.githubusercontent.com/openshift/api/master/.claude/commands/api-review.md
```

Fetch this document and apply its review workflow. It covers OpenShift-specific
conventions layered on top of the K8s rules, including field documentation
requirements, optional field behavior docs, and validation marker checks.

## Review Procedure

1. **Fetch both reference documents** using WebFetch. Parse the rules.
2. **Identify API files** to review. Look for Go files in paths matching
   `api/*/` or `pkg/apis/*/` with struct types that embed `metav1.TypeMeta`.
3. **Check every struct field** against the rules from both documents.
4. **Check every type definition** (enums, constants, type aliases).
5. **Check every list field** for `listType`, `MaxItems`.
6. **Check every string field** for `MaxLength`.
7. **Check every `bool` field** -- must be `*bool` with `omitempty`.
8. **Check every `int` field** -- must be `int32` or `int64`.
9. **Check every enum** -- values must be CamelCase.
10. **Check every `LocalObjectReference`** -- parent struct should have CEL
    validation rejecting empty `.name`.
11. **Check for `phase` fields** -- deprecated, use conditions.
12. **Check conditions fields** -- must have patch strategy/merge key tags.
13. **Check time fields** -- must use `somethingTime` naming.
14. **Check duration fields** -- must use `fooSeconds` naming.
15. **Check mutually exclusive fields** -- must have CEL enforcement.

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
