# API Keys & Model Access Control List (ACL) Guide

An enterprise-grade governance and access control specification for the **V100-local AI Gateway**, supporting cryptographically secure API keys, multi-tenant Model Access Control Lists (ACL), and Sliding Window Rate Limiting (RPM).

---

## 🏛️ 1. Architecture & Security Model

```mermaid
flowchart TD
    Client["Client Request (cURL / Python / LangChain)"] -->|"Authorization: Bearer sk-hpc-..."| Gateway["FastAPI AI Gateway"]
    
    subgraph SecurityEngine ["Security & Governance Engine"]
        AuthCheck{"Key Authentication"}
        StatusCheck{"Key Enabled?"}
        RPMCheck{"Sliding Window RPM Limit"}
        ACLCheck{"Model in Allowed ACL?"}
    end

    Gateway --> AuthCheck
    AuthCheck -->|Valid Hash| StatusCheck
    AuthCheck -->|Invalid Key| Err401["401 Unauthorized"]
    
    StatusCheck -->|Active| RPMCheck
    StatusCheck -->|Disabled/Revoked| Err401
    
    RPMCheck -->|Within Limit| ACLCheck
    RPMCheck -->|Exceeded RPM| Err429["429 Rate Limit Exceeded"]
    
    ACLCheck -->|Authorized| Upstream["Inference Engine (vLLM / llama.cpp on V100)"]
    ACLCheck -->|Unauthorized Model| Err403["403 Permission Error"]
```

### Key Security Principles:
1. **One-Way SHA-256 Hashing**: 
   - Secret keys (`sk-hpc-...`) are generated using cryptographically strong pseudo-random tokens (`secrets.token_urlsafe(32)`).
   - Only the **SHA-256 hash** is stored in the database (`gateway.db`). Raw keys are never stored on the server and are shown only once at creation time.
2. **Model Access Control Lists (ACL)**:
   - Each key is assigned an array of allowed models (e.g., `["qwen3.5-9b"]` or `["*"]` for unrestricted access).
   - Requests for models outside of the key's ACL are immediately rejected with `403 Forbidden`.
3. **Sliding Window Rate Limiting (RPM)**:
   - In-flight request timestamps are tracked in real-time sliding windows.
   - Enforces precise requests-per-minute (RPM) limits with `Retry-After: 60` HTTP headers.
4. **Instant Revocation & Status Toggling**:
   - Keys can be instantly toggled between **Active** and **Disabled** or permanently **Revoked** via the Dashboard or Admin REST API.

---

## 🔑 2. Admin Management Endpoints

All admin endpoints require either:
- Header `X-Admin-Session: sess_...` (issued upon web login), or
- Header `Authorization: Bearer <ADMIN_PASSWORD / ADMIN_TOKEN>`.

### 1. Create a New API Key
* **Endpoint**: `POST /admin/keys`
* **Request Payload**:
```json
{
  "name": "Production-Mobile-App",
  "rpm": 60,
  "allowed_models": ["qwen3.5-9b"],
  "duration": "7d"
}
```
* **Supported Durations**: `"never"` (default / permanent), `"1d"`, `"7d"`, `"30d"`, `"90d"`.
* **Response (`200 OK`)**:
```json
{
  "id": 2,
  "api_key": "sk-hpc-AbCdEf1234567890_xYz...",
  "prefix": "sk-hpc-AbCdEf12",
  "name": "Production-Mobile-App",
  "allowed_models": ["qwen3.5-9b"],
  "rpm": 60,
  "expires_at": 1788324000,
  "note": "Save this key now. The raw key is not stored and cannot be shown again."
}
```

---

### 2. List All API Keys with Real-Time Telemetry & Expiry
* **Endpoint**: `GET /admin/keys`
* **Response (`200 OK`)**:
```json
{
  "data": [
    {
      "id": 2,
      "prefix": "sk-hpc-AbCdEf12",
      "name": "Production-Mobile-App",
      "allowed_models": ["qwen3.5-9b"],
      "rpm": 60,
      "enabled": true,
      "created_at": 1787719200,
      "expires_at": 1788324000,
      "is_expired": false,
      "usage_requests": 1420,
      "usage_tokens": 358400
    }
  ]
}
```

---

