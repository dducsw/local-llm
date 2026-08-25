#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
SANDBOX="${SANDBOX:-$ROOT/build/vllm-gloo-nccl-patched.sandbox}"
WORK="${WORK:-$ROOT/build/vllm-custom}"
SRC="${SRC:-$WORK/vllm}"
VENV="${VENV:-$WORK/venv}"
WHEELHOUSE="${WHEELHOUSE:-$WORK/wheelhouse}"

VLLM_TAG="${VLLM_TAG:-v0.8.5.post1}"
MAX_JOBS="${MAX_JOBS:-8}"
NVCC_THREADS="${NVCC_THREADS:-1}"
TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-7.0}"

mkdir -p "$WORK" "$WHEELHOUSE"

[[ -d "$SANDBOX" ]] || {
  echo "ERROR: sandbox missing: $SANDBOX"
  exit 2
}

echo "============================================================"
echo " BUILD vLLM AGAINST PATCHED TORCH"
echo "============================================================"
echo "sandbox=$SANDBOX"
echo "src=$SRC"
echo "tag=$VLLM_TAG"
echo "arch=$TORCH_CUDA_ARCH_LIST"
echo

if [[ ! -d "$SRC/.git" ]]; then
  rm -rf "$SRC"
  git clone --recursive --branch "$VLLM_TAG" --depth 1 \
    https://github.com/vllm-project/vllm.git "$SRC"
else
  git -C "$SRC" fetch --tags
  git -C "$SRC" checkout "$VLLM_TAG"
  git -C "$SRC" submodule update --init --recursive
fi

echo "=== source revision ==="
git -C "$SRC" describe --tags --always
git -C "$SRC" rev-parse HEAD

rm -rf "$VENV"
mkdir -p "$WHEELHOUSE"

apptainer exec \
  --nv \
  --cleanenv \
  --bind "$WORK:$WORK" \
  "$SANDBOX" \
  bash -lc "
set -euo pipefail

python3 -m venv --system-site-packages '$VENV'
source '$VENV/bin/activate'

python - <<'PY'
import torch
print('torch =', torch.__version__)
print('torch git =', torch.version.git_version)
print('cuda =', torch.version.cuda)
print('CXX11 ABI =', torch._C._GLIBCXX_USE_CXX11_ABI)
PY

cd '$SRC'

echo
echo '=== configure vLLM for existing/custom Torch ==='
python use_existing_torch.py

python -m pip install --upgrade 'pip<26'
python -m pip install -r requirements/build.txt

export TORCH_CUDA_ARCH_LIST='$TORCH_CUDA_ARCH_LIST'
export MAX_JOBS='$MAX_JOBS'
export NVCC_THREADS='$NVCC_THREADS'
export CMAKE_BUILD_TYPE=Release

echo
echo '=== build environment ==='
python --version
cmake --version | head -1
nvcc --version | tail -4
echo TORCH_CUDA_ARCH_LIST=\$TORCH_CUDA_ARCH_LIST
echo MAX_JOBS=\$MAX_JOBS
echo NVCC_THREADS=\$NVCC_THREADS

echo
echo '=== build wheel ==='
rm -rf build dist
python -m pip wheel \
  --no-build-isolation \
  --no-deps \
  -w '$WHEELHOUSE' \
  .

echo
echo '=== wheels ==='
ls -lh '$WHEELHOUSE'/vllm-*.whl
"

WHEEL="$(find "$WHEELHOUSE" -maxdepth 1 -type f -name 'vllm-*.whl' | sort | tail -1)"
[[ -f "$WHEEL" ]] || {
  echo "ERROR: vLLM wheel not produced"
  exit 10
}

echo
echo "============================================================"
echo " VLLM BUILD COMPLETE"
echo "============================================================"
echo "$WHEEL"
