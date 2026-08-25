#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/llm_serving}"
IMAGE="${IMAGE:-$PROJECT_ROOT/build/vllm.sif}"
WORK_ROOT="${WORK_ROOT:-$PROJECT_ROOT/build/torch-gloo-port}"
SRC="$WORK_ROOT/pytorch"
BUILD_VENV="$WORK_ROOT/venv"
WHEELHOUSE="$WORK_ROOT/wheelhouse"

PYTORCH_SHA="2236df1770800ffea5697b11b0bb0d910b2e59e1"
GLOO_SHA="5354032ea08eadd7fc4456477f7f7c6308818509"

MAX_JOBS="${MAX_JOBS:-8}"
TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-7.0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHER="$SCRIPT_DIR/patch_gloo_port_range.py"

mkdir -p "$WORK_ROOT" "$WHEELHOUSE"

if [[ ! -f "$IMAGE" ]]; then
    echo "ERROR: image not found: $IMAGE" >&2
    exit 2
fi

echo "============================================================"
echo " BUILD PREFLIGHT"
echo "============================================================"
echo "image=$IMAGE"
echo "work_root=$WORK_ROOT"
echo "pytorch_sha=$PYTORCH_SHA"
echo "gloo_sha=$GLOO_SHA"
echo "arch=$TORCH_CUDA_ARCH_LIST"
echo "max_jobs=$MAX_JOBS"

apptainer exec "$IMAGE" bash -lc '
set -e
echo "python: $(python3 --version)"
echo "gcc:    $(gcc --version | head -1)"
echo "g++:    $(g++ --version | head -1)"
echo "cmake:  $(cmake --version 2>/dev/null | head -1 || true)"
echo "ninja:  $(ninja --version 2>/dev/null || true)"
echo "nvcc:"
if ! command -v nvcc >/dev/null 2>&1; then
  echo "MISSING"
  exit 91
fi
nvcc --version | tail -4
'

echo
echo "============================================================"
echo " CHECKOUT EXACT PYTORCH"
echo "============================================================"

if [[ ! -d "$SRC/.git" ]]; then
    git clone --filter=blob:none --no-checkout \
        https://github.com/pytorch/pytorch.git "$SRC"
fi

git -C "$SRC" fetch origin "$PYTORCH_SHA"
git -C "$SRC" checkout --detach "$PYTORCH_SHA"
git -C "$SRC" submodule sync --recursive
git -C "$SRC" submodule update --init --recursive

ACTUAL_TORCH="$(git -C "$SRC" rev-parse HEAD)"
ACTUAL_GLOO="$(git -C "$SRC/third_party/gloo" rev-parse HEAD)"

[[ "$ACTUAL_TORCH" == "$PYTORCH_SHA" ]] || {
  echo "ERROR: wrong PyTorch commit: $ACTUAL_TORCH" >&2
  exit 3
}
[[ "$ACTUAL_GLOO" == "$GLOO_SHA" ]] || {
  echo "ERROR: wrong Gloo commit: $ACTUAL_GLOO" >&2
  exit 3
}

echo "PyTorch commit OK: $ACTUAL_TORCH"
echo "Gloo commit OK:    $ACTUAL_GLOO"

echo
echo "============================================================"
echo " APPLY GLOO PORT-RANGE PATCH"
echo "============================================================"

(
  cd "$SRC"
  python3 "$PATCHER"
)

grep -n 'GLOO_PORT_MIN' \
  "$SRC/third_party/gloo/gloo/transport/tcp/listener.cc"

echo
echo "============================================================"
echo " BUILD TORCH WHEEL"
echo "============================================================"

mkdir -p "$BUILD_VENV" "$WHEELHOUSE"

apptainer exec \
  --bind "$SRC:/workspace/pytorch" \
  --bind "$BUILD_VENV:/workspace/venv" \
  --bind "$WHEELHOUSE:/wheelhouse" \
  "$IMAGE" \
  bash -lc "
set -euo pipefail

if [[ ! -x /workspace/venv/bin/python ]]; then
  python3 -m venv /workspace/venv
fi

source /workspace/venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install cmake ninja pyyaml typing_extensions requests
python -m pip install mkl-static mkl-include

cd /workspace/pytorch
python -m pip install -r requirements.txt

export CMAKE_PREFIX_PATH=\"/workspace/venv:\${CMAKE_PREFIX_PATH:-}\"

export PYTORCH_BUILD_VERSION='2.6.0+cu124'
export PYTORCH_BUILD_NUMBER=1
export _GLIBCXX_USE_CXX11_ABI=0

export USE_DISTRIBUTED=1
export USE_GLOO=1
export USE_CUDA=1
export USE_NCCL=1
export BUILD_TEST=0

export TORCH_CUDA_ARCH_LIST='$TORCH_CUDA_ARCH_LIST'
export MAX_JOBS='$MAX_JOBS'

rm -rf build dist
python setup.py bdist_wheel

cp -v dist/torch-*.whl /wheelhouse/
"

echo
echo "============================================================"
echo " BUILD COMPLETE"
echo "============================================================"
ls -lh "$WHEELHOUSE"/torch-*.whl
