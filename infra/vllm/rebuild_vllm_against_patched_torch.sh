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

CCACHE_DIR="${CCACHE_DIR:-$WORK/ccache}"
CCACHE_TEMPDIR="${CCACHE_TEMPDIR:-$CCACHE_DIR/tmp}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$WORK/xdg-cache}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$WORK/xdg-config}"

mkdir -p \
  "$WORK" \
  "$WHEELHOUSE" \
  "$CCACHE_DIR" \
  "$CCACHE_TEMPDIR" \
  "$XDG_CACHE_HOME" \
  "$XDG_CONFIG_HOME"

[[ -d "$SANDBOX" ]] || {
  echo "ERROR: sandbox missing: $SANDBOX"
  exit 2
}

echo "============================================================"
echo " vLLM CUSTOM TORCH BUILD v2"
echo "============================================================"
echo "sandbox=$SANDBOX"
echo "work=$WORK"
echo "src=$SRC"
echo "tag=$VLLM_TAG"
echo "arch=$TORCH_CUDA_ARCH_LIST"
echo "ccache=$CCACHE_DIR"
echo

# ----------------------------------------------------------------------
# 1) Check runtime Torch ABI.
# ----------------------------------------------------------------------
TORCH_ABI="$(
  apptainer exec --cleanenv "$SANDBOX" \
    python3 -c 'import torch; print(int(torch._C._GLIBCXX_USE_CXX11_ABI))'
)"

echo "Torch runtime CXX11 ABI = $TORCH_ABI"

# Print Torch CMake metadata. If it disagrees with runtime ABI, fix the
# generated TorchConfig.cmake inside the writable sandbox before vLLM config.
TORCH_CONFIG="$(
  apptainer exec --cleanenv "$SANDBOX" python3 - <<'PY'
import os, torch
print(os.path.join(
    os.path.dirname(torch.__file__),
    "share", "cmake", "Torch", "TorchConfig.cmake"))
PY
)"

echo "TorchConfig = $TORCH_CONFIG"

CONFIG_LINE="$(
  apptainer exec --cleanenv "$SANDBOX" \
    grep -E '_GLIBCXX_USE_CXX11_ABI=[01]' "$TORCH_CONFIG" | head -1 || true
)"
echo "TorchConfig ABI line: ${CONFIG_LINE:-<not found>}"

if [[ -n "$CONFIG_LINE" ]] && ! grep -q "_GLIBCXX_USE_CXX11_ABI=$TORCH_ABI" <<<"$CONFIG_LINE"; then
  echo
  echo "Torch runtime ABI and TorchConfig ABI disagree."
  echo "Synchronizing TorchConfig to runtime ABI=$TORCH_ABI ..."

  apptainer exec \
    --fakeroot \
    --writable \
    --env "TORCH_ABI=$TORCH_ABI" \
    "$SANDBOX" \
    python3 - <<'PY'
import os
import re
import torch

abi = os.environ["TORCH_ABI"]
path = os.path.join(
    os.path.dirname(torch.__file__),
    "share", "cmake", "Torch", "TorchConfig.cmake")

text = open(path).read()
new, count = re.subn(
    r"_GLIBCXX_USE_CXX11_ABI=[01]",
    f"_GLIBCXX_USE_CXX11_ABI={abi}",
    text)

if count == 0:
    raise SystemExit(
        f"ERROR: no _GLIBCXX_USE_CXX11_ABI flag found in {path}")

open(path, "w").write(new)
print(f"Patched {count} ABI occurrence(s) in {path} to ABI={abi}")
PY
fi

# ----------------------------------------------------------------------
# 2) vLLM source.
# ----------------------------------------------------------------------
if [[ ! -d "$SRC/.git" ]]; then
  rm -rf "$SRC"
  git clone --recursive --branch "$VLLM_TAG" --depth 1 \
    https://github.com/vllm-project/vllm.git "$SRC"
else
  git -C "$SRC" checkout "$VLLM_TAG"
  git -C "$SRC" submodule update --init --recursive
fi

echo
echo "=== vLLM source ==="
git -C "$SRC" describe --tags --always
git -C "$SRC" rev-parse HEAD

# Reuse the venv from the first attempt to avoid downloading everything again.
if [[ ! -x "$VENV/bin/python" ]]; then
  apptainer exec \
    --cleanenv \
    --bind "$WORK:$WORK" \
    "$SANDBOX" \
    python3 -m venv --system-site-packages "$VENV"
fi

# ----------------------------------------------------------------------
# 3) Build using writable cache locations.
# ----------------------------------------------------------------------
apptainer exec \
  --nv \
  --cleanenv \
  --bind "$WORK:$WORK" \
  --env "CCACHE_DIR=$CCACHE_DIR" \
  --env "CCACHE_TEMPDIR=$CCACHE_TEMPDIR" \
  --env "CCACHE_BASEDIR=$SRC" \
  --env "CCACHE_NOHASHDIR=true" \
  --env "XDG_CACHE_HOME=$XDG_CACHE_HOME" \
  --env "XDG_CONFIG_HOME=$XDG_CONFIG_HOME" \
  "$SANDBOX" \
  bash -lc "
set -euo pipefail

source '$VENV/bin/activate'
cd '$SRC'

echo '=== Torch visible to vLLM build ==='
python - <<'PY'
import torch
print('torch =', torch.__version__)
print('torch git =', torch.version.git_version)
print('cuda =', torch.version.cuda)
print('CXX11 ABI =', int(torch._C._GLIBCXX_USE_CXX11_ABI))
print('cmake prefix =', torch.utils.cmake_prefix_path)
PY

echo
echo '=== prepare custom-Torch requirements ==='
python use_existing_torch.py

python -m pip install -r requirements/build.txt

# CMake 4 produced unnecessary compatibility warnings in this stack.
# Keep the same CMake version that successfully built patched PyTorch.
python -m pip install --upgrade --force-reinstall 'cmake==3.31.6' ninja

export TORCH_CUDA_ARCH_LIST='$TORCH_CUDA_ARCH_LIST'
export MAX_JOBS='$MAX_JOBS'
export NVCC_THREADS='$NVCC_THREADS'
export CMAKE_BUILD_TYPE=Release

export CCACHE_DIR='$CCACHE_DIR'
export CCACHE_TEMPDIR='$CCACHE_TEMPDIR'
export CCACHE_BASEDIR='$SRC'
export CCACHE_NOHASHDIR=true
export XDG_CACHE_HOME='$XDG_CACHE_HOME'
export XDG_CONFIG_HOME='$XDG_CONFIG_HOME'

echo
echo '=== build environment ==='
python --version
cmake --version | head -1
nvcc --version | tail -4
which ccache || true
ccache --show-config 2>/dev/null | grep -E 'cache_dir|temporary_dir|disable' || true
echo TORCH_CUDA_ARCH_LIST=\$TORCH_CUDA_ARCH_LIST
echo MAX_JOBS=\$MAX_JOBS
echo NVCC_THREADS=\$NVCC_THREADS

# Force a fresh CMake configure so any corrected Torch ABI metadata is used.
rm -rf build dist

echo
echo '=== build vLLM wheel ==='
python -m pip wheel \
  --no-build-isolation \
  --no-deps \
  -w '$WHEELHOUSE' \
  .

echo
echo '=== resulting wheels ==='
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
