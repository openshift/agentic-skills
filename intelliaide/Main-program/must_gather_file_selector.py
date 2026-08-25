"""
Must-Gather File Selector Module

Builds file-selection prompts from must-gather structure documentation.
All LLM reasoning is performed by the orchestrating agent (Lightspeed's Claude)
that reads the prompt file written here.  No HTTP calls or credentials needed.
"""

import os
import json
from typing import Dict, List, Optional
from pathlib import Path


def load_config_by_name(config_file_name: Optional[str] = None) -> Dict:
    """Resolve config file by name, load it, and return the full config dict."""
    if config_file_name is None:
        config_file_name = "config.json"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if os.path.isabs(config_file_name) and os.path.isfile(config_file_name):
        candidates.append(config_file_name)
    else:
        try:
            from app_paths import get_config_dir
            candidates.append(str(get_config_dir() / config_file_name))
        except ImportError:
            pass
        candidates.append(os.path.join(script_dir, config_file_name))
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8-sig").strip()
            if not text:
                continue
            return json.loads(text)
        except (json.JSONDecodeError, Exception):
            continue
    print(f"Warning: Could not load config from {config_file_name}.")
    return {}


def load_config(config_path: Optional[str] = None) -> Dict:
    """Load configuration. Delegates to load_config_by_name."""
    return load_config_by_name(config_path)


def _resolve_must_gather_docs_dir() -> str:
    """Resolve the must-gather docs directory from config.json, app_paths, or fallback."""
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_script_dir)

    try:
        from app_paths import get_config_path
        cfg_path = str(get_config_path())
    except ImportError:
        cfg_path = os.path.join(_project_root, "Config", "config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            configured = cfg.get("must_gather_docs_dir", "")
            if configured:
                if not os.path.isabs(configured):
                    configured = os.path.join(_project_root, configured)
                if os.path.isdir(configured):
                    return configured
        except Exception:
            pass

    try:
        from app_paths import get_must_gather_docs_dir as _get_docs_dir
        docs_dir = str(_get_docs_dir())
        if os.path.isdir(docs_dir):
            return docs_dir
    except ImportError:
        pass

    return os.path.join(_project_root, "DataSource")


MUST_GATHER_DOCS_DIR_DEFAULT = _resolve_must_gather_docs_dir()


def load_must_gather_documentation(must_gather_docs_dir: str) -> Dict[str, str]:
    """Load all must-gather structure documentation files."""
    docs = {}
    doc_files = [
        'MUST_GATHER_STRUCTURE.md',
        'MUST_GATHER_INDEX.md',
        'MUST_GATHER_ROUTING_GUIDE.md',
        'MUST_GATHER_DOCUMENTATION_README.md',
    ]
    docs_path = Path(must_gather_docs_dir)
    if not docs_path.exists():
        raise FileNotFoundError(f"Must-gather documentation directory not found: {must_gather_docs_dir}")
    for doc_file in doc_files:
        doc_path = docs_path / doc_file
        if doc_path.exists():
            try:
                with open(doc_path, 'r', encoding='utf-8') as f:
                    docs[doc_file] = f.read()
            except Exception as e:
                print(f"Warning: Could not read {doc_file}: {e}")
        else:
            print(f"Warning: Documentation file not found: {doc_file}")
    return docs


class MustGatherFileSelector:
    """Builds must-gather file-selection prompts (no LLM calls)."""

    def _create_file_selection_prompt(self, problem_statement: str, docs: Dict[str, str]) -> str:
        docs_context = ""
        for doc_name, doc_content in docs.items():
            docs_context += f"\n\n=== {doc_name} ===\n{doc_content}\n"
        return f"""You are an expert OpenShift/Kubernetes system analyst. Analyze the user's problem statement and suggest which files from a must-gather collection need to be analyzed.

MUST-GATHER DOCUMENTATION:
{docs_context}

USER PROBLEM STATEMENT:
{problem_statement}

TASK: Suggest specific file paths from the must-gather collection.

OUTPUT FORMAT — CRITICAL: Problem category line, then numbered list with [high]/[medium]/[low] priority tags.

Problem category: <category>
1. [high] path/to/file — reason
2. [medium] path/to/file — reason
3. [low] path/to/file — reason

Rules:
- First line must be exactly "Problem category: <category>"
- Each list line: number, period, space, [high] or [medium] or [low], space, path, then " — " and a short reason
- Always include both current.log and previous.log for pod logs
- Base suggestions on the must-gather structure documentation above
- Output NOTHING else. No JSON. No markdown."""



def prepare_file_selection_prompt(problem_statement: str, docs_dir: str, job_dir: str) -> Dict:
    """Pure-Python alternative to MustGatherFileSelector.suggest_files().

    Loads must-gather documentation, builds the file-selection prompt string that
    the LLM would normally receive, and writes it to <job_dir>/file_selection_prompt.md.
    Returns a manifest dict with the prompt path so the orchestrating agent (Claude)
    can read the file and perform file-selection reasoning inline — no HTTP/LLM call made here.

    Args:
        problem_statement: The user's problem description.
        docs_dir:          Path to the must-gather documentation directory.
        job_dir:           Path to the shared IntelliAide job directory.

    Returns:
        {"prompt_path": "<job_dir>/file_selection_prompt.md",
         "docs_dir":    docs_dir,
         "has_docs":    True/False}
    """
    try:
        docs = load_must_gather_documentation(docs_dir)
    except FileNotFoundError:
        docs = {}

    has_docs = bool(docs)

    if has_docs:
        selector = MustGatherFileSelector.__new__(MustGatherFileSelector)
        prompt = selector._create_file_selection_prompt(problem_statement.strip(), docs)
    else:
        # No docs available — fall back to a minimal prompt that asks Claude to
        # suggest standard must-gather paths for the problem.
        prompt = (
            "You are an expert OpenShift/Kubernetes system analyst.\n"
            "No must-gather structure documentation is available.\n\n"
            f"USER PROBLEM STATEMENT:\n{problem_statement.strip()}\n\n"
            "Suggest the most likely must-gather file paths for this problem using your knowledge "
            "of standard OpenShift must-gather layout.\n\n"
            "OUTPUT FORMAT:\nProblem category: <category>\n"
            "1. [high] path/to/file — reason\n"
            "2. [medium] path/to/file — reason\n"
            "3. [low] path/to/file — reason"
        )

    prompt_path = Path(job_dir) / "file_selection_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    return {
        "prompt_path": str(prompt_path),
        "docs_dir":    docs_dir,
        "has_docs":    has_docs,
    }


