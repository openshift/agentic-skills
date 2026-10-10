#!/usr/bin/env python3
"""
analyze_data.py — Step 3 (per-priority pass) of IntelliAide pure-skills pipeline.

Runs ML-based YAML classification and log template mining on the
extracted cluster files for one priority tier, then serializes both the ML
classification result and the log error entries to a JSON file so that
perform_rca.py can read them without accessing the Results/ directory.

Usage:
    python /app/skills/intelliaide/analyze_data.py --job-dir /tmp/intelliaide/<job_id> --priority high

Reads:
    <job_dir>/state.json           (cluster_dir)
    <job_dir>/file_selection.json  (list of files for this priority)

Writes:
    <job_dir>/analysis_<priority>.json

Output (stdout JSON):
    {
      "priority":      "high",
      "yaml_files":    N,
      "log_files":     N,
      "log_entries":   N,
      "analysis_path": "<job_dir>/analysis_high.json"
    }
"""

import argparse
import json
import os
import sys
from pathlib import Path

# All IntelliAide engine code lives alongside this script in the same folder.
# At runtime (in the sandbox container) this resolves to /app/skills/intelliaide/
_SKILL_DIR = Path(__file__).resolve().parent
for _p in (
    str(_SKILL_DIR / "vendor"),        # vendored packages (drain3, scikit-learn, etc.)
    str(_SKILL_DIR / "Main-program"),
    str(_SKILL_DIR / "python-client"),
    str(_SKILL_DIR),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data_analyzer import DataAnalyzer   # noqa: E402
import data_analyzer as _da               # noqa: E402
import app_paths as _ap                   # noqa: E402

# The skills image volume is mounted read-only by Kubernetes.
# Redirect all IntelliAide write paths to /tmp which is always writable.
_WRITABLE_APP = Path("/tmp/intelliaide-app")
_WRITABLE_APP.mkdir(parents=True, exist_ok=True)
(Path("/tmp/intelliaide-app/Results/log_classifications")).mkdir(parents=True, exist_ok=True)

# data_analyzer.py binds get_application_dir at import time (from app_paths import ...).
# Patch its local reference so output goes to /tmp instead of the read-only image mount.
_da.get_application_dir = lambda: _WRITABLE_APP

# llm_rca_agent.py and data_analyzer.py use lazy `from app_paths import get_results_dir`.
# Patch the app_paths module so those lazy imports resolve to a writable path.
_ap.get_results_dir = lambda: _WRITABLE_APP / "Results"


def _log_pod(msg: str) -> None:
    """Write a progress line directly to the container log stream (PID 1 stdout)."""
    line = f"[intelliaide] {msg}\n"
    try:
        with open("/proc/1/fd/1", "a") as fh:
            fh.write(line)
    except Exception:
        sys.stderr.write(line)


_ERROR_LEVELS = {"RareError", "HighFreqError", "Error"}


def _build_log_entries(log_processing_result: dict) -> list:
    """Read error-level log content from per-file saved paths.

    Mirrors the logic in tools.py:execute_analyze_logs so that the resulting
    list can be passed directly to run_rca_chunked / run_rca_and_summary_continued.
    """
    entries = []
    for pf in log_processing_result.get("per_file", []):
        source_path = pf.get("file", "")
        try:
            original_size = os.path.getsize(source_path) if source_path and os.path.exists(source_path) else 0
        except Exception:
            original_size = 0

        for level_name, path in (pf.get("saved") or {}).items():
            if level_name not in _ERROR_LEVELS or not path:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                entries.append({
                    "file":          os.path.basename(path),
                    "content":       content,
                    "original_size": original_size,
                })
            except Exception:
                pass
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir",  required=True)
    parser.add_argument("--priority", required=True, choices=["high", "medium", "low"])
    args = parser.parse_args()

    job_dir     = Path(args.job_dir)
    state       = json.loads((job_dir / "state.json").read_text())
    cluster_dir = state["cluster_dir"]

    file_selection = json.loads((job_dir / "file_selection.json").read_text())
    entries        = file_selection.get(args.priority, [])

    # Use resolved paths where the extractor actually found the file
    file_paths = [
        e["resolved"] if e.get("found") else e["original"]
        for e in entries
    ]

    analysis_path = str(job_dir / f"analysis_{args.priority}.json")

    # --- No-op for empty priority tier ---
    if not file_paths:
        print(f"[analyze_data] No {args.priority}-priority files — skipping analysis.", file=sys.stderr)
        empty = {
            "priority":    args.priority,
            "yaml_errors": {},
            "log_entries": [],
            "yaml_files":  0,
            "log_files":   0,
            "failed_files": [],
        }
        Path(analysis_path).write_text(json.dumps(empty, indent=2))
        print(json.dumps({
            "priority":      args.priority,
            "yaml_files":    0,
            "log_files":     0,
            "log_entries":   0,
            "analysis_path": analysis_path,
        }))
        return

    _log_pod(f"Step 3/4 — analyze_data  priority={args.priority}  files={len(file_paths)}")
    print(
        f"[analyze_data] Analyzing {len(file_paths)} {args.priority}-priority files "
        f"under {cluster_dir}",
        file=sys.stderr,
    )

    analyzer = DataAnalyzer(must_gather_base_dir=cluster_dir)
    result = analyzer.analyze_files(
        file_paths,
        file_types=["yaml", "log", "json"],
        suggested_files_with_priority=entries,
    )

    yaml_errors           = result.get("ml_classification_result", {})
    log_processing_result = result.get("log_processing_result", {})
    log_entries           = _build_log_entries(log_processing_result)

    yaml_count = len(result.get("yaml_files_processed", []))
    log_count  = len(result.get("log_files_for_analysis", []))

    print(
        f"[analyze_data] YAML={yaml_count} log={log_count} "
        f"log_entries={len(log_entries)} failed={len(result.get('failed_files', []))}",
        file=sys.stderr,
    )

    analysis = {
        "priority":     args.priority,
        "yaml_errors":  yaml_errors,
        "log_entries":  log_entries,
        "yaml_files":   yaml_count,
        "log_files":    log_count,
        "failed_files": result.get("failed_files", []),
    }
    Path(analysis_path).write_text(json.dumps(analysis, indent=2, default=str))

    _log_pod(
        f"Step 3/4 — analyze_data done  priority={args.priority}  "
        f"yaml={yaml_count} logs={log_count} log_entries={len(log_entries)}"
    )
    print(json.dumps({
        "priority":      args.priority,
        "yaml_files":    yaml_count,
        "log_files":     log_count,
        "log_entries":   len(log_entries),
        "analysis_path": analysis_path,
    }))


if __name__ == "__main__":
    main()