### 3. Toggle Key Active / Inactive Status
* **Endpoint**: `POST /admin/keys/{key_id}/toggle`
* **Response (`200 OK`)**:
```json
{
  "id": 2,
  "enabled": false
}
```

---

### 4. Revoke / Delete API Key
* **Endpoint**: `DELETE /admin/keys/{key_id}`
* **Response (`200 OK`)**:
```json
{
  "id": 2,
  "revoked": true
}
```

---

## 💻 3. Client Integration Guide

### Endpoint URLs
* **Production Public Gateway**: `https://llm.ledinhduc.id.vn/v1`
* **Local Cluster / VM Endpoint**: `http://127.0.0.1:9001/v1`

---

### A. Python (`openai` Official SDK)

Install the OpenAI client library:
```bash
pip install openai
```

Code Example:
```python
import os
from openai import OpenAI

# Initialize the client with your self-hosted Gateway endpoint
client = OpenAI(
    base_url="https://llm.ledinhduc.id.vn/v1",
    api_key="sk-hpc-your_api_key_here",
)

# 1. Streaming Chat Completion
response = client.chat.completions.create(
    model="qwen3.5-9b",
    messages=[
        {"role": "system", "content": "You are a helpful, concise AI engineer."},
        {"role": "user", "content": "Explain how FlashAttention-V100 accelerates LLM inference on Tesla V100."}
    ],
    temperature=0.7,
    max_tokens=512,
    stream=True,
)

print("Response: ", end="")
for chunk in response:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
print()
```

---

### B. cURL / REST API

```bash
curl -N -X POST https://llm.ledinhduc.id.vn/v1/chat/completions \
  -H "Authorization: Bearer sk-hpc-your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [
      {"role": "user", "content": "Hello Qwen 3.5 on Tesla V100 cluster!"}
    ],
    "stream": true,
    "temperature": 0.7,
    "max_tokens": 256
  }'
```

---

### C. LangChain Integration

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="qwen3.5-9b",
    base_url="https://llm.ledinhduc.id.vn/v1",
    api_key="sk-hpc-your_api_key_here",
    temperature=0.7,
)

response = llm.invoke("What are the key advantages of running LLMs with Apptainer on Slurm?")
print(response.content)
```

---

### D. TypeScript / JavaScript (Node.js & Web)

```typescript
import OpenAI from "openai";

const openai = new OpenAI({
  baseURL: "https://llm.ledinhduc.id.vn/v1",
  apiKey: process.env.HPC_API_KEY || "sk-hpc-your_api_key_here",
});

async function main() {
  const stream = await openai.chat.completions.create({
    model: "qwen3.5-9b",
    messages: [{ role: "user", content: "Write a quick Python benchmark script." }],
    stream: true,
  });

  for await (const chunk of stream) {
    process.stdout.write(chunk.choices[0]?.delta?.content || "");
  }
  console.log();
}

main();
```

---

## ⚠️ 4. Error Codes & Handling

| HTTP Status | Error Type | Cause | Recommended Action |
| :--- | :--- | :--- | :--- |
| **`401 Unauthorized`** | `authentication_error` | Missing, disabled, or invalid API Key | Verify the key format `sk-hpc-...` and check if it is active in the Dashboard. |
| **`403 Forbidden`** | `permission_error` | Model requested is not permitted in Key ACL | Request access for the model from your administrator or select a permitted model. |
| **`404 Not Found`** | `invalid_request_error` | Unknown or unconfigured model ID | Check available models at `GET /v1/models`. |
| **`429 Too Many Requests`** | `rate_limit_error` | Exceeded RPM (Requests Per Minute) quota | Implement exponential backoff retry following the `Retry-After: 60` header. |
| **`502 Bad Gateway`** | `upstream_error` | Compute node / SSH Tunnel is unreachable | Verify Slurm job status and SSH tunnel connectivity in the Dashboard. |

---

## 🔒 5. Security Best Practices

1. **Keep Secrets Out of Source Control**: Always pass API keys via environment variables (e.g. `HPC_API_KEY`) or secret managers.
2. **Apply Principle of Least Privilege**:
   - Assign keys only the specific models they require (e.g., `["qwen3.5-9b"]` instead of `["*"]`).
   - Set conservative RPM limits based on client workload requirements.
3. **Periodic Key Rotation**: Regularly rotate keys for automated cron jobs and client applications.
