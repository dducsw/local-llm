#!/bin/bash
#SBATCH --job-name=hf-download-qwen
#SBATCH --partition=cpu-queue
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=logs/download-%j.out
#SBATCH --error=logs/download-%j.err

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

CACHE_ROOT=${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}
DEST_DIR="$CACHE_ROOT/models"
MODEL_FILE="Qwen3.5-9B-Q4_K_M.gguf"
DOWNLOAD_URL="https://huggingface.co/unsloth/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf"

mkdir -p "$DEST_DIR"

echo "Downloading $MODEL_FILE to $DEST_DIR..."

if command -v huggingface-cli &>/dev/null; then
  huggingface-cli download unsloth/Qwen2.5-7B-Instruct-GGUF qwen2.5-7b-instruct-q4_k_m.gguf \
    --local-dir "$DEST_DIR" \
    --local-dir-use-symlinks False
  if [[ -f "$DEST_DIR/qwen2.5-7b-instruct-q4_k_m.gguf" && ! -f "$DEST_DIR/$MODEL_FILE" ]]; then
    ln -sf "$DEST_DIR/qwen2.5-7b-instruct-q4_k_m.gguf" "$DEST_DIR/$MODEL_FILE"
  fi
elif command -v curl &>/dev/null; then
  curl -L -C - "$DOWNLOAD_URL" -o "$DEST_DIR/$MODEL_FILE"
elif command -v wget &>/dev/null; then
  wget -c "$DOWNLOAD_URL" -O "$DEST_DIR/$MODEL_FILE"
else
  echo "Error: Neither huggingface-cli, curl, nor wget is available." >&2
  exit 1
fi

echo "Download completed: $(ls -lh "$DEST_DIR/$MODEL_FILE")"
