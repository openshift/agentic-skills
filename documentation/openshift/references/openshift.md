# OpenShift Documentation Reference

Repository: `harche/openshift-docs-md`
Docs path: `docs/`
Versioning: Directories under `docs/` (e.g., `docs/4.22/`).

## Discovering Available Versions

```bash
# List available versions (highest = latest)
gh api repos/harche/openshift-docs-md/contents/docs \
  --jq '[.[] | select(.type=="dir") | .name | select(test("^[0-9]"))] | sort | reverse | .[]'

# Get the latest version into a variable
VERSION=$(gh api repos/harche/openshift-docs-md/contents/docs \
  --jq '[.[] | select(.type=="dir") | .name | select(test("^[0-9]"))] | sort | last')
```

Use the highest version by default unless the user specifies one.

## Fetching the Documentation Index

Each version has an `AGENTS.md` file that maps topics to documentation files. Always start here.

```bash
# Fetch the full index
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/AGENTS.md \
  -H "Accept: application/vnd.github.raw+json"
```

## Searching the Index

```bash
# Search for a topic (case-insensitive)
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/AGENTS.md \
  -H "Accept: application/vnd.github.raw+json" | grep -i "networking"

gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/AGENTS.md \
  -H "Accept: application/vnd.github.raw+json" | grep -i "storage"

gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/AGENTS.md \
  -H "Accept: application/vnd.github.raw+json" | grep -i "install"
```

## Reading Documentation Files

### Constructing File Paths

Index entries follow this format:
```
|section/subsection:{file1.md,file2.md}
```

Construct the `gh api` path:
```
repos/harche/openshift-docs-md/contents/docs/{VERSION}/{section}/{subsection}/{file.md}
```

Always include the raw content header:
```
-H "Accept: application/vnd.github.raw+json"
```

### Examples

```bash
# Networking overview
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/networking/index.md \
  -H "Accept: application/vnd.github.raw+json"

# Installing on AWS (IPI)
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/installing/installing_aws/ipi/installing-aws-default.md \
  -H "Accept: application/vnd.github.raw+json"

# Persistent storage with CSI
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/storage/container_storage_interface/persistent-storage-csi.md \
  -H "Accept: application/vnd.github.raw+json"

# RBAC
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/authentication/using-rbac.md \
  -H "Accept: application/vnd.github.raw+json"

# Release notes
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/release_notes/ocp-4-22-release-notes.md \
  -H "Accept: application/vnd.github.raw+json"
```

## Listing Directory Contents

```bash
# List files in a directory
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/networking \
  --jq '.[].name'

# List with type info
gh api repos/harche/openshift-docs-md/contents/docs/$VERSION/networking \
  --jq '.[] | "\(.type)\t\(.name)"'
```

## Common Documentation Sections

| Section | Description |
|---------|-------------|
| `welcome` | Overview, glossary |
| `release_notes` | Version-specific release information |
| `architecture` | System design and components |
| `installing` | Installation guides (AWS, GCP, Azure, bare metal, vSphere, etc.) |
| `post_installation_configuration` | Post-install cluster setup |
| `updating` | Cluster upgrade processes |
| `networking` | Network configuration, DNS, ingress, routes, network policies |
| `storage` | Persistent storage, CSI, ephemeral storage |
| `security` | Certificates, audit logs, compliance |
| `authentication` | Identity providers, RBAC, service accounts |
| `nodes` | Node management, pods, scheduling, taints/tolerations |
| `machine_management` | Machine sets, autoscaling, machine health checks |
| `observability` | Monitoring, logging, distributed tracing |
| `applications` | Deployments, operators, Helm, quotas |
| `cicd` | Builds, pipelines, GitOps |
| `virt` | OpenShift Virtualization |
| `edge_computing` | Remote worker nodes, single-node OpenShift |
| `windows_containers` | Windows container support |

## Tips

- **Start broad, then narrow**: Search the index first with a general term, then read the specific file.
- **Large files**: Some doc files are long. Focus on the sections relevant to the user's question.
- **Cross-reference**: Complex topics may require reading from multiple sections.
- **Version differences**: If the user is on an older version, use that version's index.
- The docs are updated weekly from the official OpenShift documentation.
