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
MODEL=${MODEL:-Qwen3.5-9B-AWQ-INT4}
MODELS_DIR=${MODELS_DIR:-$HOME/dev/models}
CACHE_ROOT=${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}
PORT=${PORT:-8000}
TP=1
MAX_MODEL_LEN=${MAX_MODEL_LEN:-8192}
GPU_MEM_UTIL=${GPU_MEM_UTIL:-0.90}
API_KEY=${API_KEY:-dacn-qwen-secret-key}
MODEL_ALIAS=${MODEL_ALIAS:-qwen3.5-9b}
ENDPOINT_FILE="$PWD/logs/endpoint-${SLURM_JOB_ID:-local}.json"

mkdir -p "$CACHE_ROOT"/{huggingface,vllm,xdg,models} logs

# Graceful signal handler for Slurm walltime expiration
cleanup() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Received shutdown signal. Terminating 1Cat-vLLM..."
  rm -f "$ENDPOINT_FILE"
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill -TERM "$VLLM_PID" 2>/dev/null || true
    wait "$VLLM_PID" 2>/dev/null || true
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Clean shutdown complete."
}
trap cleanup SIGTERM SIGINT EXIT

NODE_NAME=$(hostname)
echo "job_id=${SLURM_JOB_ID:-local}"
echo "node=$NODE_NAME"
echo "image=$IMAGE"
echo "model=$MODEL"
echo "tp=$TP"
echo "port=$PORT"
echo "backend=FLASH_ATTN_V100 (SM70 TurboMind)"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

# Write endpoint information for client discovery / automated tunneling
cat <<EOF > "$ENDPOINT_FILE"
{
  "job_id": "${SLURM_JOB_ID:-local}",
  "node": "$NODE_NAME",
  "port": $PORT,
  "model": "$MODEL_ALIAS",
  "endpoint": "http://${NODE_NAME}:${PORT}/v1",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# 1. Attempt GPU Application Clock Pinning (Volta V100 SXM2 877MHz mem, 1530MHz sm)
nvidia-smi -ac 877,1530 2>/dev/null || true

# 2. NUMA Affinity Prefix (Pin execution to GPU-attached CPU socket 0)
NUMA_PREFIX=()
if command -v numactl &>/dev/null; then
  NUMA_PREFIX=(numactl --cpunodebind=0 --membind=0)
fi

# 3. Environment overrides for Volta V100 (SM70) stability
export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0
export NCCL_P2P_DISABLE=1

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

QUANT_ARGS=()
if [[ -n "${QUANTIZATION:-}" ]]; then
  QUANT_ARGS=(--quantization "$QUANTIZATION")
fi

echo "Resolved model path in container: $MODEL_ARG"

# Run 1Cat-vLLM serving with FLASH_ATTN_V100 backend (VLLM_USE_V1=0 for Volta SM70)
"${NUMA_PREFIX[@]}" apptainer run --nv --cleanenv \
  --env VLLM_USE_V1=0,NVIDIA_TF32_OVERRIDE=0,NCCL_P2P_DISABLE=1 \
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
  --limit-mm-per-prompt '{"image": 0, "video": 0}' \
  "${QUANT_ARGS[@]}" &

VLLM_PID=$!
wait "$VLLM_PID"
