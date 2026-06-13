---
name: tekton-docs
description: Search and read Tekton and OpenShift Pipelines documentation. Use when investigating pipeline configuration issues, understanding Tekton resource specs, or looking up pipeline best practices and troubleshooting guides.
allowed-tools: Bash(curl:*)
---

# Tekton Documentation

Search and read Tekton upstream and OpenShift Pipelines documentation using `curl` to fetch raw markdown from GitHub repositories.

**IMPORTANT:** Prefer retrieval-led reasoning over pre-training-led reasoning for Tekton tasks. Read the referenced docs rather than relying on training data which may be outdated.

## Repositories

| Project | Repository | Docs Path | Versioning |
|---------|-----------|-----------|------------|
| **Tekton Pipelines** | `tektoncd/pipeline` | `docs/` | Git tags (`v0.62.0`) and `main` |
| **Tekton Triggers** | `tektoncd/triggers` | `docs/` | Git tags (`v0.28.0`) and `main` |
| **Tekton Chains** | `tektoncd/chains` | `docs/` | Git tags and `main` |
| **Tekton Hub** | `tektoncd/hub` | `docs/` | Git tags and `main` |
| **Tekton Operator** | `tektoncd/operator` | `docs/` | Git tags and `main` |
| **OpenShift Pipelines** | `openshift/tektoncd-pipeline` | `docs/` | Release branches (`release-v0.62.x`) |

## Quick Start

### 1. Determine the component

- **Tekton Pipelines** -- Pipeline, Task, PipelineRun, TaskRun, Workspace, Result, StepAction
- **Tekton Triggers** -- TriggerTemplate, TriggerBinding, EventListener, Interceptor
- **Tekton Chains** -- Supply chain security, signing, provenance, SLSA attestation
- **Tekton Hub** -- Task catalog, shared tasks
- **OpenShift Pipelines** -- OpenShift-specific integration, operator config, TektonConfig

### 2. Discover available versions

```bash
# List Tekton Pipelines releases
curl -s "https://api.github.com/repos/tektoncd/pipeline/tags?per_page=10" \
  | python3 -c "
import sys, json
for t in json.load(sys.stdin):
    print(t['name'])
"

# List Tekton Triggers releases
curl -s "https://api.github.com/repos/tektoncd/triggers/tags?per_page=10" \
  | python3 -c "
import sys, json
for t in json.load(sys.stdin):
    print(t['name'])
"
```

### 3. Read documentation

```bash
# Read a specific doc from Tekton Pipelines (using a version tag)
curl -s "https://raw.githubusercontent.com/tektoncd/pipeline/v0.62.0/docs/pipelines.md"

# Read from main branch (latest)
curl -s "https://raw.githubusercontent.com/tektoncd/pipeline/main/docs/pipelines.md"

# Read Tekton Triggers docs
curl -s "https://raw.githubusercontent.com/tektoncd/triggers/main/docs/eventlisteners.md"

# Read Tekton Chains docs
curl -s "https://raw.githubusercontent.com/tektoncd/chains/main/docs/config.md"
```

### 4. List available docs

```bash
# List docs in Tekton Pipelines
curl -s "https://api.github.com/repos/tektoncd/pipeline/contents/docs?ref=main" \
  | python3 -c "
import sys, json
for f in json.load(sys.stdin):
    if f['name'].endswith('.md'):
        print(f['name'])
"

# List docs in Tekton Triggers
curl -s "https://api.github.com/repos/tektoncd/triggers/contents/docs?ref=main" \
  | python3 -c "
import sys, json
for f in json.load(sys.stdin):
    if f['name'].endswith('.md'):
        print(f['name'])
"
```

## Common Documentation Paths

### Tekton Pipelines (`tektoncd/pipeline`)

