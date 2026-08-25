#!/usr/bin/env bash
# ==============================================================================
# Model Downloader for 1Cat-vLLM
# ==============================================================================
# Supports downloading Qwen AWQ models (recommended for V100 1Cat-vLLM)
# or GGUF / SafeTensors models from Hugging Face.
# ==============================================================================

set -euo pipefail

# Default destination directory
DEST_DIR="${1:-/home/ducledinh/dev/models}"
mkdir -p "$DEST_DIR"

# Recommended models:
# 1. drawais/Qwen3.5-9B-AWQ-INT4 (Qwen 3.5 9B AWQ 4-bit INT4)
# 2. tclf90/Qwen3.6-27B-AWQ (for multi-GPU V100 TP2/TP4)
# 3. unsloth/Qwen3.5-9B-GGUF (for single file GGUF)
MODEL_REPO="${2:-drawais/Qwen3.5-9B-AWQ-INT4}"
MODEL_SUBDIR="$DEST_DIR/$(basename "$MODEL_REPO")"

echo "=========================================================="
echo " Model Download Script for 1Cat-vLLM"
echo " HF Repository   : $MODEL_REPO"
echo " Destination Dir : $MODEL_SUBDIR"
echo "=========================================================="

export HF_HUB_ENABLE_HF_TRANSFER=1

# Check if huggingface-cli is available
if command -v huggingface-cli &> /dev/null; then
    echo "[*] Using huggingface-cli to download model..."
    huggingface-cli download "$MODEL_REPO" \
        --local-dir "$MODEL_SUBDIR" \
        --local-dir-use-symlinks False
elif python3 -c "import huggingface_hub" &> /dev/null; then
    echo "[*] Using Python huggingface_hub snapshot_download..."
    python3 -c "
import os
from huggingface_hub import snapshot_download

repo_id = '$MODEL_REPO'
local_dir = '$MODEL_SUBDIR'

print(f'Downloading {repo_id} to {local_dir}...')
snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    resume_download=True
)
print('Download completed.')
"
elif command -v git-lfs &> /dev/null; then
    echo "[*] Using git clone (git-lfs)..."
    git clone "https://huggingface.co/$MODEL_REPO" "$MODEL_SUBDIR"
else
    echo "=========================================================="
    echo "ERROR: huggingface-cli or python huggingface_hub is required."
    echo "Please install them via:"
    echo "  pip install huggingface_hub hf_transfer"
    echo "=========================================================="
    exit 1
fi

echo "=========================================================="
echo " Model download completed successfully!"
echo " Location: $MODEL_SUBDIR"
echo " Total size: $(du -sh "$MODEL_SUBDIR" | cut -f1)"
echo "=========================================================="
