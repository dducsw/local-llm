#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
BASE_IMAGE="${BASE_IMAGE:-$ROOT/build/vllm.sif}"
WORK_ROOT="${WORK_ROOT:-$ROOT/build/torch-gloo-port}"
WHEELHOUSE="${WHEELHOUSE:-$WORK_ROOT/wheelhouse}"
OUT_IMAGE="${OUT_IMAGE:-$ROOT/build/vllm-gloo-patched.sif}"
DEF_FILE="${DEF_FILE:-$WORK_ROOT/vllm-gloo-patched.def}"

WHEEL="$(find "$WHEELHOUSE" -maxdepth 1 -type f \
  -name 'torch-2.6.0+cu124-*.whl' | sort | head -1)"

[[ -f "$BASE_IMAGE" ]] || {
  echo "ERROR: base image not found: $BASE_IMAGE"
  exit 2
}

[[ -n "$WHEEL" && -f "$WHEEL" ]] || {
  echo "ERROR: patched torch wheel not found under: $WHEELHOUSE"
  exit 2
}

WHEEL_BASENAME="$(basename "$WHEEL")"
CONTAINER_WHEEL="/opt/$WHEEL_BASENAME"

echo "============================================================"
echo " BUILD PATCHED vLLM SIF"
echo "============================================================"
echo "base_image=$BASE_IMAGE"
echo "wheel=$WHEEL"
echo "wheel_basename=$WHEEL_BASENAME"
echo "container_wheel=$CONTAINER_WHEEL"
echo "output=$OUT_IMAGE"
echo "def=$DEF_FILE"
echo

cat >"$DEF_FILE" <<EOF
Bootstrap: localimage
From: $BASE_IMAGE

%files
    $WHEEL $CONTAINER_WHEEL

%post
    set -eux

    echo "Installing patched torch wheel:"
    ls -lh "$CONTAINER_WHEEL"

    python3 -m pip install \
      --no-cache-dir \
      --no-deps \
      --force-reinstall \
      "$CONTAINER_WHEEL"

%test
    python3 - <<'PY'
import torch
import torch.distributed as dist

print("torch =", torch.__version__)
print("torch git =", torch.version.git_version)
print("cuda =", torch.version.cuda)
print("gloo available =", dist.is_gloo_available())
print("nccl available =", dist.is_nccl_available())

assert torch.__version__.startswith("2.6.0")
assert dist.is_gloo_available()
PY

%labels
    org.opencontainers.image.title "vLLM with patched PyTorch Gloo port range"
    gloo.port.range.env "GLOO_PORT_MIN,GLOO_PORT_MAX"
EOF

echo "=== Generated definition ==="
cat "$DEF_FILE"
echo

rm -f "$OUT_IMAGE"

echo "=== Apptainer build ==="

if ! apptainer build --fakeroot "$OUT_IMAGE" "$DEF_FILE"; then
  echo
  echo "ERROR: apptainer build --fakeroot failed"
  echo "Definition file preserved at:"
  echo "  $DEF_FILE"
  exit 20
fi

echo
echo "============================================================"
echo " VERIFY PATCHED IMAGE"
echo "============================================================"

apptainer exec --cleanenv "$OUT_IMAGE" python3 - <<'PY'
import torch
import torch.distributed as dist

print("torch =", torch.__version__)
print("torch git =", torch.version.git_version)
print("cuda =", torch.version.cuda)
print("gloo =", dist.is_gloo_available())
print("nccl =", dist.is_nccl_available())
PY

echo
echo "=== Look for patch marker in torch binaries ==="

if apptainer exec --cleanenv "$OUT_IMAGE" \
  bash -lc '
    TORCH_LIB="$(python3 - <<'"'"'PY'"'"'
import os, torch
print(os.path.join(os.path.dirname(torch.__file__), "lib"))
PY
)"
    echo "torch_lib=$TORCH_LIB"
    grep -aR -m1 "GLOO_PORT_MIN" "$TORCH_LIB" >/dev/null 2>&1
  '
then
  echo "PATCH MARKER VERIFIED: GLOO_PORT_MIN"
else
  echo "WARNING: literal marker not found by grep."
  echo "The 2-node Gloo smoke test is the authoritative verification."
fi

echo
echo "============================================================"
echo " DONE"
echo "============================================================"
echo "$OUT_IMAGE"
