#!/usr/bin/env bash
set -euo pipefail

JUMP_HOST="${JUMP_HOST:-pnhan}"
GPU_HOST="${GPU_HOST:-u001013@10.1.1.238}"
LOCAL_PORT="${LOCAL_PORT:-18000}"
REMOTE_PORT="${REMOTE_PORT:-8000}"

echo "Opening SSH tunnel:"
echo "  localhost:${LOCAL_PORT}"
echo "    -> ${JUMP_HOST}"
echo "    -> ${GPU_HOST}"
echo "    -> localhost:${REMOTE_PORT}"

exec ssh \
  -N \
  -o ExitOnForwardFailure=yes \
  -J "$JUMP_HOST" \
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
  "$GPU_HOST"
