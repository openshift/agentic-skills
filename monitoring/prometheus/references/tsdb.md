# TSDB Operations Reference

Analyze, inspect, and manage Prometheus TSDB data.

These commands operate on local TSDB data directories. They are useful for cardinality analysis, debugging storage issues, and backfilling data.

## Table of Contents

1. [Analyze](#analyze)
2. [List Blocks](#list-blocks)
3. [Dump Data](#dump-data)
4. [Create Blocks from Rules](#create-blocks-from-rules)
5. [Benchmarking](#benchmarking)
6. [Debug](#debug)

---

## Analyze

Analyze TSDB block(s) for cardinality, label statistics, and storage efficiency.

```bash
promtool tsdb analyze [flags] [db-path] [block-id]
```

| Flag | Default | Description |
|---|---|---|
| `--limit` | 20 | Number of items to show per list |
| `--extended` | false | Run extended analysis |
| `--match` | | Series selector to filter analysis |

Defaults: `db-path` = `data/`, `block-id` = last block.

### Examples

```bash
# Analyze local TSDB (e.g., from a Prometheus data dir)
promtool tsdb analyze /path/to/prometheus/data

# Show top 50 metrics by cardinality
promtool tsdb analyze --limit=50 /path/to/prometheus/data

# Extended analysis
promtool tsdb analyze --extended /path/to/prometheus/data

# Analyze only specific metrics
promtool tsdb analyze --match='container_cpu_usage_seconds_total' /path/to/prometheus/data

# Analyze a specific block
promtool tsdb analyze /path/to/prometheus/data 01ABCDEF12345678
```

### Output Includes

- **Block metadata**: min/max time, duration, number of series/samples/chunks
- **Label pair cardinality**: which label pairs have the most series
- **Highest cardinality labels**: labels with the most unique values
- **Highest cardinality metric names**: metrics with the most series

This is the go-to command for diagnosing cardinality explosions.

---

## List Blocks

List all TSDB blocks with metadata.

```bash
promtool tsdb list [flags] [db-path]
```

| Flag | Default | Description |
|---|---|---|
| `-r` / `--human-readable` | false | Print sizes in human-readable format |

### Examples

```bash
# List blocks
promtool tsdb list /path/to/prometheus/data

# Human-readable sizes
promtool tsdb list -r /path/to/prometheus/data
```

---

## Dump Data

Dump raw time series data from TSDB blocks.

```bash
promtool tsdb dump [flags] [db-path]
```

| Flag | Default | Description |
|---|---|---|
| `--min-time` | MinInt64 | Minimum timestamp in milliseconds |
| `--max-time` | MaxInt64 | Maximum timestamp in milliseconds |
| `--match` | `{__name__=~'(?s:.*)'}` | Series selector (repeatable) |
| `--format` | `prom` | Output: `prom` or `seriesjson` |

### Examples

```bash
# Dump all data in Prometheus exposition format
promtool tsdb dump /path/to/prometheus/data

# Dump specific metrics
promtool tsdb dump --match='up' /path/to/prometheus/data

# Dump as JSON
promtool tsdb dump --format=seriesjson /path/to/prometheus/data

# Dump a time range (timestamps in milliseconds)
promtool tsdb dump \
  --min-time=1700000000000 \
  --max-time=1700003600000 \
  /path/to/prometheus/data
```

### OpenMetrics Format

```bash
promtool tsdb dump-openmetrics [flags] [db-path]
```

Same flags as `dump` except no `--format` (always OpenMetrics). Requires `--experimental`.

---

## Create Blocks from Rules

Backfill recording rules by querying historical data from a running Prometheus and producing TSDB blocks.

```bash
promtool tsdb create-blocks-from rules [flags] <rule-files...>
```

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:9090` | Prometheus API URL |
| `--start` | | Start time (required) |
| `--end` | 3 hours ago | End time |
| `--output-dir` | `data/` | Output directory |
| `--eval-interval` | `60s` | Evaluation interval |
| `--http.config.file` | | HTTP client config file |

### Examples

```bash
# Backfill a recording rule for the last 7 days
promtool tsdb create-blocks-from rules \
  --url="$PROM_URL" \
  --http.config.file="$HTTP_CONFIG" \
  --start="$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)" \
  --output-dir=/tmp/backfill-blocks \
  recording-rules.yml
```

### Import OpenMetrics Data

```bash
promtool tsdb create-blocks-from openmetrics [flags] <input-file> [output-dir]
```

| Flag | Default | Description |
|---|---|---|
| `-r` | false | Human-readable output |
| `-q` | false | Quiet mode |
| `--label` | | Labels to attach (repeatable) |

---

## Benchmarking

Benchmark TSDB write performance.

```bash
promtool tsdb bench write [flags]
```

| Flag | Default | Description |
|---|---|---|
| `--out` | `benchout` | Output path |
| `--metrics` | 10000 | Number of metrics |
| `--scrapes` | 3000 | Number of scrapes |

---

## Debug

Fetch debug information from a running Prometheus server.

```bash
promtool debug pprof <server>   # Profiling data
promtool debug metrics <server> # Current metrics
promtool debug all <server>     # Everything
```

All accept `--http.config.file` for authentication.

### Examples

```bash
# Fetch all debug info
promtool debug all "$PROM_URL" --http.config.file="$HTTP_CONFIG"

# Profiling data only
promtool debug pprof "$PROM_URL" --http.config.file="$HTTP_CONFIG"
```

Output is saved to `debug.tar.gz` in the current directory.
