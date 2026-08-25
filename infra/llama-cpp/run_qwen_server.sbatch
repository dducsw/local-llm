#!/usr/bin/env bash
#SBATCH --job-name=qwen3.5-server
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --account=summer-school
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=1:00:00
#SBATCH --output=/home/ducledinh/dev/apptainer/logs/%x-%j.out
#SBATCH --error=/home/ducledinh/dev/apptainer/logs/%x-%j.err

set -euo pipefail

# ==========================================
# ENVIRONMENT VARIABLES & PARAMETERS CONFIGURATION
# ==========================================
PROJECT_DIR="${SLURM_SUBMIT_DIR}"
IMAGE="${IMAGE:-/home/ducledinh/dev/container/llama-server-cuda.sif}"
MODEL_PATH="${MODEL_PATH:-/home/ducledinh/dev/models/Qwen3.5-9B-Q4_K_M.gguf}"
PORT="${PORT:-8000}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
API_KEY="${API_KEY:-dacn-qwen-3.5-9b-secret-key}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen3.5-9b}"

mkdir -p "$PROJECT_DIR/logs"

# 1. Check Apptainer Image file (.sif)
if [ ! -f "$IMAGE" ]; then
    echo "=========================================================="
    echo "ERROR: Image not found at: $IMAGE"
    echo "Please pull the image first on the Login Node:"
    echo "  mkdir -p /home/ducledinh/dev/container"
    echo "  apptainer pull /home/ducledinh/dev/container/llama-server-cuda.sif docker://ghcr.io/ggml-org/llama.cpp:server-cuda"
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
echo "=========================================================="
echo " Job ID          : $SLURM_JOB_ID"
echo " Compute Node    : $NODE_HOSTNAME (NVIDIA V100)"
echo " Image SIF       : $IMAGE"
echo " Port            : $PORT"
echo " Model Path      : $MODEL_PATH"
echo " Model Alias     : $MODEL_ALIAS"
echo " Context Size    : $CONTEXT_SIZE (8K)"
echo " Internal Endpoint: http://${NODE_HOSTNAME}:${PORT}/v1"
echo "=========================================================="

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
