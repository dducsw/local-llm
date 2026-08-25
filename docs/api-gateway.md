# Application Layer Gateway & Web Dashboard Guide

The application layer contains an OpenAI-compatible FastAPI gateway proxy (`app/app/main.py`) that acts as a secure, high-performance interface between client applications and the backend HPC vLLM engine running on Slurm compute nodes.

---

## 1. Network & Tunneling Topology

```mermaid
flowchart LR
    subgraph LocalMachine ["Local Workstation / Host Machine"]
        CLIENT["Client App / Web Browser"]
        GW["FastAPI Gateway<br/>(Port 9000)"]
        LOCAL_PORT["Local Tunnel Port<br/>(127.0.0.1:18000)"]

        CLIENT -->|"POST /v1/chat/completions"| GW
        GW -->|"HTTP Forward"| LOCAL_PORT
    end

    subgraph SSHChannel ["Encrypted SSH Tunnel"]
        LOCAL_PORT ==>|"SSH Local Port Forwarding"| REMOTE_PORT
    end

    subgraph HPCNode ["HPC Slurm Compute Node (e.g. gpunode1.gitc.hpc)"]
        REMOTE_PORT["Compute Node Port<br/>(0.0.0.0:8000)"]
        VLLM["vLLM Engine (Apptainer)<br/>Model: Qwen3.5-9B-Q4_K_M.gguf"]
        V100["NVIDIA Tesla V100 GPU (16GB)"]

        REMOTE_PORT --> VLLM
        VLLM --> V100
    end
```

---

## 2. Setup & SSH Tunneling Workflow

```mermaid
flowchart TD
    A["Step 1: Check Active Slurm Job Node<br/>squeue -u $USER (e.g. gpunode1.gitc.hpc)"] --> B["Step 2: Start SSH Port Forwarding Tunnel<br/>./scripts/ssh-tunnel.sh"]
    B --> C{"Is Port 18000 Reachable?"}
    C -- No --> D["Check SSH configuration / Compute node status"]
    C -- Yes --> E["Step 3: Launch Gateway API & Web App<br/>./scripts/run.sh"]
    E --> F["Step 4: Open Browser at http://127.0.0.1:9000"]
```

### Step 1: Open SSH Tunnel to HPC Compute Node
Run the SSH tunnel script to securely bridge local port `18000` to port `8000` on the active Slurm GPU compute node:

```bash
cd app
./scripts/ssh-tunnel.sh
```

Override GPU node hostname or local port if required:

```bash
GPU_NODE=gpunode1.gitc.hpc LOCAL_PORT=18000 ./scripts/ssh-tunnel.sh
```

Verify connection to upstream vLLM:

```bash
curl http://127.0.0.1:18000/v1/models
```

### Step 2: Launch Local Gateway API & Dashboard

```bash
cd app
./scripts/run.sh
```

The startup script automatically:
1. Initializes a Python virtual environment (`.venv`) if missing.
2. Installs dependencies from `requirements.txt`.
3. Copies `.env.example` to `.env` with initial admin credentials if absent.
4. Initializes the SQLite database (`gateway.db`) with tables for API keys and telemetry audit logs.
5. Starts the FastAPI server on `http://127.0.0.1:9000`.

---

## 3. Dual-Tier Authentication & Request Verification Flow

