# Deployment Guide: VM Gateway & HPC Slurm Inference

This architecture splits the system into two main components:
1. **Virtual Machine (VM)**: Runs the AI Local Gateway (FastAPI + Dashboard UI), manages API keys, rate limits, and telemetry. This Gateway exposes the service to your internal network or the internet for clients to access.
2. **HPC Slurm Node**: Runs the backend inference engine (vLLM) on GPUs (e.g., V100) using **Apptainer**. Because HPC nodes typically reside in strict private networks, the VM connects to the HPC environment via a secure **SSH Tunnel**.

Below is the detailed deployment workflow based on the project's structure:

---

## 1. Environment Preparation & Model Download on HPC

Perform these steps on the HPC Login Node (or Build Node).

### 1.1. Build the Apptainer Container for vLLM
Since HPC environments usually prohibit direct Docker usage (which requires root privileges), the system uses Apptainer (Singularity). Build the `.sif` image from the provided definition file:

```bash
cd infra
mkdir -p build
apptainer build build/vllm.sif defs/vllm.def
```
*Note: This image is optimized for V100 (Volta SM70) GPUs.*

### 1.2. Download the Model (GGUF Quantized)
Instead of downloading directly on the login node (which might be limited in bandwidth or resources), submit a Slurm job to handle the download:

```bash
cd infra
sbatch slurm/download/hf_download_qwen9b_gguf.sbatch
```
This job downloads the Qwen 3.5 9B (Q4_K_M) model to the shared scratch directory (typically `$SCRATCH/models/qwen3.5-9b-gguf/`).

---

## 2. Deploy Backend (vLLM) on HPC Compute Node

Once the model download is complete, submit the vLLM inference job to Slurm:

```bash
sbatch slurm/serving/vllm-singlegpu.sbatch
```

**Monitor the startup process:**
1. Retrieve the hostname of the active compute node (e.g., `gpunode1.gitc.hpc`):
   ```bash
   squeue -u $USER
   ```
2. Tail the log file to ensure vLLM has started successfully and is listening on port 8000:
   ```bash
   tail -f infra/logs/vllm-*.out
   ```
   *Wait until you see: `Uvicorn running on http://0.0.0.0:8000`.*

---

## 3. Establish SSH Tunnel from VM to HPC

Switch to the **VM (Gateway)** machine. You need to open an SSH Tunnel connecting directly to the Compute Node (e.g., `gpunode1.gitc.hpc`) via the HPC Login Node.

### 3.1. Configure Passwordless SSH (Required)
To allow the Gateway (and Slurm monitoring scripts) to connect automatically without prompting for a password, generate an SSH key on the VM and copy it to the HPC Login Node:

```bash
# 1. Generate SSH Key on the VM (if you haven't already)
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# 2. Copy the public key to the HPC Login Node
ssh-copy-id hpc_user@hpc-login.gitc
```
*(Replace `hpc_user@hpc-login.gitc` with your actual HPC SSH login credentials. You will be prompted for your HPC password once).*

### 3.2. Start the SSH Tunnel
The project provides a utility script to establish the tunnel:

```bash
cd app
GPU_NODE=gpunode1.gitc.hpc LOCAL_PORT=18000 ./scripts/ssh-tunnel.sh
```

This command will port-forward local port `18000` on the VM to port `8000` on the Compute Node (`gpunode1`).

---

## 4. Configure & Run AI Local Gateway on VM

On the **VM**, configure the Gateway to route requests through the established SSH Tunnel.

### 4.1. Update Model Configuration
Edit `app/config/models.json` and set the `base_url` to point to the tunneled port (`18000`):

```json
{
    "models": [
        {
            "id": "qwen3.5-9b",
            "upstream_model": "Qwen/Qwen3.5-9B-Instruct",
            "base_url": "http://127.0.0.1:18000/v1",
            "owned_by": "hpc-cluster"
        }
    ]
}
```

### 4.2. Initialize `.env`
Create or modify the `.env` file in the root directory to configure a secure Admin password:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_super_secret_password
```

### 4.3. Launch the Gateway
Start the system using Docker Compose (or the `run.sh` script if running natively):

```bash
# Using Docker Compose:
docker-compose up -d

# OR natively using the script:
cd app
./scripts/run.sh
```

---

## 5. End-to-End Testing

1. Access the **Dashboard** at `http://<VM_IP>:9000`.
2. Sign in and generate a new API Key.
3. Open the **Inference Playground** tab, select the `qwen3.5-9b` model, and send a test prompt.

**The data flow will look like this:**
`Browser Request -> VM Gateway (9000) -> VM SSH Tunnel (18000) -> HPC Login Node -> HPC Compute Node (8000) -> Apptainer vLLM`.

---

## 6. Expose Gateway with Cloudflare Tunnel (Optional but Recommended)

To securely expose your Gateway to the internet using your custom domain (e.g., `llm.ledinhduc.id.vn`) without opening any inbound ports or managing SSL certificates manually, use Cloudflare Tunnel.

### 6.1. Install `cloudflared` on the VM
```bash
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

### 6.2. Authenticate and Create Tunnel
```bash
# Login to your Cloudflare account (this will open a browser link)
cloudflared tunnel login

# Create a new tunnel
cloudflared tunnel create hpc-llm-tunnel
```
*Note down the `Tunnel-ID` outputted by the command above.*

### 6.3. Route Domain to the Tunnel
```bash
# Point your custom domain to the tunnel
cloudflared tunnel route dns hpc-llm-tunnel llm.ledinhduc.id.vn
```

### 6.4. Configure and Run the Tunnel
Create a configuration file `~/.cloudflared/config.yml` on the VM:

```yaml
tunnel: <Your-Tunnel-ID>
credentials-file: /home/<your-user>/.cloudflared/<Your-Tunnel-ID>.json

ingress:
  - hostname: llm.ledinhduc.id.vn
    service: http://localhost:9000
  - service: http_status:404
```
*(Replace `<Your-Tunnel-ID>` and `<your-user>` with your actual values).*

Finally, install and start the Cloudflare Tunnel as a background system service:
```bash
sudo cloudflared service install ~/.cloudflared/config.yml
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

🎉 **Done!** Your Gateway and API endpoints are now securely accessible at `https://llm.ledinhduc.id.vn`. Clients can send requests to `https://llm.ledinhduc.id.vn/v1/chat/completions`.
