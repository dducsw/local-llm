#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
BASE_IMAGE="${BASE_IMAGE:-$ROOT/build/vllm.sif}"
WORK_ROOT="${WORK_ROOT:-$ROOT/build/torch-gloo-port}"
WHEELHOUSE="${WHEELHOUSE:-$WORK_ROOT/wheelhouse}"
OUT_SANDBOX="${OUT_SANDBOX:-$ROOT/build/vllm-gloo-nccl-patched.sandbox}"
DEF_FILE="${DEF_FILE:-$WORK_ROOT/vllm-gloo-nccl-patched.def}"

WHEEL="$(find "$WHEELHOUSE" -maxdepth 1 -type f \
  -name 'torch-2.6.0+cu124-*.whl' | sort | head -1)"

[[ -f "$BASE_IMAGE" ]] || { echo "ERROR: base image missing"; exit 2; }
[[ -f "$WHEEL" ]] || { echo "ERROR: patched wheel missing"; exit 2; }

BASENAME="$(basename "$WHEEL")"

cat > "$DEF_FILE" <<EOF
Bootstrap: localimage
From: $BASE_IMAGE

%files
    $WHEEL /opt/$BASENAME

%post
    set -eux
    python3 -m pip install --no-cache-dir --no-deps --force-reinstall /opt/$BASENAME

%test
    python3 - <<'PY'
import os
import torch
import torch.distributed as dist

print("torch =", torch.__version__)
print("torch git =", torch.version.git_version)
print("cuda =", torch.version.cuda)
print("nccl =", torch.cuda.nccl.version())
print("gloo =", dist.is_gloo_available())
print("nccl backend =", dist.is_nccl_available())

torch_dir = os.path.dirname(torch.__file__)
cuda_lib = os.path.join(torch_dir, "lib", "libtorch_cuda.so")
cpu_lib = os.path.join(torch_dir, "lib", "libtorch_cpu.so")

cuda_data = open(cuda_lib, "rb").read()
cpu_data = open(cpu_lib, "rb").read()

assert b"NCCL_PORT_RANGE" in cuda_data
assert b"GLOO_PORT_MIN" in cpu_data or b"GLOO_PORT_MIN" in cuda_data

print("Gloo marker = True")
print("NCCL marker = True")
PY
EOF

rm -rf "$OUT_SANDBOX"
apptainer build --fakeroot --sandbox "$OUT_SANDBOX" "$DEF_FILE"

echo
echo "=== FINAL SANDBOX VERIFY ==="
apptainer exec --cleanenv "$OUT_SANDBOX" python3 - <<'PY'
import os, torch
import torch.distributed as dist

torch_dir = os.path.dirname(torch.__file__)
cuda_lib = os.path.join(torch_dir, "lib", "libtorch_cuda.so")
cpu_lib = os.path.join(torch_dir, "lib", "libtorch_cpu.so")
cuda_data = open(cuda_lib, "rb").read()
cpu_data = open(cpu_lib, "rb").read()

print("torch =", torch.__version__)
print("git =", torch.version.git_version)
print("cuda =", torch.version.cuda)
print("nccl =", torch.cuda.nccl.version())
print("gloo =", dist.is_gloo_available())
print("nccl backend =", dist.is_nccl_available())
print("GLOO_PORT_MIN marker =", b"GLOO_PORT_MIN" in cpu_data or b"GLOO_PORT_MIN" in cuda_data)
print("NCCL_PORT_RANGE marker =", b"NCCL_PORT_RANGE" in cuda_data)
PY

echo
echo "SANDBOX READY:"
echo "$OUT_SANDBOX"
