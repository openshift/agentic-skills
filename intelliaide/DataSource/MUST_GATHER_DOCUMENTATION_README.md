---
# Must-Gather Documentation Suite

This documentation suite provides comprehensive information about the OpenShift must-gather tool's output structure and how to use it for problem diagnosis. This guide ensures consistent LLM routing and reduces variance in file path recommendations across different models.

## Documentation Files

### 1. **MUST_GATHER_STRUCTURE.md**
**Purpose**: Detailed description of the directory structure and file purposes

**Contents**:
- Complete directory tree with descriptions
- File formats and contents
- Collection process overview
- Resource types collected

**Use When**: You need to understand what data is collected and where it's stored

---

### 2. **MUST_GATHER_ROUTING_GUIDE.md**
**Purpose**: Problem-based routing guide for LLM-assisted diagnosis

**Contents**:
- 15 problem categories with detailed mappings
- Keywords for each problem type
- Primary directories and files for each category
- Related resources cross-references
- Routing decision tree
- Quick reference table

**Use When**: You have a problem statement and need to identify relevant files

**Problem Categories Covered**:
1. API Server & Authentication Issues
2. Cluster Operator & Control Plane Issues
3. Networking & Connectivity Issues
4. Storage & Volume Issues
5. Node & Machine Configuration Issues
6. Pod & Container Issues
7. Performance & Resource Issues
8. Security & Audit Issues
9. Service Mesh & Istio Issues
10. Monitoring & Metrics Issues
11. Windows Node Issues
12. Platform-Specific Issues (vSphere, ARO)
13. etcd Issues
14. Storage Version Migration Issues
15. IPsec & Network Security Issues

---

### 3. **MUST_GATHER_INDEX.md**
**Purpose**: Quick reference index for fast keyword-based lookups

**Contents**:
- Directory structure quick index
- Keyword to directory mapping
- File type patterns
- Common problem patterns
- Search strategy for LLMs

**Use When**: You need quick lookups or keyword matching

---

## Standardization Rules for LLM Outputs

### Path Format Standards

1. **Use actual on-disk file extensions**: `.log`, `.yaml`, `.json` for uncompressed files; `.log.gz`, `.gz`, or `.tar.gz` for compressed files
2. **Wildcard substitution rules**:
   - `<namespace>` for actual namespace names
   - `<pod-name>` for actual pod names
   - `<node-name>` for actual node names
   - `*` only when multiple files of same type exist
3. **Consistent path separators**: Always use forward slashes `/`
4. **Base path convention**: All paths relative to `<must-gather-root>/<content-folder>/`

### Mandatory File Inclusion Rules

1. **For pod issues**: MUST include both `current.log` AND `previous.log` from container logs
2. **For operator issues**: MUST include both pod logs AND events from the operator namespace
3. **For etcd issues**: MUST include ALL files from `etcd_info/` directory
4. **For networking issues**: MUST include both pod logs AND network connectivity checks
5. **For API server issues**: MUST include both audit logs AND pod logs AND priority/fairness data

### Cross-Component Dependencies

When analyzing these components, ALWAYS include related components:

- **etcd issues** → Include API server logs and cluster operator status
- **Networking issues** → Include container runtime logs and node service logs
- **Storage issues** → Include both CSI driver logs and pod mount logs
- **Performance issues** → Include both metrics data and node-level diagnostics
- **Operator issues** → Include both operator namespace and cluster operator status

---

## Key Concepts

### Directory Organization
- **Base Path**: All data under `<must-gather-root>/<content-folder>/`
- **Namespace-based**: Most resources organized by namespace
- **Cluster-scoped**: Cluster-level resources in `cluster-scoped-resources/`
- **Feature-specific**: Some directories only exist if features enabled

### File Types
- **Logs**: `.log` for most logs; some compressed as `.log.gz` or `.gz`
- **Status**: `.json` - Health, status, configuration state
- **Config**: `.yaml`, `.config` - Resource definitions
- **Metrics**: `.openmetrics` - Performance and resource metrics
- **Archives**: `.tar.gz` - Compressed archives
