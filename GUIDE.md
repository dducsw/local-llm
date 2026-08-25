# End-to-End HPC Slurm Deployment Guide: vLLMlocal

This comprehensive guide provides step-by-step instructions for deploying and operating the **vLLMlocal** framework on an HPC cluster equipped with Slurm and NVIDIA GPUs (specifically optimized for **1x NVIDIA Tesla V100 16GB** using quantized **Qwen 3.5 9B GGUF**).

---

## 🧭 Complete Deployment Lifecycle

```mermaid
flowchart TD
    subgraph HPC_Cluster ["HPC Cluster (Login / Compute Nodes)"]
        A["1. Build Apptainer Container<br/>(apptainer build vllm.sif)"] --> B["2. Download GGUF Model<br/>(sbatch hf_download_qwen9b_gguf.sbatch)"]
        B --> C["3. Submit Slurm Inference Job<br/>(sbatch vllm-singlegpu.sbatch)"]
        C --> D["4. vLLM Server Ready on Compute Node<br/>(0.0.0.0:8000 on gpunode1)"]
    end

    subgraph Local_Host ["Local Workstation / Gateway Host"]
        E["5. Open SSH Port Forwarding Tunnel<br/>(127.0.0.1:18000 &rarr; gpunode1:8000)"]
        F["6. Launch Gateway & Web Console<br/>(./scripts/run.sh @ Port 9000)"]
        G["7. Admin Login & Issue Client API Keys"]
        H["8. Inference via Web Chatbot or Python SDK"]
    end

    D ==>|"Secure SSH Tunnel"| E
    E --> F
    F --> G
    G --> H
```

---

## 🔍 Infrastructure Review & Single-GPU Optimization Analysis

The `infra/` directory is pre-configured and optimized for **Single-GPU NVIDIA Tesla V100 (Volta SM70)** compute environments:

| Optimization Vector | Implementation Setting | Technical Rationale |
| :--- | :--- | :--- |
| **Engine Architecture** | `export VLLM_USE_V1=0` | The newer vLLM V1 engine targets Ampere (SM80+) and Hopper (SM90+). Forcing `V0` ensures compatibility and prevents crashes on Volta SM70 hardware. |
| **Precision & Data Type** | `--dtype float16`<br/>`NVIDIA_TF32_OVERRIDE=0` | Volta V100 lacks native hardware support for `Bfloat16`. Forcing `float16` prevents NaN loss divergence and activates Volta FP16 Tensor Cores. |
| **Quantization & VRAM** | `Qwen3.5-9B-Q4_K_M.gguf` | Quantized model weights consume only **~5.8 GB VRAM**, leaving **~9.5 GB (64%) free VRAM** exclusively for PagedAttention KV Cache (supporting 8k+ context length across concurrent requests). |
| **Parallelism Profile** | `--tensor-parallel-size 1` | Single-GPU execution eliminates inter-GPU communication overhead and NUMA cross-socket latency. |
| **Containerization** | `apptainer run --nv --cleanenv` | Unprivileged rootless container execution with external bind mounts (`/cache`) prevents disk quota exhaustion. |

---

## 📋 Step-by-Step Deployment Instructions

### Step 1: Build the Apptainer Container (HPC Login Node)

On the HPC login or build node, build the container image from `defs/vllm.def`:

```bash
cd infra
mkdir -p build

# Build container SIF image
apptainer build build/vllm.sif defs/vllm.def
```

*Note: Building takes approximately 5–10 minutes. The resulting `build/vllm.sif` image is immutable and can be reused across all compute jobs.*

---

### Step 2: Download Model Weights (HPC Compute Node)

Submit a batch job to download the quantized GGUF weights to high-speed cluster storage:

```bash
cd infra
sbatch slurm/download/hf_download_qwen9b_gguf.sbatch
```

Verify that the model file exists:
```bash
ls -lh $SCRATCH/models/qwen3.5-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf
```

---

### Step 3: Submit the Slurm Inference Serving Job

Submit the single-GPU serving job:

```bash
cd infra
sbatch slurm/serving/vllm-singlegpu.sbatch
```

#### Check Job Status & Assigned Node:
```bash
squeue -u $USER
```
*Example Output:*
```text
JOBID   PARTITION     NAME      USER    ST       TIME  NODES NODELIST(REASON)
491823  gpu-queue  vllm-smoke   pnhan    R       0:35      1 gpunode1
```
Note the node name: **`gpunode1`** (or `gpunode1.gitc.hpc`).

