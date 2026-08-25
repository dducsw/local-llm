#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/llm_serving}"
IMAGE="${IMAGE:-$PROJECT_ROOT/build/vllm.sif}"
WORK_ROOT="${WORK_ROOT:-$PROJECT_ROOT/build/torch-gloo-port}"
WHEELHOUSE="${WHEELHOUSE:-$WORK_ROOT/wheelhouse}"
PATCH_SITE="${PATCH_SITE:-$PROJECT_ROOT/patches/torch-gloo-port/site}"

WHEEL="$(ls -1t "$WHEELHOUSE"/torch-*.whl | head -1)"

rm -rf "$PATCH_SITE"
mkdir -p "$PATCH_SITE"

apptainer exec \
  --bind "$WHEELHOUSE:/wheelhouse" \
  --bind "$PATCH_SITE:/patchsite" \
  "$IMAGE" \
  bash -lc "python3 -m pip install \
    --no-deps \
    --no-cache-dir \
    --target /patchsite \
    /wheelhouse/$(basename "$WHEEL")"

echo
echo "=== VERIFY PATCHSITE TORCH ==="

apptainer exec \
  --nv \
  --bind "$PATCH_SITE:/patchsite" \
  --env "PYTHONPATH=/patchsite" \
  "$IMAGE" \
  python3 - <<'PY'
import torch
from pathlib import Path

print("torch =", torch.__version__)
print("git =", torch.version.git_version)
print("file =", torch.__file__)
print("cuda build =", torch.version.cuda)
print("cuda available =", torch.cuda.is_available())

assert str(torch.__file__).startswith("/patchsite/"), torch.__file__
lib = Path(torch.__file__).parent / "lib" / "libtorch_cpu.so"
print("libtorch_cpu =", lib)
PY

echo
echo "Patchsite ready: $PATCH_SITE"
echo "Runtime:"
echo "  --bind \"$PATCH_SITE:/patchsite\""
echo "  --env PYTHONPATH=/patchsite"
