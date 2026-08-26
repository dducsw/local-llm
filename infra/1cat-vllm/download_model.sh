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
elif command -v python3 &> /dev/null; then
    echo "[*] Using Python built-in urllib to download model repository files..."
    python3 - <<PY
import os
import json
import urllib.request

repo = "$MODEL_REPO"
dest = "$MODEL_SUBDIR"
os.makedirs(dest, exist_ok=True)

api_url = f"https://huggingface.co/api/models/{repo}"
req = urllib.request.Request(api_url, headers={"User-Agent": "1cat-vllm-downloader"})
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
    siblings = [f["rfilename"] for f in data.get("siblings", []) if not f["rfilename"].startswith(".")]
    print(f"Discovered {len(siblings)} files to download for {repo}...")
    for idx, fname in enumerate(siblings, 1):
        target_path = os.path.join(dest, fname)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        file_url = f"https://huggingface.co/{repo}/resolve/main/{fname}"
        print(f"[{idx}/{len(siblings)}] Downloading {fname}...")
        urllib.request.urlretrieve(file_url, target_path)
    print("All files downloaded successfully.")
except Exception as e:
    print("Download error:", e)
    raise SystemExit(1)
PY
else
    echo "=========================================================="
    echo "ERROR: Neither huggingface-cli, git-lfs, nor python3 is available."
    echo "=========================================================="
    exit 1
fi

echo "=========================================================="
echo " Model download completed successfully!"
echo " Location: $MODEL_SUBDIR"
echo " Total size: $(du -sh "$MODEL_SUBDIR" | cut -f1)"
echo "=========================================================="
