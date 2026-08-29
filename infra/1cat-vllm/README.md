# 1Cat-vLLM Infrastructure for Tesla V100 (SM70)

This repository layout mirrors the structure of [`local-llm/infra/vllm`](file:///home/dev/local-llm/infra/vllm), purpose-built for building, serving, and testing **[1Cat-vLLM](https://github.com/1CatAI/1Cat-vLLM)** on **NVIDIA Tesla V100 (Volta / SM70)** GPUs with **`FLASH_ATTN_V100`** and **TurboMind AWQ** kernels.

---

## 1. Directory Structure

```
local-llm/infra/1cat-vllm/
├── defs/
│   └── 1cat_vllm.def                 # Apptainer container definition (CUDA 12.8, PyTorch cu128, 1Cat-vLLM)
├── build_1cat_vllm_sif.sh            # Script to build immutable build/1cat-vllm.sif image
├── make_1cat_vllm_sandbox.sh         # Script to build writable build/1cat_vllm_sandbox for debugging
├── setup_env.sh                      # Alternative Conda environment setup script (1cat-vllm-sm70)
├── download_model.sh                 # Quick model download script (CLI / login node)
├── serve_local.sh                    # Interactive / local serving script
├── slurm/
│   ├── download/
│   │   └── hf_download_qwen3.5_9b_awq.sbatch   # CPU batch job to download Qwen AWQ model
│   ├── serving/
│   │   ├── vllm-1cat-singlegpu.sbatch          # Single V100 serving (TP=1, FLASH_ATTN_V100)
│   │   └── vllm-1cat-multigpu.sbatch           # Multi V100 serving (TP=2/4)
│   └── tests/
│       └── test_flash_attn_v100.sbatch         # Container & GPU sanity check sbatch
└── README.md                                   # This guide
```

---

## 2. Recommended Model

- **Model ID**: [`QuantTrio/Qwen3.5-9B-AWQ`](https://huggingface.co/QuantTrio/Qwen3.5-9B-AWQ)
- **Quantization**: AWQ 4-bit (INT4) with native TurboMind SM70 kernel acceleration.
- **Default Storage Path**: `/home/ducledinh/dev/models/Qwen3.5-9B-AWQ`

---

## 3. End-to-End Workflow

### Step 1: Build the Apptainer Container
Build the standalone `.sif` image on a machine or node with build permissions:
```bash
./build_1cat_vllm_sif.sh
```
*Output: `build/1cat-vllm.sif`*

---

### Step 2: Download Model
Option A: Run the interactive script on Login Node:
```bash
./download_model.sh /home/ducledinh/dev/models QuantTrio/Qwen3.5-9B-AWQ
```

Option B: Submit CPU Slurm batch job:
```bash
sbatch slurm/download/hf_download_qwen3.5_9b_awq.sbatch
```

---

### Step 3: Run Sanity Test
Verify that the container, PyTorch CUDA 12.8, and `FLASH_ATTN_V100` are functioning on a V100 node:
```bash
sbatch slurm/tests/test_flash_attn_v100.sbatch
```

---

### Step 4: Submit Serving Job

#### Single GPU (1 x Tesla V100):
```bash
sbatch slurm/serving/vllm-1cat-singlegpu.sbatch
```

#### Multi-GPU (2 x Tesla V100, TP=2):
```bash
sbatch slurm/serving/vllm-1cat-multigpu.sbatch
```

#### Custom Parameters:
You can override parameters on submission:
```bash
MODEL="Qwen3.5-9B-AWQ" \
PORT=8000 \
API_KEY="my-secret-key-123" \
sbatch slurm/serving/vllm-1cat-singlegpu.sbatch
```

---

## 4. Monitoring & Connection

### Check Job Status:
```bash
squeue -u "$USER"
```

### Stream Startup Logs:
```bash
tail -f logs/1cat-vllm-<JOB_ID>.out
```

When ready, the server exposes an OpenAI-compatible API endpoint recorded in `logs/endpoint-<JOB_ID>.json`:
```text
==========================================================
job_id=12345
node=gpunode2
image=.../build/1cat-vllm.sif
model=Qwen3.5-9B-AWQ
tp=1
port=8000
backend=FLASH_ATTN_V100 (SM70 TurboMind)
==========================================================
INFO:     Started server process [12345]
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## 5. Testing & API Usage

### Direct Curl Call (from HPC node):
```bash
curl http://gpunode2:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dacn-qwen-secret-key" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [{"role": "user", "content": "Hello Qwen 3.5 on Volta V100!"}],
    "temperature": 0.7
  }'
```

### SSH Tunnel to Local Laptop:
```bash
ssh -L 8000:gpunode2:8000 ducledinh@node16
```

### Python OpenAI SDK:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://gpunode2:8000/v1",  # or "http://localhost:8000/v1"
    api_key="dacn-qwen-secret-key",
)

response = client.chat.completions.create(
    model="qwen3.5-9b",
    messages=[
        {"role": "user", "content": "Write a fast matrix multiplication benchmark in Python using PyTorch."}
    ],
    temperature=0.2,
    max_tokens=512,
)

print(response.choices[0].message.content)
```

---

## 6. Stop Server

```bash
scancel <JOB_ID>
```
