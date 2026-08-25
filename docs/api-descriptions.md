# REST API Reference & Endpoint Specifications

This document provides complete technical specifications for all REST API endpoints exposed by the **vLLMlocal** Gateway (`app/app/main.py`).

The Gateway acts as a high-performance proxy and observability layer between client applications (Web UI, Python SDK, cURL, LangChain) and the local vLLM inference engine running on HPC compute nodes.

---

## Base URLs
- **Local API Gateway**: `http://127.0.0.1:9000`
- **OpenAI Compatible Base**: `http://127.0.0.1:9000/v1`
- **Health / Readiness**: `http://127.0.0.1:9000/health`

---

## Authentication Schemes

The Gateway implements a dual-tier authentication architecture:

1. **Client API Key Authentication (Bearer Token)**:
   - Header: `Authorization: Bearer sk-hpc-...`
   - Purpose: Grants access to inference endpoints (`/v1/chat/completions`, `/v1/completions`, `/v1/models`).
   - Validated against SHA-256 hashed keys stored in SQLite (`gateway.db`).
   - Enforces per-key Rate Limiting (Sliding Window RPM) and model whitelist.

2. **Admin Session Authentication**:
   - Header: `X-Admin-Session: sess_...` (or `X-Admin-Token: <token>`)
   - Purpose: Grants administrative privileges to create, inspect, and revoke API keys (`/admin/keys`).

---

## 1. System Health & Readiness

### `GET /health` / `GET /healthz`
Returns gateway operational status.

- **Authentication**: None
- **Response**: `200 OK`
```json
{
  "status": "ok"
}
```

### `GET /readyz`
Verifies backend connectivity to the upstream vLLM inference server.

- **Authentication**: None
- **Response**: `200 OK`
```json
{
  "status": "ready",
  "backends": {
    "qwen3.5-9b": {
      "reachable": true,
      "status_code": 200
    }
  }
}
```

---

## 2. OpenAI-Compatible Inference APIs

### `GET /v1/models`
Lists all active models permitted for the authenticated API key.

- **Authentication**: `Bearer sk-hpc-...`
- **Response**: `200 OK`
```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen3.5-9b",
      "object": "model",
      "owned_by": "self-hosted"
    }
  ]
}
```

---

### `POST /v1/chat/completions`
Proxies chat completion requests to vLLM. Supports both streaming (Server-Sent Events) and non-streaming responses.

- **Authentication**: `Bearer sk-hpc-...`
- **Headers**:
  - `Content-Type: application/json`
  - `X-Request-ID: <optional-tracking-id>`

#### Request Body
```json
{
  "model": "qwen3.5-9b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain PagedAttention in vLLM."}
  ],
  "temperature": 0.3,
  "max_tokens": 1024,
  "stream": true
}
```

#### Streaming Response (`stream: true`)
- **Content-Type**: `text/event-stream`
```
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1724570000,"model":"qwen3.5-9b","choices":[{"index":0,"delta":{"content":"Paged"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1724570000,"model":"qwen3.5-9b","choices":[{"index":0,"delta":{"content":"Attention"},"finish_reason":null}]}

data: [DONE]
```

#### Non-Streaming Response (`stream: false`)
- **Content-Type**: `application/json`
```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1724570000,
  "model": "qwen3.5-9b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "PagedAttention is a memory-efficient attention algorithm inspired by virtual memory paging in operating systems..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 28,
    "completion_tokens": 142,
    "total_tokens": 170
  }
}
```

---

### `POST /v1/completions`
Raw text completion endpoint.

- **Authentication**: `Bearer sk-hpc-...`
- **Request Body**:
```json
{
  "model": "qwen3.5-9b",
  "prompt": "def quicksort(arr):",
  "max_tokens": 256,
  "temperature": 0.2
}
```

---

## 3. Real-Time Telemetry & Observability APIs

### `GET /api/metrics/realtime`
Returns aggregated real-time telemetry metrics and summary statistics.

- **Authentication**: None
- **Response**: `200 OK`
```json
{
  "model": "qwen3.5-9b",
  "total_requests": 142,
  "total_prompt_tokens": 4210,
  "total_completion_tokens": 18950,
  "total_tokens": 23160,
  "current_tok_per_sec": 41.8,
  "last_ttft_ms": 184.2,
  "avg_latency_ms": 890.5,
  "vram_used_gb": 5.8,
  "vram_total_gb": 16.0,
  "gpu_name": "NVIDIA Tesla V100-SXM2-16GB",
  "kv_cache_free_pct": 64.2
}
```

---

### `GET /api/metrics/timeseries`
Returns 1-minute historical time buckets over the last 15 minutes for real-time charting.

