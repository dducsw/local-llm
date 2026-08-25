# Infrastructure Deployment & Slurm Guide

This guide details how to build containers, download models, and deploy high-performance LLM inference servers using Slurm, Apptainer/Singularity, and vLLM on an HPC cluster.

---

## 1. HPC Deployment Workflow

```mermaid
flowchart TD
    subgraph BuildPhase ["1. Build & Preparation (Login/Build Node)"]
        DEF["defs/vllm.def"] --> BUILD["apptainer build build/vllm.sif"]
        BUILD --> SIF["build/vllm.sif (Container Image)"]
    end

    subgraph DownloadPhase ["2. Model Download (Compute Node Batch Job)"]
        DL_SCRIPT["slurm/download/hf_download_qwen9b_gguf.sbatch"]
        DL_SCRIPT --> SCRATCH["$SCRATCH/models/qwen3.5-9b-gguf/<br/>Qwen3.5-9B-Q4_K_M.gguf (~5.8 GB)"]
    end

    subgraph ServingPhase ["3. Single-GPU Serving (Slurm Compute Node)"]
        SBATCH["sbatch slurm/serving/vllm-singlegpu.sbatch"]
        SBATCH --> SLURM_ALLOC["Slurm Resource Allocation<br/>1 GPU (V100) | 4 CPUs | 32GB RAM"]
        SLURM_ALLOC --> RUN_CONTAINER["Apptainer Run (vllm.sif)<br/>VLLM_USE_V1=0 | --dtype float16"]
        RUN_CONTAINER --> VLLM_PORT["vLLM Listening on 0.0.0.0:8000"]
    end

    subgraph TunnelPhase ["4. Local Access (Workstation)"]
        TUNNEL_CMD["./scripts/ssh-tunnel.sh"]
        TUNNEL_CMD --> LOCAL_PORT["127.0.0.1:18000 &rarr; compute_node:8000"]
        LOCAL_PORT --> GATEWAY["FastAPI Gateway & vLLMlocal UI (Port 9000)"]
    end

    SIF --> RUN_CONTAINER
    SCRATCH --> RUN_CONTAINER
    VLLM_PORT --> TUNNEL_CMD
```

---

## 2. Prerequisites & Environment

- **HPC Workload Scheduler**: Slurm Workload Manager.
- **Container Runtime**: Apptainer / Singularity (unprivileged runtime with GPU support `--nv`).
- **Target Hardware**: NVIDIA Tesla V100 (Volta SM70, 16GB / 32GB VRAM).
- **Filesystem**: Shared scratch or NFS filesystem accessible across cluster compute nodes.

---

## 3. Building the Apptainer Container

Build the vLLM container image from the definition file on a build or login node:

```bash
cd infra
mkdir -p build

apptainer build build/vllm.sif defs/vllm.def
```

*Note: The definition file `defs/vllm.def` builds upon `vllm/vllm-openai:v0.8.5.post1` and sets optimal flags for Volta V100 hardware (`VLLM_USE_V1=0`, `NVIDIA_TF32_OVERRIDE=0`, `--dtype float16`).*

---

## 4. Downloading Quantized GGUF Models

To avoid occupying expensive GPU node allocations during downloads, submit a dedicated batch download job:

```bash
cd infra

# Submit job to download Qwen 3.5 9B GGUF (Q4_K_M)
sbatch slurm/download/hf_download_qwen9b_gguf.sbatch
```

The script downloads the quantized GGUF weights directly to `$SCRATCH/models/qwen3.5-9b-gguf/` and automatically verifies file integrity.

---

## 5. Submitting Slurm Inference Jobs

```mermaid
sequenceDiagram
    autonumber
    actor User as User / DevOps
    participant Slurm as Slurm Scheduler (sbatch)
    participant Node as Assigned Compute Node
    participant Log as Log File (vllm-*.out)

    User->>Slurm: sbatch slurm/serving/vllm-singlegpu.sbatch
    Slurm-->>User: Submitted batch job 491823
    Slurm->>Node: Allocate 1x V100 GPU + 4 CPUs + 32GB RAM
    Node->>Node: Launch Apptainer vllm.sif
    Node->>Log: Writing startup logs & weight loading
    Note over Node,Log: VRAM allocated: 5.8 GB (Model) + 9.5 GB (KV Cache)
    Node->>Log: Uvicorn running on http://0.0.0.0:8000
    User->>Log: tail -f infra/logs/vllm-*.out
    User->>User: Identify node (e.g. gpunode1) & open SSH tunnel
```

### Job Specifications:
- **GPU Allocation**: 1 GPU (`#SBATCH --gres=gpu:1`)
- **CPU Cores**: 4 Cores (`#SBATCH --cpus-per-task=4`)
- **Memory**: 32 GB RAM (`#SBATCH --mem=32G`)
- **Target Model**: `Qwen3.5-9B-Q4_K_M.gguf`
- **Engine Flags**: `VLLM_USE_V1=0`, `--dtype float16`, `--max-model-len 8192`, `--gpu-memory-utilization 0.90`
- **Serving Port**: `8000` on the allocated compute node.

---

## 6. Monitoring & SSH Tunneling

### 6.1 Check Active Slurm Jobs
```bash
squeue -u $USER
```
Identify the assigned node name (e.g., `gpunode1.gitc.hpc`).

### 6.2 Monitor Real-Time vLLM Server Output
```bash
tail -f infra/logs/vllm-*.out
```
Wait until the log reports:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 6.3 Establish SSH Tunnel to Local Gateway
From your local machine / gateway host, forward port `18000` to port `8000` on the compute node:

```bash
cd app
GPU_NODE=gpunode1.gitc.hpc LOCAL_PORT=18000 ./scripts/ssh-tunnel.sh
```

---

## 7. Starting Gateway & Web Dashboard

Launch the FastAPI Gateway on your local machine:

```bash
cd app
./scripts/run.sh
```

Access the unified **vLLMlocal** dashboard at `http://127.0.0.1:9000/`.
