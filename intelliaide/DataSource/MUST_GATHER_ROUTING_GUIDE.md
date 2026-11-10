---
# Must-Gather Routing Guide for LLM Problem Diagnosis

This document provides a structured mapping of problem types to relevant directories and files in the must-gather output.

**Path convention**: All paths are under `<must-gather-root>/<content-folder>/`

**Path substitution rules**:
- `<namespace>` = actual namespace name (e.g. `openshift-etcd`)
- `<pod-name>` = actual pod name
- `<node-name>` = actual node name
- `*` = wildcard for any matching file/directory name

---

## 1. API Server & Authentication Issues

**Keywords**: `api server`, `apiserver`, `authentication`, `authorization`, `oauth`, `kube-apiserver`, `401`, `403`, `throttling`

### Primary Files (MANDATORY):
- `audit_logs/kube-apiserver/<node-name>-audit.log` (Conditional)
- `namespaces/openshift-kube-apiserver/pods/<pod-name>/<container>/<container>/logs/current.log`
- `namespaces/openshift-kube-apiserver/pods/<pod-name>/<container>/<container>/logs/previous.log`
- `namespaces/openshift-kube-apiserver/core/events.yaml`
- `namespaces/openshift-kube-apiserver/pods/<pod-name>/kube-apiserver/kube-apiserver/api_priority_and_fairness/queues`
- `static-pods/kube-apiserver/<node-name>-startup.log.gz` (compressed)
- `static-pods/kube-apiserver/<node-name>-termination.log.gz` (compressed)

### Cross-Component Dependencies:
- `etcd_info/endpoint_health.json`
- `cluster-scoped-resources/config.openshift.io/apiservers.yaml`

---

## 2. Cluster Operator & Control Plane Issues

**Keywords**: `cluster operator`, `operator`, `degraded`, `progressing`, `cluster version`, `upgrade`

### Primary Files (MANDATORY):
- `cluster-scoped-resources/config.openshift.io/clusteroperators.yaml`
- `cluster-scoped-resources/config.openshift.io/clusterversions.yaml`
- `namespaces/openshift-cluster-version/core/events.yaml`
- `namespaces/openshift-cluster-version/pods/<pod-name>/logs/current.log`
- `namespaces/openshift-cluster-version/pods/<pod-name>/logs/previous.log`
- `namespaces/<operator-namespace>/pods/<pod-name>/logs/current.log`
- `namespaces/<operator-namespace>/pods/<pod-name>/logs/previous.log`
- `namespaces/<operator-namespace>/core/events.yaml`

---

## 3. Networking & Connectivity Issues

**Keywords**: `network`, `connectivity`, `dns`, `ovn`, `sdn`, `OVNKubernetesResourceRetryFailure`, `bz-networking`

### Primary Files (MANDATORY):
- `pod_network_connectivity_check/podnetworkconnectivitychecks.yaml`
- `network_logs/cluster_scale`
- `cluster-scoped-resources/config.openshift.io/networks.yaml`
- `monitoring/alertmanager/` (for OVN alerts)
- `monitoring/prometheus/` (for OVN alerts)
- `network_logs/leader_ovnnb_status`
- `network_logs/leader_ovnsb_status`
- `network_logs/ovn_kubernetes_top_pods`
- `namespaces/openshift-ovn-kubernetes/pods/<pod-name>/logs/current.log`
- `namespaces/openshift-ovn-kubernetes/pods/<pod-name>/logs/previous.log`
- `namespaces/openshift-ovn-kubernetes/core/events.yaml`
- `host_service_logs/masters/NetworkManager_service.log`
- `host_service_logs/workers/NetworkManager_service.log`

---

## 4. Storage & Volume Issues

**Keywords**: `storage`, `volume`, `pvc`, `pv`, `csi`, `mount`, `attach`

### Primary Files (MANDATORY):
- `cluster-scoped-resources/storage.k8s.io/storageclasses.yaml`
- `cluster-scoped-resources/storage.k8s.io/volumeattachments/<attachment-name>.yaml`
- `namespaces/<namespace>/core/persistentvolumeclaims.yaml`
- `namespaces/openshift-cluster-csi-drivers/pods/<pod-name>/logs/current.log`
- `namespaces/openshift-cluster-csi-drivers/pods/<pod-name>/logs/previous.log`
- `cluster-scoped-resources/storage.k8s.io/csidrivers.yaml`
- `cluster-scoped-resources/storage.k8s.io/csinodes.yaml`

---

## 5. Node & Machine Configuration Issues

**Keywords**: `node`, `machine config`, `mco`, `not ready`, `kubelet`

### Primary Files (MANDATORY):
- `cluster-scoped-resources/core/nodes/<node-name>.yaml`
- `nodes/<node-name>/<node-name>_logs_kubelet.gz` (compressed)
- `host_service_logs/masters/kubelet_service.log`
- `host_service_logs/workers/kubelet_service.log`
- `namespaces/openshift-machine-config-operator/pods/<pod-name>/logs/current.log`
- `cluster-scoped-resources/machineconfiguration.openshift.io/machineconfigs.yaml`
- `cluster-scoped-resources/machineconfiguration.openshift.io/machineconfigpools.yaml`

---

## 6. Pod & Container Issues

