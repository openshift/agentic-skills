"""
RCA Agent — pure-Python data preparation helpers.

Provides chunking, prompt building, and manifest generation for the
IntelliAide RCA pipeline.  All LLM reasoning is performed by the
orchestrating agent (Lightspeed's Claude) that reads the files written
here.  No HTTP calls or external credentials are needed.
"""

import os
import re
import json
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path


def _remove_line_numbers_from_structure(structure: Any) -> Any:
    """Remove all line number metadata from a structure (dict/list)."""
    if isinstance(structure, dict):
        result = {}
        for key, value in structure.items():
            if key == "_line_numbers" or (isinstance(key, str) and key.endswith("_line_numbers")):
                continue
            result[key] = _remove_line_numbers_from_structure(value)
        return result
    if isinstance(structure, list):
        return [_remove_line_numbers_from_structure(item) for item in structure]
    return structure


try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


CHARS_PER_TOKEN: Dict[str, float] = {
    "claude":  3.5,
    "llama":   3.8,
    "gpt-4":   3.7,
    "gpt-3":   4.0,
    "mistral": 3.9,
}


def estimate_tokens(text: str, model_id: str = "") -> int:
    """Estimate token count using model-aware chars-per-token ratios."""
    if not text:
        return 0
    if TIKTOKEN_AVAILABLE:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            pass
    model_lower = (model_id or "").lower()
    cpt = next((v for k, v in CHARS_PER_TOKEN.items() if k in model_lower), 3.7)
    return max(1, int(len(text) / cpt))


SUMMARY_MAX_CHARS = 80000


def _get_folder_path(file_path: str) -> str:
    """Extracts the folder path from a file string to group logical components."""
    if not file_path:
        return "unknown"
    p = Path(file_path)
    return str(p.parent) if len(p.parts) > 1 else "root"


def _split_large_log_entry_tokens(entry: Dict[str, Any], max_tokens: int) -> List[Dict[str, Any]]:
    """Split an oversized log entry into sub-entries at line boundaries based on tokens."""
    content = entry.get("content", "")
    if estimate_tokens(content) <= max_tokens:
        return [entry]

    lines = content.split("\n")
    parts: List[str] = []
    current_lines: List[str] = []
    current_tokens = 0

    for line in lines:
        line_toks = estimate_tokens(line + "\n")
        if current_tokens + line_toks > max_tokens and current_lines:
            parts.append("\n".join(current_lines))
            current_lines = [line]
            current_tokens = line_toks
        else:
            current_lines.append(line)
            current_tokens += line_toks

    if current_lines:
        parts.append("\n".join(current_lines))

    file_name = entry.get("file", "unknown")
    total = len(parts)
    return [
        {**entry, "file": f"{file_name} (part {i+1}/{total})", "content": part}
        for i, part in enumerate(parts)
    ]


def load_config(config_path: str = "config.json") -> Dict:
    """Load configuration from JSON file.

    Only the ``max_chunk_tokens`` and ``model_id`` fields under the ``claude``
    key are used by the pure-Python helpers in this module (for token budget
    estimation).  No credentials or endpoint URLs are read here.
    """
    try:
        from app_paths import get_config_path
        path = get_config_path() if config_path == "config.json" else Path(config_path)
    except ImportError:
        path = Path(__file__).parent / config_path
    default: Dict = {"claude": {"max_chunk_tokens": 60000, "model_id": ""}}
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "claude" in cfg:
            default["claude"].update(cfg["claude"])
    except Exception:
        pass
    return default


# ISO timestamp patterns
_ISO_TS = re.compile(r"(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)")
_LOG_TIME = re.compile(r'time="(\d{4}-\d{2}-\d{2}(?:T|\s)\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)"', re.IGNORECASE)
_LOG_TIME_CRIO = re.compile(r'time="(\d{4}-\d{2}-\d{2})\s+\.(\d+)Z"', re.IGNORECASE)
_LOG_TIME_DATE = re.compile(r'time="(\d{4}-\d{2}-\d{2})[\s.]', re.IGNORECASE)


