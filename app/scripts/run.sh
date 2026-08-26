#!/usr/bin/env bash
set -euo pipefail

# Navigate to the project root (local-llm) instead of the app/ directory
cd "$(dirname "$0")/../.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
  echo "Note: If ADMIN_PASSWORD is not set, the system will automatically generate a random one and print it to the log."
fi

echo
echo "Starting AI Local Gateway using Docker Compose..."
echo
echo "Dashboard: http://127.0.0.1:9001/"
echo "Health:    http://127.0.0.1:9001/healthz"
echo

# Start using docker-compose
docker-compose up -d --build

echo
echo "Successfully started as a background daemon."
echo "To view logs, run: docker-compose logs -f"
echo
