# Upgrade Paths

Decision tree for choosing the right fix path, dependency safety checks, and rollback planning.

## Decision Tree

```
START: CVE confirmed as applicable (VEX != not_affected)
  |
  +-- Is a fixed RPM available for the CURRENT image's RHEL version?
  |     (Check affected_release[] from Security Data API, match CPE to image base)
  |     |
  |     +-- YES: Can you rebuild the image? (Dockerfile/Containerfile available?)
  |     |     +-- YES --> PATH A: RPM Rebuild
  |     |     +-- NO  --> Check if a newer tag in the same stream includes the fix
  |     |               +-- YES --> PATH B: Z-stream Tag Update
  |     |               +-- NO  --> Fall through
  |     |
  |     +-- NO: Fall through
  |
  +-- Is a newer tag in the SAME stream available with 0 fixable CVEs?
  |     (List tags via Pyxis, scan newer tags via ACS)
  |     +-- YES --> PATH B: Z-stream Tag Update
  |     +-- NO  --> Fall through
  |
  +-- Is a newer MINOR stream available with the fix?
  |     (Search Pyxis for next stream, e.g., nginx-124 -> nginx-126)
  |     +-- YES: Is the stream in Full Support? (Check Product Lifecycle API)
  |     |     +-- YES --> PATH C: Minor Stream Upgrade
  |     |     +-- NO  --> Fall through
  |     |
  |     +-- NO --> Fall through
  |
  +-- Is a UBI equivalent available for this upstream image?
        (Search Pyxis by application name)
        +-- YES --> PATH D: Image Replacement
        +-- NO  --> Report: no automated fix path. Manual remediation needed.
```

The key principle: **least disruption first**. Each path is only chosen when less-disruptive paths are not available.

## Path A: RPM Rebuild

**Risk: Low** — same base image, same application, only the vulnerable package changes.

**When applicable:**
- You own the Dockerfile/Containerfile
- The vulnerable component is an RPM in the image (not a vendored library)
- A fixed RPM exists in the RHEL repos for the image's base version

**Steps:**
1. Identify the fixed RPM NVR from Security Data API's `affected_release[].package`
2. Note the advisory ID (RHSA/RHBA) for tracking
3. Rebuild the image — if using `dnf update` in the Dockerfile, the fixed RPM will be pulled automatically
4. If using pinned versions, update the pin to the fixed NVR
5. Scan the rebuilt image through ACS to confirm the CVE is resolved

**Example:**
```
CVE-2024-21626 affects runc-1.1.9 in UBI9
Fixed in: runc-1.1.12-1.el9_4 (RHSA-2024:0195)
Action: Rebuild image to pick up the updated runc RPM
```

## Path B: Z-stream Tag Update

**Risk: Low** — same minor version, just a newer build with security fixes applied.

**When applicable:**
- The image publisher has released a newer tag in the same stream
- The newer tag includes the fix (confirmed by ACS scan)

**How to find newer tags:**

Use the Pyxis tag listing (see `container-catalog.md`), filter for tags in the same stream, and sort by build date. Then scan the newest tag through ACS to confirm the target CVE is resolved.

**Example:**
```
Current:     registry.access.redhat.com/ubi9/nginx-124:1-88
Available:   registry.access.redhat.com/ubi9/nginx-124:1-92 (built 2024-11-15)
Action: Update image reference from :1-88 to :1-92
```

**Verification:** Scan the newer tag via ACS and confirm the specific CVE is no longer present in the scan results.

## Path C: Minor Stream Upgrade

**Risk: Medium** — new features, possible behavior changes, thorough testing recommended.

**When applicable:**
- The fix is only available in a newer minor version
- The newer stream is in Full Support (check Product Lifecycle API)
- Paths A and B are not available

**Semantic versioning implications:**

| Change | Example | Risk | What might break |
|---|---|---|---|
| Patch (Z-stream) | nginx-124:1-88 -> :1-92 | Low | Bug fixes only |
| Minor | nginx-122 -> nginx-124 | Medium | New features, config changes, deprecated options |
| Major | UBI8 -> UBI9 | High | Breaking changes, removed features, different defaults |

