#!/usr/bin/env python3
"""
select_files.py — Step 2 of IntelliAide pure-skills pipeline.

Prepares a file-selection prompt and writes it to disk so the orchestrating
agent (Claude) can perform the file-selection reasoning inline, with no hidden
LLM call in this script.

Usage:
    python /app/skills/intelliaide/select_files.py --job-dir /tmp/intelliaide/<job_id>

Reads:
    <job_dir>/state.json          (query + cluster_dir from extract_cluster.py)

Writes:
    <job_dir>/file_selection_prompt.md   (formatted prompt for the orchestrator)

Output (stdout JSON):
    {
      "prompt_path":  "<job_dir>/file_selection_prompt.md",
      "cluster_dir":  "<cluster extraction directory>",
      "docs_dir":     "<must-gather docs directory>",
      "has_docs":     true/false
    }

After this script exits, the orchestrating agent MUST:
  1. cat <prompt_path>
  2. Reason about which files are most relevant.
  3. Write <job_dir>/file_selection.json with the following schema:
     {
       "query":            "<original query>",
       "cluster_dir":      "<cluster_dir>",
       "problem_category": "<category string>",
       "high":   [{"original": "path", "resolved": "path", "found": true, "reason": "..."}],
       "medium": [...],
       "low":    [...]
     }
  The "resolved" field should equal "original" when the agent cannot verify
  existence on disk; the downstream analyze_data.py step handles missing files.
"""

import argparse
import json
import sys
from pathlib import Path

# All IntelliAide engine code lives alongside this script in the same folder.
# At runtime (in the sandbox container) this resolves to /app/skills/intelliaide/
_SKILL_DIR = Path(__file__).resolve().parent
for _p in (
    str(_SKILL_DIR / "vendor"),        # vendored packages
    str(_SKILL_DIR / "Main-program"),
    str(_SKILL_DIR / "python-client"),
    str(_SKILL_DIR),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from must_gather_file_selector import prepare_file_selection_prompt  # noqa: E402
from app_paths import get_must_gather_docs_dir                       # noqa: E402


def _log_pod(msg: str) -> None:
    """Write a progress line directly to the container log stream (PID 1 stdout)."""
    line = f"[intelliaide] {msg}\n"
    try:
        with open("/proc/1/fd/1", "a") as fh:
            fh.write(line)
    except Exception:
        sys.stderr.write(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, help="Path to the shared job directory")
    args = parser.parse_args()

    job_dir = Path(args.job_dir)
    state   = json.loads((job_dir / "state.json").read_text())
    query       = state["query"]
    cluster_dir = state["cluster_dir"]
    docs_dir    = str(get_must_gather_docs_dir())

    _log_pod(f"Step 2/4 — select_files (prepare prompt)  query={query[:60]!r}")
    print(f"[select_files] query={query[:80]!r}", file=sys.stderr)
    print(f"[select_files] docs_dir={docs_dir}", file=sys.stderr)
    print(f"[select_files] cluster_dir={cluster_dir}", file=sys.stderr)

    result = prepare_file_selection_prompt(
        problem_statement=query,
        docs_dir=docs_dir,
        job_dir=str(job_dir),
    )

    _log_pod(
        f"Step 2/4 — select_files prompt ready  "
        f"has_docs={result['has_docs']}  prompt={result['prompt_path']}"
    )
    print(f"[select_files] prompt written to {result['prompt_path']}", file=sys.stderr)

    print(json.dumps({
        "prompt_path": result["prompt_path"],
        "cluster_dir": cluster_dir,
        "docs_dir":    result["docs_dir"],
        "has_docs":    result["has_docs"],
    }))


if __name__ == "__main__":
    main()
