#!/usr/bin/env bash
set -euo pipefail
: "${HPC_API_KEY:?export HPC_API_KEY=sk-hpc-...}"

curl -s http://127.0.0.1:9000/v1/chat/completions \
  -H "Authorization: Bearer $HPC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [
      {"role": "user", "content": "Hello from my laptop"}
    ],
    "temperature": 0.2,
    "max_tokens": 128
  }'
echo
