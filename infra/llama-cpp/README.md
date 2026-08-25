# Deployment Guide for Qwen 3.5 9B (Q4_K_M) on HPC Slurm & Apptainer

This document guides you through deploying the **Qwen 3.5 9B Instruct (GGUF `Q4_K_M`)** model with **8K Context Size (`8192`)** as an OpenAI-compatible API Server (`/v1/chat/completions`) secured with an **API Key** on an HPC cluster.

---

## 1. File Structure in `infra/llama-cpp/`

- [download-model.sh](file:///home/dev/local-llm/infra/llama-cpp/download-model.sh): Script to download the GGUF model to `/home/ducledinh/dev/models/`.
- [run_qwen_server.sbatch](file:///home/dev/local-llm/infra/llama-cpp/run_qwen_server.sbatch): Slurm batch script to launch `llama-server` (CUDA) via Apptainer.
- [README.md](file:///home/dev/local-llm/infra/llama-cpp/README.md): Overview and deployment guide for Slurm & Apptainer on HPC.

---

## 2. Step-by-Step Deployment Workflow

### Step 1: Log in to the Login Node
```bash
ssh ducledinh@node16
cd /home/ducledinh/dev/local-llm/infra/llama-cpp
```

---

### Step 2: Pre-download the Model on the Login Node
Run the script to download the model into `/home/ducledinh/dev/models/`:
```bash
chmod +x download-model.sh
./download-model.sh
```
*Note: Downloading ~5.7GB takes around 2–4 minutes. The downloaded file will be saved at `/home/ducledinh/dev/models/Qwen3.5-9B-Q4_K_M.gguf`.*

---

### Step 3: Submit Job with Your API Key

Submit the job and pass your desired API Key via the `API_KEY` environment variable:

```bash
API_KEY="my-secret-key-123" sbatch run_qwen_server.sbatch
```

*(If `API_KEY` is not provided, the script will default to `dacn-qwen-3.5-9b-secret-key`)*.

---

## 3. Monitoring & Connection Details

### Check Job Status:
```bash
squeue -u "$USER"
```

### View Server Startup Logs:
```bash
tail -f logs/qwen3.5-server-<JOB_ID>.out
```

Once the server has finished loading the model into GPU VRAM, the log will show:
```text
==========================================================
 Job ID          : 12345
 Compute Node    : gpunode1 (NVIDIA V100)
 Image SIF       : /home/ducledinh/dev/container/llama-server-cuda.sif
 Port            : 8000
 Model Path      : /home/ducledinh/dev/models/Qwen3.5-9B-Q4_K_M.gguf
 Model Alias     : qwen3.5-9b
 Context Size    : 8192 (8K)
 Internal Endpoint: http://gpunode1:8000/v1
==========================================================
HTTP server is listening at http://0.0.0.0:8000
```

---

## 4. Testing & API Usage

### Method A: Direct Call from Login Node / Another HPC Compute Node
```bash
curl http://gpunode1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-secret-key-123" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [
      {"role": "user", "content": "Hello! Please give a brief self-introduction."}
    ],
    "temperature": 0.7
  }'
```

### Method B: Open SSH Tunnel to Local Machine (Laptop)
From the terminal on your local laptop:
```bash
ssh -L 8000:gpunode1:8000 ducledinh@node16
```
*(Replace `gpunode1` with the Compute Node hostname shown in your Job log).*

Then make requests locally on your laptop:
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-secret-key-123" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [{"role": "user", "content": "Write a PostgreSQL query to get the top 5 customers with the highest spending."}]
  }'
```

### Method C: Call from Python (OpenAI SDK / Backend / Agent)
```python
from openai import OpenAI

# Connect directly to HPC endpoint or via SSH tunnel localhost
client = OpenAI(
    base_url="http://gpunode1:8000/v1",  # or "http://localhost:8000/v1"
    api_key="my-secret-key-123",
)

response = client.chat.completions.create(
    model="qwen3.5-9b",
    messages=[
        {"role": "system", "content": "You are an expert Text-to-SQL assistant."},
        {"role": "user", "content": "Provide a SQL query to calculate monthly revenue for 2025."}
    ],
    temperature=0.2,
    max_tokens=1024
)

print(response.choices[0].message.content)
```

---

## 5. Stopping the Server

When no longer in use, cancel the Job to release GPU resources:
```bash
scancel <JOB_ID>
```
