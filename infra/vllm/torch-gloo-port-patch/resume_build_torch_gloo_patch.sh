#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
IMAGE="${IMAGE:-$ROOT/build/vllm.sif}"
WORK_ROOT="${WORK_ROOT:-$ROOT/build/torch-gloo-port}"
CACHE_ROOT="${CACHE_ROOT:-${SCRATCH:-$HOME/.cache}/llm-serving}"

PYTORCH_SHA="${PYTORCH_SHA:-2236df1770800ffea5697b11b0bb0d910b2e59e1}"
GLOO_SHA="${GLOO_SHA:-5354032ea08eadd7fc4456477f7f7c6308818509}"

CMAKE_VERSION="${CMAKE_VERSION:-3.31.6}"
MAX_JOBS="${MAX_JOBS:-8}"
TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-7.0}"
TORCH_BUILD_VERSION="${TORCH_BUILD_VERSION:-2.6.0+cu124}"

SRC="$WORK_ROOT/pytorch"
VENV="$WORK_ROOT/venv"
WHEELHOUSE="$WORK_ROOT/wheelhouse"

echo "============================================================"
echo " RESUME PATCHED PYTORCH BUILD"
echo "============================================================"
echo "image=$IMAGE"
echo "work_root=$WORK_ROOT"
echo "cmake=$CMAKE_VERSION"
echo "arch=$TORCH_CUDA_ARCH_LIST"
echo "max_jobs=$MAX_JOBS"

test -f "$IMAGE" || { echo "ERROR: image not found: $IMAGE"; exit 2; }
test -d "$SRC/.git" || { echo "ERROR: PyTorch checkout missing: $SRC"; exit 2; }
test -x "$VENV/bin/python" || { echo "ERROR: build venv missing: $VENV"; exit 2; }

cd "$SRC"

ACTUAL_PT="$(git rev-parse HEAD)"
ACTUAL_GLOO="$(git -C third_party/gloo rev-parse HEAD)"

[[ "$ACTUAL_PT" == "$PYTORCH_SHA" ]] || {
  echo "ERROR: wrong PyTorch commit: $ACTUAL_PT"; exit 3;
}
[[ "$ACTUAL_GLOO" == "$GLOO_SHA" ]] || {
  echo "ERROR: wrong Gloo commit: $ACTUAL_GLOO"; exit 3;
}
grep -q 'GLOO_PORT_MIN' third_party/gloo/gloo/transport/tcp/listener.cc || {
  echo "ERROR: Gloo port-range patch is missing"; exit 4;
}

echo "PyTorch commit OK: $ACTUAL_PT"
echo "Gloo commit OK:    $ACTUAL_GLOO"
echo "Gloo patch OK"

mkdir -p "$WHEELHOUSE"
mkdir -p "$CACHE_ROOT"/{huggingface,vllm,xdg}

apptainer exec \
  --nv \
  --cleanenv \
  --bind "$WORK_ROOT:/workspace" \
  --bind "$CACHE_ROOT:/cache" \
  "$IMAGE" \
  /bin/bash -lc "
set -euo pipefail
source /workspace/venv/bin/activate

python --version
python -m pip install --no-cache-dir --force-reinstall 'cmake==$CMAKE_VERSION'
hash -r
cmake --version

CMV=\"\$(cmake --version | awk 'NR==1 {print \$3}')\"
case \"\$CMV\" in
  4.*) echo \"ERROR: CMake is still 4.x: \$CMV\"; exit 10 ;;
esac

cd /workspace/pytorch
grep -n -E 'GLOO_PORT_MIN|GLOO_PORT_MAX' \
  third_party/gloo/gloo/transport/tcp/listener.cc | head -20

rm -rf build dist
mkdir -p /workspace/wheelhouse

export MAX_JOBS='$MAX_JOBS'
export TORCH_CUDA_ARCH_LIST='$TORCH_CUDA_ARCH_LIST'
export PYTORCH_BUILD_VERSION='$TORCH_BUILD_VERSION'
export PYTORCH_BUILD_NUMBER=1
export USE_CUDA=1
export USE_DISTRIBUTED=1
export USE_GLOO=1
export USE_NCCL=1
export BUILD_TEST=0
export USE_CUDNN=0
export USE_CUSPARSELT=0
export USE_CUDSS=0
export USE_CUFILE=0
export USE_XPU=0
export USE_ROCM=0
export GLIBCXX_USE_CXX11_ABI=0

echo \"MAX_JOBS=\$MAX_JOBS\"
echo \"TORCH_CUDA_ARCH_LIST=\$TORCH_CUDA_ARCH_LIST\"
echo \"PYTORCH_BUILD_VERSION=\$PYTORCH_BUILD_VERSION\"
echo \"GLIBCXX_USE_CXX11_ABI=\$GLIBCXX_USE_CXX11_ABI\"
nvcc --version | tail -4

python setup.py bdist_wheel

ls -lh dist/*.whl
cp -fv dist/*.whl /workspace/wheelhouse/
"

echo
echo "============================================================"
echo " BUILD FINISHED"
echo "============================================================"
ls -lh "$WHEELHOUSE"/*.whl
