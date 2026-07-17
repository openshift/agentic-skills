# Cluster Troubleshooting Skill

Diagnose and troubleshoot OpenShift cluster issues: alerts firing, pods crashing, deployments stuck, nodes not ready, operators degraded, and other cluster anomalies.

## Structure

```
cluster-troubleshoot/
  SKILL.md          # Skill definition (agent prompt)
  tools/            # Diagnostic shell scripts (JSON output)
```

## Tools

All scripts are in `tools/`, output JSON to stdout, and return structured error objects on failure.

| Script | Purpose |
|--------|---------|
| `prometheus-setup.sh` | Get TOKEN and THANOS_URL for Prometheus access |
| `query-alert.sh` | Query firing instances of a named alert |
| `fetch-alert-rule.sh` | Get alert PromQL expression and annotations |
| `prometheus-query.sh` | Run an instant PromQL query |
| `prometheus-query-range.sh` | Run a range PromQL query |
| `discover-metrics.sh` | Search for available metric names |
| `get-firing-alerts.sh` | List all currently firing alerts |
| `diagnose-pod.sh` | Pod status, conditions, events, logs |
| `diagnose-node.sh` | Node conditions, capacity, taints |
| `diagnose-operator.sh` | ClusterOperator health |
| `diagnose-workload.sh` | Deployment/StatefulSet/DaemonSet status |
| `get-events.sh` | Events sorted by time |
| `check-recent-changes.sh` | Recent rollouts, image changes |
