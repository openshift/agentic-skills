"""
ML YAML Classification Module

This module receives critical fields extracted from YAML objects (as JSON)
and classifies them using Drain3-based ML algorithm.
Only critical field values are processed - no line numbers are used.
"""

import json
import re
from typing import List, Dict, Tuple, Optional, Any
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import yaml  
import os  

# QUIET MODE: Check if orchestrator has enabled quiet mode
def _is_quiet():
    """Check if orchestrator has enabled quiet mode via environment variable"""
    return os.environ.get('ORCHESTRATOR_QUIET', '0') == '1'

# LOAD ERROR PATTERN CONFIGURATION FROM CONFIG FILE

def _load_error_pattern_config() -> Dict[str, Any]:
    """Load error pattern configuration from config/yaml_processing.yaml"""
    config_path = Path(__file__).parent / "config" / "yaml_processing.yaml"
    
    # Default fallback configuration
    default_config = {
        "error_patterns": {
            "verbose_patterns": [
                "not progressing", "not available", "not ready", "not healthy",
                "halted", "stopped", "degraded", "unavailable", "down",
                "timeout", "timed out", "missing", "not found", "denied",
                "forbidden", "stuck", "waiting"
            ],
            "explicit_keywords": ["error", "failed", "failure", "exception", "critical", "fatal"],
            "excluded_key_patterns": ["failure-domain", "topology.kubernetes.io", 
                                     "node.kubernetes.io", "failurepolicy"]
        },
        "classification": {
            "common_pattern_threshold": 0.30,
            "majority_threshold": 0.10,
            "error_threshold": 0.01
        }
    }
    
    # Try to load from config file
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                loaded_config = yaml.safe_load(f)
                if loaded_config and "error_patterns" in loaded_config:
                    # Merge with defaults
                    default_config.update(loaded_config)
        except Exception as e:
            if not _is_quiet():
                print(f"[Warning] Could not load error patterns from config: {e}")
                print("[Warning] Using default error patterns")
    
    return default_config


# Load configuration once at module import time
_ERROR_CONFIG = _load_error_pattern_config()

# Create convenient accessors for use throughout the module
VERBOSE_ERROR_PATTERNS = _ERROR_CONFIG.get("error_patterns", {}).get("verbose_patterns", [])
EXPLICIT_ERROR_KEYWORDS = _ERROR_CONFIG.get("error_patterns", {}).get("explicit_keywords", [])
EXCLUDED_KEY_PATTERNS = _ERROR_CONFIG.get("error_patterns", {}).get("excluded_key_patterns", [])

def flatten_critical_fields_to_string(critical_fields_data: Dict[str, Any]) -> str:
    """
    Flatten critical fields JSON structure into a string for Drain3 processing.
    Recursively extracts all key-value pairs from nested JSON structure.
    Line numbers are excluded - only field paths and values are used.
    
    Args:
        critical_fields_data: Dictionary containing critical fields (nested structure)
                             Example: {"metadata": {"name": "authentication"}, 
                                      "status": {"conditions": [...]}}
    
    Returns:
        Flattened string representation: "metadata.name: authentication, status.conditions.type: Degraded, ..."
    """
    kv_pairs = []
    
    def extract_kv_pairs(obj: Any, prefix: str = ""):
        """Recursively extract key-value pairs from nested structure."""
        if isinstance(obj, dict):
             # Check if this dict represents a semantic unit (type+status pair)
            if _is_semantic_unit(obj):
                # Combine related fields into one string
                combined = _combine_semantic_fields(obj)
                if combined:
                    kv_pairs.append(f"{prefix}: {combined}")
                return  # Don't recurse further
            
            # Normal dict processing
            for key, value in obj.items():
                if key == "_line_numbers" or key.endswith("_line_numbers"):
                    continue
                
                current_path = f"{prefix}.{key}" if prefix else key
                
                if isinstance(value, dict):
                    extract_kv_pairs(value, current_path)
                elif isinstance(value, list):
                    for idx, item in enumerate(value):
                        if isinstance(item, dict):
                            extract_kv_pairs(item, f"{current_path}[{idx}]")
                        else:
                            kv_pairs.append(f"{current_path}[{idx}]: {item}")
                else:
                    kv_pairs.append(f"{current_path}: {value}")
    
    extract_kv_pairs(critical_fields_data)
    return ", ".join(kv_pairs)


def _is_semantic_unit(obj: dict) -> bool:
    """
    Check if a dict represents a semantic unit that should be combined.
    Generic heuristic: If dict has 'type' + 'status' keys, it's likely a condition.
    Or 'key' + 'value', 'name' + 'value', etc.
    """
    keys = set(obj.keys()) - {'_line_numbers'}  # Ignore metadata
    
    # Common patterns for semantic units:
    # 1. type + status (Kubernetes conditions)
    if 'type' in keys and 'status' in keys:
        return True
    
    # 2. key + value (ConfigMaps, env vars)
    if 'key' in keys and 'value' in keys:
        return True
    
    # 3. name + value (labels, annotations)
    if 'name' in keys and 'value' in keys:
        return True
    
    return False

