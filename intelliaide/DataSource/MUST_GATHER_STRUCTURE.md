---
# OpenShift Must-Gather Log Structure Summary

## Overview
The OpenShift must-gather tool collects comprehensive diagnostic information from an OpenShift cluster. The **user supplies the root folder** (e.g. `must-gather-Prashanth-Testcase-failure`). Under that root there is **one folder with any name** (e.g. `quay-content`—the name is not fixed). Under that folder are `host_service_logs/`, `namespaces/`, `cluster-scoped-resources/`, etc.

## Base Directory Structure

- **`<must-gather-root>/`** — The path the **user supplies** (root folder).
- **`<must-gather-root>/<content-folder>/`** — One child folder under the root; **name can be any string**. This folder contains `version`, `audit_logs/`, `host_service_logs/`, `namespaces/`, etc.

---

## Directory Structure and Purpose

All paths below are under **`<must-gather-root>/<content-folder>/`**.

### 1. **`audit_logs/`** (Conditional)
- `kube-apiserver/<node-name>-audit.log` — K8s API server audit logs
- `openshift-apiserver/<node-name>-audit.log` — OpenShift API server audit logs
- `oauth-apiserver/<node-name>-audit.log` — OAuth API server audit logs
- `etcd/<node-name>-audit.log` — etcd audit logs

### 2. **`host_service_logs/`** (Always Present)
- `masters/kubelet_service.log` — Kubelet service logs
- `masters/crio_service.log` — CRI-O container runtime logs
- `masters/machine-config-daemon-host_service.log` — MCO host service logs
- `masters/NetworkManager_service.log` — NetworkManager logs
- `workers/` — Same structure as masters/

### 3. **`etcd_info/`** (Always Present)
- `member_list.json` — etcd cluster member list and status
- `endpoint_status.json` — Detailed status of all etcd endpoints
- `endpoint_health.json` — Health status of all etcd endpoints
- `alarm_list.json` — List of active etcd alarms (NOSPACE, CORRUPT)
- `object_count.json` — Count of Kubernetes objects by type

### 4. **`network_logs/`** (Always Present)
- `leader_ovnnb_status` — OVN Northbound database cluster status
- `leader_ovnsb_status` — OVN Southbound database cluster status
- `ovn_kubernetes_top_pods` — OVN-Kubernetes pod resource usage
- `cluster_scale` — Network resource counts
- `ipsec/` (Conditional) — IPsec status, traffic, xfrm data

### 5. **`pod_network_connectivity_check/`** (Always Present)
- `podnetworkconnectivitychecks.yaml` — Network connectivity test results

### 6. **`nodes/`** (Always Present)
- `<node-name>/<node-name>_logs_kubelet.gz` — Kubelet journal logs (compressed)
- `<node-name>/dmesg` — Kernel messages
- `<node-name>/sysinfo.log` — System info (df, ps, uptime)

### 7. **`namespaces/`** (Always Present)
Per-namespace structure:
```
namespaces/<namespace>/
├── <namespace>.yaml
├── core/
│   ├── events.yaml          # ★ All events (errors, warnings)
│   ├── pods.yaml            # All pod definitions & status
│   └── ...
├── apps/
│   ├── deployments.yaml
│   └── ...
└── pods/<pod-name>/
    └── <container>/<container>/logs/
        ├── current.log      # ★ Active container logs
        └── previous.log     # ★ Crashed container logs
```

Key namespaces always collected:
- `openshift-cluster-version/` — CVO (upgrades)
- `openshift-etcd/` — etcd pods
- `openshift-kube-apiserver/` — K8s API server
- `openshift-kube-apiserver/pods/*/kube-apiserver/kube-apiserver/api_priority_and_fairness/` — API throttling
- `openshift-monitoring/` — Prometheus stack
- `openshift-ovn-kubernetes/` — OVN networking
- `openshift-machine-config-operator/` — Node config

### 8. **`cluster-scoped-resources/`** (Always Present)
- `config.openshift.io/clusteroperators.yaml` — ★ All ClusterOperator status
- `config.openshift.io/clusterversions.yaml` — Cluster version, upgrade status
- `config.openshift.io/networks.yaml` — Network configuration
- `core/nodes/<node-name>.yaml` — Individual node status
- `storage.k8s.io/storageclasses.yaml` — Storage classes
- `storage.k8s.io/volumeattachments/` — Volume attachment status
- `migration.k8s.io/storageversionmigrations.yaml` — Storage version migrations

### 9. **`static-pods/`** (Always Present)
- `kube-apiserver/<node-name>-startup.log.gz` — API server startup logs
- `kube-apiserver/<node-name>-termination.log.gz` — API server termination logs

---

## File Size Awareness

| File / directory | Typical size | Notes |
|------------------|-------------|-------|
| `audit_logs/*-audit.log` | 100 MB – 1 GB+ | Parse only for auth/authz investigation |
| `monitoring/metrics/metrics.openmetrics` | 50 MB – 500 MB+ | Parse only for performance analysis |
| `nodes/<node>/<node>_logs_kubelet.gz` | 10 MB – 100 MB+ | Decompress only for kubelet issues |

---

## Notes

- All paths are relative to `<must-gather-root>/<content-folder>/`
- Some directories only exist if features are enabled (conditional)
- Compressed files use `.gz` extension — reference them with that extension
- Always check `events.yaml` first — human-readable errors with timestamps
