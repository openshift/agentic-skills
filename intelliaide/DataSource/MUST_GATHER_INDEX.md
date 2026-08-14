---
# Must-Gather Directory and File Index

Quick reference index for LLM routing. Use this for fast lookups of directories and files by problem keywords.

## Directory Structure Quick Index

User supplies **`<must-gather-root>`** (e.g. `must-gather-Prashanth-Testcase-failure`). Under it there is **one folder `<content-folder>`** (any name, e.g. `quay-content`). Under that folder:

```
<must-gather-root>/
└── <content-folder>/                              # one child, any name (e.g. quay-content)
    ├── version                                    # Must-gather version info
    ├── event-filter.html                          # ★ All events in searchable web UI
    │
    ├── ── CLUSTER-WIDE RESOURCES ──
    ├── cluster-scoped-resources/                   # All cluster-level objects
    │   ├── config.openshift.io/                    # ★ PRIMARY: Cluster configuration
    │   │   ├── clusteroperators.yaml               #   ★ START HERE: Operator health
    │   │   ├── clusterversions.yaml                #   Version, upgrade status, history
    │   │   └── ...
    │   └── core/                                   # Kubernetes core resources
    │       └── nodes/                              #   ★ Per-node YAML (status, taints, labels)
    │
    ├── ── NAMESPACE RESOURCES ──
    ├── namespaces/<namespace>/                     # Per-namespace data
    │   ├── core/events.yaml                        #   ★ CRITICAL: All events
    │   ├── pods/<pod-name>/<container>/logs/
    │   │   ├── current.log                         #   ★ Active container logs
    │   │   └── previous.log                        #   ★ Crashed container logs
    │   └── ...
    │
    ├── host_service_logs/                          # ★ Systemd service logs
    │   ├── masters/kubelet_service.log
    │   ├── masters/crio_service.log
    │   └── workers/...
    │
    ├── etcd_info/                                  # Etcd cluster health
    │   ├── endpoint_health.json
    │   ├── member_list.json
    │   ├── alarm_list.json
    │   └── object_count.json
    │
    ├── network_logs/                               # Network-specific data
    │   ├── leader_ovnnb_status
    │   ├── leader_ovnsb_status
    │   └── ipsec/ (conditional)
    │
    └── pod_network_connectivity_check/
        └── podnetworkconnectivitychecks.yaml
```

---

## Decision Matrix: Problem Type → Primary Files

### 1. Cluster Health / Operator Issues
1. `cluster-scoped-resources/config.openshift.io/clusteroperators.yaml`
2. `cluster-scoped-resources/config.openshift.io/clusterversions.yaml`
3. `namespaces/openshift-<degraded-operator>/core/events.yaml`
4. `namespaces/openshift-<degraded-operator>/pods/*/<container>/<container>/logs/current.log`

### 2. Pod / Container Issues
1. `namespaces/<namespace>/core/events.yaml`
2. `namespaces/<namespace>/core/pods.yaml`
3. `namespaces/<namespace>/pods/<pod-name>/<container>/<container>/logs/current.log`
4. `namespaces/<namespace>/pods/<pod-name>/<container>/<container>/logs/previous.log`
5. `host_service_logs/masters|workers/crio_service.log`

### 3. Node Issues
1. `cluster-scoped-resources/core/nodes/<node-name>.yaml`
2. `nodes/<node-name>/dmesg`
3. `host_service_logs/masters|workers/kubelet_service.log`

### 4. Networking Issues
1. `cluster-scoped-resources/config.openshift.io/networks.yaml`
2. `namespaces/openshift-ovn-kubernetes/pods/*/logs/current.log`
3. `pod_network_connectivity_check/podnetworkconnectivitychecks.yaml`
4. `network_logs/leader_ovnnb_status`, `leader_ovnsb_status`

### 5. Storage Issues
1. `cluster-scoped-resources/storage.k8s.io/storageclasses.yaml`
2. `namespaces/<namespace>/core/persistentvolumeclaims.yaml`
3. `cluster-scoped-resources/storage.k8s.io/volumeattachments/`

### 6. API Server Issues
1. `namespaces/openshift-kube-apiserver/pods/*/logs/current.log`
2. `etcd_info/endpoint_health.json`
3. `etcd_info/alarm_list.json`

### 7. Etcd Issues
1. `etcd_info/endpoint_health.json`
2. `etcd_info/member_list.json`
3. `etcd_info/alarm_list.json`
4. `namespaces/openshift-etcd/pods/*/logs/current.log`

### 8. Storage Version Migration
1. `namespaces/openshift-kube-storage-version-migrator/core/events.yaml`
2. `namespaces/openshift-kube-storage-version-migrator/pods/*/logs/current.log`
3. `cluster-scoped-resources/migration.k8s.io/storageversionmigrations.yaml`

---

## Mandatory Inclusion Rules

- **Always include both current.log AND previous.log** for pod logs
- **Always include both pod logs AND events** for namespace issues
- **etcd issues**: Always include API server logs too
- **API Server issues**: Always include etcd health
- **Network issues**: Always include connectivity checks
