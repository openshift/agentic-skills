# Validation & Testing Reference

Validate Prometheus configuration, lint rules, check metrics naming, and run unit tests.

## Table of Contents

1. [Check Config](#check-config)
2. [Check Rules](#check-rules)
3. [Check Metrics](#check-metrics)
4. [Check Health & Readiness](#check-health--readiness)
5. [Unit Testing Rules](#unit-testing-rules)

---

## Check Config

Validate Prometheus configuration files for syntax and semantic correctness.

```bash
promtool check config <config-file> [config-file...]
```

| Flag | Default | Description |
|---|---|---|
| `--syntax-only` | false | Only check YAML syntax, skip semantic validation |
| `--lint` | `duplicate-rules` | Linting: `all`, `duplicate-rules`, `too-long-scrape-interval`, `none` |
| `--lint-fatal` | false | Make lint errors exit with code 3 |
| `--agent` | false | Check config for Prometheus Agent mode |

### Examples

```bash
# Validate a config file
promtool check config prometheus.yml

# Syntax check only (faster, no network)
promtool check config --syntax-only prometheus.yml

# Full linting
promtool check config --lint=all --lint-fatal prometheus.yml
```

---

## Check Rules

Validate Prometheus rule files (alerting and recording rules).

```bash
promtool check rules [rule-file...] # reads stdin if no files
```

| Flag | Default | Description |
|---|---|---|
| `--lint` | `duplicate-rules` | Linting: `all`, `duplicate-rules`, `none` |
| `--lint-fatal` | false | Make lint errors exit with code 3 |

### Examples

```bash
# Validate rule files
promtool check rules alerts.yml recording-rules.yml

# Validate all rule files in a directory
promtool check rules rules/*.yml

# Read from stdin
cat my-rules.yml | promtool check rules

# Strict linting
promtool check rules --lint=all --lint-fatal alerts.yml
```

---

## Check Metrics

Lint metrics exposition for naming conventions and best practices.

```bash
promtool check metrics [flags]
```

Reads metrics in Prometheus exposition format from stdin.

| Flag | Default | Description |
|---|---|---|
| `--extended` | false | Print extended cardinality information |
| `--lint` | `all` | Linting: `all`, `none` |

### Examples

```bash
# Lint metrics from a running Prometheus
curl -s http://localhost:9090/metrics | promtool check metrics

# Lint metrics from any instrumented endpoint
curl -s http://localhost:8080/metrics | promtool check metrics --extended

# From a cluster pod via port-forward
kubectl port-forward -n <ns> <pod> 8080:8080 &
curl -s http://localhost:8080/metrics | promtool check metrics --extended
kill %1
```

Common warnings:
- `counter should have _total suffix`
- `histogram should have _bucket/_count/_sum`
- `metric name should match [a-zA-Z_:][a-zA-Z0-9_:]*`
- `help string missing`

---

## Check Health & Readiness

Check if a Prometheus server is healthy or ready.

```bash
promtool check healthy [flags]
promtool check ready [flags]
```

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:9090` | Prometheus server URL |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# Check health
promtool check healthy --url="$PROM_URL" --http.config.file="$HTTP_CONFIG"

# Check readiness
promtool check ready --url="$PROM_URL" --http.config.file="$HTTP_CONFIG"
```

---

## Unit Testing Rules

Test alerting and recording rules against synthetic time series data without a running Prometheus server.

```bash
promtool test rules [flags] <test-file...>
```

| Flag | Default | Description |
|---|---|---|
| `--run` | | Only run test groups matching regex (repeatable) |
| `--debug` | false | Print debug output |
| `--diff` | false | Print colored diff output |
| `--junit` | | File path for JUnit XML results |

### Test File Format

```yaml
# test-alerts.yml
rule_files:
  - alerts.yml
  - recording-rules.yml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'up{job="prometheus", instance="localhost:9090"}'
        values: '1 1 1 0 0 0 0 0 0 0'
      # Expanding notation: start+incrementxcount
      - series: 'http_requests_total{method="GET"}'
        values: '0+10x10'  # 0, 10, 20, 30, ..., 100

    # Test alerting rules
    alert_rule_test:
      - eval_time: 5m
        alertname: InstanceDown
        exp_alerts:
          - exp_labels:
              severity: critical
              job: prometheus
              instance: 'localhost:9090'
            exp_annotations:
              summary: 'Instance localhost:9090 down'

    # Test PromQL expressions / recording rules
    promql_expr_test:
      - expr: 'http_requests_total'
        eval_time: 5m
        exp_samples:
          - labels: 'http_requests_total{method="GET"}'
            value: 50
```

### Examples

```bash
# Run all tests
promtool test rules test-alerts.yml

# Run specific test groups
promtool test rules --run="InstanceDown" test-alerts.yml

# Debug output
promtool test rules --debug --diff test-alerts.yml

# JUnit output (CI integration)
promtool test rules --junit=results.xml test-alerts.yml
```

### Expanding Notation for Input Series

| Pattern | Expansion |
|---|---|
| `1 2 3` | Literal values at each interval |
| `0+1x5` | 0, 1, 2, 3, 4, 5 |
| `10-2x3` | 10, 8, 6, 4 |
| `_` | Stale marker |
| `1x3 _ 5x2` | 1, 1, 1, stale, 5, 5 |
