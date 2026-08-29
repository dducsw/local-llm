#!/usr/bin/env bash
# ==============================================================================
# Interactive / Local Launcher for 1Cat-vLLM (Tesla V100 / SM70)
# Supports running via:
#   1. Apptainer Sandbox Directory (build/1cat_vllm_sandbox)
#   2. Apptainer SIF Image (build/1cat-vllm.sif)
#   3. Local Conda Environment (1cat-vllm-sm70)
# ==============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_MODEL="$ROOT/../models/Qwen3.5-9B-AWQ"
if [ ! -d "$DEFAULT_MODEL" ] && [ -d "$HOME/dev/models/Qwen3.5-9B-AWQ" ]; then
    DEFAULT_MODEL="$HOME/dev/models/Qwen3.5-9B-AWQ"
fi

MODEL_PATH="${1:-$DEFAULT_MODEL}"
PORT="${PORT:-8000}"
TP="${TP:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen3.5-9b}"
API_KEY="${API_KEY:-dacn-qwen-secret-key}"
CONDA_ENV="${CONDA_ENV:-1cat-vllm-sm70}"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"

# Auto-detect container runtime if available
CONTAINER_TARGET=""
if [ -d "$ROOT/build/1cat_vllm_sandbox" ]; then
    CONTAINER_TARGET="$ROOT/build/1cat_vllm_sandbox"
elif [ -f "$ROOT/build/1cat-vllm.sif" ]; then
    CONTAINER_TARGET="$ROOT/build/1cat-vllm.sif"
elif [ -f "$HOME/dev/container/1cat-vllm.sif" ]; then
    CONTAINER_TARGET="$HOME/dev/container/1cat-vllm.sif"
fi

echo "=========================================================="
echo " 1Cat-vLLM Local Server Launch"
echo " Model Path      : $MODEL_PATH"
echo " Model Alias     : $MODEL_ALIAS"
echo " Port            : $PORT"
echo " Max Context Len : $MAX_MODEL_LEN"
echo " Backend         : FLASH_ATTN_V100 (SM70 TurboMind)"
if [ -n "$CONTAINER_TARGET" ]; then
    echo " Runtime         : Apptainer ($CONTAINER_TARGET)"
else
    echo " Runtime         : Conda ($CONDA_ENV)"
fi
echo "=========================================================="

# Volta SM70 stability settings
export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0
export NCCL_P2P_DISABLE=1

EXTRA_ARGS=()
if [[ "$MODEL_PATH" =~ [Aa][Ww][Qq] ]]; then
    EXTRA_ARGS+=(--quantization awq)
fi

# Run via Apptainer if container is found
if [ -n "$CONTAINER_TARGET" ]; then
    CACHE_ROOT="${SCRATCH:-$HOME/.cache}/llm-serving"
    mkdir -p "$CACHE_ROOT"
    
    BIND_ARGS=("--bind" "$CACHE_ROOT:/cache")
    if [ -d "$MODEL_PATH" ] || [ -f "$MODEL_PATH" ]; then
        MODEL_DIR="$(cd "$(dirname "$MODEL_PATH")" && pwd)"
        MODEL_BASE="$(basename "$MODEL_PATH")"
        BIND_ARGS+=("--bind" "$MODEL_DIR:/models:ro")
        SERVE_TARGET="/models/$MODEL_BASE"
    else
        SERVE_TARGET="$MODEL_PATH"
    fi

    exec apptainer run --nv --cleanenv \
        "${BIND_ARGS[@]}" \
        "$CONTAINER_TARGET" \
        serve "$SERVE_TARGET" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --dtype float16 \
        --attention-backend FLASH_ATTN_V100 \
        --tensor-parallel-size "$TP" \
        --gpu-memory-utilization "$GPU_MEM_UTIL" \
        --max-model-len "$MAX_MODEL_LEN" \
        --served-model-name "$MODEL_ALIAS" \
        --api-key "$API_KEY" \
        --trust-remote-code \
        "${EXTRA_ARGS[@]}"

# Run via Conda fallback
else
    if command -v conda &> /dev/null; then
        eval "$(conda shell.bash hook)"
    elif [ -f "$CONDA_DIR/etc/profile.d/conda.sh" ]; then
        source "$CONDA_DIR/etc/profile.d/conda.sh"
    fi

    conda activate "$CONDA_ENV"

    exec vllm serve "$MODEL_PATH" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --dtype float16 \
        --attention-backend FLASH_ATTN_V100 \
        --tensor-parallel-size "$TP" \
        --gpu-memory-utilization "$GPU_MEM_UTIL" \
        --max-model-len "$MAX_MODEL_LEN" \
        --served-model-name "$MODEL_ALIAS" \
        --api-key "$API_KEY" \
        --trust-remote-code \
        "${EXTRA_ARGS[@]}"
fi
