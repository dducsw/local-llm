#!/usr/bin/env bash
# ==============================================================================
# Interactive / Local Launcher for 1Cat-vLLM (Tesla V100 / SM70)
# ==============================================================================

set -euo pipefail

MODEL_PATH="${1:-/home/ducledinh/dev/models/Qwen3.5-9B-AWQ-INT4}"
PORT="${PORT:-8000}"
TP="${TP:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen3.5-9b}"
API_KEY="${API_KEY:-dacn-qwen-secret-key}"
CONDA_ENV="${CONDA_ENV:-1cat-vllm-sm70}"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"

echo "=========================================================="
echo " 1Cat-vLLM Local Server Launch"
echo " Model Path      : $MODEL_PATH"
echo " Model Alias     : $MODEL_ALIAS"
echo " Port            : $PORT"
echo " Max Context Len : $MAX_MODEL_LEN"
echo " Backend         : FLASH_ATTN_V100 (SM70 TurboMind)"
echo "=========================================================="

# Activate Conda environment
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook)"
elif [ -f "$CONDA_DIR/etc/profile.d/conda.sh" ]; then
    source "$CONDA_DIR/etc/profile.d/conda.sh"
fi

conda activate "$CONDA_ENV"

# Volta SM70 stability settings
export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0
export NCCL_P2P_DISABLE=1

EXTRA_ARGS=()
if [[ "$MODEL_PATH" =~ [Aa][Ww][Qq] ]]; then
    EXTRA_ARGS+=(--quantization awq)
fi

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