def _combine_semantic_fields(obj: dict) -> str:
    """
    Combine related fields into a single meaningful string.
    Examples:
      {"type": "Degraded", "status": "False"} → "Degraded=False"
      {"key": "LOG_LEVEL", "value": "debug"} → "LOG_LEVEL=debug"
    """
    # Remove metadata keys
    clean_obj = {k: v for k, v in obj.items() if not k.endswith('_line_numbers')}
    
    # Pattern 1: type + status (most common)
    if 'type' in clean_obj and 'status' in clean_obj:
        type_val = clean_obj['type']
        status_val = clean_obj['status']
        # Include message/reason if present (but keep them short)
        extras = []
        if 'reason' in clean_obj:
            extras.append(f"reason={clean_obj['reason']}")
        if 'message' in clean_obj:
            # Truncate long messages
            msg = str(clean_obj['message'])[:50]
            extras.append(f"message={msg}")
        
        extra_str = f" ({', '.join(extras)})" if extras else ""
        return f"{type_val}={status_val}{extra_str}"
    
    # Pattern 2: key + value
    if 'key' in clean_obj and 'value' in clean_obj:
        return f"{clean_obj['key']}={clean_obj['value']}"
    
    # Pattern 3: name + value
    if 'name' in clean_obj and 'value' in clean_obj:
        return f"{clean_obj['name']}={clean_obj['value']}"
    
    # Fallback: just combine all key=value pairs
    pairs = [f"{k}={v}" for k, v in clean_obj.items()]
    return ", ".join(pairs)