**Keywords**: `pod`, `container`, `crash`, `restart`, `pending`, `image pull`, `OOMKilled`

### Primary Files (MANDATORY):
- `namespaces/<namespace>/pods/<pod-name>/<container>/<container>/logs/current.log`
- `namespaces/<namespace>/pods/<pod-name>/<container>/<container>/logs/previous.log`
- `namespaces/<namespace>/core/events.yaml`
- `namespaces/<namespace>/core/pods.yaml`
- `host_service_logs/masters/crio_service.log`
- `host_service_logs/workers/crio_service.log`

---

## 7. Performance & Resource Issues

**Keywords**: `performance`, `cpu`, `memory`, `slow`, `latency`, `high load`

### Primary Files (MANDATORY):
- `monitoring/metrics/metrics.openmetrics` (Conditional)
- `monitoring/prometheus/status/config.json`
- `monitoring/alertmanager/status.json`
- `nodes/<node-name>/` (all node performance data)
- `namespaces/openshift-kube-apiserver/pods/<pod-name>/kube-apiserver/kube-apiserver/api_priority_and_fairness/queues`
- `etcd_info/object_count.json`

---

## 13. etcd Issues

**Keywords**: `etcd`, `quorum`, `alarm`, `etcdGRPCRequestsSlow`, `NOSPACE`, `CORRUPT`

### Primary Files (MANDATORY):
- `etcd_info/endpoint_health.json`
- `etcd_info/endpoint_status.json`
- `etcd_info/member_list.json`
- `etcd_info/alarm_list.json`
- `etcd_info/object_count.json`
- `namespaces/openshift-etcd/pods/<pod-name>/<container>/<container>/logs/current.log`
- `namespaces/openshift-etcd/pods/<pod-name>/<container>/<container>/logs/previous.log`
- `namespaces/openshift-etcd/core/events.yaml`
- `namespaces/openshift-etcd-operator/pods/<pod-name>/<container>/<container>/logs/current.log`
- `namespaces/openshift-etcd-operator/pods/<pod-name>/<container>/<container>/logs/previous.log`
- `audit_logs/etcd/<node-name>-audit.log` (Conditional)

### Cross-Component Dependencies (MANDATORY):
- All API server files from section 1
- `monitoring/metrics/metrics.openmetrics` (for performance spikes)
- `host_service_logs/masters/kubelet_service.log`
- `cluster-scoped-resources/config.openshift.io/clusteroperators.yaml`

---

## 14. Storage Version Migration Issues

**Keywords**: `storage version migration`, `kube-storage-version-migrator`, `Available=False`, `KubeStorageVersionMigrator_Deploying`

### Primary Files (MANDATORY):
- `cluster-scoped-resources/migration.k8s.io/storageversionmigrations.yaml`
- `namespaces/openshift-kube-storage-version-migrator/pods/<pod-name>/logs/current.log`
- `namespaces/openshift-kube-storage-version-migrator/pods/<pod-name>/logs/previous.log`
- `namespaces/openshift-kube-storage-version-migrator/core/events.yaml`
- `namespaces/openshift-kube-storage-version-migrator/apps/deployments.yaml`
- `namespaces/openshift-kube-storage-version-migrator/batch/jobs.yaml`
- `cluster-scoped-resources/apiregistration.k8s.io/apiservices.yaml`
- `cluster-scoped-resources/apiextensions.k8s.io/customresourcedefinitions.yaml`

### Cross-Component Dependencies (MANDATORY):
- `cluster-scoped-resources/config.openshift.io/clusteroperators.yaml`
- `namespaces/openshift-cluster-version/core/events.yaml`
- `namespaces/openshift-kube-apiserver/pods/<pod-name>/logs/current.log`
- `namespaces/openshift-kube-apiserver/pods/<pod-name>/logs/previous.log`
- All `etcd_info/*.json`

---

## 15. IPsec & Network Security Issues

**Keywords**: `ipsec`, `encryption`, `libreswan`, `xfrm`, `Feature:IPsec`

### Primary Files (MANDATORY):
- `network_logs/ipsec/status/`
- `network_logs/ipsec/trafficstatus/`
- `network_logs/ipsec/xfrm/`
- `network_logs/ipsec/<pod-name>_ipsec.conf`
- `network_logs/ipsec/<pod-name>_libreswan.log`
- `pod_network_connectivity_check/podnetworkconnectivitychecks.yaml`
- `namespaces/openshift-ovn-kubernetes/pods/<pod-name>/logs/current.log`
- `namespaces/openshift-ovn-kubernetes/pods/<pod-name>/logs/previous.log`
- `namespaces/openshift-network-operator/pods/<pod-name>/logs/current.log`
- `host_service_logs/masters/NetworkManager_service.log`
- `host_service_logs/workers/NetworkManager_service.log`

---

## Mandatory File Combinations

### For any pod issue:
- **BOTH** `logs/current.log` AND `logs/previous.log`
- **BOTH** pod YAML AND namespace events

### For any etcd issue:
- **ALL** etcd health files (endpoint_health.json, member_list.json, alarm_list.json)
- **BOTH** etcd logs AND API server logs

### For any networking issue:
- **BOTH** network operator logs AND OVN database status
- **BOTH** pod connectivity checks AND network events
