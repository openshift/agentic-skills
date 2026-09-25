#!/usr/bin/env bash
set -o errexit
set -o pipefail

# -----------------------------------------------------------------------
# discover.sh — Scan a directory tree for Argo CD, Kubernetes, and
# Kustomize resources.  Uses ONLY awk (no yq dependency).
#
# Output: JSON inventory of resources grouped by kind and directory.
# -----------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR=""
EXCLUDE_DIRS=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Scan a directory for Argo CD and Kubernetes resources.

Options:
  -d <dir>    Root directory to scan (required)
  -e <dir>    Comma-separated directories to exclude (relative to root)
  -h          Show this help message

Output:
  JSON object with argoResources, kubernetesResources, and kustomizeOverlays
  grouped by kind and by directory.

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
# is_excluded — check if a path matches an excluded directory
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

# -----------------------------------------------------------------------
# is_terraform_dir — check if a directory contains .tf files
# -----------------------------------------------------------------------
is_terraform_dir() {
  local dir="$1"
  ls "$dir"/*.tf >/dev/null 2>&1
}

# -----------------------------------------------------------------------
# is_helm_chart_dir — check if a directory contains Chart.yaml
# -----------------------------------------------------------------------
is_helm_chart_dir() {
  local dir="$1"
  [[ -f "$dir/Chart.yaml" || -f "$dir/Chart.yml" ]]
}

# -----------------------------------------------------------------------
# find_yaml_files — collect YAML files, respecting .gitignore and exclusions
# -----------------------------------------------------------------------
find_yaml_files() {
  local root="$1"
  local files=()

  # Use git ls-files if inside a git repo to respect .gitignore
  if git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    while IFS= read -r f; do
      [[ -n "$f" ]] && files+=("$root/$f")
    done < <(git -C "$root" ls-files --cached --others --exclude-standard '*.yaml' '*.yml' 2>/dev/null)
  else
    while IFS= read -r f; do
      [[ -n "$f" ]] && files+=("$f")
    done < <(find "$root" -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null)
  fi

  # Filter out excluded, terraform, and helm chart directories
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
# Main: scan files and classify resources using awk
# -----------------------------------------------------------------------

# Collect YAML files
YAML_FILES=()
while IFS= read -r f; do
  [[ -n "$f" ]] && YAML_FILES+=("$f")
done < <(find_yaml_files "$ROOT_DIR")

if [[ ${#YAML_FILES[@]} -eq 0 ]]; then
  cat <<'EMPTY'
{
  "argoResources": {
    "byKind": {},
    "byDirectory": {}
  },
  "kubernetesResources": {
    "byKind": {},
    "byDirectory": {}
  },
  "kustomizeOverlays": {
    "byDirectory": {}
  }
}
EMPTY
  exit 0
fi

# Process all YAML files through a single awk invocation.
# awk handles multi-document YAML (--- separators) and extracts
# apiVersion + kind pairs, then categorises them.

printf '%s\n' "${YAML_FILES[@]}" | while IFS= read -r f; do
  # Prepend a file marker so awk knows which file it's reading
  echo "###FILE###${f}"
  cat "$f"
done | awk -v root="$ROOT_DIR" '
BEGIN {
  current_file = ""
  api = ""
  kind = ""
}

# Track current file from our marker lines
/^###FILE###/ {
  # Flush previous document
  if (api != "" && kind != "") {
    classify(current_file, api, kind)
  }
  current_file = substr($0, 11)
  api = ""
  kind = ""
  next
}

# YAML document separator — flush current document
/^---/ {
  if (api != "" && kind != "") {
    classify(current_file, api, kind)
  }
  api = ""
  kind = ""
  next
}

# Extract apiVersion (handle quoted and unquoted values)
/^apiVersion:/ {
  val = $0
  sub(/^apiVersion:[ \t]*/, "", val)
  gsub(/["'"'"']/, "", val)
  gsub(/[ \t\r]+$/, "", val)
  api = val
}

# Extract kind
/^kind:/ {
  val = $0
  sub(/^kind:[ \t]*/, "", val)
  gsub(/["'"'"']/, "", val)
  gsub(/[ \t\r]+$/, "", val)
  kind = val
}

function classify(file, apiVersion, k,    rel, dir, n) {
  # Compute relative directory
  rel = file
  n = length(root)
  if (substr(rel, 1, n) == root) {
    rel = substr(rel, n + 2)  # +2 to skip trailing /
  }
  dir = rel
  gsub(/\/[^\/]+$/, "", dir)
  if (dir == rel) dir = "."

  if (apiVersion ~ /argoproj\.io/) {
    argo_kind[k]++
    argo_dir[dir]++
  } else if (apiVersion ~ /kustomize\.config\.k8s\.io/) {
    kustomize_dir[dir]++
  } else if (apiVersion != "" && k != "") {
    k8s_kind[k]++
    k8s_dir[dir]++
  }
}

END {
  # Flush last document
  if (api != "" && kind != "") {
    classify(current_file, api, kind)
  }

  # Output JSON
  printf "{\n"

  # argoResources
  printf "  \"argoResources\": {\n"
  printf "    \"byKind\": {"
  sep = ""
  for (k in argo_kind) {
    printf "%s\"%s\": %d", sep, k, argo_kind[k]
    sep = ", "
  }
  printf "},\n"
  printf "    \"byDirectory\": {"
  sep = ""
  for (d in argo_dir) {
    printf "%s\"%s\": %d", sep, d, argo_dir[d]
    sep = ", "
  }
  printf "}\n"
  printf "  },\n"

  # kubernetesResources
  printf "  \"kubernetesResources\": {\n"
  printf "    \"byKind\": {"
  sep = ""
  for (k in k8s_kind) {
    printf "%s\"%s\": %d", sep, k, k8s_kind[k]
    sep = ", "
  }
  printf "},\n"
  printf "    \"byDirectory\": {"
  sep = ""
  for (d in k8s_dir) {
    printf "%s\"%s\": %d", sep, d, k8s_dir[d]
    sep = ", "
  }
  printf "}\n"
  printf "  },\n"

  # kustomizeOverlays
  printf "  \"kustomizeOverlays\": {\n"
  printf "    \"byDirectory\": {"
  sep = ""
  for (d in kustomize_dir) {
    printf "%s\"%s\": %d", sep, d, kustomize_dir[d]
    sep = ", "
  }
  printf "}\n"
  printf "  }\n"

  printf "}\n"
}
'
