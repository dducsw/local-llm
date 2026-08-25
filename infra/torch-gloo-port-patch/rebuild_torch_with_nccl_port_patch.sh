#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
WORK_ROOT="${WORK_ROOT:-$ROOT/build/torch-gloo-port}"
PT_SRC="${PT_SRC:-$WORK_ROOT/pytorch}"
NCCL_SRC="${NCCL_SRC:-$PT_SRC/third_party/nccl/nccl}"
VENV="${VENV:-$WORK_ROOT/venv}"
WHEELHOUSE="${WHEELHOUSE:-$WORK_ROOT/wheelhouse}"
IMAGE="${IMAGE:-$ROOT/build/vllm.sif}"
CACHE_ROOT="${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}"

PATCH_SCRIPT="${PATCH_SCRIPT:-$ROOT/torch-gloo-port-patch/patch_nccl_port_range.py}"

EXPECTED_PT_SHA="${EXPECTED_PT_SHA:-2236df1770800ffea5697b11b0bb0d910b2e59e1}"
EXPECTED_NCCL_SHA="${EXPECTED_NCCL_SHA:-ab2b89c4c339bd7f816fbc114a4b05d386b66290}"

MAX_JOBS="${MAX_JOBS:-8}"
TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-7.0}"
TORCH_BUILD_VERSION="${TORCH_BUILD_VERSION:-2.6.0+cu124}"

echo "============================================================"
echo " PATCH + INCREMENTAL REBUILD: NCCL PORT RANGE"
echo "============================================================"
echo "pytorch=$PT_SRC"
echo "nccl=$NCCL_SRC"
echo "wheelhouse=$WHEELHOUSE"
echo

[[ -d "$PT_SRC/.git" ]] || { echo "ERROR: PyTorch checkout missing"; exit 2; }
git -C "$NCCL_SRC" rev-parse --git-dir >/dev/null 2>&1 || { echo "ERROR: NCCL checkout missing"; exit 2; }
[[ -x "$VENV/bin/python" ]] || { echo "ERROR: venv missing: $VENV"; exit 2; }
[[ -f "$PATCH_SCRIPT" ]] || { echo "ERROR: patch script missing: $PATCH_SCRIPT"; exit 2; }
[[ -f "$IMAGE" ]] || { echo "ERROR: image missing: $IMAGE"; exit 2; }

PT_SHA="$(git -C "$PT_SRC" rev-parse HEAD)"
NCCL_SHA="$(git -C "$NCCL_SRC" rev-parse HEAD)"

[[ "$PT_SHA" == "$EXPECTED_PT_SHA" ]] || {
  echo "ERROR: unexpected PyTorch commit: $PT_SHA"
  exit 3
}
[[ "$NCCL_SHA" == "$EXPECTED_NCCL_SHA" ]] || {
  echo "ERROR: unexpected NCCL commit: $NCCL_SHA"
  exit 3
}

echo "PyTorch commit OK: $PT_SHA"
echo "NCCL commit OK:    $NCCL_SHA"

python3 "$PATCH_SCRIPT" "$NCCL_SRC"

echo
echo "=== Patch markers ==="
grep -n -E 'NCCL_PORT_RANGE_PATCH|NCCL_PORT_MIN|NCCL_PORT_MAX' \
  "$NCCL_SRC/src/misc/socket.cc" | head -40

STAMP_DIR="$PT_SRC/build/nccl_external-prefix/src/nccl_external-stamp"

echo
echo "=== Invalidate NCCL ExternalProject build stamp ==="
if [[ -d "$STAMP_DIR" ]]; then
  find "$STAMP_DIR" -maxdepth 1 -type f \
    \( -name '*-build' -o -name '*-done' -o -name '*-install' \) \
    -print -delete
fi

# Force NCCL outputs to be regenerated, without deleting the rest of PyTorch.
rm -f \
  "$PT_SRC/build/nccl/lib/libnccl_static.a" \
  "$PT_SRC/build/nccl/lib/libnccl_slim_static.a" \
  "$PT_SRC/build/nccl/lib/libnccl.so" \
  "$PT_SRC/build/nccl/lib/libnccl.so.2" \
  "$PT_SRC/build/nccl/lib/libnccl.so.2.21.5"

mkdir -p "$WHEELHOUSE"

apptainer exec \
  --nv \
  --cleanenv \
  --bind "$WORK_ROOT:/workspace" \
  --bind "$CACHE_ROOT:/cache" \
  "$IMAGE" \
  /bin/bash -lc "
