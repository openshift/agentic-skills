"""
Data Analyzer Sub-Agent

This module is called by orchestrator_agent.py to analyze must-gather files.
It extracts critical fields from YAML files and sends them to ML classifier.
"""

import os
import sys
import json
import yaml
import re
import glob
import importlib.util
from typing import Dict, List, Any, Optional
from pathlib import Path

# QUIET MODE: Check if orchestrator has enabled quiet mode
def _is_quiet():
    """Check if orchestrator has enabled quiet mode via environment variable"""
    return os.environ.get('ORCHESTRATOR_QUIET', '0') == '1'


def _import_ml_module(module_name: str, symbol: str):
    """
    Import a symbol from a Machine-learning module, handling both .py and .PY
    extensions (Linux is case-sensitive so .PY is invisible to normal import).
    """
    # 1. Try normal import first (works if .py exists on sys.path)
    try:
        mod = __import__(module_name, fromlist=[symbol])
        return getattr(mod, symbol)
    except (ImportError, AttributeError):
        pass

    # 2. Locate the .PY or .py file manually in Machine-learning/
    ml_dir = Path(__file__).resolve().parent.parent / "Machine-learning"
    for ext in (".py", ".PY"):
        candidate = ml_dir / f"{module_name}{ext}"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(module_name, str(candidate))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = mod
                spec.loader.exec_module(mod)
                return getattr(mod, symbol)

    raise ImportError(f"Cannot find {module_name}.py or {module_name}.PY in {ml_dir}")


try:
    classify_critical_fields = _import_ml_module("ML_YAML_CLASSIFICATION", "classify_critical_fields")
    ML_CLASSIFIER_AVAILABLE = True
except (ImportError, Exception) as e:
    ML_CLASSIFIER_AVAILABLE = False
    if not _is_quiet():
        print(f"[Data Analyzer] ML_YAML_CLASSIFICATION not available: {e}")

try:
    # analyze_logs is the public entry point (validates inputs, checks drain3, loads config)
    analyze_logs_ml = _import_ml_module("ML_LOG_CLASSIFICATION", "analyze_logs")
    ML_LOG_CLASSIFICATION_AVAILABLE = True
except (ImportError, Exception) as e:
    ML_LOG_CLASSIFICATION_AVAILABLE = False
    if not _is_quiet():
        print(f"[Data Analyzer] ML_LOG_CLASSIFICATION not available: {e}")

try:
    from odf.opendocument import load as load_odt
    from odf.table import Table, TableRow, TableCell
    from odf.text import P
    ODT_AVAILABLE = True
except ImportError:
    ODT_AVAILABLE = False

# Load from config, fallback to current directory
def _get_default_base_folder():
    config_path = Path(__file__).parent.parent / "Config" / "yaml_processing.yaml"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                if isinstance(config, dict):
                    configured_path = config.get('base_directory', {}).get('must_gather_path', '')
                    if configured_path:
                        return configured_path
        except Exception:
            pass
    return os.getcwd()

DEFAULT_BASE_FOLDER = _get_default_base_folder()

# Path to critical fields document (uses app_paths for frozen exe)
from app_paths import get_keyfields_path, get_application_dir
KEYFIELDS_ODT_PATH = get_keyfields_path()

# Load YAML processing configuration
def _load_yaml_processing_config():
    """Load YAML processing configuration from config/yaml_processing.yaml"""
    import yaml as yaml_loader
    config_path = Path(__file__).parent.parent / "Config" / "yaml_processing.yaml"
    default_config = {
        "chunking": {
            "max_items_section_indent": 2,
            "list_item_indent_offset": 2,
            "indent_tolerance": 2,
            "top_level_indent": 0,
            "list_container_keys": ["items"]
        },
        "critical_fields": {
            "default_paths": ["metadata.name", "status.conditions"],
            "file_specific": {},
            "pattern_matching": {}
        }
    }
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            loaded = yaml_loader.safe_load(f)
            if loaded:
                # Merge loaded config with defaults
                for key in loaded:
                    if key in default_config and isinstance(default_config[key], dict):
                        default_config[key].update(loaded[key])
                    else:
                        default_config[key] = loaded[key]
    except FileNotFoundError:
        if not _is_quiet():
            print(f"[DataAnalyzer] Config not found at {config_path}, using defaults")
    except Exception as e:
        if not _is_quiet():
            print(f"[DataAnalyzer] Error loading config: {e}, using defaults")
    return default_config

YAML_PROCESSING_CONFIG = _load_yaml_processing_config()

# Path-based fields for clusteroperators.yaml: use "metadata.name" to get the operator name
# (line 86, 247, etc.) without matching other "name" keys (ownerReferences.name, etc.).
# Include specific status fields - only extract what's explicitly mentioned.
# RECOMMENDED_PATHS_FOR_CLUSTEROPERATORS = ["metadata.name", "status.conditions"]

# # Path-based fields for clusterversions.yaml: version info and status
# RECOMMENDED_PATHS_FOR_CLUSTERVERSIONS = ["metadata.name", "status.history", "status.conditions"]


