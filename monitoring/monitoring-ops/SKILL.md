---
name: monitoring-ops
description: OpenShift Cluster Monitoring Operator troubleshooting and tuning
---

# Monitoring Operations

Troubleshoot and tune the OpenShift monitoring stack managed by the Cluster Monitoring Operator.

## Components

| Component | Namespace | Key Resources |
|-----------|-----------|---------------|
| Prometheus | openshift-monitoring | StatefulSet/prometheus-k8s, ConfigMap/prometheus-k8s-rulefiles-0 |
| Alertmanager | openshift-monitoring | StatefulSet/alertmanager-main, Secret/alertmanager-main |
| Thanos Querier | openshift-monitoring | Deployment/thanos-querier |
| node-exporter | openshift-monitoring | DaemonSet/node-exporter |
| kube-state-metrics | openshift-monitoring | Deployment/kube-state-metrics |
| prometheus-operator | openshift-monitoring | Deployment/prometheus-operator |
| Metrics Server | openshift-monitoring | Deployment/metrics-server |
| User Workload Prometheus | openshift-user-workload-monitoring | StatefulSet/prometheus-user-workload |
| User Workload Alertmanager | openshift-user-workload-monitoring | StatefulSet/alertmanager-user-workload |

## Configuration

CMO is configured via ConfigMap `cluster-monitoring-config` in `openshift-monitoring`:

```bash
oc -n openshift-monitoring get configmap cluster-monitoring-config -o yaml
```

User workload monitoring is configured via `user-workload-monitoring-config` in `openshift-user-workload-monitoring`.

## Common Investigations

### Prometheus Health
```bash
# Pod status
oc -n openshift-monitoring get pods -l app.kubernetes.io/name=prometheus

# Config reload status
oc -n openshift-monitoring exec prometheus-k8s-0 -c prometheus -- promtool check config /etc/prometheus/config_out/prometheus.env.yaml

# TSDB status
oc -n openshift-monitoring exec prometheus-k8s-0 -c prometheus -- promtool tsdb analyze /prometheus

# Memory usage
oc -n openshift-monitoring top pod -l app.kubernetes.io/name=prometheus
```

### Alertmanager Health
```bash
# Pod status and cluster membership
oc -n openshift-monitoring get pods -l app.kubernetes.io/name=alertmanager

# Config validation
oc -n openshift-monitoring get secret alertmanager-main -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | amtool check-config -

# Cluster status
oc -n openshift-monitoring exec alertmanager-main-0 -c alertmanager -- amtool cluster show --alertmanager.url=http://localhost:9093
```

### Target Scrape Issues
```bash
# Down targets
oc -n openshift-monitoring exec prometheus-k8s-0 -c prometheus -- curl -s http://localhost:9090/api/v1/targets | python3 -c "import sys,json; [print(t['scrapeUrl'],t['lastError']) for t in json.load(sys.stdin)['data']['activeTargets'] if t['health']!='up']"

# ServiceMonitor/PodMonitor validation
oc get servicemonitors -A
oc get podmonitors -A
```

### Storage Issues
```bash
# PV usage for monitoring
oc -n openshift-monitoring get pvc
oc -n openshift-monitoring exec prometheus-k8s-0 -c prometheus -- df -h /prometheus

# Retention settings
oc -n openshift-monitoring get prometheus k8s -o jsonpath='{.spec.retention}'
```

### Thanos Querier Issues
```bash
# Store API endpoints
oc -n openshift-monitoring exec deploy/thanos-querier -- thanos query stores

# Query health
oc -n openshift-monitoring logs deploy/thanos-querier -c thanos-query --tail=50
```

## Tuning Recommendations

### High Memory / Cardinality
- Reduce scrape targets via ServiceMonitor label selectors
- Lower retention: `prometheusK8s.retention: 12h` in cluster-monitoring-config
- Add metric relabeling to drop high-cardinality labels
- Check for label explosion in custom ServiceMonitors

### Slow Rule Evaluation
- Split large rule groups into smaller ones
- Increase evaluation interval for non-critical rules
- Check for expensive PromQL in recording rules (joins, high-cardinality aggregations)

### Storage Pressure
- Reduce retention period
- Increase PVC size: `prometheusK8s.volumeClaimTemplate.spec.resources.requests.storage`
- Enable compaction tuning

### Alertmanager Notification Failures
- Check webhook endpoints are reachable from the cluster
- Verify TLS certificates for notification receivers
- Check network policies blocking egress from openshift-monitoring
