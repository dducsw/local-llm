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
USE_APPTAINER="${USE_APPTAINER:-1}"
DEFAULT_IMAGE="$PROJECT_DIR/build/1cat-vllm.sif"
if [ ! -f "$DEFAULT_IMAGE" ] && [ -f "$HOME/dev/container/1cat-vllm.sif" ]; then
    DEFAULT_IMAGE="$HOME/dev/container/1cat-vllm.sif"
fi
APPTAINER_IMAGE="${APPTAINER_IMAGE:-$DEFAULT_IMAGE}"
CONDA_ENV="${CONDA_ENV:-1cat-vllm-sm70}"
CONDA_DIR="${CONDA_DIR:-$HOME/miniconda3}"
CACHE_DIR="${SCRATCH:-$HOME/.cache}/llm-serving"

# Model & Serving Parameters
DEFAULT_MODEL="$PROJECT_DIR/../../models/Qwen3.5-9B-AWQ"
if [ ! -d "$DEFAULT_MODEL" ] && [ -d "$PROJECT_DIR/../models/Qwen3.5-9B-AWQ" ]; then
    DEFAULT_MODEL="$PROJECT_DIR/../models/Qwen3.5-9B-AWQ"
elif [ ! -d "$DEFAULT_MODEL" ] && [ -d "$HOME/dev/models/Qwen3.5-9B-AWQ" ]; then
    DEFAULT_MODEL="$HOME/dev/models/Qwen3.5-9B-AWQ"
fi
MODEL_PATH="${MODEL_PATH:-$DEFAULT_MODEL}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen3.5-9b}"
PORT="${PORT:-8000}"
TP="${TP:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
API_KEY="${API_KEY:-dacn-qwen-3.5-9b-secret-key}"
TOKENIZER="${TOKENIZER:-}"

# Remote Headnode & Tunnel Configuration (for app/scripts/ssh-tunnel.sh & app/config/models.json)
HEADNODE_IP="${HEADNODE_IP:-10.1.1.239}"
TUNNEL_REMOTE_PORT="${TUNNEL_REMOTE_PORT:-18000}"

# Volta V100 Stability & Performance Settings
export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0
export NCCL_P2P_DISABLE=1
# export VLLM_1CAT_ENABLE_SM70_MTP_DEFAULTS=1


mkdir -p "$PROJECT_DIR/logs" "$CACHE_DIR"/{huggingface,vllm,xdg,models}

# Check model path
if [ ! -e "$MODEL_PATH" ] && [ ! -d "$MODEL_PATH" ]; then
    echo "=========================================================="
    echo "ERROR: Model not found at: $MODEL_PATH"
    echo "Please download the model first using download_awq_model.sh:"
    echo "  ./download_awq_model.sh $HOME/dev/models"
    echo "=========================================================="
    exit 1
fi

NODE_HOSTNAME=$(hostname)

echo "=========================================================="
echo " Starting 1Cat-vLLM Service (Volta V100 / SM70)"
echo " Job ID            : ${SLURM_JOB_ID:-local}"
echo " Compute Node      : $NODE_HOSTNAME (NVIDIA V100)"
echo " Model Path        : $MODEL_PATH"
echo " Model Alias       : $MODEL_ALIAS"
echo " Tensor Parallel   : $TP"
echo " Max Context Len   : $MAX_MODEL_LEN"
echo " Port              : $PORT"
echo " Internal Endpoint : http://${NODE_HOSTNAME}:${PORT}/v1"
echo " Headnode Tunnel   : http://${HEADNODE_IP}:${TUNNEL_REMOTE_PORT}/v1"
echo "=========================================================="

# Save endpoint metadata for automated client discovery / tunneling
ENDPOINT_FILE="$PROJECT_DIR/logs/endpoint-${SLURM_JOB_ID:-local}.json"
cat <<EOF > "$ENDPOINT_FILE"
{
  "job_id": "${SLURM_JOB_ID:-local}",
  "node": "$NODE_HOSTNAME",
  "port": $PORT,
  "headnode_ip": "$HEADNODE_IP",
  "tunnel_port": $TUNNEL_REMOTE_PORT,
  "model": "$MODEL_ALIAS",
  "model_path": "$MODEL_PATH",
  "endpoint": "http://${NODE_HOSTNAME}:${PORT}/v1",
  "headnode_endpoint": "http://${HEADNODE_IP}:${TUNNEL_REMOTE_PORT}/v1",
  "api_key": "$API_KEY",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# Resilient Reverse SSH Tunnel: Wait for server to be ready before establishing tunnel
echo "Starting reverse SSH tunnel keep-alive loop: $NODE_HOSTNAME:$PORT -> $HEADNODE_IP:$TUNNEL_REMOTE_PORT..."
(
    # Wait until vLLM is healthy before opening the reverse tunnel to prevent 502 Bad Gateway
    echo "[Tunnel Worker] Waiting for vLLM server to become healthy on port $PORT..."
    while ! curl -s -f "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; do
        sleep 3
    done
    echo "[Tunnel Worker] vLLM server is healthy! Opening reverse SSH tunnel..."

    while true; do
        ssh -N \
            -o StrictHostKeyChecking=no \
            -o ConnectTimeout=5 \
            -o ServerAliveInterval=15 \
            -o ServerAliveCountMax=3 \
            -o ExitOnForwardFailure=yes \
            -R "${TUNNEL_REMOTE_PORT}:127.0.0.1:${PORT}" \
            "$HEADNODE_IP" || true
        sleep 2
    done
) &
TUNNEL_LOOP_PID=$!


# Clean shutdown handler
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Shutdown signal received. Terminating vLLM server and tunnel..."
    rm -f "$ENDPOINT_FILE"
    kill -TERM "$TUNNEL_LOOP_PID" 2>/dev/null || true
    pkill -P "$TUNNEL_LOOP_PID" 2>/dev/null || true
    if [[ -n "${SERVER_PID:-}" ]]; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Clean shutdown complete."
}
trap cleanup EXIT SIGTERM SIGINT

# Build command line arguments for vLLM
MTP_TOKENS="${ENABLE_MTP_TOKENS:-2}"
SPEC_CONFIG="{\"num_speculative_tokens\": ${MTP_TOKENS}, \"attention_backend\": \"FLASH_ATTN_V100\", \"draft_sample_method\": \"probabilistic\"}"

EXTRA_ARGS=(
    --enable-prefix-caching
    --enable-chunked-prefill
    --reasoning-parser qwen3
    --limit-mm-per-prompt '{"image":0,"video":0}'
    # MTP speculative decoding: 2-token draft (lower overhead than 4 on V100 SM70)
    # Set ENABLE_MTP_TOKENS=0 in env to disable speculative decoding
    # --spec-method mtp
    # --speculative-config "$SPEC_CONFIG"
)

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
    
    apptainer run --nv --cleanenv \
        --env VLLM_USE_V1=0,NVIDIA_TF32_OVERRIDE=0,NCCL_P2P_DISABLE=1 \
        --bind "$CACHE_DIR:/cache" \
        --bind "$MODEL_PATH:/model:ro" \
        "$APPTAINER_IMAGE" \
        serve /model \
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

