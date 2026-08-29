#!/bin/bash
#SBATCH --job-name=hf-download-qwen-awq
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --account=summer-school
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
MODEL_REPO="${MODEL_REPO:-QuantTrio/Qwen3.5-9B-AWQ}"
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
elif command -v python3 &>/dev/null; then
  echo "Using Python urllib fallback to download repository files..."
  python3 - <<PY
import os
import json
import urllib.request

repo = "$MODEL_REPO"
dest = "$MODEL_SUBDIR"
os.makedirs(dest, exist_ok=True)

api_url = f"https://huggingface.co/api/models/{repo}"
req = urllib.request.Request(api_url, headers={"User-Agent": "1cat-vllm-downloader"})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
siblings = [f["rfilename"] for f in data.get("siblings", []) if not f["rfilename"].startswith(".")]
for idx, fname in enumerate(siblings, 1):
    target_path = os.path.join(dest, fname)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    file_url = f"https://huggingface.co/{repo}/resolve/main/{fname}"
    print(f"[{idx}/{len(siblings)}] Downloading {fname}...")
    urllib.request.urlretrieve(file_url, target_path)
print("Done.")
PY
else
  echo "Error: Neither huggingface-cli, huggingface_hub, nor python3 is available." >&2
  exit 1
fi

echo "Download completed: $(du -sh "$MODEL_SUBDIR" | cut -f1)"