```mermaid
flowchart TD
    REQ["Incoming HTTP Request"] --> CHECK_TYPE{"Request Target"}
    
    CHECK_TYPE -- "Admin Endpoints (/admin/*, /api/auth/*)" --> ADMIN_VAL{"Check X-Admin-Session or X-Admin-Token"}
    ADMIN_VAL -- "Valid Session Token" --> EXEC_ADMIN["Execute Admin Action (Issue/Revoke Key)"]
    ADMIN_VAL -- "Invalid / Missing" --> ERR_401["Return 401 Unauthorized"]

    CHECK_TYPE -- "Inference Endpoints (/v1/*)" --> KEY_VAL{"Extract Bearer Token (sk-hpc-...)"}
    KEY_VAL -- "Missing Header" --> ERR_401
    KEY_VAL -- "Key Present" --> HASH["Compute SHA-256(Key)"]
    HASH --> DB_LOOKUP{"Lookup in SQLite (api_keys)"}
    DB_LOOKUP -- "Not Found or Disabled" --> ERR_401
    DB_LOOKUP -- "Valid Key" --> CHECK_RPM{"Check Sliding Window RPM"}
    CHECK_RPM -- "Exceeded" --> ERR_429["Return 429 Too Many Requests"]
    CHECK_RPM -- "Within Limit" --> CHECK_ACL{"Check Model Permissions"}
    CHECK_ACL -- "Model Disallowed" --> ERR_403["Return 403 Forbidden"]
    CHECK_ACL -- "Authorized" --> PROXY["Proxy Request to vLLM Upstream & Record Telemetry"]
```

---

## 4. Configuration Parameters

### Environment Variables (`.env`)
```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=CHANGE_ME_TO_A_SECURE_PASSWORD
ADMIN_TOKEN=CHANGE_ME_TO_A_LONG_RANDOM_SECRET
MODEL_CONFIG=./config/models.json
KEY_DB=./data/gateway.db
UPSTREAM_TIMEOUT=3600
LOG_LEVEL=INFO
```

### Model Registry (`config/models.json`)
Maps user-facing model IDs to upstream vLLM instances:

```json
{
  "models": [
    {
      "id": "qwen3.5-9b",
      "owned_by": "hpc-selfhosted",
      "base_url": "http://127.0.0.1:18000/v1",
      "upstream_model": "Qwen3.5-9B-Q4_K_M.gguf",
      "api_key": ""
    }
  ]
}
```

---

## 5. Web UI Dashboard Modules

```mermaid
mindmap
  root((vLLMlocal Console))
    Inference Telemetry
      Speedometer (tok/s)
      Time to First Token (TTFT)
      Chart.js 15-min Timeline
      Live Audit Ledger
      Inference Playground
    Slurm Jobs Monitor
      squeue Cluster Status
      Allocated Compute Nodes
      GPU GRES Allocation
      Real-time Log Viewer
    AI Chatbot Studio
      Multi-turn Dialogue History
      Markdown & Table Parser
      Atom One Dark Code Blocks
      1-Click Copy Code
    API Keys Governance
      Admin Login & Session HUD
      Issue sk-hpc- Tokens
      Sliding Window RPM Limiting
      Instant Key Revocation
```

---

## 6. SQLite Database Schema (`data/gateway.db`)

### Table: `api_keys`
```sql
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    allowed_models TEXT NOT NULL,
    rpm INTEGER NOT NULL DEFAULT 60,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
```

### Table: `inference_logs`
```sql
CREATE TABLE IF NOT EXISTS inference_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    req_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    ttft_ms REAL NOT NULL,
    total_latency_ms REAL NOT NULL,
    tok_per_sec REAL NOT NULL,
    key_prefix TEXT NOT NULL,
    status TEXT NOT NULL
);
```

---

## 7. Client Integration Examples

### Python (OpenAI Official SDK)
```python
import openai

client = openai.OpenAI(
    base_url="http://127.0.0.1:9000/v1",
    api_key="sk-hpc-YOUR_GENERATED_KEY"
)

response = client.chat.completions.create(
    model="qwen3.5-9b",
    messages=[
        {"role": "system", "content": "You are a helpful assistant running on HPC."},
        {"role": "user", "content": "Explain KV Cache optimization in vLLM in two sentences."}
    ],
    temperature=0.3,
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

### cURL
```bash
curl http://127.0.0.1:9000/v1/chat/completions \
  -H "Authorization: Bearer sk-hpc-YOUR_GENERATED_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [{"role": "user", "content": "Hello from HPC!"}],
    "temperature": 0.2,
    "stream": false
  }'
```