class DataAnalyzer:
    """
    Analyzes must-gather files (YAML, log, JSON). Called by the orchestrator.
    """

    def __init__(self, must_gather_base_dir: str = None):
        """
        Initialize Data Analyzer.

        Parameters:
        -----------
        must_gather_base_dir : str, optional
            Base directory of the must-gather (or quay) collection
        """
        self.must_gather_base_dir = must_gather_base_dir or ""
        # Memory for storing extracted metadata
        self.extracted_metadata = {}
        # Critical fields are loaded per-file from docx table (not at init)
        self.config = YAML_PROCESSING_CONFIG
        # Transient error from last chunking operation (set by _extract_yaml_object_chunks)
        self._last_chunk_error = None

    @staticmethod
    def _strip_must_gather_prefix(path: str) -> str:
        """Strip the leading wildcard / must-gather / quay prefix from a path.

        These prefixes represent the variable subfolder name in must-gather
        collections (quay-content, must-gather.local.xxx, random hash, etc.).
        """
        prefixes_to_strip = [
            "/quay*/",
            "/quay*",
            "/must-gather*/",
            "/must-gather*",
            "/must-gather/",
            "/must-gather",
            "/"
        ]
        for prefix in prefixes_to_strip:
            if path.lower().startswith(prefix.lower()):
                path = path[len(prefix):].lstrip("/\\")
                break
        return path

    @staticmethod
    def _is_path_under_base(resolved: str, base_folder: str) -> bool:
        """Verify that *resolved* is under *base_folder* (prevent path traversal)."""
        try:
            resolved_real = os.path.realpath(resolved)
            base_real = os.path.realpath(base_folder)
            return resolved_real.startswith(base_real + os.sep) or resolved_real == base_real
        except (ValueError, OSError):
            return False

    def _resolve_path(self, relative_path: str, base_folder: str) -> str:
        """
        Resolve orchestrator path (e.g. /quay*/namespaces/...) to full path under base_folder.
    
        The wildcard prefix (/quay*/, /must-gather/, etc.) represents the variable subfolder
        name in must-gather collections. This can be any name (quay-content, must-gather.local.xxx,
        random hash, etc.) - NOT hardcoded to any specific value.
    
        User should point base_folder to either:
        1. The actual subfolder containing cluster-scoped-resources/, namespaces/, etc.
        2. The parent folder - we'll search for */path pattern using glob

        NOTE: For paths containing wildcards (e.g. pods/*/logs/current.log)
        use :meth:`_resolve_path_glob` instead — it returns ALL matches.
        """
    
        import glob
    
        path = relative_path.strip()
        base_folder = base_folder.rstrip("/\\")

        # Fast path: already an absolute path under base — use directly, no stripping.
        if os.path.isabs(path) and self._is_path_under_base(path, base_folder):
            return os.path.normpath(path)

        path = self._strip_must_gather_prefix(path)
    
        if not path:
            return base_folder

        # Convert path separators for current OS
        path_normalized = path.replace("/", os.sep)
    
        # Try 1: Direct join with base_folder
        direct_path = os.path.normpath(os.path.join(base_folder, path_normalized))
        if os.path.exists(direct_path) and self._is_path_under_base(direct_path, base_folder):
            return direct_path
    
        # Try 2: Search with wildcard for first subfolder
        wildcard_pattern = os.path.join(base_folder, "*", path_normalized)
        for m in glob.glob(wildcard_pattern):
            if self._is_path_under_base(m, base_folder):
                return m
    
        # Try 3: Search with two levels of wildcards
        wildcard_pattern_2 = os.path.join(base_folder, "*", "*", path_normalized)
        for m in glob.glob(wildcard_pattern_2):
            if self._is_path_under_base(m, base_folder):
                return m
    
        # Return direct path as fallback (will fail — file treated as not found)
        return direct_path


    def _resolve_path_glob(self, relative_path: str, base_folder: str) -> List[str]:
        """
        Resolves paths containing wildcards by searching through nested folders.

        Handles must-gather's deep pod structure where the LLM suggests
        'pods/*/logs/current.log' but the real layout is
        'pods/<pod>/<container>/<container>/logs/current.log' (any depth).

        Strategy — try four patterns in order:
          1. Direct:       base/path/*/rest          (single-level * as written)
          2. Deep prefix:  base/**/path/*/rest        (allow prefix dirs, single-level *)
          3. Deep star:    base/path/**/rest          (replace every * with ** for any depth)
          4. Deep both:    base/**/path/**/rest       (combine prefix + deep star)
        """
        import re as _re

        path = relative_path.strip()
        base_folder = os.path.abspath(base_folder.rstrip("/\\"))

        # Fast path: already an absolute path under base — skip stripping.
        if not os.path.isabs(path) or not self._is_path_under_base(path, base_folder):
            path = self._strip_must_gather_prefix(path)
        if not path:
            return []

        path_normalized = path.replace("/", os.sep)

        # Build a "deep" version: replace every standalone * (not already **) with **
        # so  pods/*/logs/current.log  →  pods/**/logs/current.log
        # This matches pods/<any depth of dirs>/logs/current.log
        deep_path = _re.sub(r'(?<!\*)\*(?!\*)', '**', path_normalized)

        patterns = [
            os.path.join(base_folder, path_normalized),           # direct, single-level *
            os.path.join(base_folder, "**", path_normalized),     # deep prefix, single-level *
            os.path.join(base_folder, deep_path),                 # direct, multi-level **
            os.path.join(base_folder, "**", deep_path),           # deep prefix, multi-level **
        ]

        seen: set = set()
        result: List[str] = []

        for pattern in patterns:
            for m in glob.glob(pattern, recursive=True):
                normed = os.path.normpath(m)
                if (os.path.isfile(normed)
                        and normed not in seen
                        and self._is_path_under_base(normed, base_folder)):
                    seen.add(normed)
                    result.append(normed)

        return result

    # Regex matching typical OpenShift/Kubernetes node directory names in must-gather.
    # Covers: AWS (ip-10-0-xxx-xxx...), master-N, worker-N, infra-N, FQDNs, UUIDs.
    MUST_GATHER_NODE_NAME_RE = re.compile(
        r'^('
        r'ip-\d+-\d+-\d+-\d+[\w.-]*'          # AWS EC2 internal DNS
        r'|master[-.]?\d*[\w.-]*'               # master / master-0 / master-0.example.com
        r'|worker[-.]?\d*[\w.-]*'               # worker / worker-0 / worker-0.example.com
        r'|infra[-.]?\d*[\w.-]*'                # infra / infra-0
        r'|compute[-.]?\d*[\w.-]*'              # compute / compute-0
        r'|[\w]+-[\w]+-[\w]+-[\w]+-[\w]{12,}'   # UUID-like segments
        r'|[\w]+\.[\w]+\.[\w]+[\w.-]*'          # FQDN (at least 2 dots)
        r')$',
        re.IGNORECASE
    )

    @staticmethod
    def _normalize_placeholders(path: str) -> str:
        """Replace LLM template placeholders with appropriate glob patterns.

        ``<node-name>`` (and variations like ``<node_name>``, ``<nodename>``)
        are replaced with ``**`` so glob can match zero-or-more directory
        levels — this handles layouts where the node-name directory does not
        exist (e.g. ``host_service_logs/masters/kubelet_service.log`` has no
        per-node subdirectory).

        All other ``<placeholder>`` tokens are replaced with ``*`` (single
        directory level).
        """
        import re
        path = re.sub(r'<node[_-]?name>', '**', path, flags=re.IGNORECASE)
        return re.sub(r'<[^>]+>', '*', path)

    def _expand_node_name_placeholder(self, path: str, base_folder: str) -> list:
        """Expand ``<node-name>`` by scanning actual directories and matching
        against :pyattr:`MUST_GATHER_NODE_NAME_RE`.

        Returns a list of concrete paths (one per matching node directory).
        Falls back to glob ``**`` expansion if directory scanning yields nothing.
        """
        import re as _re
        placeholder_re = _re.compile(r'<node[_-]?name>', _re.IGNORECASE)
        m = placeholder_re.search(path)
        if not m:
            return []

        prefix_raw = path[:m.start()].rstrip("/\\")
        suffix_raw = path[m.end():].lstrip("/\\")
        prefix_stripped = self._strip_must_gather_prefix(prefix_raw)

        # Resolve the prefix directory on disk
        candidate_dirs = []
        if prefix_stripped:
            direct = os.path.normpath(os.path.join(base_folder, prefix_stripped.replace("/", os.sep)))
            if os.path.isdir(direct):
                candidate_dirs.append(direct)
            # Also try one level deeper (must-gather subfolder)
            for d in glob.glob(os.path.join(base_folder, "*", prefix_stripped.replace("/", os.sep))):
                if os.path.isdir(d):
                    candidate_dirs.append(d)

        expanded: list = []
        for parent_dir in candidate_dirs:
            try:
                entries = os.listdir(parent_dir)
            except OSError:
                continue
            for entry in entries:
                full_entry = os.path.join(parent_dir, entry)
                if not os.path.isdir(full_entry):
                    continue
                if self.MUST_GATHER_NODE_NAME_RE.match(entry):
                    if suffix_raw:
                        target = os.path.normpath(os.path.join(full_entry, suffix_raw.replace("/", os.sep)))
                        if os.path.exists(target):
                            expanded.append(target)
                    else:
                        expanded.append(full_entry)

        # If regex-based scan found nothing, try without the node-name segment
        # (the directory level may simply not exist in this must-gather layout)
        if not expanded and suffix_raw:
            for parent_dir in candidate_dirs:
                target = os.path.normpath(os.path.join(parent_dir, suffix_raw.replace("/", os.sep)))
                if os.path.exists(target):
                    expanded.append(target)

        return expanded

    @staticmethod
    def _path_has_wildcard(path: str) -> bool:
        """Return True if the path contains glob wildcard characters or LLM placeholders."""
        return '*' in path or '?' in path or '<' in path

    def _check_file_access(self, file_paths: List[str], base_folder: str) -> Dict:
        """
        Check if each file sent by the orchestrator is accessible under base_folder.

        Paths that contain wildcard characters (``*``, ``?``) are expanded via
        :func:`glob.glob` so that ``namespaces/openshift-etcd/pods/*/logs/current.log``
        resolves to *all* matching pod log files.  Each match is added as a
        separate accessible entry (with the original wildcard path preserved so
        the caller can trace where it came from).

        Returns dict with accessible, not_found, and errors lists.
        """
        base_folder = base_folder or DEFAULT_BASE_FOLDER
        accessible = []
        not_found = []
        errors = []

        for raw_path in file_paths:
            # Fast path: if this is already a fully-resolved absolute path that
            # exists on disk (e.g. returned by a prior report_files_availability
            # call and stored in agent_state), use it directly — no re-resolution.
            if os.path.isabs(raw_path) and os.path.exists(raw_path) and self._is_path_under_base(raw_path, base_folder):
                if os.path.isfile(raw_path):
                    accessible.append({"original": raw_path, "resolved": raw_path})
                else:
                    accessible.append({"original": raw_path, "resolved": raw_path, "note": "path is a directory"})
                continue

            # Try regex-based node-name expansion first (before generic placeholder normalization)
            node_expanded = self._expand_node_name_placeholder(raw_path, base_folder) if '<' in raw_path else []
            if node_expanded:
                for resolved in node_expanded:
                    accessible.append({"original": raw_path, "resolved": resolved, "note": "node-name expansion"})
                if not _is_quiet():
                    print(f"  [Node] {raw_path} -> {len(node_expanded)} file(s) found via node-name regex")
                continue

            path = self._normalize_placeholders(raw_path)
            try:
                if self._path_has_wildcard(self._strip_must_gather_prefix(path)):
                    # ── Wildcard path: expand to all matching files ──
                    matches = self._resolve_path_glob(path, base_folder)
                    if matches:
                        for resolved in matches:
                            accessible.append({
                                "original": path,
                                "resolved": resolved,
                                "note": "glob expansion",
                            })
                        if not _is_quiet():
                            print(f"  [Glob] {path} -> {len(matches)} file(s) found")
                    else:
                        not_found.append({"original": path, "resolved": path})
                else:
                    # ── Concrete path (no wildcards) ──
                    full_path = self._resolve_path(path, base_folder)
                    if os.path.exists(full_path):
                        if os.path.isfile(full_path):
                            with open(full_path, "rb") as f:
                                f.read(1)
                            accessible.append({"original": path, "resolved": full_path})
                        else:
                            accessible.append({"original": path, "resolved": full_path, "note": "path is a directory"})
                    else:
                        not_found.append({"original": path, "resolved": full_path})
            except Exception as e:
                errors.append({"original": path, "resolved": path, "error": str(e)})

        return {"accessible": accessible, "not_found": not_found, "errors": errors}

    def _load_critical_fields(self, file_path: str) -> List[str]:
        """
        Load critical field paths from config, with fallback to docx table.
        
        Priority:
        1. ODT/docx table (primary source of truth)
        2. File-specific config (fallback)
        3. Default paths from config
        """
        file_name = os.path.basename(file_path).lower()
        cf_config = self.config.get("critical_fields", {})
        
        # 1. Try ODT/docx table FIRST (primary source)
        docx_fields = self._load_critical_fields_from_docx(file_path)
        if docx_fields:
            if not _is_quiet():
                print(f"[DataAnalyzer] Using document critical fields for {file_name}: {docx_fields}")
            return docx_fields
    
        # 2. Fallback to file-specific config
        file_specific = cf_config.get("file_specific", {})
        if file_name in file_specific:
            paths = file_specific[file_name].get("paths", [])
            if paths:
                if not _is_quiet():
                    print(f"[DataAnalyzer] Using config critical fields for {file_name}: {paths}")
            return paths.copy()
    
        # 3. Fallback to default paths
        default_paths = cf_config.get("default_paths", [])
        if default_paths:
            if not _is_quiet():
                print(f"[DataAnalyzer] Using default critical fields for {file_name}: {default_paths}")
            return default_paths.copy()
    
        return []

    def _load_critical_fields_from_docx(self, file_path: str) -> List[str]:
        """
        Read critical field names from keyfields_yaml_ml_input.odt table.
        (Original _load_critical_fields logic moved here)

        Returns:
            List of field path strings, or [] if not available / no match.
        """
        if not ODT_AVAILABLE:
            if not _is_quiet():
                print("[DataAnalyzer] ODT library not installed — keyfields document not applied")
            return []
        
        if not KEYFIELDS_ODT_PATH.exists():
            if not _is_quiet():
                print(f"[DataAnalyzer] Keyfields document not found at {KEYFIELDS_ODT_PATH}")
            return []
        
        def get_cell_text(cell) -> str:
            """Extract text content from an ODT table cell."""
            text_parts = []
            for p in cell.getElementsByType(P):
                for node in p.childNodes:
                    if hasattr(node, 'data'):
                        text_parts.append(node.data)
            return ''.join(text_parts).strip()

        try:
            doc = load_odt(str(KEYFIELDS_ODT_PATH))
            
            file_path_normalized = file_path.strip().lower()
            if file_path_normalized.startswith("/quay*/"):
                file_path_normalized = file_path_normalized[7:]
            elif file_path_normalized.startswith("/quay*"):
                file_path_normalized = file_path_normalized[6:]
            file_path_normalized = file_path_normalized.lstrip("/\\")
            
            file_name = os.path.basename(file_path_normalized).lower()
            
            fields = []
            matched_cells = None
            
            for table in doc.getElementsByType(Table):
                for row in table.getElementsByType(TableRow):
                    cells = row.getElementsByType(TableCell)
                    if len(cells) < 2:
                        continue
                    
                    first_cell = get_cell_text(cells[0])
                    first_cell_normalized = first_cell.lower().replace('\\','/')
                    
                    if not first_cell_normalized:
                        continue

                    if first_cell_normalized.startswith("/quay*/"):
                        first_cell_normalized = first_cell_normalized[7:]
                    elif first_cell_normalized.startswith("/quay*"):
                        first_cell_normalized = first_cell_normalized[6:]
                    first_cell_normalized = first_cell_normalized.lstrip("/\\")
                    
                    if (file_path_normalized == first_cell_normalized or
                        file_path_normalized in first_cell_normalized or
                        first_cell_normalized in file_path_normalized or
                        file_name == os.path.basename(first_cell_normalized).lower() or
                        file_name in first_cell_normalized):
                        matched_cells = cells
                        break
                
                if matched_cells:
                    break
            
            if not matched_cells:
                return []  # No match in docx, let caller use defaults
            
            for cell in matched_cells[1:]:
                cell_text = get_cell_text(cell)
                if not cell_text:
                    continue
                
                lines = cell_text.replace(',', '\n').replace('•', '\n').split('\n')
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    line = line.lstrip('•-* \t')
                    
                    if ('.' in line or '[' in line or 
                        line.startswith('metadata.') or 
                        line.startswith('status.') or 
                        line.startswith('spec.') or
                        line.startswith('data.') or
                        any(keyword in line.lower() for keyword in ['name', 'status', 'type', 'message', 'reason', 'condition'])):
                        if line not in fields:
                            fields.append(line)
            
            fields = [f.strip() for f in fields if f and f.strip()]
            return fields
            
        except Exception as e:
            if not _is_quiet():
                print(f"[DataAnalyzer] Failed to read keyfields document: {e}")
            return []

    def _find_key_in_yaml_lines(self, lines: List[str], key_name: str) -> List[int]:
        """
        Find all line numbers where a key appears in YAML lines.
        Returns list of line numbers where the key is found.
        """
        line_numbers = []
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if ':' in stripped:
                key = stripped.split(':')[0].strip()
                # Check if key matches (case-insensitive, or as part of path)
                if key.lower() == key_name.lower() or key_name.lower() in key.lower():
                    line_numbers.append(line_num)
        return line_numbers

    def _extract_yaml_object_chunks(self, yaml_file_path: str) -> List[tuple]:
        """
        Step 2: Extract YAML objects as chunks using the proven extraction logic.
        Each list item (starting with '-') at the items level is treated as a single chunk.
        
        Returns:
        --------
        List of (chunk_string, start_line, end_line, key_value_pairs) tuples
        where key_value_pairs is List[Tuple[str, str, int]] = (path, value, line_number)
        and path is the YAML path (e.g. "metadata.name") so "metadata.name" can be matched
        without matching other "name" keys (e.g. metadata.ownerReferences.name).
        """
        import re
        
        try:
            with open(yaml_file_path, 'r', encoding='utf-8') as f:
                yaml_content = f.read()
            
            lines = yaml_content.split('\n')
            chunks = []
            current_chunk = []
            current_chunk_start = None
            current_chunk_lines = []
            list_item_indent = None  # Track the indent level of list items (e.g., under 'items:')
            indent_stack = []  # [(indent, key), ...] for building YAML path (e.g. metadata.name)
            
            for line_num, line in enumerate(lines, start=1):
                stripped = line.strip()
                
                # Skip empty lines
                if not stripped:
                    if current_chunk_start is not None:
                        current_chunk_lines.append(line)
                    continue
                
                if stripped.startswith('#'):
                    if current_chunk_start is not None:
                        current_chunk_lines.append(line)
                    continue
                
                if stripped.startswith('---'):
                    # Document separator - end current chunk if any
                    if current_chunk_start is not None:
                        chunks.append((
                            '\n'.join(current_chunk_lines),
                            current_chunk_start,
                            line_num - 1,
                            current_chunk
                        ))
                        current_chunk = []
                        current_chunk_lines = []
                        current_chunk_start = None
                        list_item_indent = None
                    continue
                
                # Calculate indentation
                indent = len(line) - len(stripped)

                # Start a chunk if we haven't started one yet (for files without --- at the start)
                if current_chunk_start is None:
                    current_chunk_start = line_num
                    current_chunk_lines = []  # Don't add line here, it will be added below
                    current_chunk = []
                    indent_stack = []
                
                # Check if this is a list item under 'items:' (typically starts with '- ' at indent 0 or 2)
                is_list_item = stripped.startswith('-')
                
                # Detect if we're in the 'items:' section (only at low indent - Kubernetes list items)
                # High-indent 'items:' (like in CRD schemas) should be ignored
                # if indent <= 2 and ('items:' in stripped.lower() or (stripped.endswith(':') and 'items' in stripped.lower())):
                chunking_cfg = self.config.get("chunking", {})
                max_indent = chunking_cfg.get("max_items_section_indent", 2)
                container_keys = chunking_cfg.get("list_container_keys", ["items"])

                if indent <= max_indent and any(k + ':' in stripped.lower() or (stripped.endswith(':') and k in stripped.lower()) for k in container_keys):
                    # This is the items: line, next list items will be chunks
                    # list_item_indent = indent + 2  # List items are typically indented 2 spaces after 'items:'
                    indent_offset = chunking_cfg.get("list_item_indent_offset", 2)
                    list_item_indent = indent + indent_offset
                    continue
                
                # Check if this is a new list item (new chunk)
                if is_list_item:
                    # Check if this is at the list item indent level (or close to it)
                    # if list_item_indent is not None and abs(indent - list_item_indent) <= 2:
                    tolerance = chunking_cfg.get("indent_tolerance", 2)
                    if list_item_indent is not None and abs(indent - list_item_indent) <= tolerance:
                        # This is a new list item - start a new chunk
                        if current_chunk_start is not None:
                            # Save previous chunk
                            chunks.append((
                                '\n'.join(current_chunk_lines),
                                current_chunk_start,
                                line_num - 1,
                                current_chunk
                            ))
                            indent_stack = []
                        
                        # Start new chunk
                        current_chunk = []
                        current_chunk_lines = [line]
                        current_chunk_start = line_num
                        list_item_indent = indent  # Update to current list item indent
                        indent_stack = []  # Reset path stack for new object
                    else:
                        # This is a nested list item - continue current chunk
                        if current_chunk_start is not None:
                            current_chunk_lines.append(line)
                else:
                    # Regular line - add to current chunk if we have one
                    if current_chunk_start is not None:
                        # Check if we've gone back to a higher level (end of current object)
                        if list_item_indent is not None and indent <= list_item_indent and not is_list_item:
                            # Check if this is a top-level key that signals end of items section
                            # Keys like 'kind:', 'metadata:', 'apiVersion:' at indent 0 after items
                            # indicate the list wrapper metadata, not part of the item
                            # is_top_level_key = indent == 0 and ':' in stripped and not stripped.startswith('-')
                            top_level_indent = chunking_cfg.get("top_level_indent", 0)
                            is_top_level_key = indent == top_level_indent and ':' in stripped and not stripped.startswith('-')
                            if is_top_level_key:
                                # End of chunk - this is list wrapper metadata
                                chunks.append((
                                    '\n'.join(current_chunk_lines),
                                    current_chunk_start,
                                    line_num - 1,
                                    current_chunk
                                ))
                                current_chunk = []
                                current_chunk_lines = []
                                current_chunk_start = None
                                list_item_indent = None
                                indent_stack = []
                            else:
                                # Continue adding to chunk
                                current_chunk_lines.append(line)
                        else:
                            current_chunk_lines.append(line)
                
                # Extract key-value pair if present (for current chunk); track YAML path
                if current_chunk_start is not None:
                    match = re.match(r'^(\s*)([^:]+?):\s*(.*)$', line)
                    if match:
                        key = match.group(2).strip()
                        value = match.group(3).strip()
                        if not key:
                            continue
                        # Pop stack until we're at a parent of this indent
                        while indent_stack and indent_stack[-1][0] >= indent:
                            indent_stack.pop()
                        if value:
                            # Leaf key: value on same line — build path and store (path, value, line_num)
                            path = ".".join(k for _, k in indent_stack) + "." + key if indent_stack else key
                            value = value.strip('"\'')
                            current_chunk.append((path, value, line_num))
                        else:
                            # Parent key (e.g. "metadata:" or "annotations:") — push for path context
                            indent_stack.append((indent, key))
            
            # Add final chunk if exists
            if current_chunk_start is not None:
                chunks.append((
                    '\n'.join(current_chunk_lines),
                    current_chunk_start,
                    len(lines),
                    current_chunk
                ))
            
            return chunks
        except Exception as e:
            if not _is_quiet():
                print(f"[DataAnalyzer] YAML parse error in {yaml_file_path}: {e}")
            self._last_chunk_error = str(e)
            return []

    def _get_line_numbers_for_key(self, lines: List[str], key: str, value: Any = None) -> List[int]:
        """
        Find line numbers where a key appears in YAML lines.
        """
        line_numbers = []
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if ':' in stripped:
                line_key = stripped.split(':')[0].strip()
                # Remove quotes if present
                line_key = line_key.strip('"\'')
                if line_key == key:
                    line_numbers.append(line_num)
        return line_numbers

    def _get_nested_value(self, data: Any, path: str) -> Any:
        """
        Navigate through nested dict/list structure using a path like "metadata.name" or "status.conditions[].type".
        Returns the value at that path, or None if not found.
        """
        if not path or not data:
            return None
        
        parts = path.split('.')
        current = data
        
        for part in parts:
            if '[]' in part:
                # Handle array notation like "conditions[]" - means all items in array
                key = part.replace('[]', '')
                if isinstance(current, dict) and key in current:
                    current = current[key]
                    if isinstance(current, list):
                        # Return the list itself for array paths
                        return current
                    else:
                        return None
                else:
                    return None
            elif '[' in part and ']' in part:
                # Handle indexed access like "conditions[0]"
                key, index_str = part.split('[', 1)
                index_str = index_str.rstrip(']')
                if isinstance(current, dict) and key in current:
                    current = current[key]
                    if isinstance(current, list):
                        try:
                            index = int(index_str)
                            if 0 <= index < len(current):
                                current = current[index]
                            else:
                                return None
                        except ValueError:
                            return None
                    else:
                        return None
                else:
                    return None
            else:
                # Regular key access
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
        
        return current
    
    def _extract_nested_structure(self, data: Any, path: str, path_parts: List[str] = None) -> Dict[str, Any]:
        """
        Extract a nested structure from data following the path, preserving hierarchy.
        For paths like "status.conditions[].type", extracts the full "status.conditions" array.
        Returns a nested dict structure that contains the value at the path.
        """
        if path_parts is None:
            path_parts = path.split('.') if path else []
        
        if not path_parts:
            return data if isinstance(data, dict) else {}
        
        part = path_parts[0]
        remaining = path_parts[1:]
        
        if '[]' in part:
            # Array notation - extract the full array structure
            key = part.replace('[]', '')
            if isinstance(data, dict) and key in data:
                value = data[key]
                if isinstance(value, list):
                    # If there are remaining parts (e.g., "conditions[].type"), 
                    # we still extract the full array but could filter later
                    # For now, extract the full array to preserve structure
                    return {key: value}
                else:
                    return {key: value}
            else:
                return None
        else:
            # Regular key
            if isinstance(data, dict) and part in data:
                value = data[part]
                if remaining:
                    # Continue deeper
                    extracted = self._extract_nested_structure(value, None, remaining)
                    if extracted is not None:
                        return {part: extracted}
                    else:
                        # If deeper extraction failed, return what we have
                        return {part: value}
                else:
                    # This is the target - return the structure containing this key
                    return {part: value}
            else:
                return None
    
    def _merge_dicts(self, dict1: Dict, dict2: Dict) -> Dict:
        """
        Deep merge two dictionaries, combining nested structures.
        """
        result = dict1.copy()
        for key, value in dict2.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = self._merge_dicts(result[key], value)
                elif isinstance(result[key], list) and isinstance(value, list):
                    # For lists, we might need to merge or append - for now, prefer dict2
                    result[key] = value
                else:
                    # Prefer dict2 value
                    result[key] = value
            else:
                result[key] = value
        return result
    
    def _group_line_numbers_into_ranges(self, line_numbers: List[int]) -> List[List[int]]:
        """
        Group consecutive line numbers into ranges.
        Returns a list of [start, end] pairs for consecutive ranges.
        
        Example:
        [4, 5, 8, 9, 10, 11, 12, 14, 15] -> [[4, 5], [8, 12], [14, 15]]
        """
        if not line_numbers:
            return []
        
        sorted_lines = sorted(set(line_numbers))
        ranges = []
        start = sorted_lines[0]
        end = sorted_lines[0]
        
        for i in range(1, len(sorted_lines)):
            if sorted_lines[i] == end + 1:
                # Consecutive - extend current range
                end = sorted_lines[i]
            else:
                # Gap found - save current range and start new one
                ranges.append([start, end])
                start = sorted_lines[i]
                end = sorted_lines[i]
        
        # Add the last range
        ranges.append([start, end])
        
        return ranges
    
    def _add_line_numbers_to_structure(self, structure: Dict, key_value_pairs: List[tuple], path_prefix: str = "") -> Dict:
        """
        Add line number metadata to the structure by matching paths from key_value_pairs.
        Returns structure with line number ranges added at appropriate levels.
        Line numbers are grouped into ranges for compact representation.
        """
        # Create a mapping of paths to line numbers
        path_to_lines = {}
        for path, value, line_num in key_value_pairs:
            if path not in path_to_lines:
                path_to_lines[path] = []
            path_to_lines[path].append(line_num)
        
        # Find the overall line range for the structure
        all_lines = []
        for path, value, line_num in key_value_pairs:
            all_lines.append(line_num)
        
        if all_lines:
            sorted_all_lines = sorted(set(all_lines))
            ranges = self._group_line_numbers_into_ranges(sorted_all_lines)
            structure["_line_numbers"] = {
                "min": min(sorted_all_lines),
                "max": max(sorted_all_lines),
                "ranges": ranges
            }
        
        # Recursively add line numbers for nested keys
        def add_lines(obj, current_path=""):
            if isinstance(obj, dict):
                result = {}
                for key, value in obj.items():
                    if key == "_line_numbers":
                        result[key] = value
                        continue
                    
                    full_path = f"{current_path}.{key}" if current_path else key
                    if isinstance(value, (dict, list)):
                        nested = add_lines(value, full_path)
                        result[key] = nested
                    else:
                        result[key] = value
                    
                    # Add line number if we have it for this specific path
                    if full_path in path_to_lines:
                        lines = sorted(set(path_to_lines[full_path]))
                        ranges = self._group_line_numbers_into_ranges(lines)
                        result[f"{key}_line_numbers"] = {
                            "min": min(lines),
                            "max": max(lines),
                            "ranges": ranges
                        }
                return result
            elif isinstance(obj, list):
                return [add_lines(item, current_path) for item in obj]
            else:
                return obj
        
        return add_lines(structure)
    
    def _extract_critical_fields_from_chunk(self, chunk_string: str, key_value_pairs: List[tuple], critical_fields: List[str]) -> Dict[str, Any]:
        """
        Extract critical fields from a YAML chunk, preserving the original nested structure.
        
        Parameters:
        -----------
        chunk_string : str
            The YAML chunk as a string
        key_value_pairs : List[Tuple[str, str, int]]
            List of (path, value, line_number) for line number tracking
        critical_fields : List[str]
            List of critical field paths to extract (e.g., ["metadata.name", "status.conditions[].type"])
            For paths like "status.conditions[].type", extracts the full "status.conditions" array.
        
        Returns:
        --------
        Dict: Nested JSON structure preserving YAML hierarchy, with line number metadata
        """
        try:
            # Parse the chunk as YAML to get the full structure
            # The chunk might start with '-' (list item) or be a direct dict
            yaml_data = yaml.safe_load(chunk_string)
            if yaml_data is None:
                return {}
            
            # Handle case where chunk is a list item (starts with -)
            # If it's a list, take the first item (the actual object)
            if isinstance(yaml_data, list):
                if len(yaml_data) > 0:
                    yaml_data = yaml_data[0]
                else:
                    return {}
            
            if not isinstance(yaml_data, dict):
                return {}
            
            # Extract structures for each critical field and merge them
            merged_structure = {}
            
            for critical_field in critical_fields:
                field = critical_field.strip()
                if not field:
                    continue

                # Strip items[]. prefix - chunks are already individual items
                if field.startswith('items[].'):
                    field = field[8:]  # Remove 'items[].'
                
                # Extract ONLY the specific path mentioned in critical fields
                # For "status.conditions[].type", extract only "status.conditions" (not entire "status")
                # For "status", extract only "status"
                if '[]' in field:
                    # Extract up to and including the array (e.g., "status.conditions")
                    parts = field.split('.')
                    array_part_idx = None
                    for i, part in enumerate(parts):
                        if '[]' in part:
                            array_part_idx = i
                            break
                    
                    if array_part_idx is not None:
                        # Extract only up to the array level, not the parent
                        path_up_to_array = '.'.join(parts[:array_part_idx + 1])
                        extracted = self._extract_nested_structure(yaml_data, path_up_to_array)
                    else:
                        extracted = self._extract_nested_structure(yaml_data, field)
                else:
                    # Regular path - extract only this specific path
                    extracted = self._extract_nested_structure(yaml_data, field)
                
                if extracted is not None:
                    merged_structure = self._merge_dicts(merged_structure, extracted)
            
            # If no structure was extracted, return empty
            if not merged_structure:
                return {}
            
            # Add line number metadata
            structure_with_lines = self._add_line_numbers_to_structure(merged_structure, key_value_pairs)
            
            return structure_with_lines
        except Exception as e:
            return {}

    def _remove_line_numbers_from_structure(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove all line number metadata from the structure, keeping only the actual field values.
        
        Args:
            structure: Dictionary containing critical fields with line number metadata
        
        Returns:
            Dictionary with line numbers removed
        """
        if not isinstance(structure, dict):
            return structure
        
        result = {}
        for key, value in structure.items():
            # Skip line number fields
            if key == "_line_numbers" or key.endswith("_line_numbers"):
                continue
            
            if isinstance(value, dict):
                result[key] = self._remove_line_numbers_from_structure(value)
            elif isinstance(value, list):
                result[key] = [self._remove_line_numbers_from_structure(item) if isinstance(item, dict) else item for item in value]
            else:
                result[key] = value
        
        return result
    
    def _remove_timestamps_from_structure(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove all timestamp fields from the structure before passing to ML classifier.
        Only verbose error patterns are needed, not timestamps.
        
        Args:
            structure: Dictionary containing critical fields
        
        Returns:
            Dictionary with timestamp fields removed
        """
        if not isinstance(structure, dict):
            return structure
        
        # Exact timestamp field names (case-insensitive exact match, not substring)
        timestamp_keys_exact = {
            'lasttransitiontime', 'lasttransition', 'transitiontime',
            'timestamp', 'time', 'created', 'updated', 'creationtimestamp',
            'starttime', 'endtime', 'firsttimestamp', 'lasttimestamp',
            'eventtime', 'observedat', 'observedtime',
        }
        
        # Pattern to match ISO timestamp strings (e.g., "2026-01-12T14:08:28Z")
        iso_timestamp_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
        
        result = {}
        for key, value in structure.items():
            # Skip timestamp fields by exact key name match (not substring)
            if key.lower() in timestamp_keys_exact:
                continue
            
            if isinstance(value, dict):
                result[key] = self._remove_timestamps_from_structure(value)
            elif isinstance(value, list):
                filtered_list = []
                for item in value:
                    if isinstance(item, dict):
                        filtered_item = self._remove_timestamps_from_structure(item)
                        # Only add if the item has non-timestamp content
                        if filtered_item:
                            filtered_list.append(filtered_item)
                    else:
                        # Check if the value itself is a timestamp string
                        if isinstance(item, str) and iso_timestamp_pattern.match(item):
                            continue  # Skip timestamp values
                        filtered_list.append(item)
                if filtered_list:  # Only add list if it has content after filtering
                    result[key] = filtered_list
            else:
                # Check if the value itself is a timestamp string
                if isinstance(value, str) and iso_timestamp_pattern.match(value):
                    continue  # Skip timestamp values
                result[key] = value
        
        return result
    
    def _remove_alphanumeric_patterns_from_messages(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove alphanumeric patterns (version strings, commit hashes, etc.) from message fields
        before sending to ML classifier. Only verbose error patterns are needed.
        
        Args:
            structure: Dictionary containing critical fields
        
        Returns:
            Dictionary with alphanumeric patterns removed from message fields
        """
        if not isinstance(structure, dict):
            return structure
        
        # Patterns to match and remove:
        # - Version strings: "0.0.0-7d2dd62c2a73b66aa99e82c90f64ab53dd523ddf"
        # - Commit hashes: long hex strings (40+ chars)
        # - Version numbers: "v1.2.3", "1.2.3-abc123"
        # - UUIDs: already handled, but keep pattern for completeness
        
        # Pattern for version strings with commit hashes: "0.0.0-<long-hex>"
        version_commit_pattern = re.compile(r'\d+\.\d+\.\d+[-\w]*[a-f0-9]{20,}', re.IGNORECASE)
        # Pattern for long hex strings (commit hashes, etc.) — 20+ hex chars
        long_hex_pattern = re.compile(r'\b[a-f0-9]{20,}\b', re.IGNORECASE)
        # Pattern for version numbers: "v1.2.3" or "1.2.3-abc"
        version_pattern = re.compile(r'v?\d+\.\d+\.\d+[-\w]*', re.IGNORECASE)
        # Pattern for build IDs: require at least one segment that is mostly
        # digits/hex (e.g., "abc123-def456-789"), not plain hyphenated words
        # like "kube-api-server" which are meaningful identifiers
        build_id_pattern = re.compile(
            r'\b[a-z0-9]{8,}[-_][a-z0-9]{4,}[-_][a-z0-9]{4,}\b', re.IGNORECASE
        )
        
        def clean_message_value(value: str) -> str:
            """Remove alphanumeric patterns from a message string."""
            if not isinstance(value, str):
                return value
            
            # Remove version strings with commit hashes
            value = version_commit_pattern.sub('', value)
            # Remove long hex strings
            value = long_hex_pattern.sub('', value)
            # Remove version numbers
            value = version_pattern.sub('', value)
            # Remove build IDs
            value = build_id_pattern.sub('', value)
            
            # Clean up extra spaces
            value = re.sub(r'\s+', ' ', value).strip()
            
            return value
        
        result = {}
        for key, value in structure.items():
            key_lower = key.lower()
            
            # Process message fields
            if 'message' in key_lower:
                if isinstance(value, str):
                    cleaned = clean_message_value(value)
                    if cleaned:  # Only add if there's content left after cleaning
                        result[key] = cleaned
                    # If message becomes empty after cleaning, skip it
                elif isinstance(value, list):
                    cleaned_list = []
                    for item in value:
                        if isinstance(item, str):
                            cleaned = clean_message_value(item)
                            if cleaned:
                                cleaned_list.append(cleaned)
                        else:
                            cleaned_list.append(item)
                    if cleaned_list:
                        result[key] = cleaned_list
                else:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._remove_alphanumeric_patterns_from_messages(value)
            elif isinstance(value, list):
                processed_list = []
                for item in value:
                    if isinstance(item, dict):
                        processed_item = self._remove_alphanumeric_patterns_from_messages(item)
                        if processed_item:
                            processed_list.append(processed_item)
                    else:
                        processed_list.append(item)
                if processed_list:
                    result[key] = processed_list
            else:
                result[key] = value
        
        return result
    
    def _extract_critical_fields_from_yaml(self, yaml_file_path: str, original_path: str = None) -> Dict[str, Any]:
        """
        Extract critical fields from YAML file - process ALL objects.
        Returns JSON with filename, extracted critical fields, ML classifications, and classification table.
        
        Parameters:
        -----------
        yaml_file_path : str
            Resolved full path to the YAML file
        original_path : str, optional
            Original path from orchestrator (relative from quay*) for table lookup
        """
        file_name = os.path.basename(yaml_file_path)
        result = {
            'file_name': file_name,
            'file_path': yaml_file_path,
            'objects': [],
            'classification_table': []
        }
        
        try:
            # Step 1: Load critical fields for this specific file from docx table
            file_path_for_lookup = original_path or yaml_file_path
            critical_fields = self._load_critical_fields(file_path_for_lookup)
            
            # Step 2: Extract YAML object chunks (using proven extraction logic)
            self._last_chunk_error = None
            chunks = self._extract_yaml_object_chunks(yaml_file_path)
            
            if not chunks:
                if self._last_chunk_error:
                    result['error'] = f"YAML parse error in {file_name}: {self._last_chunk_error}"
                else:
                    result['error'] = f"No YAML objects found in {file_name}"
                return result
            
            # Step 3: Process ALL chunks (all objects)
            critical_fields_list = []  # For ML classifier (without line numbers)
            objects_with_lines = []  # For result (with line numbers for reference)
            
            for idx, (chunk_string, start_line, end_line, key_value_pairs) in enumerate(chunks):
                # Extract critical fields preserving YAML structure
                critical_fields_data = self._extract_critical_fields_from_chunk(
                    chunk_string,
                    key_value_pairs, 
                    critical_fields
                )
                
                # Remove line numbers, timestamps, and alphanumeric patterns from messages for ML classifier
                # Only verbose error patterns are needed
                critical_fields_clean = self._remove_line_numbers_from_structure(critical_fields_data)
                critical_fields_clean = self._remove_timestamps_from_structure(critical_fields_clean)
                critical_fields_clean = self._remove_alphanumeric_patterns_from_messages(critical_fields_clean)
                critical_fields_list.append(critical_fields_clean)
                
                # Store object with line numbers for reference
                object_result = {
                    'object_index': idx,
                    'start_line': start_line,
                    'end_line': end_line,
                    'key_value_pairs_count': len(key_value_pairs),
                    'critical_fields': critical_fields_data
                }
                objects_with_lines.append(object_result)
            
            #result['objects'] = objects_with_lines

            filtered_critical_fields = []
            filtered_objects = []
            
            for cf, obj in zip(critical_fields_list, objects_with_lines):
                # Skip empty chunks (wrapper metadata)
                if not cf or cf == {}:
                    if not _is_quiet():
                        print(f"  [Filter] Skipping Chunk {obj['object_index']+1} (lines {obj['start_line']}-{obj['end_line']}): Empty/wrapper metadata")
                    continue
                
                # Skip chunks with only wrapper fields (continue, resourceVersion)
                keys = set(cf.keys()) if isinstance(cf, dict) else set()
                if keys == {'metadata'}:
                    nested_keys = set(cf.get('metadata', {}).keys())
                    if nested_keys <= {'continue', 'resourceVersion'}:
                        if not _is_quiet():
                            print(f"  [Filter] Skipping Chunk {obj['object_index']+1} (lines {obj['start_line']}-{obj['end_line']}): List wrapper metadata only")
                        continue
                
                filtered_critical_fields.append(cf)
                filtered_objects.append(obj)
            
            # Replace lists with filtered versions
            critical_fields_list = filtered_critical_fields
            objects_with_lines = filtered_objects

            # Update result with filtered objects
            result['objects'] = objects_with_lines
            
            # Step 4: Send to ML Classifier
            if ML_CLASSIFIER_AVAILABLE and critical_fields_list:
                ml_response = classify_critical_fields(critical_fields_list)

                # Handle both structured (dict) and legacy (list) returns
                if isinstance(ml_response, dict):
                    ml_results = ml_response.get('results', [])
                    ml_error = ml_response.get('error')
                else:
                    ml_results = ml_response if isinstance(ml_response, list) else []
                    ml_error = None

                if ml_error:
                    result.setdefault('warnings', []).append(f"ML classification: {ml_error}")
                    if not _is_quiet():
                        print(f"  [ML Warning] {ml_error}")

                # Validate result count matches input
                if ml_results and len(ml_results) != len(objects_with_lines):
                    if not _is_quiet():
                        print(f"  [ML Warning] Result count mismatch: expected {len(objects_with_lines)}, got {len(ml_results)}")
                    result.setdefault('warnings', []).append(
                        f"ML result count mismatch: expected {len(objects_with_lines)}, got {len(ml_results)}"
                    )

                # Warn when ML returns empty for a file that had objects
                if not ml_results and objects_with_lines:
                    warning_msg = f"ML classification returned no results for {file_name} ({len(objects_with_lines)} objects submitted)"
                    result.setdefault('warnings', []).append(warning_msg)
                    if not _is_quiet():
                        print(f"  [ML Warning] {warning_msg}")

                # Step 5: Create classification table
                classification_table = []
                for obj_result, ml_result in zip(objects_with_lines, ml_results):
                    chunk_num = obj_result['object_index'] + 1
                    lines = f"{obj_result['start_line']}-{obj_result['end_line']}"
                    classification = ml_result.get('classification', 'Unknown')
                    reason = ml_result.get('reason', 'No reason provided')
                    
                    classification_table.append({
                        'Chunk': chunk_num,
                        'Lines': lines,
                        'Classification': classification,
                        'Reason': reason
                    })
                
                result['classification_table'] = classification_table
                result['ml_results'] = ml_results
                
                # Step 6: Collect raw critical fields for objects classified as
                # Error only (not Majority Error — Majority Error represents
                # common negative patterns that are widespread and less useful
                # for root-cause analysis; only rare/anomalous "Error" objects
                # are sent to the LLM RCA agent).
                error_objects_raw = []
                for obj_result, ml_result in zip(objects_with_lines, ml_results):
                    if ml_result.get('classification') == 'Error':
                        critical_fields_no_lines = self._remove_line_numbers_from_structure(obj_result['critical_fields'])
                        error_objects_raw.append({
                            'object_index': obj_result['object_index'],
                            'start_line': obj_result['start_line'],
                            'end_line': obj_result['end_line'],
                            'critical_fields': critical_fields_no_lines,
                        })
                result['error_objects_raw'] = error_objects_raw
            else:
                result['error_objects_raw'] = []
                if not ML_CLASSIFIER_AVAILABLE:
                    result['error'] = "ML Classifier not available"
                else:
                    result['error'] = "No critical fields extracted"
            
        except Exception as e:
            result['error'] = str(e)
            result['error_objects_raw'] = []
        
        return result
    
    def print_classification_table(self, classification_table: List[Dict[str, Any]], file_name: str = None):
        """
        Print the ML classification table in the requested format.
        
        Args:
            classification_table: List of dicts with keys: Chunk, Lines, Classification, Reason
            file_name: Optional file name to print as header (e.g., clusterversions.yaml)
        """
        if not classification_table:
            return
        
        # Print file name header when processing multiple files
        if not _is_quiet():
            if file_name:
                print(f"\n--- {file_name} ---")
            
            # Print header
            print(f"\n{'Chunk':<8} {'Lines':<15} {'Classification':<20} {'Reason':<60}")
            print("-" * 100)
            
            # Print each row
            for row in classification_table:
                chunk = str(row.get('Chunk', ''))
                lines = str(row.get('Lines', ''))
                classification = str(row.get('Classification', ''))
                reason = str(row.get('Reason', ''))
                
                # Handle long reasons - wrap to next line if needed
                if len(reason) <= 60:
                    print(f"{chunk:<8} {lines:<15} {classification:<20} {reason:<60}")
                else:
                    # First line - show first 60 chars
                    print(f"{chunk:<8} {lines:<15} {classification:<20} {reason[:60]}")
                    # Continuation lines - indent to align with Reason column (8+15+20+1 = 44 spaces before Reason)
                    remaining = reason[60:]
                    while remaining:
                        # Align continuation with Reason column start
                        print(f"{'':<44}{remaining[:60]}")
                        remaining = remaining[60:]
            
            print()

    def _is_yaml_path(self, path: str) -> bool:
        """True if path looks like a YAML file."""
        p = (path or "").lower()
        return p.endswith(".yaml") or p.endswith(".yml")

    def _is_log_path(self, path: str) -> bool:
        """True if path looks like a log/txt file (extension or path contains logs)."""
        p = (path or "").lower()
        return p.endswith(".log") or p.endswith(".txt") or "/logs/" in p or "\\logs\\" in p

    def report_files_availability(self, file_paths: List[str]) -> Dict:
        """
        Search which shortlisted files are available in the supplied must-gather directory
        or elsewhere under root. Prints a report to terminal and returns data for UI.
        Saves a full resolved_paths.json to Results/ for debuggability.

        The JSON has exactly one entry per input path so the total always adds up.
        Wildcard paths show all matched physical files. Deduplicated paths are flagged
        instead of silently dropped.
        """
        import json as _json
        base_folder = self.must_gather_base_dir or DEFAULT_BASE_FOLDER

        # ── Track seen resolved paths for deduplication across all input paths ──
        seen_resolved: set = set()

        # ── Per-path records (one entry per raw input path) ──
        # Each record:  raw_path, normalized_path, status, resolved_paths[], note, searched_path
        # status: "found" | "not_found" | "error"
        # Duplicates are reported as "not_found" with a "duplicate" note.
        per_path_records: List[Dict] = []

        # Also build the legacy lists needed by the return dict and callers
        found_in_supplied_dir: List[Dict] = []
        not_found_list: List[str] = []

        for raw_path in file_paths:
            # Try regex-based node-name expansion before generic placeholder normalization
            if '<' in raw_path:
                node_expanded = self._expand_node_name_placeholder(raw_path, base_folder)
                if node_expanded:
                    new_matches = []
                    for ne in node_expanded:
                        key = os.path.normpath(os.path.normcase(ne))
                        if key not in seen_resolved:
                            seen_resolved.add(key)
                            new_matches.append(ne)
                            found_in_supplied_dir.append({"original": raw_path, "resolved": ne})
                    if new_matches:
                        per_path_records.append({
                            "raw_path": raw_path,
                            "status": "found",
                            "resolved_paths": new_matches,
                            "note": f"node-name regex expansion: {len(node_expanded)} file(s) matched",
                        })
                    else:
                        not_found_list.append(raw_path)
                        per_path_records.append({
                            "raw_path": raw_path,
                            "status": "not_found",
                            "resolved_paths": [],
                            "note": "duplicate — node-name expanded files already resolved by earlier entries",
                        })
                    continue

            normalized = self._normalize_placeholders(raw_path)
            is_wildcard = self._path_has_wildcard(self._strip_must_gather_prefix(normalized))

            try:
                if is_wildcard:
                    matches = self._resolve_path_glob(normalized, base_folder)
                    if matches:
                        new_matches = []
                        dup_matches = []
                        for m in matches:
                            key = os.path.normpath(os.path.normcase(m))
                            if key not in seen_resolved:
                                seen_resolved.add(key)
                                new_matches.append(m)
                                found_in_supplied_dir.append({"original": raw_path, "resolved": m})
                            else:
                                dup_matches.append(m)
                        if new_matches:
                            per_path_records.append({
                                "raw_path": raw_path,
                                "normalized_path": normalized if normalized != raw_path else None,
                                "status": "found",
                                "resolved_paths": new_matches,
                                "duplicate_paths": dup_matches if dup_matches else None,
                                "note": f"glob expansion: {len(matches)} physical file(s) matched",
                            })
                        else:
                            not_found_list.append(raw_path)
                            per_path_records.append({
                                "raw_path": raw_path,
                                "normalized_path": normalized if normalized != raw_path else None,
                                "status": "not_found",
                                "resolved_paths": [],
                                "note": "duplicate — all matched files already resolved by earlier entries",
                            })
                    else:
                        # Wildcard found no matches at all
                        not_found_list.append(raw_path)
                        per_path_records.append({
                            "raw_path": raw_path,
                            "normalized_path": normalized if normalized != raw_path else None,
                            "status": "not_found",
                            "resolved_paths": [],
                            "note": "wildcard/placeholder pattern — 0 files matched",
                            "searched_pattern": normalized,
                        })
                else:
                    # Concrete (non-wildcard) path
                    # Fast path: already resolved absolute path under base — skip re-resolution.
                    if (os.path.isabs(normalized)
                            and self._is_path_under_base(normalized, base_folder)):
                        full_path = os.path.normpath(normalized)
                    else:
                        full_path = self._resolve_path(normalized, base_folder)
                    if os.path.exists(full_path) and os.path.isfile(full_path):
                        key = os.path.normpath(os.path.normcase(full_path))
                        if key not in seen_resolved:
                            seen_resolved.add(key)
                            found_in_supplied_dir.append({"original": raw_path, "resolved": full_path})
                            per_path_records.append({
                                "raw_path": raw_path,
                                "status": "found",
                                "resolved_paths": [full_path],
                                "note": "direct",
                            })
                        else:
                            not_found_list.append(raw_path)
                            per_path_records.append({
                                "raw_path": raw_path,
                                "status": "not_found",
                                "resolved_paths": [],
                                "note": "duplicate — same physical file already resolved by an earlier entry",
                            })
                    else:
                        not_found_list.append(raw_path)
                        per_path_records.append({
                            "raw_path": raw_path,
                            "status": "not_found",
                            "resolved_paths": [],
                            "note": "not found",
                            "searched_path": full_path,
                        })
            except Exception as exc:
                not_found_list.append(raw_path)
                per_path_records.append({
                    "raw_path": raw_path,
                    "normalized_path": normalized if normalized != raw_path else None,
                    "status": "error",
                    "resolved_paths": [],
                    "note": f"exception during resolution: {exc}",
                })

        # ── Summary counts (all based on per_path_records → always add up to total) ──
        total_raw = len(file_paths)
        total_found = sum(1 for r in per_path_records if r["status"] == "found")
        total_not_found = sum(1 for r in per_path_records if r["status"] == "not_found")
        total_error = sum(1 for r in per_path_records if r["status"] == "error")
        total_physical = len(seen_resolved)
        total_duplicate = sum(1 for r in per_path_records if "duplicate" in (r.get("note") or "").lower())

        if not _is_quiet():
            print("\n" + "=" * 100)
            print("Shortlisted files: availability in must-gather directory")
            print("=" * 100)
            print(f"Supplied must-gather directory: {base_folder}")
            print(f"Total raw paths shortlisted : {total_raw}")
            print(f"  Found (unique physical)    : {total_found} raw paths → {total_physical} physical file(s)")
            print(f"    In supplied directory     : {len(found_in_supplied_dir)}")
            print(f"  NOT found                  : {total_not_found}"
                  + (f"  (of which {total_duplicate} are duplicates of already-resolved files)" if total_duplicate else ""))
            if total_error:
                print(f"  Errors during resolution   : {total_error}")
            print(f"  CHECK: {total_found} + {total_not_found}"
                  + (f" + {total_error} errors" if total_error else "")
                  + f" = {total_found + total_not_found + total_error}"
                  + (" ✓" if total_found + total_not_found + total_error == total_raw else " ✗ MISMATCH"))
            print()
            for rec in per_path_records:
                status = rec["status"]
                raw = rec["raw_path"]
                note = rec.get("note", "")
                if status == "found":
                    paths = rec.get("resolved_paths", [])
                    print(f"  [FOUND]     {raw}")
                    for p in paths:
                        print(f"               -> {p}  [{note}]")
                elif status == "not_found":
                    is_dup = "duplicate" in note.lower()
                    tag = "NOT FOUND (duplicate)" if is_dup else "NOT FOUND"
                    print(f"  [{tag}] {raw}")
                    if is_dup:
                        print(f"               reason: {note}")
                    else:
                        searched = rec.get("searched_path") or rec.get("searched_pattern", "")
                        if searched:
                            print(f"               searched: {searched}")
                elif status == "error":
                    print(f"  [ERROR]     {raw}  — {note}")
            print("=" * 100 + "\n")

        # ── Save resolved_paths.json (one entry per input path — always N entries for N paths) ──
        try:
            from app_paths import get_results_dir
            out_path = get_results_dir() / "resolved_paths.json"
            with open(out_path, "w", encoding="utf-8") as _f:
                _json.dump({
                    "base_folder": base_folder,
                    "total_raw_paths": total_raw,
                    "summary": {
                        "found": total_found,
                        "not_found": total_not_found,
                        "not_found_duplicates": total_duplicate,
                        "error": total_error,
                        "physical_files": total_physical,
                        "check": f"{total_found}+{total_not_found}"
                                 + (f"+{total_error}(err)" if total_error else "")
                                 + f"={total_found+total_not_found+total_error}"
                                 + (" OK" if total_found+total_not_found+total_error == total_raw else " MISMATCH"),
                    },
                    "entries": per_path_records,
                }, _f, indent=2, ensure_ascii=False)
            if not _is_quiet():
                print(f"[Availability] Full path resolution saved to: {out_path}")
        except Exception as _e:
            if not _is_quiet():
                print(f"[Availability] Warning: could not save resolved_paths.json: {_e}")

        # Build summary text for UI
        lines = [
            f"Supplied directory: {base_folder}",
            f"Total raw paths shortlisted: {total_raw}",
            f"  Found: {total_found} paths → {total_physical} physical files",
            f"  Duplicate (same file, not re-sent): {total_duplicate}",
            f"  Not found: {total_not_found}",
        ]
        return {
            "base_folder": base_folder,
            "total_shortlisted": total_raw,
            "total_physical_files": total_physical,
            "found_in_supplied_dir": found_in_supplied_dir,
            "found_elsewhere": [],
            "not_found": not_found_list,
            "summary_text": "\n".join(lines),
        }

    def analyze_files(
        self,
        file_paths: List[str],
        file_types: List[str] = None,
        progress_callback=None,
        suggested_files_with_priority: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Analyze a list of files (YAML and log). Called by orchestrator_agent.py.
        Resolves paths under base folder; files not found are skipped.
        Prints all YAML and log files to analyze, grouped by priority (high/medium/low).

        Parameters:
        -----------
        file_paths : List[str]
            List of file paths (suggested by LLM or default)
        file_types : List[str], optional
            List of file types to include ('yaml', 'log', 'json'). If None, ['yaml', 'log', 'json'].
        suggested_files_with_priority : List[Dict], optional
            LLM suggested list with 'path' and 'priority' (high/medium/low) for printing by priority.

        Returns:
        --------
        dict : Analysis results (analyzed_files, failed_files, data, summary, log_files_for_analysis, etc.)
        """
        if file_types is None:
            file_types = ["yaml", "log", "json"]

        # Check if files are accessible under the configured base folder
        base_folder = self.must_gather_base_dir or DEFAULT_BASE_FOLDER
        access_result = self._check_file_access(file_paths, base_folder)

        # Files not found at their resolved path are marked as not found.
        # No parent-directory fallback search is performed.

        # Build priority map from LLM suggested list (original path -> priority)
        path_to_priority = {}
        if suggested_files_with_priority:
            for s in suggested_files_with_priority:
                p = (s.get("path") or "").strip()
                if p:
                    path_to_priority[p] = (s.get("priority") or "medium").lower()

        # Deduplicate by resolved path so same file (e.g. kubelet from LLM + ALWAYS_INCLUDE) is processed once
        def _dedupe_accessible_by_resolved(items: list) -> list:
            seen = set()
            out = []
            for item in items:
                res = item.get("resolved", "")
                key = os.path.normpath(os.path.normcase(res)) if res else res
                if key and key not in seen:
                    seen.add(key)
                    out.append(item)
            return out

        accessible_deduped = _dedupe_accessible_by_resolved(access_result["accessible"])
        # Create mapping: resolved_path -> original_path for table lookup
        path_mapping = {item['resolved']: item['original'] for item in accessible_deduped}

        # Classify accessible items as YAML or log (only actual files, not directories)
        all_resolved = []
        for item in accessible_deduped:
            res = item.get("resolved", "")
            orig = item.get("original", "")
            if not res or item.get("note") == "path is a directory":
                continue
            if not os.path.isfile(res):
                continue
            all_resolved.append((res, orig))

        yaml_files = [res for res, _ in all_resolved if self._is_yaml_path(res)]
        # Deduplicate log files by normalized path so same file (e.g. kubelet_service from two names) is processed once
        _log_seen = set()
        log_files = []
        for res, _ in all_resolved:
            if not self._is_log_path(res):
                continue
            key = os.path.normpath(os.path.normcase(os.path.abspath(res)))
            if key not in _log_seen:
                _log_seen.add(key)
                log_files.append(res)

        # Print resolved file paths
        if not _is_quiet():
            yaml_here = [(r, o) for r, o in all_resolved if self._is_yaml_path(r)]
            log_here = [(r, o) for r, o in all_resolved if self._is_log_path(r)]
            other_here = [(r, o) for r, o in all_resolved if not self._is_yaml_path(r) and not self._is_log_path(r)]
            print("\n" + "=" * 100)
            print(f"Resolved files to analyze ({len(all_resolved)} total)")
            print("=" * 100)
            for res, orig in yaml_here:
                print(f"  [YAML]  {res}")
            for res, orig in log_here:
                print(f"  [LOG]   {res}")
            for res, orig in other_here:
                print(f"  [FILE]  {res}")
            print("=" * 100 + "\n")

        total_yaml_bytes = 0
        yaml_file_sizes = {}
        if progress_callback and (yaml_files or log_files):
            try:
                progress_callback("file_analysis_intent", "Intent: Load critical fields from docx, extract YAML objects, and classify each with ML (Error, Majority Error, Majority, CONFIG). Log files are listed for analysis.", None)
                all_names = [os.path.basename(r) for r in yaml_files] + [os.path.basename(r) for r in log_files]
                progress_callback("yaml_files_list", "Shortlisted files for analysis (YAML + log, resolved under base dir):", {"files": all_names})
            except Exception:
                pass
        
        if yaml_files:
            # Process all YAML files (clusteroperators.yaml, clusterversions.yaml, etc.)
            for yaml_file in yaml_files:
                file_key = os.path.basename(yaml_file)
                original_path = path_mapping.get(yaml_file, yaml_file)
                if progress_callback:
                    try:
                        progress_callback("yaml_processing", f"Sending to ML: {file_key}", {"file": file_key})
                    except Exception:
                        pass
                try:
                    sz = os.path.getsize(yaml_file)
                    total_yaml_bytes += sz
                    yaml_file_sizes[file_key] = sz
                except Exception:
                    yaml_file_sizes[file_key] = 0
                
                if not _is_quiet():
                    print(f"\n[Data Analyzer] Processing: {file_key}")
                metadata = self._extract_critical_fields_from_yaml(yaml_file, original_path)
                
                # Store in memory
                self.extracted_metadata[file_key] = metadata
                
                # Progress: classification table for this file (with brief explanation of labels)
                if progress_callback and metadata.get('classification_table'):
                    try:
                        progress_callback("classification", f"ML results for {file_key}", {
                            "file": file_key,
                            "table": metadata['classification_table'],
                            "explanation": "Error = rare/anomaly; Majority Error = common negative pattern; Majority = common healthy; CONFIG = config change.",
                        })
                    except Exception:
                        pass
                elif progress_callback and file_key:
                    # No table: report why
                    reason = "no objects found" if not metadata.get('objects') else "no critical fields extracted or no ML table"
                    try:
                        progress_callback("classification_no_output", f"No ML output for {file_key}: {reason}.", {"file": file_key, "reason": reason})
                    except Exception:
                        pass
                
                # Check for errors or issues
                if not _is_quiet():
                    if 'error' in metadata:
                        print(f"\n[Warning] Error processing {file_key}: {metadata['error']}")
                    elif not metadata.get('objects'):
                        print(f"\n[Info] {file_key}: No objects found in file")
                    elif not metadata.get('classification_table'):
                        print(f"\n[Info] {file_key}: No classification table generated (may have no critical fields extracted)")
                
                # Print classification table for this file if available
                if 'classification_table' in metadata and metadata['classification_table']:
                    # Print file name so user knows which file the table is for
                    self.print_classification_table(metadata['classification_table'], file_key)

        # Process log/txt files with ML_LOG_CLASSIFICATION (Error, Information, Warning)
        # analyze_logs_ml is the public entry point: takes a single file_path, returns
        # {"status", "files": {"rare_errors": {path, templates, lines}, ...}, "totals", ...}
        log_processing_result = {}
        if log_files and ML_LOG_CLASSIFICATION_AVAILABLE:
            output_dir = str(get_application_dir() / "Results" / "log_classifications")
            _level_map = {
                "rare_errors": "RareError",
                "highfreq_errors": "HighFreqError",
                "warnings": "Warning",
                "information": "Information",
                "unknown": "Unknown",
                "config_changes": "CONFIG",
            }
            all_per_file = []
            try:
                for log_file in log_files:
                    try:
                        result = analyze_logs_ml(log_file, output_dir=output_dir)
                        if result.get("error"):
                            if not _is_quiet():
                                print(f"[Data Analyzer] Log classification error for {os.path.basename(log_file)}: {result['error']}")
                            continue
                        saved = {}
                        for out_key, file_info in result.get("files", {}).items():
                            level_name = _level_map.get(out_key, out_key)
                            if isinstance(file_info, dict) and file_info.get("path"):
                                saved[level_name] = file_info["path"]
                        all_per_file.append({"file": log_file, "saved": saved})
                        if not _is_quiet():
                            print(f"[Data Analyzer] Log processed: {os.path.basename(log_file)} "
                                  f"({result.get('totals', {}).get('lines', 0)} lines, "
                                  f"{result.get('totals', {}).get('templates', 0)} templates)")
                    except Exception as e:
                        if not _is_quiet():
                            print(f"[Data Analyzer] Log classification error for {os.path.basename(log_file)}: {e}")

                log_processing_result = {
                    "per_file": all_per_file,
                    "logs_count": len(all_per_file),
                    "summary": {},
                }

                if not _is_quiet() and all_per_file:
                    print("\n" + "=" * 80)
                    print("LOG PROCESSING (Error, Information, Warning) — one set per log file (each file once)")
                    print("=" * 80)
                    print(f"  Log files processed: {len(all_per_file)}")
                    for pf in all_per_file:
                        print(f"  {pf.get('file', '')}:")
                        for level_name, path in (pf.get("saved") or {}).items():
                            print(f"    {level_name} -> {path}")
                    print("=" * 80 + "\n")

                if progress_callback:
                    try:
                        progress_callback("log_processing_result", "Log processing complete (Error, Information, Warning)", log_processing_result)
                    except Exception:
                        pass
            except Exception as e:
                if not _is_quiet():
                    print(f"[Data Analyzer] Log classification error: {e}")
                log_processing_result = {"error": str(e), "summary": {}, "saved_files": {}}
                if progress_callback:
                    try:
                        progress_callback("log_processing_result", "Log processing failed", log_processing_result)
                    except Exception:
                        pass
        elif log_files and not ML_LOG_CLASSIFICATION_AVAILABLE:
            if not _is_quiet():
                print("[Data Analyzer] Log files present but ML_LOG_CLASSIFICATION not available (install drain3).")
            if progress_callback:
                try:
                    progress_callback("log_processing_result", "Log processing skipped (drain3 not installed)", {"error": "drain3 not installed", "summary": {}, "saved_files": {}})
                except Exception:
                    pass

                # Load output flags from config (with defaults)
        DEFAULT_OUTPUT_FLAGS = {
            'include_errors': True,
            'include_majority_errors': True,
            'include_config_changes': True,
            'include_normal_reports': False,
            'include_summary': True
        }
        output_flags = {**DEFAULT_OUTPUT_FLAGS, **self.config.get('output_flags', {})}
        
        # Aggregate classified objects based on flags across all files
        aggregated_results = {}
        files_with_no_output = []
        all_warnings = []
        
        for file_key, file_data in self.extracted_metadata.items():
            ml_results = file_data.get('ml_results', [])
            objects_with_lines = file_data.get('objects', [])

            # Collect per-file warnings (ML failures, parse errors, etc.)
            for w in file_data.get('warnings', []):
                all_warnings.append(f"{file_key}: {w}")
            
            if not ml_results:
                if not file_data.get('classification_table'):
                    file_error = file_data.get('error', '')
                    if 'parse error' in (file_error or '').lower():
                        reason = f"YAML parse error: {file_error}"
                    elif not objects_with_lines:
                        reason = "no objects in file"
                    else:
                        reason = "no critical fields matched or ML produced no table"
                    files_with_no_output.append({"file": file_key, "reason": reason})
                continue
            
            # Filter objects based on output flags
            file_classified_objects = []
            
            for obj_result, ml_result in zip(objects_with_lines, ml_results):
                classification = ml_result.get('classification')
                
                # Apply flags to determine if this object should be included
                should_include = False
                
                if classification == 'Error' and output_flags.get('include_errors', True):
                    should_include = True
                elif classification == 'Majority Error' and output_flags.get('include_majority_errors', True):
                    should_include = True
                elif classification == 'CONFIG' and output_flags.get('include_config_changes', True):
                    should_include = True
                elif classification == 'Majority' and output_flags.get('include_normal_reports', False):
                    should_include = True
                
                if should_include:
                    # Remove line numbers from critical fields for clean output
                    critical_fields_clean = self._remove_line_numbers_from_structure(obj_result['critical_fields'])
                    
                    file_classified_objects.append({
                        'object_index': obj_result['object_index'],
                        'start_line': obj_result['start_line'],
                        'end_line': obj_result['end_line'],
                        'classification': classification,
                        'reason': ml_result.get('reason', ''),
                        'patterns': ml_result.get('verbose_patterns', []),
                        'has_config_change': ml_result.get('has_config_change', False),
                        'critical_fields': critical_fields_clean
                    })
            
            # Add file results if any objects were included
            if file_classified_objects:
                file_result = {
                    'objects': file_classified_objects
                }
                
                # Add summary if enabled
                if output_flags.get('include_summary', True):
                    summary = {
                        'total_objects': len(ml_results),
                        'error_count': sum(1 for ml in ml_results if ml.get('classification') == 'Error'),
                        'majority_error_count': sum(1 for ml in ml_results if ml.get('classification') == 'Majority Error'),
                        'config_change_count': sum(1 for ml in ml_results if ml.get('classification') == 'CONFIG'),
                        'normal_count': sum(1 for ml in ml_results if ml.get('classification') == 'Majority'),
                        'included_in_output': len(file_classified_objects)
                    }
                    file_result['summary'] = summary
                
                aggregated_results[file_key] = file_result
        
        if progress_callback and files_with_no_output:
            try:
                progress_callback("files_no_output", "Why no ML output for some files:", {"files": files_with_no_output})
            except Exception:
                pass
        
        # Store aggregated results JSON to file
        results_output_path = get_application_dir() / "errors_aggregate.json"
        
        # Add metadata to output
        output_data = {
            'output_flags': output_flags,
            'files': aggregated_results
        }
        
        try:
            with open(results_output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, default=str)
        except (IOError, OSError) as e:
            if not _is_quiet():
                print(f"[DataAnalyzer] Failed to write {results_output_path}: {e}")
            results_output_path = None
        
        # Build included_categories and results_text unconditionally
        # (used by progress_callback and return value even in quiet mode)
        included_categories = []
        if output_flags.get('include_errors', True):
            included_categories.append('Error')
        if output_flags.get('include_majority_errors', True):
            included_categories.append('Majority Error')
        if output_flags.get('include_config_changes', True):
            included_categories.append('CONFIG')
        if output_flags.get('include_normal_reports', False):
            included_categories.append('Majority')

        results_text = json.dumps(output_data, indent=2, default=str)

        if not _is_quiet():
            print("\n" + "=" * 80)
            print("YAML Classifications (filtered by output flags)")
            print("=" * 80)
            print(f"Included categories: {', '.join(included_categories)}")
            print("=" * 80)
            print(results_text)
            print("=" * 80)
            if results_output_path:
                print(f"Written to: {results_output_path}")
            else:
                print("Warning: errors_aggregate.json could not be written")
        
        if progress_callback:
            try:
                progress_callback("yaml_classifications", "YAML Classifications (filtered by output flags)", {
                    "text": results_text,
                    "path": str(results_output_path) if results_output_path else None,
                    "included_categories": included_categories
                })
            except Exception:
                pass

        # Return structure expected by orchestrator
        # Aggregate classification tables from ALL processed files (not just the first one)
        classification_table = []
        for file_data in self.extracted_metadata.values():
            if 'classification_table' in file_data:
                classification_table.extend(file_data['classification_table'])
        if not classification_table:
            classification_table = None
        
        # Log files are listed for analysis (no ML classification; available for future processing)
        log_files_original = [path_mapping.get(r, r) for r in log_files]

        return {
            "analyzed_files": [item['original'] for item in accessible_deduped],
            "failed_files": [item['original'] for item in access_result['not_found'] + access_result['errors']],
            "data": self.extracted_metadata,
            "classification_table": classification_table,
            "ml_classification_result": output_data,
            "yaml_classifications_path": str(results_output_path) if results_output_path else None,
            "output_flags": output_flags,
            "included_categories": included_categories,
            "total_yaml_bytes": total_yaml_bytes,
            "files_with_no_output": files_with_no_output,
            "warnings": all_warnings,
            "log_files_for_analysis": log_files_original,
            "yaml_files_processed": yaml_files,
            "log_files_resolved": log_files,
            "log_processing_result": log_processing_result,
            "yaml_file_sizes": yaml_file_sizes,
            "summary": {
                "files_processed": len(yaml_files),
                "log_files_for_analysis": len(log_files),
                "critical_fields_extracted": sum(len(m.get('objects', [])) for m in self.extracted_metadata.values()),
            },
            "errors": [item.get('error', '') for item in access_result['errors']],
            "file_count": len(file_paths),
            "file_types_processed": file_types,
            "file_access_check": access_result,
        }
