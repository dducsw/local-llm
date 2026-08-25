#!/bin/bash
#SBATCH --job-name=test-1cat-v100
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=logs/test-1cat-v100-%j.out
#SBATCH --error=logs/test-1cat-v100-%j.err

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

if [[ -f "$PWD/build/1cat-vllm.sif" ]]; then
  IMAGE="$PWD/build/1cat-vllm.sif"
elif [[ -d "$PWD/build/1cat_vllm_sandbox" ]]; then
  IMAGE="$PWD/build/1cat_vllm_sandbox"
elif [[ -f "$HOME/dev/container/1cat-vllm.sif" ]]; then
  IMAGE="$HOME/dev/container/1cat-vllm.sif"
else
  IMAGE="$PWD/build/1cat-vllm.sif"
fi

echo "Testing 1Cat-vLLM container: $IMAGE on $(hostname)"

apptainer exec \
  --nv \
  --cleanenv \
  "$IMAGE" \
  python3 - <<'PY'
import torch
print("PyTorch Version :", torch.__version__)
print("CUDA Available  :", torch.cuda.is_available())
print("Device Name     :", torch.cuda.get_device_name(0))
print("Capability (SM) :", torch.cuda.get_device_capability(0))

try:
    import vllm
    print("1Cat-vLLM       :", vllm.__version__)
except Exception as e:
    print("vLLM import error:", e)

try:
    import flash_attn_v100
    print("flash_attn_v100 : OK")
except Exception as e:
    print("flash_attn_v100 note:", e)

print("1CAT_VLLM_V100_CHECK_COMPLETE")
PY
