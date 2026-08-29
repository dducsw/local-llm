#!/usr/bin/env bash
# ==============================================================================
# Fast & Safe Model Downloader for 1Cat-vLLM (Qwen 3.5 9B AWQ INT4)
# Uses wget/curl with auto-resume (-c) and progress bar. No Python dependencies needed.
# ==============================================================================

set -euo pipefail

# ==============================================================================
# WARNING: This script downloads a hardcoded list of files via wget/curl.
# It is a quick fallback for environments with no Python/HF Hub available.
#
# PREFERRED: Use the Slurm batch job for a complete, resumable download:
#   sbatch slurm/download/hf_download_qwen3.5_9b_awq.sbatch
#
# This script may MISS files if the model has multiple safetensors shards
# (e.g., model-00001-of-00002.safetensors). Verify with:
#   ls -lh "$DEST_ROOT/Qwen3.5-9B-AWQ/"
# ==============================================================================


DEST_ROOT="${1:-$HOME/dev/models}"
MODEL_DIR="$DEST_ROOT/Qwen3.5-9B-AWQ"
BASE_URL="https://huggingface.co/QuantTrio/Qwen3.5-9B-AWQ/resolve/main"

mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"

echo "=========================================================="
echo " 1Cat-vLLM AWQ Model Downloader"
echo " Model Repository : QuantTrio/Qwen3.5-9B-AWQ"
echo " Destination Dir  : $MODEL_DIR"
echo "=========================================================="

FILES=(
    "config.json"
    "generation_config.json"
    "tokenizer.json"
    "tokenizer_config.json"
    "model.safetensors"
)

download_file() {
    local file="$1"
    local url="$BASE_URL/$file"
    echo
    echo ">> Downloading: $file ..."
    if command -v wget &> /dev/null; then
        wget -c --show-progress --progress=bar:force:noscroll "$url" -O "$file"
    elif command -v curl &> /dev/null; then
        curl -# -L -C - "$url" -o "$file"
    else
        echo "ERROR: Neither wget nor curl is available on this system."
        exit 1
    fi
}

for f in "${FILES[@]}"; do
    download_file "$f"
done

echo
echo "=========================================================="
echo " Model download completed successfully!"
echo " Location   : $MODEL_DIR"
echo " Total size : $(du -sh "$MODEL_DIR" | cut -f1)"
echo "=========================================================="