def _parse_iso_like(ts_str: str) -> Optional[str]:
    """Normalize to sortable ISO-like string. Returns None if unparseable."""
    if not ts_str or len(ts_str) < 19:
        return None
    normalized = ts_str.replace(" ", "T", 1).strip()
    if "T" in normalized:
        date_part, rest = normalized.split("T", 1)
        rest = re.sub(r"[^\d:]", "", rest[:8])
        if len(rest) >= 6:
            return f"{date_part}T{rest[:2]}:{rest[2:4]}:{rest[4:6]}"
    return normalized[:19] if len(normalized) >= 19 else None


def _extract_timestamps_from_value(value: Any, key_path: str, out: List[Tuple[str, str, str]]) -> None:
    """Recursively extract timestamp keys and ISO values from YAML-like structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            key_lower = k.lower() if isinstance(k, str) else ""
            path = f"{key_path}.{k}" if key_path else k
            if any(t in key_lower for t in ("timestamp", "time", "created", "updated", "transition", "eventtime", "observed")):
                if isinstance(v, str) and _ISO_TS.search(v):
                    sortable = _parse_iso_like(_ISO_TS.search(v).group(1))
                    if sortable:
                        out.append((sortable, path, v[:120]))
                else:
                    _extract_timestamps_from_value(v, path, out)
            else:
                _extract_timestamps_from_value(v, path, out)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _extract_timestamps_from_value(item, f"{key_path}[{i}]", out)
    elif isinstance(value, str) and key_path and _ISO_TS.search(value):
        sortable = _parse_iso_like(_ISO_TS.search(value).group(1))
        if sortable:
            out.append((sortable, key_path, value[:120]))


def build_chronology_from_payload(
    payload_yaml: Dict[str, List[Dict[str, Any]]],
    log_error_entries: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, str]]:
    """Build a time-ordered chronology from YAML timestamps and log line timestamps."""
    events: List[Tuple[str, str, str]] = []

    for file_name, objects in (payload_yaml or {}).items():
        for obj in objects:
            cf = obj if isinstance(obj, dict) else (obj.get("critical_fields") or obj)
            _extract_timestamps_from_value(cf, f"YAML:{file_name}", events)

    for entry in (log_error_entries or []):
        content = entry.get("content") or ""
        file_name = entry.get("file") or "log"
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _LOG_TIME.search(line)
            if m:
                raw = m.group(1)
                sortable = _parse_iso_like(raw.replace(" ", "T"))
                if sortable:
                    events.append((sortable, file_name, line[:150].replace("\n", " ")))
                continue
            m_crio = _LOG_TIME_CRIO.search(line)
            if m_crio:
                date_part = m_crio.group(1)
                frac = m_crio.group(2)[:9].ljust(9, "0")
                sortable = f"{date_part}T00:00:00.{frac}"
                events.append((sortable, file_name, line[:150].replace("\n", " ")))
                continue
            m2 = _LOG_TIME_DATE.search(line)
            if m2:
                sortable = _parse_iso_like(m2.group(1) + "T00:00:00")
                if sortable:
                    events.append((sortable, file_name, line[:150].replace("\n", " ")))
                continue
            iso = _ISO_TS.match(line)
            if iso:
                sortable = _parse_iso_like(iso.group(1))
                if sortable:
                    events.append((sortable, file_name, line[:150].replace("\n", " ")))

    seen = set()
    unique = []
    for sortable_ts, source, snippet in events:
        key = (sortable_ts, snippet[:80])
        if key in seen:
            continue
        seen.add(key)
        unique.append((sortable_ts, source, snippet))
    unique.sort(key=lambda x: x[0])

    return [{"timestamp": ts, "source": src, "snippet": snip} for ts, src, snip in unique]


def format_chronology_block(chronology: List[Dict[str, str]], max_events: int = 150) -> str:
    """Format chronology list as a clear text block for the prompt."""
    if not chronology:
        return ""
    if len(chronology) <= max_events:
        sampled = chronology
    else:
        half = max_events // 2
        sampled = chronology[:half] + chronology[-half:]
    lines = []
    for e in sampled:
        ts = e.get("timestamp", "")
        src = e.get("source", "")
        snip = (e.get("snippet") or "").replace("\n", " ").strip()[:120]
        lines.append(f"  {ts}  |  {src}  |  {snip}")
    return "\n".join(lines)


def prepare_payload_for_llm(ml_classification_result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Prepare data for LLM: normalize input format, remove line numbers, keep only YAML objects."""
    payload = {}
    for file_name, file_data in (ml_classification_result or {}).items():
        if isinstance(file_data, dict) and "objects" in file_data:
            objects = file_data["objects"]
        elif isinstance(file_data, list):
            objects = file_data
        else:
            continue

        yaml_objects = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            raw_critical_fields = obj.get("critical_fields", {})
            cleaned = _remove_line_numbers_from_structure(raw_critical_fields)
            if cleaned:
                yaml_objects.append(cleaned)
        if yaml_objects:
            payload[file_name] = yaml_objects
    return payload


