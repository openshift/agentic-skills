#!/usr/bin/env bash
set -o errexit
set -o pipefail

# -----------------------------------------------------------------------
# validate.sh — Validate YAML syntax, Kubernetes schemas, and Kustomize
# overlays in an Argo CD GitOps repository.
#
# Prerequisites: yq >= 4.50, kustomize >= 5.8, kubeconform >= 0.7
# -----------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ASSETS_SCHEMAS_DIR="$SKILL_DIR/assets/schemas"
ROOT_DIR=""
EXCLUDE_DIRS=""
ERROR_COUNT=0
WARN_COUNT=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Validate YAML files in an Argo CD GitOps repository.

Options:
  -d <dir>    Root directory to validate (required)
  -e <dir>    Comma-separated directories to exclude (relative to root)
  -h          Show this help message

Validation passes:
  1. YAML syntax check (yq)
  2. Kubernetes schema validation (kubeconform + Argo CRD schemas)
  3. Kustomize overlay builds (kustomize build | kubeconform)

Prerequisites:
  yq          >= 4.50    https://github.com/mikefarah/yq
  kustomize   >= 5.8     https://github.com/kubernetes-sigs/kustomize
  kubeconform >= 0.7     https://github.com/yannh/kubeconform

Example:
  $(basename "$0") -d /path/to/gitops-repo
  $(basename "$0") -d . -e vendor,tmp
EOF
  exit 0
}

while getopts ":d:e:h" opt; do
  case $opt in
    d) ROOT_DIR="$OPTARG" ;;
    e) EXCLUDE_DIRS="$OPTARG" ;;
    h) usage ;;
    \?) echo "Error: Unknown option -$OPTARG" >&2; exit 1 ;;
    :) echo "Error: Option -$OPTARG requires an argument" >&2; exit 1 ;;
  esac
done

if [[ -z "$ROOT_DIR" ]]; then
  echo "Error: -d <dir> is required" >&2
  exit 1
fi

ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"

if [[ ! -d "$ROOT_DIR" ]]; then
  echo "Error: $ROOT_DIR is not a directory" >&2
  exit 1
fi

# -----------------------------------------------------------------------
# Check prerequisites
# -----------------------------------------------------------------------
check_prereqs() {
  local missing=()

  if ! command -v yq >/dev/null 2>&1; then
    missing+=("yq (>= 4.50)")
  fi
  if ! command -v kustomize >/dev/null 2>&1; then
    missing+=("kustomize (>= 5.8)")
  fi
  if ! command -v kubeconform >/dev/null 2>&1; then
    missing+=("kubeconform (>= 0.7)")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: Missing required tools:" >&2
    for tool in "${missing[@]}"; do
      echo "  - $tool" >&2
    done
    echo "" >&2
    echo "Install via: brew bundle --file=Brewfile" >&2
    exit 1
  fi
}

check_prereqs

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------
is_excluded() {
  local path="$1"
  if [[ -z "$EXCLUDE_DIRS" ]]; then
    return 1
  fi
  IFS=',' read -ra dirs <<< "$EXCLUDE_DIRS"
  for d in "${dirs[@]}"; do
    d="${d#/}"
    d="${d%/}"
    if [[ "$path" == *"/$d/"* || "$path" == *"/$d" || "$path" == "$d/"* || "$path" == "$d" ]]; then
      return 0
    fi
  done
  return 1
}

