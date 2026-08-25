#!/usr/bin/env bash
set -euo pipefail

# 1. Load .env file if available
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/../../.env" ]]; then
  set -a
  source "$SCRIPT_DIR/../../.env"
  set +a
elif [[ -f "$SCRIPT_DIR/../.env" ]]; then
  set -a
  source "$SCRIPT_DIR/../.env"
  set +a
elif [[ -f "$PWD/.env" ]]; then
  set -a
  source "$PWD/.env"
  set +a
fi

# 2. Configuration parameters (priority: CLI Environment > .env)
HPC_HOST="${GPU_HOST:-${HPC_SSH_HOST:-}}"
HPC_USER="${GPU_USER:-${HPC_SSH_USER:-}}"
SSH_KEY="${SSH_KEY:-${HPC_HOST_SSH_KEY:-${HPC_SSH_KEY:-}}}"
JUMP_HOST="${JUMP_HOST:-}"
NODE="${NODE:-${TARGET_NODE:-127.0.0.1}}"
LOCAL_PORT="${LOCAL_PORT:-18000}"
REMOTE_PORT="${REMOTE_PORT:-18000}"

# 3. Validation
if [[ -z "$HPC_HOST" ]]; then
  echo "[ERROR] HPC Host is not configured!" >&2
  echo "Please set HPC_SSH_HOST in your .env file or pass GPU_HOST=<ip_or_host>." >&2
  echo "Example:" >&2
  echo "  GPU_HOST=10.1.1.239 ./scripts/ssh-tunnel.sh" >&2
  echo "  or add 'HPC_SSH_HOST=10.1.1.239' to your .env file." >&2
  exit 1
fi

# Resolve target connection string
if [[ "$HPC_HOST" == *"@"* ]]; then
  TARGET_HOST="$HPC_HOST"
elif [[ -n "$HPC_USER" ]]; then
  TARGET_HOST="${HPC_USER}@${HPC_HOST}"
else
  TARGET_HOST="$HPC_HOST"
fi

echo "=================================================="
echo " Starting SSH Tunnel for vLLM AI Gateway"
echo "=================================================="
echo "  Local Listen:   0.0.0.0:${LOCAL_PORT}"
if [[ -n "$JUMP_HOST" ]]; then
  echo "  Jump Host:     ${JUMP_HOST}"
fi
echo "  Remote Host:   ${TARGET_HOST}"
echo "  Remote Port:   ${REMOTE_PORT}"
if [[ -n "$SSH_KEY" ]]; then
  echo "  SSH Key:       ${SSH_KEY}"
fi
echo "=================================================="

# 3. Build SSH options
SSH_OPTS=(
  -N
  -g
  -o ExitOnForwardFailure=yes
  -o ServerAliveInterval=60
  -o ServerAliveCountMax=3
  -L "0.0.0.0:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}"
)

# Expand ~ in SSH_KEY path for test
EXPANDED_KEY="${SSH_KEY/#\~/$HOME}"
if [[ -n "$SSH_KEY" && -f "$EXPANDED_KEY" ]]; then
  SSH_OPTS+=(-i "$EXPANDED_KEY")
fi

if [[ -n "$JUMP_HOST" ]]; then
  SSH_OPTS+=(-J "$JUMP_HOST")
fi

exec ssh "${SSH_OPTS[@]}" "$TARGET_HOST"