def build_rca_prompt(payload_for_llm: Dict[str, Any], problem_statement: Optional[str] = None) -> str:
    """Build the full RCA user-content prompt string from the payload."""
    chronology = payload_for_llm.get("chronology") or []
    chronology_block = format_chronology_block(chronology)
    payload_for_data = {k: v for k, v in payload_for_llm.items() if k != "chronology"}
    data_str = json.dumps(payload_for_data, indent=2, default=str)
    user_problem = (problem_statement or "").strip() or "Not specified"

    if chronology_block:
        chronology_section = f"""
2. CHRONOLOGY OF EVENTS (include in your ## Chronology of Events section):
{chronology_block}

3. AGGREGATED DATA (YAML/LOG/JSON error objects with file metadata):
"""
    else:
        chronology_section = """
2. AGGREGATED DATA (YAML/LOG/JSON error objects with file metadata):
"""

    return f"""You are an expert OpenShift/Kubernetes system analyst performing root cause analysis.

TASK: Identify the root cause(s) and state clearly: "The key cause for the user's problem is: [...]"

SOURCES:

1. USER REPORTED ISSUE (primary focus):
{user_problem}
{chronology_section}
{data_str}

INSTRUCTIONS:
- Correlate the user's issue with YAML error patterns and/or log error content.
- Identify PRIMARY root cause(s) with evidence, SECONDARY contributing factors.
- Prioritize root causes by relevance to the USER REPORTED ISSUE.
- Base analysis on actual evidence only — do not fabricate.

OUTPUT FORMAT — use these EXACT ## headings (frontend parses them programmatically):

## User Reported Issue
## Executive Summary
## Chronology of Events
## Primary Root Cause(s)
## Secondary Causes / Contributing Factors
## Aggregated Error Patterns
(MUST be a pipe-delimited markdown table:
| Pattern | Source | Classification | Significance |
|---------|--------|----------------|--------------|
| ... | ... | ... | ... |)
## Recommendations
(MANDATORY — always include. Numbered, actionable remediation steps.
 This section MUST appear last in the report.)

Do NOT rename headings. Do NOT use plain text for Aggregated Error Patterns."""




def chunk_payload(
    yaml_errors: Dict[str, Any],
    log_entries: List[Dict[str, Any]],
    max_chunk_tokens: int = 80000
) -> List[Dict[str, Any]]:
    """Groups files logically by folder path, then builds chunks up to max_chunk_tokens."""
    all_items = []

    for fkey, objs in yaml_errors.items():
        all_items.append({"folder": _get_folder_path(fkey), "type": "yaml", "file": fkey, "payload": objs})

    for entry in log_entries:
        fkey = entry.get("file", "")
        all_items.append({"folder": _get_folder_path(fkey), "type": "log", "file": fkey, "payload": entry})

    grouped_items = {}
    for item in all_items:
        grouped_items.setdefault(item["folder"], []).append(item)

    chunks = []
    current_chunk = {"yaml_errors": {}, "log_entries": [], "_tokens": 0}

    def close_chunk():
        nonlocal current_chunk
        if current_chunk["yaml_errors"] or current_chunk["log_entries"]:
            clean_chunk = {"yaml_errors": current_chunk["yaml_errors"], "log_entries": current_chunk["log_entries"]}
            chunks.append(clean_chunk)
            current_chunk = {"yaml_errors": {}, "log_entries": [], "_tokens": 0}

    for folder, items in grouped_items.items():
        for item in items:
            item_str = json.dumps(item["payload"], indent=2, default=str)
            item_tokens = estimate_tokens(item_str)

            if item_tokens > max_chunk_tokens:
                if item["type"] == "log":
                    split_logs = _split_large_log_entry_tokens(item["payload"], max_chunk_tokens)
                    for sub_log in split_logs:
                        sub_toks = estimate_tokens(json.dumps(sub_log, indent=2, default=str))
                        if current_chunk["_tokens"] + sub_toks > max_chunk_tokens:
                            close_chunk()
                        current_chunk["log_entries"].append(sub_log)
                        current_chunk["_tokens"] += sub_toks
                elif item["type"] == "yaml":
                    if current_chunk["_tokens"] > 0:
                        close_chunk()
                    current_chunk["yaml_errors"][item["file"]] = item["payload"]
                    close_chunk()
                continue

            if current_chunk["_tokens"] + item_tokens > max_chunk_tokens:
                close_chunk()

            if item["type"] == "yaml":
                current_chunk["yaml_errors"][item["file"]] = item["payload"]
            else:
                current_chunk["log_entries"].append(item["payload"])
            current_chunk["_tokens"] += item_tokens

    close_chunk()
    print(f"[RCA Chunked] Produced {len(chunks)} contextual chunk(s) (Limit: {max_chunk_tokens:,} tokens)")
    return chunks




