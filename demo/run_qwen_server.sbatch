#!/bin/bash
#SBATCH --job-name=qwen3.5-9b-vllm
#SBATCH --partition=gpu-queue
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --qos=gpu-q
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/qwen-server-%j.out
#SBATCH --error=logs/qwen-server-%j.err
#SBATCH --signal=B:SIGTERM@60

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

# Configuration
IMAGE=${IMAGE:-$PWD/build/vllm.sif}
MODEL_FILE=${MODEL_FILE:-Qwen3.5-9B-Q4_K_M.gguf}
CACHE_ROOT=${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}
PORT=${PORT:-8000}
TP=${TP:-1}
TOKENIZER=${TOKENIZER:-Qwen/Qwen2.5-7B-Instruct}
ENDPOINT_FILE="$CACHE_ROOT/endpoint.json"

mkdir -p "$CACHE_ROOT"/{huggingface,vllm,xdg,models}

# Graceful signal handler
cleanup() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Received shutdown signal. Terminating vLLM..."
  rm -f "$ENDPOINT_FILE"
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill -TERM "$VLLM_PID" 2>/dev/null || true
    wait "$VLLM_PID" 2>/dev/null || true
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Clean shutdown complete."
}
trap cleanup SIGTERM SIGINT EXIT

NODE_NAME=$(hostname)
echo "============================================================"
echo "Job ID:    ${SLURM_JOB_ID:-N/A}"
echo "Node:      $NODE_NAME"
echo "Image:     $IMAGE"
echo "Model:     $MODEL_FILE"
echo "Port:      $PORT"
echo "TP:        $TP"
echo "============================================================"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
nvidia-smi -ac 877,1530 2>/dev/null || true

# Write endpoint information for automated tunneling
cat <<EOF > "$ENDPOINT_FILE"
{
  "job_id": "${SLURM_JOB_ID:-local}",
  "node": "$NODE_NAME",
  "port": $PORT,
  "model": "$MODEL_FILE",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# NUMA Node Affinity (Socket 0)
NUMA_PREFIX=()
if command -v numactl &>/dev/null; then
  NUMA_PREFIX=(numactl --cpunodebind=0 --membind=0)
fi

export VLLM_USE_V1=0
export NVIDIA_TF32_OVERRIDE=0

# Resolve GGUF model path inside container binding (/cache/models or direct path)
if [[ -f "$CACHE_ROOT/models/$MODEL_FILE" ]]; then
  CONTAINER_MODEL_PATH="/cache/models/$MODEL_FILE"
elif [[ -f "$MODEL_FILE" ]]; then
  CONTAINER_MODEL_PATH="$MODEL_FILE"
else
  CONTAINER_MODEL_PATH="/cache/models/$MODEL_FILE"
fi

TOKENIZER_ARGS=()
if [[ -n "${TOKENIZER:-}" ]]; then
  TOKENIZER_ARGS=(--tokenizer "$TOKENIZER")
fi

# Run vLLM serving with FP16 KV Cache, Prefix Caching and Chunked Prefill
"${NUMA_PREFIX[@]}" apptainer run --nv --cleanenv \
  --bind "$CACHE_ROOT:/cache" \
  "$IMAGE" \
  serve "$CONTAINER_MODEL_PATH" \
  "${TOKENIZER_ARGS[@]}" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --dtype float16 \
  --tensor-parallel-size "$TP" \
  --gpu-memory-utilization 0.90 \
  --max-model-len 4096 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-num-seqs 64 \
  --max-num-batched-tokens 2048 &

VLLM_PID=$!
wait "$VLLM_PID"
