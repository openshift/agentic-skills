#!/bin/bash
# Run evals against live container servers — one per provider.
# Usage: bash evals/run.sh [pytest args...]
#
# Starts a container per provider, waits for /health, runs evals, then tears down.
# Providers without credentials are automatically skipped by pytest.

set -euo pipefail

IMAGE="${IMAGE:-lightspeed-agentic-sandbox:latest}"
RUNTIME="${CONTAINER_RUNTIME:-$(command -v podman 2>/dev/null || command -v docker 2>/dev/null || true)}"
BASE_PORT="${EVAL_BASE_PORT:-18080}"
HEALTH_TIMEOUT="${EVAL_HEALTH_TIMEOUT:-60}"
EVAL_ARGS=("$@")

if [ -z "$RUNTIME" ]; then
    echo "Error: no container runtime found. Install podman or docker."
    exit 1
fi

GCLOUD_ADC="${GOOGLE_APPLICATION_CREDENTIALS:-$HOME/.config/gcloud/application_default_credentials.json}"
GCLOUD_MOUNT_ARGS=()
if [ -f "$GCLOUD_ADC" ]; then
    GCLOUD_MOUNT_ARGS=(-v "$GCLOUD_ADC:/tmp/gcloud-adc.json:ro,Z" -e "GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcloud-adc.json")
fi

# Available providers: claude gemini openai deepagents-claude deepagents-gemini deepagents-openai
IFS=',' read -ra PROVIDERS <<< "${EVAL_PROVIDERS:-claude}"

CONTAINERS=()
WORKDIRS=()
OUTDIRS=()

cleanup() {
    for i in "${!PROVIDERS[@]}"; do
        name="${PROVIDERS[$i]}"
        outdir="$(pwd)/.eval-workspaces/output-${name}"
        $RUNTIME logs "eval-${name}" > "${outdir}/container.log" 2>&1 || true
        $RUNTIME stop "eval-${name}" 2>/dev/null || true
        $RUNTIME rm -f "eval-${name}" 2>/dev/null || true
    done
    for d in "${WORKDIRS[@]}"; do
        rm -rf "$d" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Map provider names to LIGHTSPEED_AGENT_PROVIDER values
provider_env() {
    case "$1" in
        deepagents-claude|deepagents-gemini|deepagents-openai) echo "deepagents" ;;
        *) echo "$1" ;;
    esac
}

# Map provider names to model env var overrides
model_env() {
    case "$1" in
        claude)            echo "-e ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-claude-sonnet-4-6}" ;;
        gemini)            echo "-e GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.1-pro-preview}" ;;
        openai)            echo "-e OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.4}" ;;
        deepagents-claude) echo "-e DEEPAGENTS_MODEL=${DEEPAGENTS_MODEL:-claude-opus-4-6}" ;;
        deepagents-gemini) echo "-e DEEPAGENTS_MODEL=${DEEPAGENTS_GEMINI_MODEL:-gemini-3.1-pro-preview}" ;;
        deepagents-openai) echo "-e DEEPAGENTS_MODEL=${DEEPAGENTS_OPENAI_MODEL:-gpt-5.4}" ;;
    esac
}

echo "Starting provider containers..."

mkdir -p "$(pwd)/.eval-workspaces"

# Materialize workspace once, share across providers via hardlinks.
# Skills are symlinked under evals/workspace/skills/ — run.sh dereferences
# them (cp -rL) and copies the real files into the container workspace.
SHARED_WORKSPACE=$(mktemp -d "$(pwd)/.eval-workspaces/shared-XXXXXX")
mkdir -p "$SHARED_WORKSPACE/skills"
if [ -d "$(pwd)/evals/workspace/skills" ]; then
    cp -rL "$(pwd)/evals/workspace/skills/"* "$SHARED_WORKSPACE/skills/"
fi

for i in "${!PROVIDERS[@]}"; do
    name="${PROVIDERS[$i]}"
    port=$((BASE_PORT + i))
    agent_provider=$(provider_env "$name")
    workdir=$(mktemp -d "$(pwd)/.eval-workspaces/eval-${name}-XXXXXX")
    outdir="$(pwd)/.eval-workspaces/output-${name}"
    mkdir -p "$outdir"
    WORKDIRS+=("$workdir")
    OUTDIRS+=("$outdir")
    cp -al "$SHARED_WORKSPACE/skills" "$workdir/skills"
    mkdir -p "$workdir/.claude"
    ln -s ../skills "$workdir/.claude/skills"
    chmod -R 777 "$workdir" "$outdir"

    cid=$($RUNTIME run -d --rm \
        --name "eval-${name}" \
        -p "${port}:8080" \
        -v "${workdir}:/app/workspace:Z" \
        -v "${outdir}:/app/eval-output:Z" \
        -e EVAL_OUTPUT_DIR="/app/eval-output" \
        -e PYTHONPATH="/app/src:/opt/app-root/lib64/python3.12/site-packages" \
        "${GCLOUD_MOUNT_ARGS[@]}" \
        -e LIGHTSPEED_AGENT_PROVIDER="$agent_provider" \
        -e LIGHTSPEED_SKILLS_DIR="/app/workspace" \
        -e ANTHROPIC_API_KEY \
        -e CLAUDE_CODE_USE_VERTEX \
        -e ANTHROPIC_VERTEX_PROJECT_ID \
        -e CLOUD_ML_REGION \
        -e GOOGLE_API_KEY \
        -e GEMINI_API_KEY \
        -e OPENAI_API_KEY \
        -e OPENAI_BASE_URL \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_REGION \
        $(model_env "$name") \
        "$IMAGE")

    CONTAINERS+=("$cid")
    echo "  ${name}: port ${port} (container ${cid:0:12})"
done

# Wait for all servers to be healthy (parallel)
echo "Waiting for servers..."
WAIT_PIDS=()
for i in "${!PROVIDERS[@]}"; do
    name="${PROVIDERS[$i]}"
    port=$((BASE_PORT + i))
    (
        for attempt in $(seq 1 "$HEALTH_TIMEOUT"); do
            if curl -sf "http://localhost:${port}/health" > /dev/null 2>&1; then
                echo "  ${name}: ready"
                exit 0
            fi
            sleep 1
        done
        echo "  ${name}: FAILED to start (timeout after ${HEALTH_TIMEOUT}s)"
        $RUNTIME logs "eval-${name}" 2>&1 | tail -10
        exit 1
    ) &
    WAIT_PIDS+=($!)
done
for pid in "${WAIT_PIDS[@]}"; do
    wait "$pid" || exit 1
done

# Build server URL + workdir maps as env vars for pytest
SERVER_URLS=""
WORKSPACE_MAP=""
for i in "${!PROVIDERS[@]}"; do
    name="${PROVIDERS[$i]}"
    port=$((BASE_PORT + i))
    SERVER_URLS="${SERVER_URLS}${name}=http://localhost:${port},"
    WORKSPACE_MAP="${WORKSPACE_MAP}${name}=${OUTDIRS[$i]},"
done

echo ""
echo "Running evals..."
PYTEST="${PYTEST:-python3 -m pytest}"

export EVAL_SERVER_URLS="$SERVER_URLS"
export EVAL_WORKSPACES="$WORKSPACE_MAP"
$PYTEST evals/ -v "${EVAL_ARGS[@]}"