def process_objects_with_drain3(critical_fields_list: List[Dict[str, Any]]) -> Tuple[Dict, List[Dict], Dict]:
    """
    Process critical fields from multiple objects using Drain3 to extract templates.
    
    Args:
        critical_fields_list: List of critical fields dictionaries (one per object)
                             Each dict contains the extracted critical fields structure
    
    Returns:
        Tuple of (cluster_info_dict, template_list, object_to_cluster)
    """
    try:
        from drain3 import TemplateMiner
        from drain3.template_miner_config import TemplateMinerConfig
    except ImportError:
        print("Error: drain3 library not installed. Please install it using: pip install drain3")
        raise
    
    # Configure Drain3 - create config programmatically
    config = TemplateMinerConfig()
    config.sim_th = 0.3  # Lower threshold for key-value pairs
    config.depth = 4
    config.max_children = 100
    config.profiling_enabled = False
    
    # Set masking patterns
    config.masking = [
        {"regex_pattern": r"(?<=:\s).+", "mask_with": "VALUE"},  # Mask all values after ": "
        {"regex_pattern": r"\d+", "mask_with": "NUM"},
        {"regex_pattern": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "mask_with": "UUID"},
        {"regex_pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "mask_with": "TIMESTAMP"},
    ]
    
    # Create miner with config
    miner = TemplateMiner(config=config)
    
    # Flatten each object's critical fields to string
    object_strings = []
    for critical_fields_data in critical_fields_list:
        flattened = flatten_critical_fields_to_string(critical_fields_data)
        object_strings.append(flattened)
    
    # Process each object string
    cluster_sizes = {}
    cluster_templates = {}
    object_to_cluster = {}  # Map object index to cluster_id
    
    for idx, obj_string in enumerate(object_strings):
        if not obj_string.strip():
            continue
        
        # Add to Drain3
        result = miner.add_log_message(obj_string)
        cluster_id = result.get("cluster_id")
        
        if cluster_id:
            object_to_cluster[idx] = cluster_id
    
    # Get all clusters with their templates
    clusters = miner.drain.clusters
    if not isinstance(clusters, dict):
        clusters = {cid: cluster for cid, cluster in enumerate(clusters)} if hasattr(clusters, '__iter__') else {}
    
    # Build cluster information
    template_list = []
    for cluster_id, cluster in clusters.items():
        if hasattr(cluster, 'get_template') and hasattr(cluster, 'size'):
            cluster_sizes[cluster_id] = cluster.size
            template = cluster.get_template()
            cluster_templates[cluster_id] = template
            template_list.append({
                'id': cluster_id,
                'template': template,
                'size': cluster.size
            })
        else:
            # Alternative access method
            try:
                size = cluster.size if hasattr(cluster, 'size') else 1
                template = cluster.get_template() if hasattr(cluster, 'get_template') else str(cluster)
                cluster_sizes[cluster_id] = size
                cluster_templates[cluster_id] = template
                template_list.append({
                    'id': cluster_id,
                    'template': template,
                    'size': size
                })
            except (AttributeError, TypeError) as e:
                if not _is_quiet():
                    print(f"[ML YAML] Fallback for cluster {cluster_id}: {e}")
                cluster_sizes[cluster_id] = 1
                template = f"cluster_{cluster_id}"
                cluster_templates[cluster_id] = template
                template_list.append({
                    'id': cluster_id,
                    'template': template,
                    'size': 1
                })
    
    return cluster_sizes, template_list, object_to_cluster


def extract_key_value_pairs_from_critical_fields(critical_fields_data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Extract flat list of (key_path, value) pairs from critical fields structure.
    No line numbers - only paths and values.
    
    Args:
        critical_fields_data: Dictionary containing critical fields
    
    Returns:
        List of (key_path, value) tuples
    """
    kv_pairs = []
    
    def extract_pairs(obj: Any, prefix: str = ""):
        if isinstance(obj, dict):
            #  Check if semantic unit
            if _is_semantic_unit(obj):
                combined = _combine_semantic_fields(obj)
                if combined:
                    kv_pairs.append((prefix, combined))
                return  # Don't recurse
            
            # Normal processing
            for key, value in obj.items():
                if key == "_line_numbers" or key.endswith("_line_numbers"):
                    continue
                
                current_path = f"{prefix}.{key}" if prefix else key
                
                if isinstance(value, dict):
                    extract_pairs(value, current_path)
                elif isinstance(value, list):
                    for idx, item in enumerate(value):
                        if isinstance(item, dict):
                            extract_pairs(item, f"{current_path}[{idx}]")
                        else:
                            kv_pairs.append((f"{current_path}[{idx}]", str(item)))
                else:
                    kv_pairs.append((current_path, str(value)))
    
    extract_pairs(critical_fields_data)
    return kv_pairs


def detect_verbose_error(key: str, value: str) -> bool:
    """
    Detect if a key-value pair indicates an error condition.
    Uses generic linguistic patterns to detect positive vs negative contexts.
    
    Args:
        key: The key path (e.g., "status.conditions.type")
        value: The value
    
    Returns:
        True if appears to be an error condition
    """
    key_lower = key.lower()
    value_lower = str(value).lower()
    combined = f"{key_lower} {value_lower}"

    # Exclude known label/annotation patterns that contain error-like words but aren't errors
    # Use patterns from config
    excluded_key_patterns = EXCLUDED_KEY_PATTERNS
    
    for excluded_pattern in excluded_key_patterns:
        if excluded_pattern in key_lower:
            return False  # Not an error, just a label/annotation name

    # Handle combined semantic values (e.g., "Degraded=False")
    if '=' in value_lower:
        # This is a combined field like "Degraded=False" or "Available=True"
        # Split by the FIRST '=' only (in case message contains '=')
        parts = value_lower.split('=', 1)
        if len(parts) == 2:
            field_name, field_value = parts[0].strip(), parts[1].strip()
            
            # Extract just the boolean part if there's extra context
            # e.g., "false (reason=xyz)" → "false"
            if '(' in field_value:
                field_value = field_value.split('(')[0].strip()
            
            # Now check for error conditions based on field_name + field_value
            
            # 1. Degraded=True → ERROR
            if field_name == 'degraded':
                if field_value == 'true':
                    return True  # Error condition
                elif field_value == 'false':
                    return False  # Healthy condition
            
            # 2. Available=False → ERROR
            if field_name == 'available':
                if field_value == 'false':
                    return True  # Error condition
                elif field_value == 'true':
                    return False  # Healthy condition
            
            # 3. Ready=False → ERROR
            if field_name == 'ready':
                if field_value == 'false':
                    return True  # Error condition
                elif field_value == 'true':
                    return False  # Healthy condition
            
            # 4. Healthy=False → ERROR
            if field_name == 'healthy':
                if field_value == 'false':
                    return True  # Error condition
                elif field_value == 'true':
                    return False  # Healthy condition
            
            # 5. Progressing=True → MAYBE error (depends on context)
            if field_name == 'progressing':
                if field_value == 'true':
                    # Check if there's error context in the message/reason
                    if 'error' in value_lower or 'failed' in value_lower or 'unable' in value_lower:
                        return True  # Error condition
                    # Otherwise, progressing is normal
                    return False
                elif field_value == 'false':
                    return False  # Not progressing is usually normal
            
            # 6. Failing=True → ERROR
            if field_name == 'failing':
                if field_value == 'true':
                    return True  # Error condition
                elif field_value == 'false':
                    return False  # Healthy condition
            
            # 7. Upgradeable=False → MAYBE error (but often normal)
            if field_name == 'upgradeable':
                # Upgradeable=False is often normal during updates
                # Only flag as error if there's explicit error context
                if field_value == 'false' and ('error' in value_lower or 'failed' in value_lower):
                    return True
                return False  # Usually not an error
            
            # If we couldn't determine from the combined value, fall through to existing checks
    
    # Generic positive status words
    positive_status_words = ['deployed', 'available', 'ready', 'healthy', 'running', 'active', 
                            'operational', 'functioning', 'working', 'completed', 'finished', 
                            'successful', 'successfully', 'done', 'replicas', 'replica']
    
    # Generic negative status words
    negative_status_words = ['unstarted', 'pending', 'waiting', 'stuck', 'hung', 'broken', 
                             'degraded', 'unhealthy', 'unavailable', 'down', 'halted', 
                             'stopped', 'paused', 'suspended', 'blocked']
    
    # Negation words
    negation_words = ['no', 'not', 'none', 'without', 'lack']
    
    # Positive action verbs
    positive_verbs = ['is', 'are', 'has', 'have', 'was', 'were']
    
    # Check for explicit errors first
    explicit_error_keywords = ['error', 'failed', 'failure', 'exception', 'critical', 'fatal']
    for keyword in explicit_error_keywords:
        if keyword in combined:
            return True
    
    # Check for positive status indicators with positive verbs
    words = value_lower.split()
    for i in range(len(words) - 1):
        if words[i] in positive_verbs and any(pos_word in words[i+1] for pos_word in positive_status_words):
            if i > 0 and words[i-1] in ['not', 'no']:
                continue  # "is not deployed" = error
            return False  # "is deployed" = positive, not an error
    
    # Check for negation + negative status word pattern
    for i in range(len(words) - 1):
        if words[i] in negation_words and any(neg_word in words[i+1] for neg_word in negative_status_words):
            return False
    
    # Check for "all" + positive status
    for i in range(len(words) - 1):
        if words[i] == 'all' and any(pos_word in words[i+1] for pos_word in positive_status_words):
            return False
    
    # Generic error patterns
    error_patterns = [
        'not progressing', 'not available', 'not ready', 'not healthy',
        'unable to reach', 'cannot connect', 'connection refused', 'connection failed',
        'out of memory', 'out of disk', 'resource exhausted', 'quota exceeded',
        'timeout', 'timed out', 'expired',
        'missing', 'not found', 'not exist', 'does not exist',
        'denied', 'forbidden', 'unauthorized', 'access denied', 'permission denied',
        'rejected', 'not allowed',
        'retry failed', 'retries exhausted', 'max retries',
    ]
    
    # Check for error patterns
    for pattern in error_patterns:
        if pattern in value_lower:
            return True
    
    # Check for negative status words
    # BUT: Skip if value is in "key=value" format (already handled above)
    if '=' not in value_lower:  # Only check if NOT combined format
        for neg_word in negative_status_words:
            if neg_word in value_lower:
                words_list = value_lower.split()
                neg_index = -1
                for idx, word in enumerate(words_list):
                    if neg_word in word:
                        neg_index = idx
                        break
                if neg_index > 0 and words_list[neg_index - 1] in negation_words:
                    continue  # Negated, so it's positive
                return True  # Not negated, so it's an error
    
    # Check for status keys with negative values
    # NOTE: "Status: False" and "Status: True" are common patterns and should NOT be treated as errors
    # They are normal state indicators, not error conditions
    status_keys = ['status', 'progressing', 'available', 'ready', 'healthy', 'condition']
    if any(status_key in key_lower for status_key in status_keys):
        # "Status: True" is a positive indicator - never an error
        if 'true' in value_lower or '1' in value_lower:
            return False  # "Status: True" is always positive, not an error
        
        # "Status: False" or "status: false" is a common pattern (e.g., "Progressing: False" means not progressing, which is normal)
        # Only treat as error if combined with explicit error indicators
        negative_values = ['false', '0', 'none', 'null']
        if any(neg_val in value_lower for neg_val in negative_values):
            # Check if this is just a status indicator without error context
            # "Status: False" alone is not an error - it's a normal state
            # Only treat as error if there are additional error indicators
            if 'degraded' in value_lower or 'error' in value_lower or 'failed' in value_lower:
                return True
            # "Status: False" without error context is NOT an error - return False
            return False
        
        # "degraded" status is still an error indicator
        if 'degraded' in value_lower:
            if 'no' in value_lower:
                words_list = value_lower.split()
                for i in range(len(words_list) - 1):
                    if words_list[i] == 'no' and any(neg_word in words_list[i+1] for neg_word in negative_status_words):
                        return False  # "no degraded" = positive
            return True
    
    # Check for message/reason fields with error indicators
    if 'message' in key_lower or 'reason' in key_lower:
        error_indicators = ['unable', 'cannot', 'failed', 'error', 'issue', 'problem',
                           'not working', 'not functioning', 'not responding']
        if any(indicator in value_lower for indicator in error_indicators):
            return True
    
    return False


def detect_config_change(key: str, value: str) -> bool:
    """
    Detect if a key-value pair indicates a configuration change.
    
    PRINCIPLE: Only flag changes to DESIRED STATE (spec, config, data)
               NOT changes to OBSERVED STATE (status, metadata)
    
    Args:
        key: The key path (e.g., "spec.image", "metadata.resourceVersion")
        value: The value
    
    Returns:
        True if appears to indicate a configuration change
    """
    key_lower = key.lower()
    value_lower = str(value).lower()

    # UNIVERSAL RULE: Config changes MUST be in user-controlled sections
    # - spec.*        = Desired state (Deployments, StatefulSets, etc.)
    # - config.*      = Configuration objects
    # - data.*        = ConfigMap/Secret data
    # 
    # NOT in:
    # - metadata.*    = Kubernetes housekeeping (resourceVersion, uid, etc.)
    # - status.*      = Observed state (not desired state)
    
    # Extract the first section of the key path
    path_parts = key_lower.split('.')
    if len(path_parts) > 0:
        first_section = path_parts[0]
        
        # EXCLUDE: metadata and status sections entirely
        if first_section in ['metadata', 'status']:
            return False  # Housekeeping/observed state, not config
        
        # ONLY check for config changes in spec/config/data sections
        if first_section not in ['spec', 'config', 'data']:
            return False  # Not a recognized config section
    
    # Now check for config change indicators within spec/config/data sections
    
    # Version/image changes (most common config changes)
    if 'version' in key_lower or 'image' in key_lower:
        return True
    
    # Resource scaling and limits
    if any(indicator in key_lower for indicator in ['replicas', 'limits', 'requests', 'resources']):
        return True
    
    # Environment variables, volumes, and mounts
    if any(indicator in key_lower for indicator in ['env', 'volume', 'mount', 'secret', 'configmap']):
        return True
    
    # Check if value contains change action verbs (e.g., "updated to version X")
    change_verbs = ['update', 'change', 'modify', 'set', 'configure', 'adjust',
                   'alter', 'edit', 'replace', 'switch', 'toggle', 'enable', 'disable']
    
    if '=' not in value_lower:  # Skip semantic values like "Available=True"
        words = value_lower.split()
        
        for i in range(len(words)):
            word = words[i]
            
            # Check if word contains a change verb
            matched_verb = None
            for verb in change_verbs:
                if verb in word:
                    matched_verb = verb
                    break
            
            if matched_verb:
                # Check for action context patterns
                if i > 0 and words[i-1] in ['was', 'were', 'has', 'have', 'is', 'are', 'being', 'been']:
                    return True  # e.g., "was updated", "has been changed"
                
                if i > 0 and words[i-1] == 'to':
                    return True  # e.g., "updated to version 4.11"
                
                if i < len(words) - 1 and words[i+1] in ['to', 'from', 'with', 'version', 'image']:
                    return True  # e.g., "changed to", "updated version"
    
    return False

def analyze_verbose_error_patterns(critical_fields_list: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Analyze all objects to find verbose error patterns and their frequencies.
    
    Args:
        critical_fields_list: List of critical fields dictionaries (one per object)
    
    Returns:
        Dictionary mapping verbose error patterns to their occurrence count
    """
    pattern_counts = {}
    
    for critical_fields_data in critical_fields_list:
        kv_pairs = extract_key_value_pairs_from_critical_fields(critical_fields_data)
        object_patterns = set()
        
        for key_path, value in kv_pairs:
            if detect_verbose_error(key_path, value):
                key_lower = key_path.lower()
                value_lower = str(value).lower()
                combined = f"{key_lower} {value_lower}"
                
                # Use patterns from config instead of hardcoded list
                verbose_error_patterns = VERBOSE_ERROR_PATTERNS
                
                # Find matching pattern
                matched_pattern = None

                # If value is in "key=value" format, extract the actual error part
                actual_value_for_matching = value_lower
                if '=' in value_lower:
                    parts = value_lower.split('=', 1)
                    if len(parts) == 2:
                        value_part = parts[1].strip()
                        if '(' in value_part:
                            actual_value_for_matching = value_part.split('(', 1)[1].rstrip(')')
                        else:
                            actual_value_for_matching = ""
                
                for pattern in verbose_error_patterns:
                    search_string = f"{key_lower} {actual_value_for_matching}"
                    if pattern in search_string:
                        matched_pattern = pattern
                        break
                
                # Check for explicit error keywords if no pattern matched yet
                if not matched_pattern:
                    explicit_errors = EXPLICIT_ERROR_KEYWORDS
                    for err in explicit_errors:
                        # Check in combined string (includes both key and value)
                        if err in combined:
                            matched_pattern = err
                            break

                # Also check for status keys with negative values
                if not matched_pattern:
                    status_keys = ['status', 'progressing', 'available', 'ready', 'healthy', 'condition']
                    negative_values = ['no', '0', 'none', 'null', 'unknown']
                    
                    # "Status: False" is a common pattern, not an error - exclude it
                    if any(status_key in key_lower for status_key in status_keys):
                        if any(neg_val in value_lower for neg_val in negative_values):
                            matched_pattern = f"{key_lower}:{value_lower}"
                        # Only treat "false" as error if combined with other error indicators
                        elif 'false' in value_lower:
                            if 'error' in combined or 'failed' in combined:
                                matched_pattern = f"{key_lower}:{value_lower}_error"
                            # Otherwise, "Status: False" is normal - don't create error pattern
                
                # Also check for explicit error keywords
                if not matched_pattern:
                    explicit_errors = ['error', 'failed', 'failure', 'exception', 'critical', 'fatal']
                    for err in explicit_errors:
                        if err in combined:
                            matched_pattern = err
                            break
                
                # Use a simplified pattern if no specific match
                if not matched_pattern:
                    # "Status: False" is a common pattern, not an error - don't mark as verbose error
                    # Only mark as error if combined with other error indicators
                    if 'false' in value_lower and any(sk in key_lower for sk in ['status', 'progressing', 'available']):
                        # Check if there are additional error indicators
                        if 'error' in combined or 'failed' in combined:
                            matched_pattern = f"status_false_error"
                        else:
                            # "Status: False" alone is not an error pattern - skip it
                            continue  # Don't add this as a verbose error pattern
                    elif 'unknown' in value_lower:
                        matched_pattern = 'unknown'
                    else:
                        matched_pattern = 'other_verbose'
                
                object_patterns.add(matched_pattern)
        
        # Count each pattern once per object
        for pattern in object_patterns:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
    
    return pattern_counts


def classify_objects(
    critical_fields_list: List[Dict[str, Any]],
    cluster_sizes: Dict,
    template_list: List[Dict],
    object_to_cluster: Dict[int, int],
    frequency_threshold: float = 0.05
) -> Tuple[List[Dict], Dict[str, int], Dict[str, int]]:
    """
    Classify each object as 'Majority Error', 'Majority', 'CONFIG', or 'Error' based on frequency and patterns.
    
    Args:
        critical_fields_list: List of critical fields dictionaries (one per object)
        cluster_sizes: Dictionary of cluster_id -> size
        template_list: List of template dictionaries
        object_to_cluster: Map of object index to cluster_id
        frequency_threshold: Threshold for majority (default 5% of total)
    
    Returns:
        Tuple of (classifications, common_patterns, rare_patterns)
    """
    if not cluster_sizes or not critical_fields_list:
        return [], {}, {}
    
    total_objects = len(critical_fields_list)
    total_clustered = sum(cluster_sizes.values())
    
    # Step 1: Analyze verbose error patterns
    pattern_counts = analyze_verbose_error_patterns(critical_fields_list)
    
    # Determine threshold for common patterns (from config)
    common_threshold_pct = _ERROR_CONFIG.get("classification", {}).get("common_pattern_threshold", 0.30)
    common_pattern_threshold = max(3, int(total_objects * common_threshold_pct))
    common_patterns = {pattern: count for pattern, count in pattern_counts.items() 
                      if count >= common_pattern_threshold}
    rare_patterns = {pattern: count for pattern, count in pattern_counts.items() 
                    if count < common_pattern_threshold}
    
    if not _is_quiet():
        print(f"\nVerbose Error Pattern Analysis:")
        print(f"  Total objects analyzed: {total_objects}")
        print(f"  Common pattern threshold: {common_pattern_threshold} objects")
        print(f"  Common negative patterns (-> Majority Error): {len(common_patterns)}")
        if common_patterns:
            print(f"    Examples: {', '.join(list(common_patterns.keys())[:5])}")
        print(f"  Rare patterns (-> Error): {len(rare_patterns)}")
        if rare_patterns:
            print(f"    Examples: {', '.join(list(rare_patterns.keys())[:5])}")
        
    # Calculate frequency for each cluster
    cluster_frequencies = {}
    for cluster_id, size in cluster_sizes.items():
        frequency = size / total_clustered if total_clustered > 0 else 0
        cluster_frequencies[cluster_id] = frequency
    
    # Determine majority threshold
    if cluster_frequencies:
        frequencies = list(cluster_frequencies.values())
        median_freq = sorted(frequencies)[len(frequencies) // 2] if frequencies else 0
        majority_threshold = max(frequency_threshold, median_freq * 2)
    else:
        majority_threshold = frequency_threshold
       
    # Get thresholds from config (with fallbacks)
    classification_config = _ERROR_CONFIG.get("classification", {})
    error_threshold = classification_config.get("error_threshold", 0.01)
    # majority_threshold can be overridden if needed
    config_majority_threshold = classification_config.get("majority_threshold", 0.10)
    # Use the dynamic majority_threshold calculated above, but can be adjusted by config
    
    # Helper function to get verbose patterns in an object
    def get_verbose_patterns_in_object(critical_fields_data):
        """Get verbose error patterns found in an object."""
        patterns = set()
        kv_pairs = extract_key_value_pairs_from_critical_fields(critical_fields_data)
        
        for key_path, value in kv_pairs:
            if detect_verbose_error(key_path, value):
                key_lower = key_path.lower()
                value_lower = str(value).lower()
                combined = f"{key_lower} {value_lower}"
                
                # Use the SAME pattern matching logic as analyze_verbose_error_patterns
                verbose_error_patterns = VERBOSE_ERROR_PATTERNS
                
                matched_pattern = None

                # If value is in "key=value" format, extract the actual error part
                actual_value_for_matching = value_lower
                if '=' in value_lower:
                    # For "Degraded=False (message=...)", we want to check the message part, not "degraded"
                    # Split by '=' and only check after the first boolean value
                    parts = value_lower.split('=', 1)
                    if len(parts) == 2:
                        # Extract just the value part: "false (message=xyz)" 
                        value_part = parts[1].strip()
                        # If there's a parenthesis (extra info), check that
                        if '(' in value_part:
                            actual_value_for_matching = value_part.split('(', 1)[1].rstrip(')')
                        else:
                            # Just the boolean value - skip pattern matching
                            # (already handled by detect_verbose_error)
                            actual_value_for_matching = ""
                
                                # Check verbose_error_patterns FIRST (same order as analyze_verbose_error_patterns)
                for pattern in verbose_error_patterns:
                    search_string = f"{key_lower} {actual_value_for_matching}"
                    if pattern in search_string:
                        matched_pattern = pattern
                        break
                
                # Check explicit errors SECOND if no pattern matched yet
                if not matched_pattern:
                    explicit_errors = EXPLICIT_ERROR_KEYWORDS
                    for err in explicit_errors:
                        # Check in combined string (includes both key and value)
                        if err in combined:
                            matched_pattern = err
                            break
                
                # If still no match, check for other patterns (continue with existing code)
                if not matched_pattern:
                    # "Status: False" is a common pattern, not an error - don't mark as verbose error
                    # Only mark as error if combined with other error indicators
                    if 'false' in value_lower and any(sk in key_lower for sk in ['status', 'progressing', 'available']):
                        # Check if there are additional error indicators
                        if 'error' in combined or 'failed' in combined:
                            matched_pattern = f"status_false_error"
                        else:
                            # "Status: False" alone is not an error pattern - skip it
                            continue  # Don't add this as a verbose error pattern
                    elif 'unknown' in value_lower:
                        matched_pattern = 'unknown'
                    else:
                        matched_pattern = 'other_verbose'
                
                patterns.add(matched_pattern)
        
        return patterns
    
    # Helper function to check for positive indicators
    def has_positive_indicators(critical_fields_data):
        """Check if object has positive/healthy status indicators."""
        kv_pairs = extract_key_value_pairs_from_critical_fields(critical_fields_data)

        # Check for "FieldName=True" format first
        # This handles combined semantic values like "Available=True", "Ready=True"
        for key, value in kv_pairs:
                value_lower = str(value).lower()
        
                # Check if value is in "fieldname=status" format
                if '=' in value_lower:
                    parts = value_lower.split('=', 1)
                    if len(parts) == 2:
                        field_name = parts[0].strip()
                        field_value = parts[1].split()[0] if ' ' in parts[1] else parts[1]  # Take first word before any extra text
                
                        # Positive field names with True status
                        positive_field_names = ['available', 'ready', 'healthy', 'running', 'active', 
                                            'deployed', 'operational', 'functioning', 'working',
                                            'successful', 'completed', 'succeeded', 'accepted', 'established']
                
                        # Negative field names with False status
                        negative_field_names = ['degraded', 'failed', 'error', 'failing', 'unhealthy',
                                            'unavailable', 'notready', 'broken', 'stuck', 'blocked',
                                            'progressing']
                
                        # Check patterns:
                        # "Available=True" or "Ready=True" → Positive
                        if any(pos in field_name for pos in positive_field_names) and field_value == 'true':
                            return True
                
                        # "Degraded=False" or "Failed=False" → Positive (absence of problem)
                        if any(neg in field_name for neg in negative_field_names) and field_value == 'false':
                            return True
        # Check for verb+adjective patterns (keep this as fallback)
        value_lower_combined = " ".join([str(value).lower() for _, value in kv_pairs])
    
        positive_status_words = ['deployed', 'available', 'ready', 'healthy', 'running', 'active', 
                                'operational', 'functioning', 'working', 'completed', 'finished', 
                                'successful', 'successfully', 'done']
        positive_verbs = ['is', 'are', 'has', 'have', 'was', 'were']
    
        words = value_lower_combined.split()
        for i in range(len(words) - 1):
            if words[i] in positive_verbs and any(pos_word in words[i+1] for pos_word in positive_status_words):
                if i > 0 and words[i-1] in ['not', 'no']:
                    continue
                return True
    
        for i in range(len(words) - 1):
            if words[i] == 'all' and any(pos_word in words[i+1] for pos_word in positive_status_words):
                return True
    
        return False
    
    # Classify each object
    classifications = []
    for idx, critical_fields_data in enumerate(critical_fields_list):
        cluster_id = object_to_cluster.get(idx)
        
        # Extract key-value pairs for this object
        kv_pairs = extract_key_value_pairs_from_critical_fields(critical_fields_data)
        
        # Check if object contains configuration changes
        has_config_change = any(detect_config_change(key, value) for key, value in kv_pairs)
        
        # Check verbose error patterns
        object_verbose_patterns = get_verbose_patterns_in_object(critical_fields_data)
        has_common_negative = any(pattern in common_patterns for pattern in object_verbose_patterns)
        has_rare_negative = any(pattern in rare_patterns for pattern in object_verbose_patterns)
        
        # Check for positive indicators
        has_positive = has_positive_indicators(critical_fields_data)

        # Check if object has meaningful status conditions
        # If no conditions exist and no error patterns, treat as config/metadata object (Majority)
        has_status_conditions = any('condition' in key.lower() for key, _ in kv_pairs)
        has_any_errors = bool(object_verbose_patterns)  # Has any error patterns detected
        
        if cluster_id is None:
            # Not clustered
            if has_rare_negative:
                classification = "Error"
            elif has_common_negative:
                classification = "Majority Error"
            elif has_config_change:
                classification = "CONFIG"
            elif has_positive:
                classification = "Majority"
            else:
                if has_any_errors:  
                    classification = "Error"
                else:
                    classification = "Majority"  # Unique but healthy
            frequency = 0.0
            template = "UNCLUSTERED"
            cluster_size = 0
        else:
            frequency = cluster_frequencies.get(cluster_id, 0.0)
            cluster_size = cluster_sizes.get(cluster_id, 0)
            
            # Find template
            template = None
            for tmpl in template_list:
                if tmpl['id'] == cluster_id:
                    template = tmpl['template']
                    break
            
            # Classify based on frequency, config detection, and verbose error detection
            # Priority: Rare Negative (Error) > Common Negative (Majority Error) > CONFIG > Majority (frequency/positive) > Error > Other
            if has_rare_negative:
                # Rare negative pattern = Error (highest priority)
                classification = "Error"
            elif has_common_negative:
                # Common negative patterns (high frequency) = Majority Error
                classification = "Majority Error"
            elif has_config_change:
                # Configuration change detected = CONFIG
                classification = "CONFIG"
            elif has_positive or (frequency >= majority_threshold or cluster_size >= (total_objects * majority_threshold)):
                # Normal/healthy logs or high frequency = Majority
                classification = "Majority"
            elif not has_status_conditions and not has_any_errors:
                # Object has no status conditions and no errors = config/metadata object
                classification = "Majority"
            elif frequency <= error_threshold:
                if has_any_errors:
                    classification = "Error"
                else:
                    classification = "Majority"
            else:
                classification = "Majority"  # Default to Majority for medium frequency
        
        # Generate reason for classification (pass kv_pairs for detailed reasons)
        reason = get_classification_reason(
            classification, 
            object_verbose_patterns, 
            common_patterns, 
            rare_patterns,
            frequency,
            cluster_size,
            has_config_change,
            has_positive,
            kv_pairs
        )
        
        classifications.append({
            'object_index': idx,
            'critical_fields': critical_fields_data,
            'classification': classification,
            'frequency': frequency,
            'cluster_id': cluster_id,
            'cluster_size': cluster_size,
            'template': template or "UNCLUSTERED",
            'num_key_value_pairs': len(kv_pairs),
            'verbose_patterns': list(object_verbose_patterns),
            'has_config_change': has_config_change,
            'reason': reason
        })
    
    return classifications, common_patterns, rare_patterns


def get_classification_reason(
    classification: str,
    verbose_patterns: List[str],
    common_patterns: Dict[str, int] = None,
    rare_patterns: Dict[str, int] = None,
    frequency: float = 0.0,
    cluster_size: int = 0,
    has_config_change: bool = False,
    has_positive: bool = False,
    kv_pairs: List[Tuple[str, str]] = None
) -> str:
    """
    Get the reason for a classification. Matches the logic from cluster_yaml_with_drain3.py.
    
    Args:
        classification: The classification result
        verbose_patterns: List of verbose error patterns found
        common_patterns: Dictionary of common patterns
        rare_patterns: Dictionary of rare patterns
        frequency: Cluster frequency
        cluster_size: Cluster size
        has_config_change: Whether config changes were detected
        has_positive: Whether positive indicators were found
        kv_pairs: List of (key, value) pairs for detailed reason generation
    
    Returns:
        String describing the reason for classification
    """
    if classification == "Error":
        # Check if it's an error due to rare verbose patterns
        if verbose_patterns:
            rare_found = [p for p in verbose_patterns if rare_patterns and p in rare_patterns]
            if rare_found:
                # Show all rare patterns found, not just first 3
                patterns_str = ', '.join(rare_found)
                return f"Rare patterns (anomaly): {patterns_str}"
        
        # Other error reasons
        if cluster_size == 0:
            return "Not clustered / unique pattern"
        elif frequency <= 0.01:
            return f"Very low frequency ({frequency:.2%})"
        else:
            return "Rare/unique pattern"
    
    elif classification == "Majority Error":
        reasons = []
        if verbose_patterns:
            common_found = [p for p in verbose_patterns if common_patterns and p in common_patterns]
            if common_found:
                # Format: "Common verbose patterns: pattern1, pattern2, pattern3"
                patterns_str = ', '.join(common_found[:3])
                reasons.append(f"Common verbose patterns: {patterns_str}")
        
        if frequency > 0:
            reasons.append(f"High frequency ({frequency:.2%})")
        elif cluster_size > 1:
            reasons.append(f"Cluster size: {cluster_size}")
        
        if reasons:
            return "; ".join(reasons)
        return "Common negative pattern (high frequency)"
    
    elif classification == "Majority":
        reasons = []
        if frequency > 0:
            reasons.append(f"High frequency ({frequency:.2%})")
        elif cluster_size > 1:
            reasons.append(f"Cluster size: {cluster_size}")
        
        # Check if it has positive indicators (using kv_pairs if available)
        if has_positive:
            reasons.append("Normal/healthy status indicators")
        elif kv_pairs:
            # Re-check positive indicators from kv_pairs
            value_lower_combined = " ".join([str(value).lower() for _, value in kv_pairs])
            words = value_lower_combined.split()
            positive_verbs = ['is', 'are', 'has', 'have']
            positive_words = ['deployed', 'available', 'ready', 'healthy', 'running', 'active']
            for i in range(len(words) - 1):
                if words[i] in positive_verbs and any(pw in words[i+1] for pw in positive_words):
                    if i == 0 or words[i-1] not in ['not', 'no']:
                        reasons.append("Normal/healthy status indicators")
                        break
        
        if reasons:
            return "; ".join(reasons)
        return "High frequency pattern (normal/healthy)"
    
    elif classification == "CONFIG":
        # Find which keys indicate config changes
        config_change_keys = []
        if kv_pairs:
            for key, value in kv_pairs:
                if detect_config_change(key, value):
                    config_change_keys.append(key)
        if config_change_keys:
            return f"Configuration change detected in: {', '.join(config_change_keys[:3])}"
        return "Configuration change detected (updated/modified/set)"
    
    else:  # Other
        return f"Medium frequency ({frequency:.2%})"


def classify_critical_fields(critical_fields_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Main function to classify objects based on their critical fields.
    
    Args:
        critical_fields_list: List of critical fields dictionaries (one per object)
                            Each dict contains extracted critical fields (no line numbers)
    
    Returns:
        Dict with keys:
        - results: List of classification dicts, one per object/chunk.
          Each result contains: object_index, classification, frequency,
          cluster_id, cluster_size, template, verbose_patterns,
          has_config_change, reason.
        - error: None on success, error message string on failure.
    """
    # Input validation
    if not isinstance(critical_fields_list, list):
        return {"results": [], "error": f"Input must be a list, got {type(critical_fields_list).__name__}"}

    if not critical_fields_list:
        return {"results": [], "error": None}

    valid_items = []
    for i, item in enumerate(critical_fields_list):
        if isinstance(item, dict):
            valid_items.append(item)
        else:
            if not _is_quiet():
                print(f"[ML YAML] Skipping non-dict item at index {i}: {type(item).__name__}")
    if not valid_items:
        return {"results": [], "error": "No valid dict items in input list"}

    if not _is_quiet():
        print("Starting ML classification of critical fields...")
        print(f"Processing {len(valid_items)} objects\n")

    # Step 1: Drain3 Clustering
    if not _is_quiet():
        print("Processing with Drain3...")
    try:
        cluster_sizes, template_list, object_to_cluster = process_objects_with_drain3(valid_items)
        if not _is_quiet():
            print(f"Found {len(template_list)} unique clusters")
    except ImportError as e:
        msg = f"drain3 not installed: {e}"
        if not _is_quiet():
            print(f"[ML YAML] {msg}")
        return {"results": [], "error": msg}
    except Exception as e:
        msg = f"Drain3 processing failed: {e}"
        if not _is_quiet():
            print(f"[ML YAML] {msg}")
            import traceback
            traceback.print_exc()
        return {"results": [], "error": msg}
    
    # Step 2: Classify objects
    if not _is_quiet():
        print("\nClassifying objects...")
    classifications, common_patterns, rare_patterns = classify_objects(
        valid_items,
        cluster_sizes,
        template_list,
        object_to_cluster
    )
    
    # Build clean result list
    results = []
    for classification in classifications:
        results.append({
            'object_index': classification['object_index'],
            'classification': classification['classification'],
            'frequency': classification['frequency'],
            'cluster_id': classification['cluster_id'],
            'cluster_size': classification['cluster_size'],
            'template': classification['template'],
            'verbose_patterns': classification['verbose_patterns'],
            'has_config_change': classification['has_config_change'],
            'reason': classification['reason']
        })
    
    return {"results": results, "error": None}
