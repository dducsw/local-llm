#!/usr/bin/env bash
#SBATCH --job-name=qwen3.5-server
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --account=summer-school
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=4:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

set -euo pipefail

# ==========================================
# ENVIRONMENT VARIABLES & PARAMETERS CONFIGURATION
# ==========================================
PROJECT_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
CACHE_DIR="${SCRATCH:-$HOME/.cache}/llm-serving"

# Model and image path resolution with dynamic fallbacks
DEFAULT_IMAGE="${HOME}/dev/container/llama-server-cuda.sif"
if [ ! -f "$DEFAULT_IMAGE" ] && [ -f "$PROJECT_DIR/../build/llama-server-cuda.sif" ]; then
    DEFAULT_IMAGE="$PROJECT_DIR/../build/llama-server-cuda.sif"
fi
IMAGE="${IMAGE:-$DEFAULT_IMAGE}"

DEFAULT_MODEL="${HOME}/dev/models/Qwen3.5-9B-Q4_K_M.gguf"
if [ ! -f "$DEFAULT_MODEL" ] && [ -f "$PROJECT_DIR/../models/Qwen3.5-9B-Q4_K_M.gguf" ]; then
    DEFAULT_MODEL="$PROJECT_DIR/../models/Qwen3.5-9B-Q4_K_M.gguf"
fi
MODEL_PATH="${MODEL_PATH:-$DEFAULT_MODEL}"

PORT="${PORT:-8000}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
API_KEY="${API_KEY:-dacn-qwen-3.5-9b-secret-key}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen3.5-9b}"

mkdir -p "$PROJECT_DIR/logs" "$CACHE_DIR"

# 1. Check Apptainer Image file (.sif)
if [ ! -f "$IMAGE" ]; then
    echo "=========================================================="
    echo "ERROR: Image not found at: $IMAGE"
    echo "Please pull the image first on the Login Node:"
    echo "  mkdir -p $(dirname "$IMAGE")"
    echo "  apptainer pull $IMAGE docker://ghcr.io/ggml-org/llama.cpp:server-cuda"
    echo "=========================================================="
    exit 1
fi

# 2. Check existence of pre-downloaded model file
if [ ! -f "$MODEL_PATH" ]; then
    echo "=========================================================="
    echo "ERROR: Model file not found at: $MODEL_PATH"
    echo "Please run the download-model.sh script on the Login Node first:"
    echo "  cd $PROJECT_DIR && ./download-model.sh"
    echo "=========================================================="
    exit 1
fi

NODE_HOSTNAME=$(hostname)
HEADNODE_IP="${HEADNODE_IP:-10.1.1.239}"
TUNNEL_REMOTE_PORT="${TUNNEL_REMOTE_PORT:-18000}"

echo "=========================================================="
echo " Job ID           : ${SLURM_JOB_ID:-local}"
echo " Compute Node     : $NODE_HOSTNAME (NVIDIA V100)"
echo " Image SIF        : $IMAGE"
echo " Port             : $PORT"
echo " Model Path       : $MODEL_PATH"
echo " Model Alias      : $MODEL_ALIAS"
echo " Context Size     : $CONTEXT_SIZE (8K)"
echo " Internal Endpoint: http://${NODE_HOSTNAME}:${PORT}/v1"
echo " Headnode Tunnel  : http://${HEADNODE_IP}:${TUNNEL_REMOTE_PORT}/v1"
echo "=========================================================="

# Resilient Reverse SSH Tunnel with Auto-Reconnect Loop
echo "Starting reverse SSH tunnel keep-alive loop: $NODE_HOSTNAME:$PORT -> $HEADNODE_IP:$TUNNEL_REMOTE_PORT..."
(
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

cleanup() {
    echo "Shutting down server and reverse tunnel..."
    kill -TERM "$TUNNEL_LOOP_PID" 2>/dev/null || true
    pkill -P "$TUNNEL_LOOP_PID" 2>/dev/null || true
}
trap cleanup EXIT SIGTERM SIGINT

# ==========================================
# LAUNCH LLAMA-SERVER VIA APPTAINER (GPU V100)
# ==========================================
apptainer exec --nv \
  --pwd /app \
  --env LD_LIBRARY_PATH="/app:${LD_LIBRARY_PATH:-}" \
  --bind "$MODEL_PATH:/model.gguf:ro" \
  "$IMAGE" \
  /app/llama-server \
    -m /model.gguf \
    --host 0.0.0.0 \
    --port "$PORT" \
    -c "$CONTEXT_SIZE" \
    -ngl 99 \
    --alias "$MODEL_ALIAS" \
    --api-key "$API_KEY"