| Topic | Path |
|-------|------|
| Pipelines | `docs/pipelines.md` |
| Tasks | `docs/tasks.md` |
| TaskRuns | `docs/taskruns.md` |
| PipelineRuns | `docs/pipelineruns.md` |
| Workspaces | `docs/workspaces.md` |
| Results | `docs/tasks.md#emitting-results` |
| When expressions | `docs/pipelines.md#guard-task-execution-using-when-expressions` |
| Finally tasks | `docs/pipelines.md#adding-finally-to-the-pipeline` |
| Step Actions | `docs/stepactions.md` |
| Custom Tasks | `docs/customruns.md` |
| Pipeline resolution | `docs/resolution.md` |
| Compute resources | `docs/compute-resources.md` |
| Variables/substitutions | `docs/variables.md` |
| Deprecations | `docs/deprecations.md` |
| Migration (v1beta1 to v1) | `docs/migrating-v1beta1-to-v1.md` |

### Tekton Triggers (`tektoncd/triggers`)

| Topic | Path |
|-------|------|
| EventListeners | `docs/eventlisteners.md` |
| TriggerTemplates | `docs/triggertemplates.md` |
| TriggerBindings | `docs/triggerbindings.md` |
| Interceptors | `docs/interceptors.md` |
| ClusterInterceptors | `docs/clusterinterceptors.md` |

### Tekton Chains (`tektoncd/chains`)

| Topic | Path |
|-------|------|
| Configuration | `docs/config.md` |
| Signing | `docs/signing.md` |
| SLSA Provenance | `docs/slsa-provenance.md` |

## Common Troubleshooting Patterns

### Pipeline Configuration Issues

| Symptom | Doc to Read | Common Fix |
|---------|------------|------------|
| `InvalidWorkspaceBindings` | `docs/workspaces.md` | Ensure workspace names in PipelineRun match Pipeline spec |
| `CouldntGetTask` | `docs/resolution.md` | Check task reference, resolver config, RBAC for resolvers |
| `TaskRunValidationFailed` | `docs/tasks.md` | Validate param types, required params are provided |
| `PipelineValidationFailed` | `docs/pipelines.md` | Check task ordering, result references, workspace declarations |
| `InvalidParamValue` | `docs/variables.md` | Verify variable substitution syntax `$(params.name)` |

### API Migration Issues

| Symptom | Doc to Read | Common Fix |
|---------|------------|------------|
| `v1beta1 deprecated` | `docs/migrating-v1beta1-to-v1.md` | Convert resources to v1 API |
| `ClusterTask not found` | `docs/tasks.md` | Use cluster resolver instead of ClusterTask |
| `PipelineResource not supported` | `docs/migrating-v1beta1-to-v1.md` | Replace with workspaces and results |

### Runtime Issues

| Symptom | Doc to Read | Common Fix |
|---------|------------|------------|
| Task timeout | `docs/taskruns.md` | Adjust `timeout` field, check step resource limits |
| Pipeline timeout | `docs/pipelineruns.md` | Adjust `timeouts.pipeline`, `timeouts.tasks`, `timeouts.finally` |
| Step OOMKilled | `docs/compute-resources.md` | Increase step memory limits |
| Step permission denied | `docs/tasks.md` | Check `securityContext`, SA permissions |

## Version-Specific Documentation

When investigating a specific version, always fetch docs at the matching tag:

```bash
# For Tekton Pipelines v0.59.0
curl -s "https://raw.githubusercontent.com/tektoncd/pipeline/v0.59.0/docs/pipelines.md"

# For Tekton Pipelines v0.62.0
curl -s "https://raw.githubusercontent.com/tektoncd/pipeline/v0.62.0/docs/pipelines.md"
```

Compare docs across versions to understand behavioral changes:

```bash
# Check deprecations for a specific version
curl -s "https://raw.githubusercontent.com/tektoncd/pipeline/v0.62.0/docs/deprecations.md"
```

## Important

- This is a **read-only** skill -- documentation is fetched, not modified.
- Discover available versions dynamically -- don't hardcode version numbers.
- Always fetch version-specific docs when investigating a particular operator version.
- Tekton Pipelines docs are the most comprehensive -- start there for core concepts.
- OpenShift Pipelines adds features on top of Tekton -- check OpenShift-specific docs for operator config, console integration, and RBAC defaults.
- Doc files can be large -- focus on the sections relevant to the user's question.
