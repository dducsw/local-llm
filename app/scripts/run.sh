#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  SECRET="$(openssl rand -hex 32)"
  sed -i "s/CHANGE_ME_TO_A_LONG_RANDOM_SECRET/$SECRET/" .env
  chmod 600 .env
  echo "Created .env with a random ADMIN_TOKEN."
fi

set -a
source .env
set +a

echo
echo "Dashboard: http://127.0.0.1:9000/"
echo "Health:    http://127.0.0.1:9000/healthz"
echo
echo "ADMIN_TOKEN is stored in: $PWD/.env"
echo

exec uvicorn app.main:app --host 127.0.0.1 --port 9000
