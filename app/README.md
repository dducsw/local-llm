# V100-local — NVIDIA Tesla V100 HPC Inference Gateway & Web Console

An enterprise-ready OpenAI-compatible reverse proxy, telemetry collector, and administrative console running locally to interface with HPC compute clusters.

---

## 🏛️ Architecture

```mermaid
flowchart TD
    CLIENT["Client Applications / Web Browser"] -->|"HTTP /v1 (Authorization: Bearer sk-hpc-...)"| GW
    
    subgraph LocalGateway ["V100-local Gateway (FastAPI @ localhost:9000)"]
        GW["Reverse Proxy Core"]
        AUTH["Admin Auth & Key ACL"]
        SPEED["tok/s & TTFT Telemetry"]
        DB[("SQLite Database (gateway.db)")]

        GW --- AUTH
        GW --- SPEED
        AUTH --- DB
        SPEED --- DB
    end

    GW -->|"Forward: http://127.0.0.1:18000/v1"| TUNNEL["SSH Local Port Forwarding Tunnel"]
    TUNNEL -->|"Proxy: port 8000"| NODE["HPC Compute Node (gpunode1.gitc.hpc)"]
    
    subgraph HPCNode ["HPC Slurm Node"]
        NODE --> VLLM["vLLM Engine (Apptainer vllm.sif)"]
        VLLM --> MODEL["Qwen 3.5 9B GGUF (FP16)"]
        MODEL --> V100["1x NVIDIA Tesla V100 GPU"]
    end
```

---

## 🚀 Key Features

- **OpenAI Standard Compatibility**: Drop-in replacement for OpenAI endpoints (`/v1/chat/completions`, `/v1/completions`, `/v1/models`).
- **Real-Time Token Telemetry**: Continuous throughput tracker (`tok/s`), Time To First Token (`TTFT`), dual-axis Chart.js timeline, and live audit ledger.
- **Slurm Cluster Monitor**: Embedded queue observer (`squeue`) tracking job lifecycle, node allocations, and execution logs.
- **AI Chatbot Studio**: Multi-turn dialogue playground with rich Markdown rendering and 1-click code block copying.
- **Security & Governance**: Admin authentication (Username & Password) + SHA-256 hashed API keys with Sliding Window Rate Limiting (RPM).

---

## 🛠️ Getting Started

### 1. Open SSH Port Forwarding Tunnel

In your terminal:

```bash
cd app
./scripts/ssh-tunnel.sh
```

*By default, this tunnels `127.0.0.1:18000` to port `8000` on `gpunode1.gitc.hpc`.*

To override the compute node:
```bash
GPU_NODE=gpunode2.gitc.hpc ./scripts/ssh-tunnel.sh
```

Verify reachability:
```bash
curl http://127.0.0.1:18000/v1/models
```

---

### 2. Launch Gateway Server

In a second terminal:

```bash
cd app
./scripts/run.sh
```

The startup script automatically:
1. Creates the Python virtual environment (`.venv`).
2. Installs requirements from `requirements.txt`.
3. Initializes `.env` with administrative credentials if missing.
4. Starts FastAPI on `http://127.0.0.1:9000`.

---

### 3. Open Web Dashboard

Navigate to:
```
http://127.0.0.1:9000/
```

- Click **`ADMIN LOGIN`** on the top right or go to the **`API KEYS`** tab.
- Enter admin credentials (default `admin` / `123456` or as set in `.env`).
- Issue new `sk-hpc-...` API keys and start chatting or benchmarking.

---

## 💻 Integration Examples

### Python (using official `openai` SDK)
```python
import openai

client = openai.OpenAI(
    base_url="http://127.0.0.1:9000/v1",
    api_key="sk-hpc-YOUR_GENERATED_KEY"
)

response = client.chat.completions.create(
    model="qwen3.5-9b",
    messages=[
        {"role": "system", "content": "You are a helpful HPC assistant."},
        {"role": "user", "content": "Explain PagedAttention in vLLM."}
    ],
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
    "messages": [
      {"role": "user", "content": "Hello vLLMlocal!"}
    ],
    "stream": false
  }'
```