**Before recommending a minor upgrade, check:**
1. Release notes between the current and target versions for breaking changes
2. Deprecated configuration options that the workload might use
3. Changed default values (ports, user IDs, paths)
4. New dependencies or removed packages

**Example:**
```
Current:     ubi9/nginx-122:latest (EOL)
Recommended: ubi9/nginx-124:latest (Full Support)
Risk: Medium — check nginx config compatibility between 1.22 and 1.24
```

## Path D: Image Replacement

**Risk: High** — switching from an upstream/third-party image to a UBI equivalent. Functional testing required.

**When applicable:**
- The current image is from Docker Hub, Quay.io, or another non-Red Hat source
- No fix is available in the current image's ecosystem
- A UBI equivalent exists in the Red Hat Container Catalog

**Compatibility checklist:**

Before recommending image replacement, flag these potential differences:

| Concern | What to check | Example difference |
|---|---|---|
| Config file paths | Where the app reads its config | `/etc/nginx/nginx.conf` vs `/etc/nginx/conf.d/` |
| Default ports | What port the container listens on | 80 vs 8080 (UBI images often use non-privileged ports) |
| User ID | Whether the image runs as root | Docker Hub nginx runs as root; UBI nginx runs as non-root |
| Volume mount paths | Where data is stored | `/var/www/html` vs `/opt/app-root/src` |
| Entrypoint/CMD | How the process starts | Different entrypoint scripts |
| Package manager | How to install additional packages | `apt` (Debian-based) vs `dnf` (RHEL-based) |
| Environment variables | Config via env vars | Different variable names or defaults |
| Init system | Process supervision | Different signal handling |

**Always include this checklist in the recommendation** so the user can verify compatibility.

## Dependency Safety Checklist

Before recommending any upgrade path, check for these dependency risks:

1. **Version-specific application features** — Does the app's code or config use features specific to the current image version? (e.g., nginx config directives added in 1.21 that changed in 1.24)

2. **Sidecar and init containers** — Do other containers in the pod depend on specific behavior of this image? (e.g., shared volumes, network expectations, startup ordering)

3. **NetworkPolicies and ServiceMesh** — Are there NetworkPolicies, Istio VirtualServices, or other network config that reference specific ports or paths that might change?

4. **ConfigMaps and Secrets** — Are there ConfigMaps or Secrets mounted into the container that are version-specific? (e.g., config files with syntax that changed between versions)

5. **Health checks** — Do liveness/readiness probes hit endpoints that might change path or port in the new image?

6. **Operator-managed resources** — Is the Deployment managed by an operator that might revert manual image changes?

7. **Image pull policies and registries** — Does the cluster have pull access to the recommended registry? Are there ImagePullSecrets configured?

Flag any of these as risks in the recommendation. Do not silently assume compatibility.

## Rollback Planning

Every recommendation must include rollback instructions.

### Before upgrading

Record the current state:

```bash
# Record the exact image reference (digest, not just tag)
CURRENT_IMAGE=$(oc get deployment <name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].image}')
CURRENT_DIGEST=$(skopeo inspect "docker://${CURRENT_IMAGE}" | python3 -c "import json,sys;print(json.load(sys.stdin)['Digest'])")
echo "Rollback image: ${CURRENT_IMAGE}@${CURRENT_DIGEST}"
```

### Rollback commands

```bash
# Option 1: Set image back to the original
oc set image deployment/<name> <container>=<original-image>@<digest> -n <namespace>

# Option 2: Rollout undo (reverts to previous ReplicaSet)
oc rollout undo deployment/<name> -n <namespace>

# Verify rollback
oc rollout status deployment/<name> -n <namespace>
oc get pods -n <namespace> -l app=<name> -o jsonpath='{.items[*].spec.containers[*].image}'
```

### Post-rollback verification

1. Confirm the pod is running with the original image
2. Check application health (liveness/readiness probes passing)
3. Verify the application is serving traffic correctly
4. Re-scan via ACS to confirm the original vulnerability profile is back (expected)
