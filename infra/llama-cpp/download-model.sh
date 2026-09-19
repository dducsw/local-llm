#!/usr/bin/env bash
set -euo pipefail

# ==========================================
# MODEL STORAGE PATH CONFIGURATION
# ==========================================
DEST_DIR="${1:-${MODELS_DIR:-$HOME/dev/models}}"
mkdir -p "$DEST_DIR"

MODEL_NAME="Qwen3.5-9B-Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"
OUTPUT_FILE="$DEST_DIR/$MODEL_NAME"

echo "=========================================================="
echo " Downloading model : $MODEL_NAME"
echo " HF Source         : $MODEL_URL"
echo " Destination path  : $OUTPUT_FILE"
echo "=========================================================="

# Display progress bar (percentage %, speed MB/s, ETA)
if command -v wget &> /dev/null; then
    wget -c --show-progress --progress=bar:force:noscroll "$MODEL_URL" -O "$OUTPUT_FILE"
elif command -v curl &> /dev/null; then
    curl -# -L -C - "$MODEL_URL" -o "$OUTPUT_FILE"
else
    echo "ERROR: Neither wget nor curl found on the system!"
    exit 1
fi

echo "=========================================================="
echo " Model downloaded successfully: $OUTPUT_FILE"
echo " File size: $(du -sh "$OUTPUT_FILE" | cut -f1)"
echo "=========================================================="