#### Inspect Server Startup Logs:
```bash
tail -f infra/logs/vllm-491823.out
```
Wait until you see:
```text
INFO:     Started server process [12894]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

### Step 4: Establish SSH Port Forwarding Tunnel (Local Workstation)

From your local machine, open an SSH tunnel bridging local port `18000` to port `8000` on the allocated compute node:

```bash
cd app
GPU_NODE=gpunode1.gitc.hpc LOCAL_PORT=18000 ./scripts/ssh-tunnel.sh
```

#### Test Tunnel Connectivity:
In another terminal:
```bash
curl http://127.0.0.1:18000/v1/models
```
*Expected Response:*
```json
{"object":"list","data":[{"id":"/cache/models/Qwen3.5-9B-Q4_K_M.gguf","object":"model"}]}
```

---

### Step 5: Launch the Gateway & Web Console

In the `app/` directory, run the gateway startup script:

```bash
cd app
./scripts/run.sh
```

The script automatically sets up the Python virtual environment (`.venv`), installs dependencies, initializes SQLite (`gateway.db`), and starts FastAPI on **`http://127.0.0.1:9000`**.

---

### Step 6: Access Dashboard & Authenticate

1. Open your web browser and navigate to: **`http://127.0.0.1:9000`**.
2. Click **`ADMIN LOGIN`** in the top navigation bar or go to the **`API KEYS`** tab.
3. Enter default credentials (configured in `.env`):
   - **Username**: `admin`
   - **Password**: `123456` (or the password configured in `app/.env`)
4. Once authenticated:
   - Go to **`API KEYS`** $\to$ Click **`GENERATE API KEY`**.
   - Copy the issued key (e.g. `sk-hpc-xxxxxxxxxxxxxxxx`).
   - Click **`SET AS ACTIVE`**.

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Data Scientist
    participant UI as Web Dashboard (Port 9000)
    participant GW as FastAPI Gateway
    participant LLM as vLLM on V100 GPU

    User->>UI: Submit Admin Login (admin / password)
    UI->>GW: POST /api/auth/login
    GW-->>UI: 200 OK (Session Token issued)
    
    User->>UI: Create Client API Key (Name: 'python-sdk', RPM: 60)
    UI->>GW: POST /admin/keys
    GW-->>UI: 200 OK (Returns raw key: sk-hpc-...)

    User->>UI: Open AI Chatbot Studio & Send Message
    UI->>GW: POST /v1/chat/completions (Bearer sk-hpc-...)
    GW->>LLM: Forward to 127.0.0.1:18000 (vLLM Engine)
    LLM-->>GW: Streaming SSE Chunks
    GW-->>UI: Real-time Markdown response with syntax highlighting
```

---

## 💻 Step 7: Client Integration Examples

### Python (OpenAI SDK)
```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:9000/v1",
    api_key="sk-hpc-YOUR_GENERATED_KEY"
)

response = client.chat.completions.create(
    model="qwen3.5-9b",
    messages=[
        {"role": "system", "content": "You are an expert AI assistant on HPC."},
        {"role": "user", "content": "Explain how PagedAttention solves KV Cache fragmentation."}
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
    "messages": [
      {"role": "user", "content": "Hello from HPC!"}
    ],
    "stream": false
  }'
```

---

## 🔧 Troubleshooting & Common Issues

| Issue / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| **CUDA error: no kernel image is available for execution** | vLLM V1 engine attempting to run unsupported kernels on Volta V100. | Ensure `export VLLM_USE_V1=0` is set in the environment or `.def` file. |
| **NaN output or loss divergence** | `Bfloat16` precision selected on hardware lacking BF16 Tensor Cores. | Add `--dtype float16` and set `NVIDIA_TF32_OVERRIDE=0`. |
| **`Connection refused` on port 18000** | Slurm compute node has not started Uvicorn yet, or SSH tunnel is pointing to wrong node. | Check `squeue -u $USER` to confirm GPU node hostname and inspect `vllm-*.out` log. |
| **`401 Unauthorized` on Gateway** | Client API key is missing or invalid. | Log in as admin at `http://127.0.0.1:9000/` and issue a new `sk-hpc-...` key. |
| **Out of Memory (OOM) during serving** | Context window `max-model-len` exceeds available VRAM. | Set `--gpu-memory-utilization 0.90` and `--max-model-len 4096` or `8192`. |
