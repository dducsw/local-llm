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
MODEL_NAME="Qwen3.5-9B-AWQ"
MODEL_DIR="$DEST_ROOT/$MODEL_NAME"
REPO_ID="QuantTrio/Qwen3.5-9B-AWQ"

mkdir -p "$MODEL_DIR"

echo "=========================================================="
echo " 1Cat-vLLM AWQ Model Downloader"
echo " Model Repository : $REPO_ID"
echo " Destination Dir  : $MODEL_DIR"
echo "=========================================================="

if command -v huggingface-cli &>/dev/null; then
    echo ">> Using huggingface-cli for full snapshot download..."
    huggingface-cli download "$REPO_ID" --local-dir "$MODEL_DIR" --local-dir-use-symlinks False
elif python3 -c "import huggingface_hub" &>/dev/null; then
    echo ">> Using huggingface_hub python package..."
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='$REPO_ID', local_dir='$MODEL_DIR', local_dir_use_symlinks=False)
"
elif command -v python3 &>/dev/null; then
    echo ">> Using Python API downloader to fetch all repo files dynamically..."
    python3 - <<PY
import os
import json
import urllib.request

repo = "$REPO_ID"
dest = "$MODEL_DIR"
os.makedirs(dest, exist_ok=True)

api_url = f"https://huggingface.co/api/models/{repo}"
req = urllib.request.Request(api_url, headers={"User-Agent": "1cat-vllm-downloader"})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())

siblings = [f["rfilename"] for f in data.get("siblings", []) if not f["rfilename"].startswith(".")]
print(f"Found {len(siblings)} files to download.")

for idx, fname in enumerate(siblings, 1):
    target_path = os.path.join(dest, fname)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 0 and not fname.endswith(".safetensors"):
        print(f"[{idx}/{len(siblings)}] Skipping already downloaded {fname}")
        continue
    file_url = f"https://huggingface.co/{repo}/resolve/main/{fname}"
    print(f"[{idx}/{len(siblings)}] Downloading {fname} ...")
    urllib.request.urlretrieve(file_url, target_path)
print("All files downloaded successfully.")
PY
else
    echo "ERROR: Python 3 is required to resolve repository file structure."
    exit 1
fi

echo
echo "=========================================================="
echo " Model download completed successfully!"
echo " Location   : $MODEL_DIR"
echo " Total size : $(du -sh "$MODEL_DIR" | cut -f1)"
echo "=========================================================="

