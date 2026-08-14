"""
Application paths for normal run vs PyInstaller frozen exe.
Layout: DataSource/, Config/, Machine-learning/, Main-program/, Chatbot/, Results/
- When frozen: APPLICATION_DIR = folder containing the .exe.
- Config: config.json, json_config.json, agent_memory.json
- DataSource: keyfields_yaml_ml_input.docx, keyfields_json_ml_input.odt, MUST_GATHER_*.md
- Results: errors_aggregate.json, rca_summary.txt, ML output files

When running inside the agentic-operator skills image, this file lives at:
  /intelliaide/app_paths.py  →  container path /app/skills/intelliaide/app_paths.py

So Path(__file__).resolve().parent == /app/skills/intelliaide/
And Config/ == /app/skills/intelliaide/Config/   (read-only image mount)
    DataSource/ == /app/skills/intelliaide/DataSource/  (read-only image mount)
    Results/ is redirected to /tmp by the skill scripts at startup.
"""

import sys
from pathlib import Path

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)

def get_application_dir() -> Path:
    """Project root (or exe dir when frozen)."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def get_resource_dir() -> Path:
    """Read-only bundled resources. When frozen = sys._MEIPASS."""
    if _is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def get_config_dir() -> Path:
    """Config directory (config.json, agent_memory.json)."""
    return get_application_dir() / "Config"

def get_config_path() -> Path:
    """Config file: Config/config.json (or bundled)."""
    app = get_application_dir()
    cfg_dir = get_config_dir()
    res = get_resource_dir()
    for d in (cfg_dir, app, res, res / "Config"):
        p = d / "config.json"
        if p.exists():
            return p
    return cfg_dir / "config.json"

def get_data_source_dir() -> Path:
    """DataSource directory (keyfields, MUST_GATHER docs)."""
    return get_application_dir() / "DataSource"

def get_keyfields_path() -> Path:
    """Path to keyfields_yaml_ml_input.docx (DataSource or bundled)."""
    app_ds = get_data_source_dir() / "keyfields_yaml_ml_input.docx"
    if app_ds.exists():
        return app_ds
    res_ds = get_resource_dir() / "DataSource" / "keyfields_yaml_ml_input.docx"
    if res_ds.exists():
        return res_ds
    return get_resource_dir() / "keyfields_yaml_ml_input.docx"

def get_json_keyfields_path() -> Path:
    """Path to keyfields_json_ml_input.odt (DataSource or bundled)."""
    app_ds = get_data_source_dir() / "keyfields_json_ml_input.odt"
    if app_ds.exists():
        return app_ds
    res_ds = get_resource_dir() / "DataSource" / "keyfields_json_ml_input.odt"
    if res_ds.exists():
        return res_ds
    return get_resource_dir() / "keyfields_json_ml_input.odt"

def get_json_config_path() -> Path:
    """JSON processing config: Config/json_config.json (or bundled)."""
    cfg_dir = get_config_dir()
    res = get_resource_dir()
    for d in (cfg_dir, get_application_dir(), res, res / "Config"):
        p = d / "json_config.json"
        if p.exists():
            return p
    return cfg_dir / "json_config.json"

def get_memory_file_path() -> Path:
    """Agent memory file: Config/agent_memory.json."""
    return get_config_dir() / "agent_memory.json"

def get_must_gather_docs_dir() -> Path:
    """MUST_GATHER topology docs: DataSource (MUST_GATHER_*.md)."""
    return get_data_source_dir()

def get_results_dir() -> Path:
    """Results directory (errors_aggregate.json, rca_summary.txt, ML outputs).
    NOTE: skill scripts redirect this to /tmp at startup since the image is read-only."""
    d = get_application_dir() / "Results"
    d.mkdir(parents=True, exist_ok=True)
    return d

# Convenience
APPLICATION_DIR = get_application_dir()
RESOURCE_DIR = get_resource_dir()