def prepare_rca_chunks(
    ml_classification_result: Dict[str, Any],
    job_dir: str,
    priority: str,
    log_error_entries: Optional[List[Dict[str, Any]]] = None,
    config_path: str = "config.json",
) -> Dict[str, Any]:
    """Pure-Python Map phase: chunk cluster data and write formatted prompt files to disk.

    Replicates all of run_rca_chunked()'s pure-Python work — token estimation,
    chunking, chronology extraction, prompt formatting — WITHOUT making any LLM
    call.  The resulting chunk files are ready for the orchestrating agent (Claude)
    to read and reason over inline.

    Args:
        ml_classification_result: Output of analyze_data.py (yaml_errors dict).
        job_dir:   Path to the shared IntelliAide job directory.
        priority:  "high" | "medium" | "low" — used in output file names.
        log_error_entries: List of log error dicts from analyze_data.py (may be None).
        config_path: Path to config.json (used to read max_chunk_tokens / model_id).

    Writes:
        <job_dir>/chunk_<priority>_<n>.md           — formatted RCA prompt per chunk
        <job_dir>/rca_chunks_<priority>_manifest.json

    Returns manifest dict:
        {
          "priority":    "high",
          "chunk_count": 3,
          "chunk_files": [
            {"path": "<job_dir>/chunk_high_1.md", "estimated_tokens": 58200},
            ...
          ],
          "manifest_path": "<job_dir>/rca_chunks_high_manifest.json"
        }
    """
    config = load_config(config_path)
    claude_config = config.get("claude", {})
    max_chunk_tokens = claude_config.get("max_chunk_tokens", 60000)

    payload_yaml = prepare_payload_for_llm(ml_classification_result)
    log_entries  = log_error_entries or []

    chunks = chunk_payload(
        yaml_errors=payload_yaml,
        log_entries=log_entries,
        max_chunk_tokens=max_chunk_tokens,
    )

    job_path   = Path(job_dir)
    chunk_files: List[Dict[str, Any]] = []

    for i, chunk_data in enumerate(chunks, start=1):
        chunk_yaml = chunk_data["yaml_errors"]
        chunk_logs = chunk_data["log_entries"]

        chunk_llm_payload: Dict[str, Any] = {"yaml_errors": chunk_yaml}
        if chunk_logs:
            chunk_llm_payload["log_errors"] = chunk_logs

        chronology = build_chronology_from_payload(
            chunk_yaml if isinstance(chunk_yaml, dict) else {}, chunk_logs,
        )
        if chronology:
            chunk_llm_payload["chronology"] = chronology

        prompt_str     = build_rca_prompt(chunk_llm_payload, problem_statement=None)
        estimated_toks = estimate_tokens(prompt_str)

        chunk_path = job_path / f"chunk_{priority}_{i}.md"
        chunk_path.write_text(prompt_str, encoding="utf-8")

        chunk_files.append({
            "path":             str(chunk_path),
            "estimated_tokens": estimated_toks,
        })

    manifest = {
        "priority":      priority,
        "chunk_count":   len(chunk_files),
        "chunk_files":   chunk_files,
    }
    manifest_path = job_path / f"rca_chunks_{priority}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    manifest["manifest_path"] = str(manifest_path)

    print(
        f"[prepare_rca_chunks] priority={priority}  chunks={len(chunk_files)}  "
        f"manifest={manifest_path}",
        file=__import__("sys").stderr,
    )
    return manifest


