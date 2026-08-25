#!/bin/bash
#SBATCH --job-name=hf-download-qwen-awq
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
DEST_DIR="${MODELS_DIR:-$HOME/dev/models}"
MODEL_REPO="${MODEL_REPO:-drawais/Qwen3.5-9B-AWQ-INT4}"
MODEL_SUBDIR="$DEST_DIR/$(basename "$MODEL_REPO")"

mkdir -p "$DEST_DIR"

echo "Downloading $MODEL_REPO to $MODEL_SUBDIR..."

export HF_HUB_ENABLE_HF_TRANSFER=1

if command -v huggingface-cli &>/dev/null; then
  huggingface-cli download "$MODEL_REPO" \
    --local-dir "$MODEL_SUBDIR" \
    --local-dir-use-symlinks False
elif python3 -c "import huggingface_hub" &>/dev/null; then
  python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='$MODEL_REPO', local_dir='$MODEL_SUBDIR', local_dir_use_symlinks=False)
"
else
  echo "Error: huggingface-cli or huggingface_hub Python package not found." >&2
  exit 1
fi

echo "Download completed: $(du -sh "$MODEL_SUBDIR" | cut -f1)"
