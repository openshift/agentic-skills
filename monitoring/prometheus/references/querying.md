# Querying Reference

All `promtool query` subcommands for querying a Prometheus server.

Every command below requires:
- `--http.config.file="$HTTP_CONFIG"` for auth (see cluster-access.md)
- The Prometheus server URL as `$PROM_URL`

## Table of Contents

1. [Instant Query](#instant-query)
2. [Range Query](#range-query)
3. [Series Discovery](#series-discovery)
4. [Label Discovery](#label-discovery)
5. [Metric Analysis](#metric-analysis)
6. [PromQL Formatting](#promql-formatting)

---

## Instant Query

Evaluate a PromQL expression at a single point in time.

```bash
promtool query instant [flags] <server> <expression>
```

| Flag | Default | Description |
|---|---|---|
| `--time` | now | Evaluation time (RFC3339 or Unix timestamp) |
| `-o` / `--format` | `promql` | Output format: `promql` or `json` |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# Basic query
promtool query instant --http.config.file="$HTTP_CONFIG" "$PROM_URL" 'up'

# JSON output — promtool outputs a raw JSON array: [{metric:{...}, value:[ts, val]}, ...]
promtool query instant --http.config.file="$HTTP_CONFIG" -o json "$PROM_URL" 'up' | jq .

# Query at a specific time
promtool query instant --http.config.file="$HTTP_CONFIG" \
  --time="2024-01-15T10:00:00Z" \
  "$PROM_URL" 'up'

# Aggregated query — extract namespace and value
promtool query instant --http.config.file="$HTTP_CONFIG" -o json \
  "$PROM_URL" 'sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace)' \
  | jq '.[] | {namespace: .metric.namespace, value: .value[1]}'

# Top 10 memory consumers
promtool query instant --http.config.file="$HTTP_CONFIG" -o json \
  "$PROM_URL" 'topk(10, container_memory_working_set_bytes{container!=""})' \
  | jq '.[] | {pod: .metric.pod, namespace: .metric.namespace, bytes: .value[1]}'
```

---

## Range Query

Evaluate a PromQL expression over a time range.

```bash
promtool query range [flags] <server> <expression>
```

| Flag | Default | Description |
|---|---|---|
| `--start` | | Start time (RFC3339 or Unix timestamp, required) |
| `--end` | | End time (RFC3339 or Unix timestamp, required) |
| `--step` | | Step size (duration like `1m`, `5m`, `1h`, required) |
| `-o` / `--format` | `promql` | Output format: `promql` or `json` |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# Last hour, 1-minute resolution (cross-platform: tries GNU date first, falls back to BSD)
promtool query range --http.config.file="$HTTP_CONFIG" \
  --start="$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)" \
  --end="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --step=1m \
  "$PROM_URL" 'node_memory_MemAvailable_bytes'

# Last 24 hours, 5-minute resolution
promtool query range --http.config.file="$HTTP_CONFIG" \
  --start="$(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-1d +%Y-%m-%dT%H:%M:%SZ)" \
  --end="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --step=5m -o json \
  "$PROM_URL" 'avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)' | jq .
```

### Choosing Step Size

- **1m** — fine-grained, last 1-2 hours
- **5m** — standard, last 6-24 hours
- **15m** — daily overview
- **1h** — weekly/monthly trends

Rule of thumb: aim for 100-500 data points per series.

---

## Series Discovery

Find time series matching label selectors.

```bash
promtool query series [flags] <server>
```

| Flag | Default | Description |
|---|---|---|
| `--match` | | Series selector (required, repeatable) |
| `--start` | | Start time |
| `--end` | | End time |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# All series for a metric
promtool query series --http.config.file="$HTTP_CONFIG" \
  --match='container_cpu_usage_seconds_total' \
  "$PROM_URL"

# Series in a specific namespace
promtool query series --http.config.file="$HTTP_CONFIG" \
  --match='container_cpu_usage_seconds_total{namespace="kube-system"}' \
  "$PROM_URL"

# Multiple selectors (OR)
promtool query series --http.config.file="$HTTP_CONFIG" \
  --match='up' --match='scrape_duration_seconds' \
  "$PROM_URL"
```

---

## Label Discovery

List label names or values.

```bash
promtool query labels [flags] <server> <label-name>
```

| Flag | Default | Description |
|---|---|---|
| `--start` | | Start time |
| `--end` | | End time |
| `--match` | | Restrict to series matching selector (repeatable) |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# List all metric names
promtool query labels --http.config.file="$HTTP_CONFIG" "$PROM_URL" __name__

# List all namespaces that have metrics
promtool query labels --http.config.file="$HTTP_CONFIG" "$PROM_URL" namespace

# List pods for a specific metric
promtool query labels --http.config.file="$HTTP_CONFIG" \
  --match='container_cpu_usage_seconds_total' \
  "$PROM_URL" pod

# List all label names (pass empty string)
promtool query labels --http.config.file="$HTTP_CONFIG" "$PROM_URL" ""
```

---

## Metric Analysis

Analyze metric usage patterns (e.g., histogram bucket boundaries).

```bash
promtool query analyze [flags]
```

| Flag | Default | Description |
|---|---|---|
| `--server` | | Prometheus server URL (required) |
| `--type` | `histogram` | Metric type to analyze |
| `--duration` | `1h` | Time frame to analyze |
| `--time` | now | Query time |
| `--match` | | Series selector (required, repeatable) |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# Analyze histogram bucket distribution
promtool query analyze \
  --server="$PROM_URL" \
  --http.config.file="$HTTP_CONFIG" \
  --match='apiserver_request_duration_seconds_bucket' \
  --duration=1h

# Analyze a specific histogram
promtool query analyze \
  --server="$PROM_URL" \
  --http.config.file="$HTTP_CONFIG" \
  --match='http_request_duration_seconds_bucket{handler="/api/v1/query"}' \
  --duration=6h
```

---

## PromQL Formatting

Pretty-print and manipulate PromQL expressions (requires `--experimental` flag).

```bash
# Format / pretty-print a query
promtool --experimental promql format 'sum(rate(container_cpu_usage_seconds_total{namespace!=""}[5m])) by (namespace, pod)'

# Add a label matcher to a query
promtool --experimental promql label-matchers set \
  'sum(rate(http_requests_total[5m])) by (code)' \
  namespace myapp

# Set a regex label matcher
promtool --experimental promql label-matchers set -t '=~' \
  'up' job 'kube.*'

# Remove a label matcher
promtool --experimental promql label-matchers delete \
  'up{job="prometheus"}' job
```
