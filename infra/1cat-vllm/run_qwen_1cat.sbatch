#!/usr/bin/env bash
#SBATCH --job-name=qwen-1cat-vllm
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --account=summer-school
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --signal=B:SIGTERM@60

set -euo pipefail

# ==============================================================================
# 1Cat-vLLM Slurm Serving Script for Qwen on Tesla V100 (SM70)
# ==============================================================================

PROJECT_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p "$PROJECT_DIR/logs"

# Environment / Execution Mode Configuration
USE_APPTAINER="${USE_APPTAINER:-0}"
APPTAINER_IMAGE="${APPTAINER_IMAGE:-/home/ducledinh/dev/container/1cat-vllm.sif}"
CONDA_ENV="${CONDA_ENV:-1cat-vllm-sm70}"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"

# Model & Serving Parameters
MODEL_PATH="${MODEL_PATH:-/home/ducledinh/dev/models/Qwen3.5-9B-AWQ-INT4}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen3.5-9b}"
PORT="${PORT:-8000}"
TP="${TP:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
API_KEY="${API_KEY:-dacn-qwen-secret-key}"
TOKENIZER="${TOKENIZER:-}"

# Volta V100 Stability & Performance Settings
export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0
export NCCL_P2P_DISABLE=1

# Clean shutdown handler
ENDPOINT_FILE="$PROJECT_DIR/logs/endpoint-$SLURM_JOB_ID.json"
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Shutdown signal received. Terminating vLLM server..."
    rm -f "$ENDPOINT_FILE"
    if [[ -n "${SERVER_PID:-}" ]]; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server stopped cleanly."
}
trap cleanup SIGTERM SIGINT EXIT

# Check model path
if [ ! -e "$MODEL_PATH" ] && [ ! -d "$MODEL_PATH" ]; then
    echo "=========================================================="
    echo "ERROR: Model not found at: $MODEL_PATH"
    echo "Please download the model first using download_model.sh:"
    echo "  ./download_model.sh /home/ducledinh/dev/models"
    echo "=========================================================="
    exit 1
fi

NODE_HOSTNAME=$(hostname)

echo "=========================================================="
echo " Starting 1Cat-vLLM Service (Volta V100 / SM70)"
echo " Job ID            : ${SLURM_JOB_ID:-local}"
echo " Compute Node      : $NODE_HOSTNAME"
echo " Model Path        : $MODEL_PATH"
echo " Model Alias       : $MODEL_ALIAS"
echo " Tensor Parallel   : $TP"
echo " Max Context Len   : $MAX_MODEL_LEN"
echo " Port              : $PORT"
echo " Internal Endpoint : http://${NODE_HOSTNAME}:${PORT}/v1"
echo "=========================================================="

# Save endpoint metadata for automated client discovery / tunneling
cat <<EOF > "$ENDPOINT_FILE"
{
  "job_id": "${SLURM_JOB_ID:-local}",
  "node": "$NODE_HOSTNAME",
  "port": $PORT,
  "model": "$MODEL_ALIAS",
  "model_path": "$MODEL_PATH",
  "api_base": "http://${NODE_HOSTNAME}:${PORT}/v1",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# Build command line arguments for vLLM
EXTRA_ARGS=()

# Detect AWQ / Quantization
if [[ "$MODEL_PATH" =~ [Aa][Ww][Qq] ]]; then
    EXTRA_ARGS+=(--quantization awq)
fi

# GGUF tokenizer handling
if [[ "$MODEL_PATH" == *.gguf* ]] && [[ -n "$TOKENIZER" ]]; then
    EXTRA_ARGS+=(--tokenizer "$TOKENIZER")
fi

# Mode A: Run with Apptainer Container
if [ "$USE_APPTAINER" = "1" ]; then
    if [ ! -f "$APPTAINER_IMAGE" ]; then
        echo "ERROR: Apptainer image not found at $APPTAINER_IMAGE"
        exit 1
    fi
    echo "[*] Launching via Apptainer image: $APPTAINER_IMAGE..."
    
    apptainer exec --nv --cleanenv \
        --bind "$MODEL_PATH:/model:ro" \
        "$APPTAINER_IMAGE" \
        vllm serve /model \
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
            "${EXTRA_ARGS[@]}" &
    
    SERVER_PID=$!
    wait "$SERVER_PID"

# Mode B: Run with Conda Environment
else
    if command -v conda &> /dev/null; then
        eval "$(conda shell.bash hook)"
    elif [ -f "$CONDA_DIR/etc/profile.d/conda.sh" ]; then
        source "$CONDA_DIR/etc/profile.d/conda.sh"
    fi
    
    conda activate "$CONDA_ENV"
    
    echo "[*] Launching via Conda environment: $CONDA_ENV..."
    
    vllm serve "$MODEL_PATH" \
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
        "${EXTRA_ARGS[@]}" &
    
    SERVER_PID=$!
    wait "$SERVER_PID"
fi
