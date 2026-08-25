#!/bin/bash
#SBATCH --job-name=vllm-smoke
#SBATCH --partition=gpu-queue
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --qos=gpu-q
#SBATCH --cpus-per-task=8
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --output=logs/vllm-%j.out
#SBATCH --error=logs/vllm-%j.err
#SBATCH --signal=B:SIGTERM@60

set -euo pipefail

# Override these from sbatch --export=ALL,IMAGE=...,MODEL=...,CACHE_ROOT=...
IMAGE=${IMAGE:-$PWD/build/vllm.sif}
MODEL=${MODEL:-Qwen3.5-9B-Q4_K_M.gguf}
CACHE_ROOT=${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}
PORT=${PORT:-8000}
TP=${TP:-1}
TOKENIZER=${TOKENIZER:-Qwen/Qwen2.5-7B-Instruct}
ENDPOINT_FILE="$CACHE_ROOT/endpoint.json"

mkdir -p "$CACHE_ROOT"/{huggingface,vllm,xdg,models} logs

# Graceful signal handler for Slurm walltime expiration
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
echo "job_id=${SLURM_JOB_ID:-local}"
echo "node=$NODE_NAME"
echo "image=$IMAGE"
echo "model=$MODEL"
echo "tp=$TP"
echo "port=$PORT"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

# Write endpoint information for client discovery / automated tunneling
cat <<EOF > "$ENDPOINT_FILE"
{
  "job_id": "${SLURM_JOB_ID:-local}",
  "node": "$NODE_NAME",
  "port": $PORT,
  "model": "$MODEL",
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

# Resolve GGUF model path if stored in cache or local directory
MODEL_ARG="$MODEL"
if [[ -f "$CACHE_ROOT/models/$MODEL" ]]; then
  MODEL_ARG="/cache/models/$MODEL"
elif [[ -f "$MODEL" ]]; then
  MODEL_ARG="$MODEL"
fi

TOKENIZER_ARGS=()
if [[ "$MODEL" == *.gguf* ]] && [[ -n "${TOKENIZER:-}" ]]; then
  TOKENIZER_ARGS=(--tokenizer "$TOKENIZER")
fi

# Run vLLM serving with FP16 KV Cache, Prefix Caching and Chunked Prefill
"${NUMA_PREFIX[@]}" apptainer run --nv --cleanenv \
  --bind "$CACHE_ROOT:/cache" \
  "$IMAGE" \
  serve "$MODEL_ARG" \
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