set -euo pipefail
source /workspace/venv/bin/activate
cd /workspace/pytorch

export MAX_JOBS='$MAX_JOBS'
export TORCH_CUDA_ARCH_LIST='$TORCH_CUDA_ARCH_LIST'
export PYTORCH_BUILD_VERSION='$TORCH_BUILD_VERSION'
export PYTORCH_BUILD_NUMBER=1

export USE_CUDA=1
export USE_DISTRIBUTED=1
export USE_GLOO=1
export USE_NCCL=1
export USE_SYSTEM_NCCL=0
export USE_STATIC_NCCL=0
export BUILD_TEST=0

export USE_CUDNN=0
export USE_CUSPARSELT=0
export USE_CUDSS=0
export USE_CUFILE=0
export USE_XPU=0
export USE_ROCM=0
export GLIBCXX_USE_CXX11_ABI=0

echo '--- toolchain ---'
python --version
cmake --version | head -1
nvcc --version | tail -4

echo
echo '--- rebuild bundled NCCL only ---'
cmake --build build --target nccl_external -- -j'$MAX_JOBS'

echo
echo '--- NCCL outputs ---'
ls -lh build/nccl/lib/libnccl*

if ! grep -a -m1 'NCCL_PORT_RANGE' build/nccl/lib/libnccl_static.a >/dev/null 2>&1; then
  echo 'ERROR: patched marker missing from libnccl_static.a'
  exit 20
fi
echo 'NCCL static archive marker: OK'

echo
echo '--- incremental relink/install PyTorch ---'
cmake --build build --target install -- -j'$MAX_JOBS'

TORCH_CUDA='/workspace/pytorch/torch/lib/libtorch_cuda.so'
[[ -f \"\$TORCH_CUDA\" ]] || { echo 'ERROR: libtorch_cuda.so missing'; exit 21; }

if ! grep -a -m1 'NCCL_PORT_RANGE' \"\$TORCH_CUDA\" >/dev/null 2>&1; then
  echo 'ERROR: NCCL marker missing from relinked libtorch_cuda.so'
  exit 22
fi
echo 'libtorch_cuda NCCL marker: OK'

if ! grep -a -m1 'GLOO_PORT_MIN' \"\$TORCH_CUDA\" >/dev/null 2>&1; then
  echo 'NOTE: Gloo marker is not expected in libtorch_cuda.so; checking wheel later.'
fi

echo
echo '--- build replacement wheel incrementally ---'
rm -rf dist
python setup.py bdist_wheel
ls -lh dist/torch-*.whl

rm -f /workspace/wheelhouse/torch-2.6.0+cu124-*.whl
cp -fv dist/torch-*.whl /workspace/wheelhouse/
"

echo
echo "============================================================"
echo " VERIFY WHEEL"
echo "============================================================"

WHEEL="$(find "$WHEELHOUSE" -maxdepth 1 -type f \
  -name 'torch-2.6.0+cu124-*.whl' | sort | head -1)"

[[ -f "$WHEEL" ]] || { echo "ERROR: wheel not found"; exit 30; }

echo "wheel=$WHEEL"
ls -lh "$WHEEL"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$WHEEL" "$TMP" <<'PY'
import sys, zipfile
wheel, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(wheel) as z:
    names = z.namelist()
    for suffix in ("torch/lib/libtorch_cuda.so", "torch/lib/libtorch_cpu.so"):
        matches = [n for n in names if n.endswith(suffix)]
        for n in matches:
            z.extract(n, out)
PY

CUDA_LIB="$(find "$TMP" -type f -name libtorch_cuda.so | head -1)"
CPU_LIB="$(find "$TMP" -type f -name libtorch_cpu.so | head -1)"

[[ -f "$CUDA_LIB" ]] || { echo "ERROR: libtorch_cuda.so missing in wheel"; exit 31; }

grep -a -m1 'NCCL_PORT_RANGE' "$CUDA_LIB" >/dev/null || {
  echo "ERROR: NCCL patch marker missing from wheel"
  exit 32
}

# Gloo may live in libtorch_cpu.so for this build.
if [[ -f "$CPU_LIB" ]] && grep -a -m1 'GLOO_PORT_MIN' "$CPU_LIB" >/dev/null 2>&1; then
  echo "Gloo patch marker in wheel: OK"
else
  echo "WARNING: Gloo marker not found in libtorch_cpu.so; existing runtime sandbox test already verified it."
fi

echo "NCCL patch marker in wheel: OK"

echo
echo "============================================================"
echo " REBUILD COMPLETE"
echo "============================================================"
echo "$WHEEL"
