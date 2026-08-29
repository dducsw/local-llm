#!/bin/bash
#SBATCH --job-name=1cat-vllm-single
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --account=summer-school
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/1cat-vllm-%j.out
#SBATCH --error=logs/1cat-vllm-%j.err
#SBATCH --signal=B:SIGTERM@60

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

# Image Resolution
if [[ -f "$PWD/build/1cat-vllm.sif" ]]; then
  DEFAULT_IMAGE="$PWD/build/1cat-vllm.sif"
elif [[ -d "$PWD/build/1cat_vllm_sandbox" ]]; then
  DEFAULT_IMAGE="$PWD/build/1cat_vllm_sandbox"
elif [[ -f "$HOME/dev/container/1cat-vllm.sif" ]]; then
  DEFAULT_IMAGE="$HOME/dev/container/1cat-vllm.sif"
else
  DEFAULT_IMAGE="$PWD/build/1cat-vllm.sif"
fi

IMAGE=${IMAGE:-$DEFAULT_IMAGE}
MODEL=${MODEL:-Qwen3.5-9B-AWQ}
MODELS_DIR=${MODELS_DIR:-$HOME/dev/models}
CACHE_ROOT=${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}
PORT=${PORT:-8000}
TP=1
MAX_MODEL_LEN=${MAX_MODEL_LEN:-8192}
GPU_MEM_UTIL=${GPU_MEM_UTIL:-0.90}
API_KEY=${API_KEY:-dacn-qwen-3.5-9b-secret-key}
MODEL_ALIAS=${MODEL_ALIAS:-qwen3.5-9b}
HEADNODE_IP="${HEADNODE_IP:-10.1.1.239}"
TUNNEL_REMOTE_PORT="${TUNNEL_REMOTE_PORT:-18000}"
ENDPOINT_FILE="$PWD/logs/endpoint-${SLURM_JOB_ID:-local}.json"

mkdir -p "$CACHE_ROOT"/{huggingface,vllm,xdg,models} logs

NODE_NAME=$(hostname)
echo "job_id=${SLURM_JOB_ID:-local}"
echo "node=$NODE_NAME"
echo "image=$IMAGE"
echo "model=$MODEL"
echo "tp=$TP"
echo "port=$PORT"
echo "backend=FLASH_ATTN_V100 (SM70 TurboMind)"
echo "Internal Endpoint: http://${NODE_NAME}:${PORT}/v1"
echo "Headnode Tunnel  : http://${HEADNODE_IP}:${TUNNEL_REMOTE_PORT}/v1"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

# Write endpoint information for client discovery / automated tunneling
cat <<EOF > "$ENDPOINT_FILE"
{
  "job_id": "${SLURM_JOB_ID:-local}",
  "node": "$NODE_NAME",
  "port": $PORT,
  "headnode_ip": "$HEADNODE_IP",
  "tunnel_port": $TUNNEL_REMOTE_PORT,
  "model": "$MODEL_ALIAS",
  "endpoint": "http://${NODE_NAME}:${PORT}/v1",
  "headnode_endpoint": "http://${HEADNODE_IP}:${TUNNEL_REMOTE_PORT}/v1",
  "api_key": "$API_KEY",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# Resilient Reverse SSH Tunnel: Wait for server to be ready before establishing tunnel
echo "Starting reverse SSH tunnel keep-alive loop: $NODE_NAME:$PORT -> $HEADNODE_IP:$TUNNEL_REMOTE_PORT..."
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


# Graceful signal handler for Slurm walltime expiration
cleanup() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Received shutdown signal. Terminating 1Cat-vLLM and tunnel..."
  rm -f "$ENDPOINT_FILE"
  kill -TERM "$TUNNEL_LOOP_PID" 2>/dev/null || true
  pkill -P "$TUNNEL_LOOP_PID" 2>/dev/null || true
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill -TERM "$VLLM_PID" 2>/dev/null || true
    wait "$VLLM_PID" 2>/dev/null || true
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Clean shutdown complete."
}
trap cleanup SIGTERM SIGINT EXIT


# 1. Attempt GPU Application Clock Pinning (Volta V100 SXM2 877MHz mem, 1530MHz sm)
nvidia-smi -ac 877,1530 2>/dev/null || true

# 2. NUMA Affinity Prefix (Pin execution to GPU-attached CPU socket 0)
NUMA_PREFIX=()
if command -v numactl &>/dev/null; then
  NUMA_PREFIX=(numactl --cpunodebind=0 --membind=0)
fi

# 3. Environment overrides for Volta V100 (SM70) stability & MTP speedup
export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0
export NCCL_P2P_DISABLE=1
export VLLM_1CAT_ENABLE_SM70_MTP_DEFAULTS="${ENABLE_MTP:-1}"

# Resolve model location and bind mounts
BIND_ARGS=("--bind" "$CACHE_ROOT:/cache")
MODEL_ARG="$MODEL"

if [[ -d "$MODEL" || -f "$MODEL" ]]; then
  MODEL_DIR=$(dirname "$(realpath "$MODEL")")
  MODEL_BASE=$(basename "$MODEL")
  BIND_ARGS+=("--bind" "$MODEL_DIR:/models:ro")
  MODEL_ARG="/models/$MODEL_BASE"
elif [[ -n "${MODELS_DIR:-}" && -d "$MODELS_DIR/$MODEL" ]]; then
  ABS_MODELS_DIR=$(realpath "$MODELS_DIR")
  BIND_ARGS+=("--bind" "$ABS_MODELS_DIR:/models:ro")
  MODEL_ARG="/models/$MODEL"
elif [[ -d "$HOME/dev/models/$MODEL" ]]; then
  BIND_ARGS+=("--bind" "$HOME/dev/models:/models:ro")
  MODEL_ARG="/models/$MODEL"
fi

# Auto-detect AWQ from model name; override with $QUANTIZATION env if set explicitly
QUANT_ARGS=()
if [[ -n "${QUANTIZATION:-}" ]]; then
  QUANT_ARGS=(--quantization "$QUANTIZATION")
elif [[ "$MODEL" =~ [Aa][Ww][Qq] ]]; then
  QUANT_ARGS=(--quantization awq)
  echo "[auto] Detected AWQ model — adding --quantization awq"
fi

echo "Resolved model path in container: $MODEL_ARG"

# JSON string for --limit-mm-per-prompt (must be a single shell word)
LIMIT_MM='{"image":0,"video":0}'

# Run 1Cat-vLLM serving with FLASH_ATTN_V100 backend (VLLM_USE_V1=0 for Volta SM70, MTP enabled)
"${NUMA_PREFIX[@]}" apptainer run --nv --cleanenv \
  --env VLLM_USE_V1=0,NVIDIA_TF32_OVERRIDE=0,NCCL_P2P_DISABLE=1,VLLM_1CAT_ENABLE_SM70_MTP_DEFAULTS="$VLLM_1CAT_ENABLE_SM70_MTP_DEFAULTS" \
  "${BIND_ARGS[@]}" \
  "$IMAGE" \

  serve "$MODEL_ARG" \
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
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --reasoning-parser qwen3 \
  --limit-mm-per-prompt "$LIMIT_MM" \
  "${QUANT_ARGS[@]}" &

VLLM_PID=$!
wait "$VLLM_PID"
