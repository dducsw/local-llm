#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
SANDBOX="${SANDBOX:-$ROOT/build/vllm-gloo-nccl-patched.sandbox}"
WHEELHOUSE="${WHEELHOUSE:-$ROOT/build/vllm-custom/wheelhouse}"

WHEEL="$(find "$WHEELHOUSE" -maxdepth 1 -type f -name 'vllm-*.whl' | sort | tail -1)"

[[ -d "$SANDBOX" ]] || {
  echo "ERROR: sandbox missing: $SANDBOX"
  exit 2
}
[[ -f "$WHEEL" ]] || {
  echo "ERROR: rebuilt vLLM wheel missing in $WHEELHOUSE"
  exit 2
}

echo "Installing:"
echo "  $WHEEL"
echo "into:"
echo "  $SANDBOX"

apptainer exec \
  --fakeroot \
  --writable \
  --bind "$WHEELHOUSE:$WHEELHOUSE" \
  "$SANDBOX" \
  python3 -m pip install \
    --no-deps \
    --force-reinstall \
    "$WHEEL"

apptainer exec \
  --fakeroot \
  --writable \
  "$SANDBOX" \
  python3 -m pip uninstall -y torchvision >/dev/null 2>&1 || true

echo
echo "=== verify vLLM native extension ==="

apptainer exec \
  --nv \
  --cleanenv \
  "$SANDBOX" \
  python3 - <<'PY'
import torch
print("torch =", torch.__version__)
print("torch git =", torch.version.git_version)
print("CXX11 ABI =", torch._C._GLIBCXX_USE_CXX11_ABI)

import vllm
print("vllm =", vllm.__version__)

import vllm._C
print("vllm._C import = OK")

try:
    import xformers
    import xformers.ops
    print("xformers =", xformers.__version__)
    print("xformers.ops import = OK")
except Exception as e:
    print("XFORMERS_IMPORT_FAILED:", repr(e))
    raise
PY

echo
echo "SANDBOX READY FOR vLLM RETEST"
