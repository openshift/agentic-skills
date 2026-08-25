#!/usr/bin/env python3
"""
extract_cluster.py — Step 1 of IntelliAide pure-skills pipeline.

Reads diagnostic data from /data/input (mounted from a PVC specified in the
Proposal's spec.dataSource.claimName) and validates it.

The PVC mount point is /data/input; cluster_dir in state.json is the deepest
directory that serves as the logical root for downstream file resolution.
Single-child wrapper directories are unwrapped so cluster_dir lands as close
to the real data as possible.  No assumptions are made about the internal
layout — downstream DataAnalyzer._resolve_path handles path expansion with
glob wildcards for any directory structure.

The PVC must be pre-populated with diagnostic data before the Proposal is
created. The operator mounts it read-only at /data/input.

Usage:
    python /app/skills/intelliaide/extract_cluster.py --query "etcd pods not ready"

    # Reuse an existing job dir (skips validation)
    python /app/skills/intelliaide/extract_cluster.py --query "..." --job-dir /tmp/intelliaide/abc123

Output (stdout JSON):
    {
      "job_id":      "<8-char id>",
      "job_dir":     "/tmp/intelliaide/<job_id>",
      "cluster_dir": "/data/input/...",
      "mode":        "must-gather",
      "success":     true,
      "return_code": 0
    }

On failure the script prints JSON with success=false and exits with code 1 so
the orchestrating agent stops immediately rather than proceeding with no data.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent
_JOB_BASE  = "/tmp/intelliaide"

_DATA_INPUT_DIR = Path("/data/input")


def _log_pod(msg: str) -> None:
    """Write a progress line directly to the container log stream (PID 1 stdout).

    Skill scripts run as subprocesses of the Claude Code CLI whose stdout is
    piped internally — it never reaches the pod log stream.  Opening PID 1's
    stdout directly is the only way to surface progress in `oc logs`.
    Falls back silently if the file is not accessible.
    """
    line = f"[intelliaide] {msg}\n"
    try:
        with open("/proc/1/fd/1", "a") as fh:
            fh.write(line)
    except Exception:
        sys.stderr.write(line)


_SKIP_DIRS = frozenset({"lost+found"})

_MIN_DATA_FILES = 3

_MAX_UNWRAP_DEPTH = 4


def _real_entries(parent: Path) -> "list[Path]":
    """List children of *parent*, skipping lost+found and hidden entries."""
    try:
        return sorted(
            p for p in parent.iterdir()
            if p.name not in _SKIP_DIRS and not p.name.startswith(".")
        )
    except OSError:
        return []


def _unwrap_single_child_dirs(raw_dir: Path) -> Path:
    """Walk single-child wrapper directories to reach the actual data root.

    Many diagnostic bundles wrap content in one or more levels of a single
    subdirectory (e.g. /data/input/bundle-abc123/cluster-dump/...).  This
    traverses down as long as a directory has exactly one real child that is
    itself a directory, stopping when the directory fans out or max depth is
    reached.
    """
    current = raw_dir
    for _ in range(_MAX_UNWRAP_DEPTH):
        children = _real_entries(current)
        dirs = [c for c in children if c.is_dir()]
        if len(dirs) == 1 and len(children) == 1:
            current = dirs[0]
        else:
            break
    return current


def _total_files(entries: "list[Path]") -> int:
    """Count files across all top-level entries (dirs and regular files)."""
    total = 0
    for entry in entries:
        if entry.is_file():
            total += 1
        elif entry.is_dir():
            total += sum(1 for _ in entry.rglob("*") if _.is_file())
    return total


def _check_data_source() -> "tuple[Path, bool, str]":
    """Validate /data/input and return the data root for downstream resolution.

    Checks: mount exists, is readable, is non-empty, has enough files.
    Then unwraps single-child wrapper directories so cluster_dir is as close
    to the real data as possible.

    Returns (cluster_dir, success, error_message).
    """
    if not _DATA_INPUT_DIR.exists():
        return _DATA_INPUT_DIR, False, (
            "No data source found at /data/input. "
            "Ensure spec.dataSource.claimName is set on the Proposal "
            "and the PVC contains diagnostic data."
        )

    try:
        list(_DATA_INPUT_DIR.iterdir())
    except OSError as exc:
        return _DATA_INPUT_DIR, False, (
            f"Cannot read /data/input: {exc}. "
            "Check PVC permissions and content."
        )

    real = _real_entries(_DATA_INPUT_DIR)
    if not real:
        return _DATA_INPUT_DIR, False, (
            "Data source at /data/input is empty (only lost+found). "
            "Ensure the PVC contains diagnostic data before creating the Proposal."
        )

    total_files = _total_files(real)
    if total_files < _MIN_DATA_FILES:
        return _DATA_INPUT_DIR, False, (
            f"Data source at /data/input has too few files ({total_files}). "
            "Ensure the PVC contains a complete diagnostic bundle."
        )

    data_root = _unwrap_single_child_dirs(_DATA_INPUT_DIR)
    return data_root, True, ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True,
                        help="Problem statement for RCA (passed through to state.json)")
    parser.add_argument("--job-dir", default=None,
                        help="Reuse an existing job dir (skips validation, updates state.json)")
    args = parser.parse_args()

    if args.job_dir:
        job_dir = Path(args.job_dir)
        job_id  = job_dir.name
    else:
        job_id  = str(uuid.uuid4())[:8]
        job_dir = Path(_JOB_BASE) / job_id

    job_dir.mkdir(parents=True, exist_ok=True)

    mode = "must-gather"

    if args.job_dir:
        cluster_dir, success, error_msg = _check_data_source()
    else:
        _log_pod(f"Step 1/4 — extract_cluster  job_id={job_id}  mode=must-gather")
        print(f"[extract_cluster] job_id={job_id}  mode=must-gather", file=sys.stderr)

        _log_pod("Step 1/4 — checking data source at /data/input (PVC mount)")
        cluster_dir, success, error_msg = _check_data_source()

    state = {
        "job_id":      job_id,
        "job_dir":     str(job_dir),
        "cluster_dir": str(cluster_dir),
        "query":       args.query,
        "mode":        mode,
    }
    (job_dir / "state.json").write_text(json.dumps(state, indent=2))

    if not success:
        _log_pod(f"Step 1/4 — extract_cluster FAILED: {error_msg}")
        print(json.dumps({
            "job_id":        job_id,
            "job_dir":       str(job_dir),
            "cluster_dir":   str(cluster_dir),
            "mode":          mode,
            "success":       False,
            "return_code":   1,
            "error":         error_msg,
        }))
        sys.exit(1)

    _log_pod(f"Step 1/4 — extract_cluster done  mode={mode}  cluster_dir={cluster_dir}")
    print(f"[extract_cluster] Data source validated: {cluster_dir}", file=sys.stderr)
    print(json.dumps({
        "job_id":      job_id,
        "job_dir":     str(job_dir),
        "cluster_dir": str(cluster_dir),
        "mode":        mode,
        "success":     True,
        "return_code": 0,
    }))


if __name__ == "__main__":
    main()