is_terraform_dir() {
  local dir="$1"
  ls "$dir"/*.tf >/dev/null 2>&1
}

is_helm_chart_dir() {
  local dir="$1"
  [[ -f "$dir/Chart.yaml" || -f "$dir/Chart.yml" ]]
}

is_sops_encrypted() {
  local file="$1"
  grep -q "sops:" "$file" 2>/dev/null && grep -q "encrypted_regex\|lastmodified\|mac:\|pgp:\|azure_kv:\|gcp_kms:\|hc_vault:" "$file" 2>/dev/null
}

rel_path() {
  local file="$1"
  echo "${file#$ROOT_DIR/}"
}

# -----------------------------------------------------------------------
# Collect YAML files
# -----------------------------------------------------------------------
find_yaml_files() {
  local root="$1"
  local files=()

  if git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    while IFS= read -r f; do
      [[ -n "$f" ]] && files+=("$root/$f")
    done < <(git -C "$root" ls-files --cached --others --exclude-standard '*.yaml' '*.yml' 2>/dev/null)
  else
    while IFS= read -r f; do
      [[ -n "$f" ]] && files+=("$f")
    done < <(find "$root" -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null)
  fi

  for f in "${files[@]}"; do
    local rel="${f#$root/}"
    local dir
    dir="$(dirname "$f")"

    if is_excluded "$rel"; then
      continue
    fi
    if is_terraform_dir "$dir"; then
      continue
    fi
    if is_helm_chart_dir "$dir"; then
      continue
    fi

    echo "$f"
  done
}

# -----------------------------------------------------------------------
# Find kustomization.yaml files for overlay builds
# -----------------------------------------------------------------------
find_kustomize_dirs() {
  local root="$1"

  if git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$root" ls-files --cached --others --exclude-standard 2>/dev/null | \
      grep -E '(^|/)kustomization\.(yaml|yml)$' | while IFS= read -r f; do
        local dir
        dir="$(dirname "$root/$f")"
        local rel="${dir#$root/}"
        if ! is_excluded "$rel" && ! is_terraform_dir "$dir" && ! is_helm_chart_dir "$dir"; then
          echo "$dir"
        fi
      done
  else
    find "$root" -type f \( -name 'kustomization.yaml' -o -name 'kustomization.yml' \) 2>/dev/null | while IFS= read -r f; do
      local dir
      dir="$(dirname "$f")"
      local rel="${dir#$root/}"
      if ! is_excluded "$rel" && ! is_terraform_dir "$dir" && ! is_helm_chart_dir "$dir"; then
        echo "$dir"
      fi
    done
  fi
}

# -----------------------------------------------------------------------
# Pass 1: YAML Syntax Validation
# -----------------------------------------------------------------------
pass_yaml_syntax() {
  echo "=== Pass 1: YAML Syntax Validation ==="
  local count=0
  local errors=0

  while IFS= read -r f; do
    count=$((count + 1))

    # Skip SOPS-encrypted files
    if is_sops_encrypted "$f"; then
      echo "  SKIP (sops): $(rel_path "$f")"
      continue
    fi

    if ! yq e 'true' "$f" >/dev/null 2>&1; then
      echo "  FAIL: $(rel_path "$f")"
      errors=$((errors + 1))
      ERROR_COUNT=$((ERROR_COUNT + 1))
    fi
  done < <(find_yaml_files "$ROOT_DIR")

  echo "  Checked $count files, $errors errors"
  echo ""
}

# -----------------------------------------------------------------------
# Pass 2: Kubernetes Schema Validation
# -----------------------------------------------------------------------
pass_k8s_schema() {
  echo "=== Pass 2: Kubernetes Schema Validation ==="

  local schema_args=("-skip=Secret" "-strict" "-ignore-missing-schemas" "-schema-location" "default" "-verbose")

  # Add Argo CRD schemas if available
  if [[ -d "$ASSETS_SCHEMAS_DIR" ]] && ls "$ASSETS_SCHEMAS_DIR"/*.json >/dev/null 2>&1; then
    schema_args+=("-schema-location" "$ASSETS_SCHEMAS_DIR/{{.ResourceKind}}{{.KindSuffix}}.json")
    echo "  Using Argo CRD schemas from: $ASSETS_SCHEMAS_DIR"
  else
    echo "  WARNING: No Argo CRD schemas found at $ASSETS_SCHEMAS_DIR"
    echo "  Run 'make download-schemas' to download them"
    WARN_COUNT=$((WARN_COUNT + 1))
  fi

  local count=0
  local errors=0
  local tmpfile
  tmpfile="$(mktemp)"
  trap "rm -f '$tmpfile'" EXIT

  # Collect non-SOPS YAML files
  while IFS= read -r f; do
    if is_sops_encrypted "$f"; then
      continue
    fi
    echo "$f"
    count=$((count + 1))
  done < <(find_yaml_files "$ROOT_DIR") > "$tmpfile"

  if [[ $count -eq 0 ]]; then
    echo "  No files to validate"
    echo ""
    return
  fi

  # Run kubeconform on all files
  local output
  output="$(cat "$tmpfile" | xargs kubeconform "${schema_args[@]}" 2>&1)" || true

  # Parse output for errors
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then
      continue
    fi

    # kubeconform verbose output format: <file> - <Kind> <name> is <status>
    if echo "$line" | grep -q "is invalid"; then
      local rel
      rel="$(echo "$line" | sed "s|$ROOT_DIR/||")"
      echo "  FAIL: $rel"
      errors=$((errors + 1))
      ERROR_COUNT=$((ERROR_COUNT + 1))
    elif echo "$line" | grep -q "is valid"; then
      : # valid, skip
    elif echo "$line" | grep -q "skipped"; then
      local rel
      rel="$(echo "$line" | sed "s|$ROOT_DIR/||")"
      echo "  SKIP: $rel"
    else
      # Other output (error details)
      echo "  $line"
    fi
  done <<< "$output"

  echo "  Checked $count files, $errors errors"
  echo ""
}

# -----------------------------------------------------------------------
# Pass 3: Kustomize Overlay Builds
# -----------------------------------------------------------------------
pass_kustomize_builds() {
  echo "=== Pass 3: Kustomize Overlay Builds ==="

  local schema_args=("-skip=Secret" "-strict" "-ignore-missing-schemas" "-schema-location" "default" "-verbose")
  if [[ -d "$ASSETS_SCHEMAS_DIR" ]] && ls "$ASSETS_SCHEMAS_DIR"/*.json >/dev/null 2>&1; then
    schema_args+=("-schema-location" "$ASSETS_SCHEMAS_DIR/{{.ResourceKind}}{{.KindSuffix}}.json")
  fi

  local count=0
  local errors=0

  while IFS= read -r dir; do
    [[ -z "$dir" ]] && continue
    count=$((count + 1))
    local rel="${dir#$ROOT_DIR/}"

    # Try to build the overlay
    local build_output
    if ! build_output="$(kustomize build "$dir" 2>&1)"; then
      echo "  FAIL (build): $rel"
      echo "    $(echo "$build_output" | head -3)"
      errors=$((errors + 1))
      ERROR_COUNT=$((ERROR_COUNT + 1))
      continue
    fi

    # Validate the built output
    local validate_output
    validate_output="$(echo "$build_output" | kubeconform "${schema_args[@]}" 2>&1)" || true

    local has_error=false
    while IFS= read -r line; do
      if echo "$line" | grep -q "is invalid"; then
        echo "  FAIL (schema): $rel — $line"
        has_error=true
      fi
    done <<< "$validate_output"

    if $has_error; then
      errors=$((errors + 1))
      ERROR_COUNT=$((ERROR_COUNT + 1))
    else
      echo "  OK: $rel"
    fi
  done < <(find_kustomize_dirs "$ROOT_DIR")

  echo "  Checked $count overlays, $errors errors"
  echo ""
}

# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
echo "Validating: $ROOT_DIR"
echo ""

pass_yaml_syntax
pass_k8s_schema
pass_kustomize_builds

echo "=== Summary ==="
echo "  Errors:   $ERROR_COUNT"
echo "  Warnings: $WARN_COUNT"

if [[ $ERROR_COUNT -gt 0 ]]; then
  echo ""
  echo "Validation FAILED with $ERROR_COUNT error(s)"
  exit 1
else
  echo ""
  echo "Validation PASSED"
  exit 0
fi