- **Authentication**: None
- **Response**: `200 OK`
```json
{
  "labels": ["14:40", "14:42", "14:44", "14:46", "14:48", "14:50", "14:52", "14:54"],
  "tokens_per_minute": [0, 450, 1200, 890, 2100, 1450, 3200, 1800],
  "cumulative_tokens": [0, 450, 1650, 2540, 4640, 6090, 9290, 11090],
  "throughput_series": [0.0, 38.2, 42.1, 40.5, 43.8, 39.7, 44.2, 41.8]
}
```

---

### `GET /api/metrics/logs`
Fetches recent inference audit records with latency, token breakdown, and HTTP status.

- **Authentication**: None
- **Parameters**: `limit` (integer, default: 50)
- **Response**: `200 OK`
```json
{
  "logs": [
    {
      "id": "req_8f1a2b3c4d5e",
      "model": "qwen3.5-9b",
      "prompt_tokens": 34,
      "completion_tokens": 210,
      "tokens": 210,
      "latency": "1420",
      "latency_ms": 1420.4,
      "ttft_ms": 182.1,
      "speed": "41.5",
      "tok_per_sec": 41.5,
      "status": "200 OK",
      "key_prefix": "sk-hpc-7a8b",
      "time": "14:54:12"
    }
  ]
}
```

---

### `GET /api/gpu/telemetry`
Returns detailed hardware specifications and memory allocation metrics for the active GPU node.

- **Authentication**: None
- **Response**: `200 OK`
```json
{
  "device_name": "NVIDIA Tesla V100-SXM2-16GB",
  "architecture": "Volta (SM70)",
  "vram_total_mb": 16384,
  "vram_used_mb": 5940,
  "vram_free_mb": 10444,
  "gpu_utilization_pct": 24,
  "driver_version": "535.183.01",
  "cuda_version": "12.2",
  "model_loaded": "Qwen3.5-9B-Q4_K_M.gguf (FP16)",
  "tp_size": 1
}
```

---

### `GET /api/slurm/jobs`
Queries active and scheduled jobs on the Slurm cluster queue (`squeue`).

- **Authentication**: None
- **Response**: `200 OK`
```json
{
  "jobs": [
    {
      "job_id": "491823",
      "name": "qwen3.5-9b-vllm",
      "partition": "gpu-queue",
      "status": "RUNNING",
      "time": "01:24:18",
      "node": "gpunode1.gitc.hpc",
      "gres": "gpu:1 (NVIDIA V100)",
      "model": "Qwen3.5-9B-Q4_K_M.gguf",
      "port": 8000,
      "tp": 1
    }
  ]
}
```

---

## 4. Admin Authentication & Session Management

### `POST /api/auth/login`
Authenticates the administrator using credentials configured in `.env` and issues a session token.

- **Request Body**:
```json
{
  "username": "admin",
  "password": "your_admin_password"
}
```
- **Response**: `200 OK`
```json
{
  "status": "ok",
  "token": "sess_9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d",
  "username": "admin",
  "expires_in": 604800
}
```

---

### `POST /api/auth/logout`
Terminates the active administrator session.

- **Headers**: `X-Admin-Session: sess_...`
- **Response**: `200 OK`
```json
{
  "status": "logged_out"
}
```

---

### `GET /api/auth/me`
Verifies current session validity.

- **Headers**: `X-Admin-Session: sess_...`
- **Response**: `200 OK`
```json
{
  "authenticated": true,
  "username": "admin"
}
```

---

## 5. API Key Governance & Lifecycle Management

### `GET /admin/keys`
Lists all issued API keys, including rate limits, allowed models, and status.

- **Authentication**: `X-Admin-Session: sess_...` (or `X-Admin-Token: <token>`)
- **Response**: `200 OK`
```json
{
  "data": [
    {
      "id": 1,
      "prefix": "sk-hpc-7a8b9c0d",
      "name": "python-research-client",
      "allowed_models": ["qwen3.5-9b"],
      "rpm": 60,
      "enabled": true,
      "created_at": 1724570000
    }
  ]
}
```

---

### `POST /admin/keys`
Issues a new client API key. The raw plaintext secret is returned once and stored as a SHA-256 hash.

- **Authentication**: `X-Admin-Session: sess_...` (or `X-Admin-Token: <token>`)
- **Request Body**:
```json
{
  "name": "data-science-team",
  "allowed_models": ["qwen3.5-9b"],
  "rpm": 120
}
```
- **Response**: `200 OK`
```json
{
  "id": 2,
  "api_key": "sk-hpc-k3J9_mF2xL9qP0rT4vW8zY1bA7cE5gH2",
  "prefix": "sk-hpc-k3J9_mF2",
  "name": "data-science-team",
  "allowed_models": ["qwen3.5-9b"],
  "rpm": 120,
  "note": "Save this key now. The raw key is not stored and cannot be shown again."
}
```

---

### `DELETE /admin/keys/{key_id}`
Revokes an active API key immediately.

- **Authentication**: `X-Admin-Session: sess_...` (or `X-Admin-Token: <token>`)
- **Response**: `200 OK`
```json
{
  "id": 2,
  "revoked": true
}
```