def prepare_reduce_batches(
    summary_files: List[str],
    job_dir: str,
    level: int,
    problem_statement: Optional[str] = None,
    config_path: str = "config.json",
) -> Dict[str, Any]:
    """Pure-Python Reduce phase: batch Claude-generated summary files by token budget.

    Replicates _hierarchical_reduce()'s token estimation and batching decisions
    WITHOUT making any LLM call.  The returned manifest tells the orchestrating
    agent (Claude) exactly which summary files belong in each batch and where to
    write its synthesis output, so Claude can execute just the reasoning step.

    Args:
        summary_files:     List of paths to Claude-written chunk summary files.
        job_dir:           Path to the shared IntelliAide job directory.
        level:             Reduce level (1 for first reduce, 2+ for recursive).
        problem_statement: Original problem text (used for overhead estimation).
        config_path:       Path to config.json (max_chunk_tokens, model_id).

    Writes:
        <job_dir>/reduce_level<level>_manifest.json

    Returns manifest dict:
        {
          "level":       1,
          "batch_count": 2,
          "is_final":    false,
          "batches": [
            {
              "batch_index":    0,
              "summary_files":  ["<job_dir>/chunk_summary_high_1.md", ...],
              "output_file":    "<job_dir>/reduce_level1_batch1.md"
            },
            ...
          ],
          "manifest_path": "<job_dir>/reduce_level1_manifest.json"
        }

    If is_final=True there is exactly one batch.  The orchestrating agent should
    write its synthesis to batches[0]["output_file"] and treat that as the final
    RCA text.  If is_final=False, the agent processes each batch, then calls
    prepare_reduce_batches() again at level+1 with the output_file paths.
    """
    import sys as _sys

    config = load_config(config_path)
    claude_config = config.get("claude", {})
    max_chunk_tokens = claude_config.get("max_chunk_tokens", 60000)
    model_id         = claude_config.get("model_id", "")

    overhead         = estimate_tokens(problem_statement or "", model_id) + 2000
    available_tokens = max_chunk_tokens - overhead

    summaries: List[Dict[str, Any]] = []
    for fp in summary_files:
        try:
            text = Path(fp).read_text(encoding="utf-8")
        except Exception as e:
            print(f"[prepare_reduce_batches] Warning: could not read {fp}: {e}", file=_sys.stderr)
            text = ""
        summaries.append({
            "file":   fp,
            "tokens": estimate_tokens(text, model_id),
        })

    batches: List[List[Dict[str, Any]]] = []
    current_batch: List[Dict[str, Any]] = []
    current_tokens = 0

    for s in summaries:
        if current_tokens + s["tokens"] > available_tokens and current_batch:
            batches.append(current_batch)
            current_batch  = [s]
            current_tokens = s["tokens"]
        else:
            current_batch.append(s)
            current_tokens += s["tokens"]

    if current_batch:
        batches.append(current_batch)

    job_path = Path(job_dir)
    manifest_batches = []
    for i, batch in enumerate(batches):
        manifest_batches.append({
            "batch_index":   i,
            "summary_files": [s["file"] for s in batch],
            "output_file":   str(job_path / f"reduce_level{level}_batch{i + 1}.md"),
        })

    manifest = {
        "level":       level,
        "batch_count": len(batches),
        "is_final":    len(batches) == 1,
        "batches":     manifest_batches,
    }
    manifest_path = job_path / f"reduce_level{level}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    manifest["manifest_path"] = str(manifest_path)

    print(
        f"[prepare_reduce_batches] level={level}  batches={len(batches)}  "
        f"is_final={manifest['is_final']}  manifest={manifest_path}",
        file=_sys.stderr,
    )
    return manifest


