# Local HPC LLM Architecture Overview

This document describes the high-level system architecture, design decisions, component interactions, and data flows for the **vLLMlocal** infrastructure and application stack.

---

## 1. System Architecture Diagram

```mermaid
flowchart TB
    subgraph ClientLayer ["Client Layer"]
        SDK["Python SDK (openai)"]
        REST["cURL / REST Clients"]
        WEB["vLLMlocal Web Dashboard"]
    end

    subgraph AppLayer ["Application Layer (Local Gateway @ 127.0.0.1:9000)"]
        direction TB
        FASTAPI["FastAPI Gateway Proxy (main.py)"]
        
        subgraph SecurityModule ["Security & Governance"]
            ADMIN_AUTH["Admin Auth (/api/auth/login)<br/>Session Tokens (7-day TTL)"]
            KEY_ACL["API Key ACL & Sliding Window RPM<br/>SHA-256 Hashed in SQLite"]
        end

        subgraph TelemetryModule ["Observability & Metrics"]
            SPEEDOMETER["Real-Time Speedometer (tok/s)"]
            TTFT_TRACKER["Time To First Token (TTFT)"]
            CHART_TS["Timeseries 1-min Buckets (Chart.js)"]
        end

        DB[("SQLite Database (gateway.db)<br/>api_keys & inference_logs")]
        
        FASTAPI --> SecurityModule
        FASTAPI --> TelemetryModule
        SecurityModule --> DB
        TelemetryModule --> DB
    end

    subgraph NetworkLayer ["Networking Layer"]
        TUNNEL["SSH Local Port Forwarding Tunnel<br/>127.0.0.1:18000 &rarr; gpunode1.gitc.hpc:8000"]
    end

    subgraph InfraLayer ["Infrastructure Layer (HPC Slurm Cluster)"]
        SLURM["Slurm Workload Manager<br/>(vllm-singlegpu.sbatch)"]
        CONTAINER["Apptainer Container Runtime<br/>(vllm.sif with VLLM_USE_V1=0)"]
        VLLM_ENGINE["vLLM Serving Engine (TP=1)<br/>Model: Qwen3.5-9B-Q4_K_M.gguf (FP16)"]
        GPU["1x NVIDIA Tesla V100 GPU (16GB VRAM)<br/>~5.8GB Weights | 64% KV Cache Free"]

        SLURM --> CONTAINER
        CONTAINER --> VLLM_ENGINE
        VLLM_ENGINE --> GPU
    end

    ClientLayer -->|"HTTP /v1 (sk-hpc-...)"| FASTAPI
    FASTAPI -->|"HTTP Reverse Proxy"| TUNNEL
    TUNNEL -->|"HTTP Forwarding"| VLLM_ENGINE
```

---

## 2. End-to-End Inference & Telemetry Sequence

The sequence diagram below illustrates the lifecycle of a streaming request from the client, through the Gateway, down to the vLLM engine, including real-time TTFT and token generation speed measurement.

```mermaid
sequenceDiagram
    autonumber
    actor Client as Client / Web UI
    participant GW as FastAPI Gateway (Port 9000)
    participant DB as SQLite (gateway.db)
    participant SSH as SSH Tunnel (Port 18000)
    participant vLLM as vLLM Engine on V100 (Port 8000)

    Client->>GW: POST /v1/chat/completions (Bearer sk-hpc-...)
    
    rect rgb(240, 245, 255)
        Note over GW,DB: Authentication & Rate Limiting
        GW->>DB: Query SHA-256(key_hash) & ACL
        DB-->>GW: Key valid, RPM OK, Model Whitelisted
    end

    GW->>SSH: Forward payload to 127.0.0.1:18000
    SSH->>vLLM: Proxy request to compute node:8000
    
    rect rgb(255, 248, 240)
        Note over vLLM,GPU: vLLM PagedAttention Inference
        vLLM-->>SSH: Stream Chunk 1 (First Token)
        SSH-->>GW: Chunk 1 received
        GW->>GW: Record TTFT (Time To First Token)
        GW-->>Client: SSE data: {"choices": [{"delta": {"content": "..."}}]}
    end

    loop Token Generation Stream
        vLLM-->>SSH: Stream Chunk N
        SSH-->>GW: Chunk N received
        GW->>GW: Increment completion token counter
        GW-->>Client: SSE data: {"choices": [{"delta": {"content": "..."}}]}
    end

    vLLM-->>SSH: Stream [DONE]
    SSH-->>GW: Stream closed

    rect rgb(240, 255, 240)
        Note over GW,DB: Telemetry Aggregation
        GW->>GW: Calculate total_latency & tok/s throughput
        GW->>DB: INSERT into inference_logs (req_id, tokens, latency, ttft, speed)
    end
    
    GW-->>Client: SSE data: [DONE]
```

