#!/usr/bin/env python3
"""
perform_rca.py — Step 4 of IntelliAide pure-skills pipeline (LLM-free).

This script has two modes, selected with --mode:

  chunks (default)
  ----------------
  Reads analyze_data.py output, runs token-aware chunking and prompt formatting
  (all pure Python), writes chunk prompt files to disk, and outputs a manifest.
  NO LLM call is made.  After this script exits, the orchestrating agent (Claude)
  must read each chunk file, reason about root cause, and write one summary file
  per chunk: <job_dir>/chunk_summary_<priority>_<n>.md

  reduce
  ------
  Reads the Claude-written summary files, estimates their token sizes, and groups
  them into batches that fit within the configured token budget — exactly as
  _hierarchical_reduce() did, but without calling an LLM.  Outputs a reduce
  manifest.  After this exits, the orchestrating agent synthesises each batch and
  writes <batch["output_file"]>.  If is_final=false, the agent calls this script
  again at level+1 with the batch output files as --summary-files.

Usage:
    # Chunk phase (first call per priority):
    python perform_rca.py --job-dir <job_dir> --priority high

    # Reduce phase (after Claude writes chunk summaries):
    python perform_rca.py --job-dir <job_dir> --priority high --mode reduce \\
        --level 1 \\
        --summary-files <job_dir>/chunk_summary_high_1.md \\
                        <job_dir>/chunk_summary_high_2.md

    # Continuation pass — medium priority, building on high-priority results:
    python perform_rca.py --job-dir <job_dir> --priority medium
    python perform_rca.py --job-dir <job_dir> --priority medium --mode reduce \\
        --level 1 --summary-files <job_dir>/chunk_summary_medium_1.md ...

Reads (chunks mode):
    <job_dir>/state.json
    <job_dir>/analysis_<priority>.json
    <job_dir>/file_selection.json          (to determine has_medium / has_low)

Writes (chunks mode):
    <job_dir>/chunk_<priority>_<n>.md
    <job_dir>/rca_chunks_<priority>_manifest.json

Writes (reduce mode):
    <job_dir>/reduce_level<level>_manifest.json

Output (chunks mode, stdout JSON):
    {
      "mode":          "chunks",
      "priority":      "high",
      "chunk_count":   3,
      "manifest_path": "<job_dir>/rca_chunks_high_manifest.json",
      "has_medium":    true,
      "has_low":       false
    }

Output (reduce mode, stdout JSON):
    {
      "mode":             "reduce",
      "priority":         "high",
      "level":            1,
      "batch_count":      2,
      "is_final":         false,
      "manifest_path":    "<job_dir>/reduce_level1_manifest.json"
    }
"""

import argparse
import json
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent
for _p in (
    str(_SKILL_DIR / "vendor"),
    str(_SKILL_DIR / "Main-program"),
    str(_SKILL_DIR / "python-client"),
    str(_SKILL_DIR),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from llm_rca_agent import prepare_rca_chunks, prepare_reduce_batches  # noqa: E402
from app_paths import get_config_path                                   # noqa: E402


def _log_pod(msg: str) -> None:
    line = f"[intelliaide] {msg}\n"
    try:
        with open("/proc/1/fd/1", "a") as fh:
            fh.write(line)
    except Exception:
        sys.stderr.write(line)


def _mode_chunks(args: argparse.Namespace) -> None:
    job_dir   = Path(args.job_dir)
    state     = json.loads((job_dir / "state.json").read_text())
    query     = state["query"]

    analysis_file = job_dir / f"analysis_{args.priority}.json"
    analysis      = json.loads(analysis_file.read_text())
    yaml_errors   = analysis.get("yaml_errors", {})
    log_entries   = analysis.get("log_entries", []) or None

    _log_pod(
        f"Step 4 — perform_rca (chunks)  priority={args.priority}  "
        f"yaml_keys={len(yaml_errors)}  "
        f"log_entries={len(log_entries) if log_entries else 0}"
    )
    print(
        f"[perform_rca] chunks  priority={args.priority}  "
        f"yaml_keys={len(yaml_errors)}  "
        f"log_entries={len(log_entries) if log_entries else 0}",
        file=sys.stderr,
    )

    config_path = str(get_config_path())
    manifest = prepare_rca_chunks(
        ml_classification_result=yaml_errors,
        job_dir=str(job_dir),
        priority=args.priority,
        log_error_entries=log_entries,
        config_path=config_path,
    )

    file_selection = json.loads((job_dir / "file_selection.json").read_text())
    has_medium     = len(file_selection.get("medium", [])) > 0
    has_low        = len(file_selection.get("low",    [])) > 0

    _log_pod(
        f"Step 4 — perform_rca chunks done  priority={args.priority}  "
        f"chunks={manifest['chunk_count']}"
    )
    print(json.dumps({
        "mode":          "chunks",
        "priority":      args.priority,
        "chunk_count":   manifest["chunk_count"],
        "manifest_path": manifest["manifest_path"],
        "has_medium":    has_medium,
        "has_low":       has_low,
    }))


def _mode_reduce(args: argparse.Namespace) -> None:
    job_dir = Path(args.job_dir)
    state   = json.loads((job_dir / "state.json").read_text())
    query   = state["query"]

    if not args.summary_files:
        print(
            json.dumps({"error": "--summary-files is required in reduce mode"}),
        )
        sys.exit(1)

    _log_pod(
        f"Step 5 — perform_rca (reduce)  priority={args.priority}  "
        f"level={args.level}  files={len(args.summary_files)}"
    )
    print(
        f"[perform_rca] reduce  priority={args.priority}  "
        f"level={args.level}  files={len(args.summary_files)}",
        file=sys.stderr,
    )

    config_path = str(get_config_path())
    manifest = prepare_reduce_batches(
        summary_files=args.summary_files,
        job_dir=str(job_dir),
        level=args.level,
        problem_statement=query,
        config_path=config_path,
    )

    _log_pod(
        f"Step 5 — perform_rca reduce done  priority={args.priority}  "
        f"level={args.level}  batches={manifest['batch_count']}  "
        f"is_final={manifest['is_final']}"
    )
    print(json.dumps({
        "mode":          "reduce",
        "priority":      args.priority,
        "level":         args.level,
        "batch_count":   manifest["batch_count"],
        "is_final":      manifest["is_final"],
        "manifest_path": manifest["manifest_path"],
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir",      required=True)
    parser.add_argument("--priority",     required=True, choices=["high", "medium", "low"])
    parser.add_argument("--mode",         default="chunks", choices=["chunks", "reduce"],
                        help="'chunks' (default): prepare chunk prompts; "
                             "'reduce': batch Claude-written summaries")
    parser.add_argument("--level",        type=int, default=1,
                        help="Reduce level (1 = first reduce pass). Only used with --mode reduce.")
    parser.add_argument("--summary-files", nargs="+", default=[],
                        help="Paths to Claude-written summary files. Only used with --mode reduce.")
    args = parser.parse_args()

    if args.mode == "chunks":
        _mode_chunks(args)
    else:
        _mode_reduce(args)


if __name__ == "__main__":
    main()
