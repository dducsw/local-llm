#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$HOME/llm_serving}"
BASE_IMAGE="${BASE_IMAGE:-$ROOT/build/vllm.sif}"
WORK_ROOT="${WORK_ROOT:-$ROOT/build/torch-gloo-port}"
WHEELHOUSE="${WHEELHOUSE:-$WORK_ROOT/wheelhouse}"
OUT_SANDBOX="${OUT_SANDBOX:-$ROOT/build/vllm-gloo-patched.sandbox}"
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
echo " BUILD PATCHED vLLM SANDBOX"
echo "============================================================"
echo "base_image=$BASE_IMAGE"
echo "wheel=$WHEEL"
echo "output=$OUT_SANDBOX"
echo

cat >"$DEF_FILE" <<EOF
Bootstrap: localimage
From: $BASE_IMAGE

%files
    $WHEEL $CONTAINER_WHEEL

%post
    set -eux
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
assert dist.is_nccl_available()
PY
EOF

rm -rf "$OUT_SANDBOX"

echo "=== Apptainer sandbox build ==="
apptainer build \
  --fakeroot \
  --sandbox \
  "$OUT_SANDBOX" \
  "$DEF_FILE"

echo
echo "============================================================"
echo " VERIFY PATCHED SANDBOX"
echo "============================================================"

apptainer exec --cleanenv "$OUT_SANDBOX" python3 - <<'PY'
import torch
import torch.distributed as dist
print("torch =", torch.__version__)
print("torch git =", torch.version.git_version)
print("cuda =", torch.version.cuda)
print("gloo =", dist.is_gloo_available())
print("nccl =", dist.is_nccl_available())
PY

echo
echo "=== Patch marker ==="

if apptainer exec --cleanenv "$OUT_SANDBOX" bash -lc '
  LIB="$(python3 - <<'"'"'PY'"'"'
import os, torch
print(os.path.join(os.path.dirname(torch.__file__), "lib"))
PY
)"
  grep -aR -m1 "GLOO_PORT_MIN" "$LIB" >/dev/null 2>&1
'; then
  echo "PATCH MARKER VERIFIED: GLOO_PORT_MIN"
else
  echo "WARNING: patch literal not found by grep."
  echo "The 2-node runtime smoke test is authoritative."
fi

echo
echo "============================================================"
echo " SANDBOX READY"
echo "============================================================"
echo "$OUT_SANDBOX"
