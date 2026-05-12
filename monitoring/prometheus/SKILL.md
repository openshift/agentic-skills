---
name: prometheus
description: Query and analyze Prometheus metrics on Kubernetes and OpenShift clusters using promtool. Use when the user asks about Prometheus metrics, PromQL queries, metric analysis, alerting rules, recording rules, TSDB cardinality, or anything related to Prometheus monitoring — even if they just say "check metrics" or "why is CPU high on the cluster". Also trigger when the user mentions promtool, Thanos, or wants to validate Prometheus configuration or rules.
---

# Prometheus Metrics Analysis via promtool

Query, analyze, and validate Prometheus metrics on Kubernetes and OpenShift clusters using `promtool`.

## Prerequisites

- `promtool` must be installed (`brew install prometheus` includes it)
- `kubectl` or `oc` CLI with a valid kubeconfig pointing to the target cluster

## Critical Rules

These rules exist because they caused real failures during testing. Follow them exactly.

1. **Run setup + queries in a single bash call.** Shell variables (`$PROM_URL`, `$HTTP_CONFIG`, `$TOKEN`) do not persist across separate bash invocations. Combine setup and queries into one command using `&&`.

2. **Never use `!=` in PromQL.** Zsh mangles `!=` into `\!=` via history expansion, even inside single quotes. Bash does not have this issue, but avoid `!=` for portability. Use `=~".+"` instead of `!=""`, and `=~"^((?!value).)*$"` or a negated regex instead of `!=`:
   ```bash
   # WRONG — zsh corrupts this
   '{container!=""}'
   # CORRECT
   '{container=~".+"}'
   ```

3. **JSON output is a raw array.** `promtool -o json` outputs `[{metric:{...}, value:[ts, val]}, ...]` — NOT `{data:{result:...}}`. Parse with `jq '.[]'`, not `jq '.data.result[]'`.

4. **Token acquisition priority.** Inside a pod, use the mounted SA token first: `TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token 2>/dev/null || true)`. Only fall back to `oc whoami -t` when running outside a pod. The SA must have `cluster-monitoring-view` ClusterRole bound for Prometheus/Thanos access on OpenShift.

5. **`promtool check healthy/ready` returns 503 on Thanos Querier.** This is expected — Thanos doesn't expose `/-/healthy`. Verify connectivity with `promtool query instant ... 'up'` instead.

6. **Clean up temp files when done.** Always `rm -f "$HTTP_CONFIG"` and `kill $PF_PID 2>/dev/null` (if port-forwarding) after queries complete.

## Setup + Query (Single Bash Call)

Every promtool session should follow this pattern in one bash command. Adapt the query section as needed.

### OpenShift

```bash
TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token 2>/dev/null || true) && \
if [ -z "$TOKEN" ]; then TOKEN=$(oc whoami -t 2>/dev/null || true); fi && \
if [ -z "$TOKEN" ]; then echo "ERROR: No token available"; exit 1; fi && \
HOST=$(oc -n openshift-monitoring get route thanos-querier -o jsonpath='{.status.ingress[].host}') && \
PROM_URL="https://$HOST" && \
HTTP_CONFIG=$(mktemp /tmp/prom-http-XXXXXX.yaml) && \
cat > "$HTTP_CONFIG" <<EOF
authorization:
  type: Bearer
  credentials: $TOKEN
tls_config:
  insecure_skip_verify: true
EOF
# --- queries go here, chained with && ---
promtool query instant --http.config.file="$HTTP_CONFIG" "$PROM_URL" 'up' && \
# --- clean up ---
rm -f "$HTTP_CONFIG"
```

### Kubernetes

```bash
export KUBECONFIG=<path-to-kubeconfig> && \
PROM_NS="monitoring" && \
PROM_SVC=$(kubectl get svc -n "$PROM_NS" -o jsonpath='{.items[?(@.spec.ports[*].port==9090)].metadata.name}') && \
kubectl port-forward -n "$PROM_NS" "svc/$PROM_SVC" 9090:9090 &
PF_PID=$! && sleep 2 && \
PROM_URL="http://localhost:9090" && \
HTTP_CONFIG=$(mktemp /tmp/prom-http-XXXXXX.yaml) && \
cat > "$HTTP_CONFIG" <<EOF
tls_config:
  insecure_skip_verify: true
EOF
# --- queries go here ---
promtool query instant --http.config.file="$HTTP_CONFIG" "$PROM_URL" 'up' && \
# --- clean up ---
rm -f "$HTTP_CONFIG" && kill $PF_PID 2>/dev/null
```

## Query Examples

All examples below assume `$HTTP_CONFIG` and `$PROM_URL` are set (from the setup block above). Chain them in the same bash call.

```bash
# Instant query (text output)
promtool query instant --http.config.file="$HTTP_CONFIG" "$PROM_URL" 'up'

# Instant query (JSON, parsed with jq)
promtool query instant --http.config.file="$HTTP_CONFIG" -o json "$PROM_URL" \
  'sum(rate(container_cpu_usage_seconds_total{container=~".+"}[5m])) by (namespace)' | \
  jq -r '.[] | "\(.metric.namespace): \(.value[1] | tonumber | . * 1000 | round / 1000) cores"'

# Range query (last hour, 1-minute steps)
# macOS: date -u -v-1H    Linux: date -u -d '1 hour ago'
promtool query range --http.config.file="$HTTP_CONFIG" \
  --start="$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)" \
  --end="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --step=1m \
  "$PROM_URL" 'node_memory_MemAvailable_bytes'

# Discover all metric names
promtool query labels --http.config.file="$HTTP_CONFIG" "$PROM_URL" __name__

# Find series matching a selector
promtool query series --http.config.file="$HTTP_CONFIG" \
  --match='container_cpu_usage_seconds_total{namespace="default"}' \
  "$PROM_URL"
```

## References

Detailed command references — read on demand when you need specifics:

|references/cluster-access.md — Discovery, auth, and port-forward setup for OpenShift and Kubernetes
|references/querying.md — Instant, range, series, labels, analyze, and PromQL formatting
|references/validation.md — Check config, check rules, check metrics, test rules (unit testing)
|references/tsdb.md — Analyze cardinality, list blocks, dump data, create blocks from rules

## Common PromQL Patterns

Useful starting points when the user asks broad questions:

| Question | PromQL |
|---|---|
| Which targets are down? | `up == 0` |
| CPU usage by namespace | `sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace)` |
| Memory usage by pod | `container_memory_working_set_bytes{container=~".+"}` |
| Disk pressure | `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.1` |
| API server request rate | `sum(rate(apiserver_request_total[5m])) by (verb, resource)` |
| API server error rate | `sum(rate(apiserver_request_total{code=~"5.."}[5m])) by (resource)` |
| Pod restart count | `increase(kube_pod_container_status_restarts_total[1h]) > 0` |
| Node CPU saturation | `1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)` |
| etcd leader changes | `increase(etcd_server_leader_changes_seen_total[1h])` |
| Scrape duration | `scrape_duration_seconds` |

## Important

- For OpenShift, always query the Thanos Querier route — it aggregates data from all Prometheus instances.
- Use `-o json` with `jq` when you need to parse or filter results programmatically.
- **Cross-platform date**: Use `date -u -d '1 hour ago' +FMT 2>/dev/null || date -u -v-1H +FMT` to work on both Linux (GNU date) and macOS (BSD date).
