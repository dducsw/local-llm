#!/usr/bin/env bash
# ==============================================================================
# Create Writable 1Cat-vLLM Apptainer Sandbox
# ==============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT/build"
DEF_FILE="$ROOT/defs/1cat_vllm.def"
OUT_SANDBOX="${1:-$BUILD_DIR/1cat_vllm_sandbox}"

mkdir -p "$BUILD_DIR"

echo "============================================================"
echo " BUILD 1CAT-vLLM WRITABLE SANDBOX"
echo "============================================================"
echo "Definition     : $DEF_FILE"
echo "Output Sandbox : $OUT_SANDBOX"
echo "============================================================"

if [ ! -f "$DEF_FILE" ]; then
    echo "ERROR: Definition file not found at: $DEF_FILE"
    exit 1
fi

rm -rf "$OUT_SANDBOX"

apptainer build --sandbox --fakeroot "$OUT_SANDBOX" "$DEF_FILE"

echo "============================================================"
echo " SANDBOX CREATED: $OUT_SANDBOX"
echo "============================================================"