---

## 3. Administrator Authentication & API Key Lifecycle Flow

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Administrator
    participant UI as Web Dashboard
    participant GW as FastAPI Gateway
    participant DB as SQLite (gateway.db)

    Admin->>UI: Submit Username & Password
    UI->>GW: POST /api/auth/login {username, password}
    GW->>GW: Validate credentials vs .env
    GW->>GW: Generate session token (sess_...) with 7-day TTL
    GW-->>UI: 200 OK {token, username}
    UI->>UI: Store session in localStorage

    rect rgb(245, 245, 255)
        Note over Admin,DB: Issue New Client API Key
        Admin->>UI: Enter Client Name, RPM limit, Model
        UI->>GW: POST /admin/keys (Header: X-Admin-Session)
        GW->>GW: Validate session token
        GW->>GW: Generate raw key (sk-hpc-...) & compute SHA-256 hash
        GW->>DB: INSERT INTO api_keys (key_hash, prefix, name, rpm, allowed_models)
        GW-->>UI: 200 OK {api_key: "sk-hpc-...", prefix, rpm}
        UI->>Admin: Display raw secret once (1-Click Copy & Use)
    end

    rect rgb(255, 240, 240)
        Note over Admin,DB: Key Revocation
        Admin->>UI: Click REVOKE on Key #ID
        UI->>GW: DELETE /admin/keys/{id} (Header: X-Admin-Session)
        GW->>DB: UPDATE api_keys SET enabled = 0 WHERE id = {id}
        GW-->>UI: 200 OK {revoked: true}
        UI->>Admin: Update status badge to REVOKED
    end
```

---

## 4. Key Component Architecture

### 4.1 Infrastructure Layer (`infra/`)
- **Single-GPU Slurm Batch Job (`slurm/serving/vllm-singlegpu.sbatch`)**:
  - Allocates `1` GPU (`#SBATCH --gres=gpu:1`), `4` CPUs, and `32GB` RAM.
  - Launches vLLM with `TP=1`, `--dtype float16`, and `VLLM_USE_V1=0` on NVIDIA Tesla V100 (Volta SM70).
- **Hugging Face Downloader (`slurm/download/hf_download_qwen9b_gguf.sbatch`)**:
  - Automated downloader script that fetches quantized GGUF weights directly onto the shared scratch/lustre storage on compute nodes with automatic checksum verification.

### 4.2 Application Layer (`app/`)
- **FastAPI Gateway Proxy (`app/main.py`)**:
  - OpenAI-compliant reverse proxy supporting streaming Server-Sent Events (SSE) and batch requests.
  - Dual-tier authentication: Admin username/password session auth + Client `sk-hpc-...` bearer tokens.
  - Granular rate limiting (Sliding Window RPM) and per-key model whitelisting.
  - Live token dynamics metrics calculation (`tok/s`, TTFT, prompt & completion token counts).
- **Web UI Dashboard (`ui/index.html`)**:
  - **Inference Telemetry**: Dual-axis Chart.js token timeline, real-time speed meter, live inference audit ledger, and playground.
  - **Slurm Jobs Monitor**: Cluster job queue inspection, node allocation, and live log reader.
  - **AI Chatbot Studio**: Multi-turn chat interface with rich Markdown formatting, syntax highlighting, and 1-click code block copying.
  - **API Key Governance**: Dedicated administration view for token issuance, rate limit configuration, and instant key revocation.
