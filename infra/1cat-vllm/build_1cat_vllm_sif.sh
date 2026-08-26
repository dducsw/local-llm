#!/usr/bin/env bash
# ==============================================================================
# Build Standalone 1Cat-vLLM Apptainer SIF Image
# ==============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT/build"
DEF_FILE="$ROOT/defs/1cat_vllm.def"
OUT_IMAGE="${1:-$BUILD_DIR/1cat-vllm.sif}"

mkdir -p "$BUILD_DIR"

echo "============================================================"
echo " BUILD 1CAT-vLLM APPTAINER SIF"
echo "============================================================"
echo "Definition  : $DEF_FILE"
echo "Output SIF  : $OUT_IMAGE"
echo "Started at  : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

if [ ! -f "$DEF_FILE" ]; then
    echo "ERROR: Definition file not found at: $DEF_FILE"
    exit 1
fi

rm -f "$OUT_IMAGE"

if ! apptainer build --fakeroot "$OUT_IMAGE" "$DEF_FILE"; then
    echo
    echo "ERROR: apptainer build --fakeroot failed."
    exit 20
fi

echo
echo "============================================================"
echo " BUILD COMPLETE"
echo " Image created: $OUT_IMAGE ($(du -sh "$OUT_IMAGE" | cut -f1))"
echo "============================================================"
