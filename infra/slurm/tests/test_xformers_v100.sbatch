#!/bin/bash
#SBATCH --job-name=xf-v100
#SBATCH --partition=gpu-queue
#SBATCH --qos=gpu-q
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=logs/xformers-v100-%j.out
#SBATCH --error=logs/xformers-v100-%j.err

set -euo pipefail

SB="$HOME/llm_serving/build/vllm-gloo-nccl-patched.sandbox"

apptainer exec \
  --nv \
  --cleanenv \
  --env XFORMERS_MORE_DETAILS=1 \
  "$SB" \
  python3 - <<'PY'
import torch
import xformers
import xformers.ops as xops

print("torch =", torch.__version__)
print("xformers =", xformers.__version__)
print("GPU =", torch.cuda.get_device_name(0))
print("CC =", torch.cuda.get_device_capability(0))

q = torch.randn(
    1, 2048, 2, 8, 128,
    device="cuda",
    dtype=torch.float16,
)
k = torch.randn_like(q)
v = torch.randn_like(q)

bias = xops.fmha.attn_bias.BlockDiagonalCausalMask.from_seqlens([2048])

out = xops.memory_efficient_attention_forward(
    q,
    k,
    v,
    attn_bias=bias,
)

torch.cuda.synchronize()

print("out =", tuple(out.shape))
print("finite =", torch.isfinite(out).all().item())
print("XFORMERS_V100_OK")
PY
