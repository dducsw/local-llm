# Deployment Guide: VM Gateway & HPC Slurm Inference

This architecture splits the system into two main components:
1. **Virtual Machine (VM)**: Runs the AI Local Gateway (FastAPI + Dashboard UI), manages API keys, rate limits, and telemetry. This Gateway exposes the service to your internal network or the internet for clients to access.
2. **HPC Slurm Node**: Runs the backend inference engine (vLLM) on GPUs (e.g., V100) using **Apptainer**. Because HPC nodes typically reside in strict private networks, the VM connects to the HPC environment via a secure **SSH Tunnel**.

Below is the detailed deployment workflow based on the project's structure:

---

## 1. Environment Preparation & Model Download on HPC

Perform these steps on the HPC Login Node (or Build Node).

### 1.1. Build the Apptainer Container for vLLM
Since HPC environments usually prohibit direct Docker usage (which requires root privileges), the system uses Apptainer (Singularity). You can build either a standalone `.sif` image or an editable `--sandbox` directory.

#### Option A: Build Standalone SIF Image (Production)
```bash
cd infra
mkdir -p build
apptainer build build/vllm.sif defs/vllm.def
```

#### Option B: Build Editable Sandbox (`--sandbox`) (Recommended for Development & Patching)
A sandbox directory extracts the root filesystem into a folder instead of an immutable `.sif` file. This allows you to hot-patch libraries, install additional Python packages, or debug without rebuilding the entire multi-gigabyte container image from scratch:

```bash
cd infra
mkdir -p build

# 1. Build sandbox directly from definition file:
apptainer build --sandbox build/vllm.sandbox defs/vllm.def

# (Or convert an existing .sif image into a sandbox):
# apptainer build --sandbox build/vllm.sandbox build/vllm.sif
```

**Modifying & Testing within the Sandbox:**
```bash
# Enter sandbox with write permissions (to install wheels, modify vLLM/PyTorch source):
apptainer shell --writable --fakeroot build/vllm.sandbox

# Example: Reinstall custom patched torch/nccl wheel inside sandbox
# pip install --no-cache-dir --force-reinstall /path/to/custom_wheel.whl

# Test running directly against the sandbox:
apptainer run --nv build/vllm.sandbox python3 -m vllm.entrypoints.openai.api_server --help
```

**Exporting Sandbox back to SIF (When Stable):**
```bash
apptainer build build/vllm-final.sif build/vllm.sandbox
```
*Note: Both `.sif` and `.sandbox` can be referenced directly in Slurm job scripts (`vllm-singlegpu.sbatch`).*

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

---

## 3. Establish SSH Tunnel from VM to HPC (Secure 2-Hop Architecture)

Trong cụm HPC Slurm thực tế, các Compute Node (`gpunode1`) được đặt trong mạng riêng biệt đằng sau tường lửa (Firewall) và không mở cổng trực tiếp ra ngoài. Kiến trúc kết nối an toàn 2 chặng (**2-Hop Reverse Tunnel**) được sử dụng để chuyển tiếp dữ liệu an toàn.

### 3.1. Sơ đồ luồng mạng & Bảo mật
```text
[AI Gateway (Docker)] ➔ host.docker.internal:18000
       │
       │  [Chặng 2: SSH Local Forward (-L)] (Mã hóa SSH Ed25519)
       ▼
[Login Node: 10.1.1.239] ➔ 127.0.0.1:18000 (Chỉ lắng nghe Localhost)
       │
       │  [Chặng 1: Slurm Reverse Tunnel (-R)] (Mã hóa SSH nội bộ)
       ▼
[Compute Node: gpunode1] ➔ localhost:8000 (GPU V100 - sau Firewall)
```

### 3.2. Chặng 1: Thiết lập Reverse Tunnel từ Compute Node về Login Node
Sau khi job Slurm được cấp phát trên node (ví dụ: `gpunode1`, Job ID `5123`), chạy lệnh cầu nối ngược:

```bash
# Thực hiện trên HPC Login Node (10.1.1.239)
srun --jobid=<JOB_ID> --overlap ssh -o StrictHostKeyChecking=no -N -R 18000:localhost:8000 $USER@10.1.1.239 &
```
*(Mẹo: Bạn có thể đưa dòng lệnh này trực tiếp vào cuối file `.sbatch` để tự động hóa khi khởi chạy model).*

### 3.3. Chặng 2: Thiết lập SSH Tunnel từ VM / Local Gateway
Trên máy **VM / Local Gateway**, chỉ cần khởi chạy script hỗ trợ:

```bash
cd /home/dev/local-llm
./app/scripts/ssh-tunnel.sh
```

*(Chạy ngầm dưới dạng background service):*
```bash
nohup ./app/scripts/ssh-tunnel.sh > /tmp/ssh-tunnel.log 2>&1 &
```

### 3.4. Đánh giá tính An toàn & Bảo mật (Security Audit)
Cách tiếp cận này tuân thủ đầy đủ chuẩn bảo mật cao cấp của hệ thống HPC:
1. **Không mở cổng Firewall công khai:** Compute Node hoàn toàn ẩn sau Firewall nội bộ, không bị quét cổng hay tấn công dò quét từ bên ngoài.
2. **Mã hóa đa tầng (End-to-End SSH Encryption):** Toàn bộ prompt, dữ liệu nhạy cảm và token suy luận được mã hóa bằng chuẩn `Ed25519` + `ChaCha20-Poly1305 / AES-GCM`.
3. **Localhost Binding Isolation:** Cổng `18000` trên Login Node chỉ lắng nghe trên `127.0.0.1`, chỉ người dùng có khóa SSH hợp lệ mới có thể tương tác.
4. **Xác thực 2 lớp (Double Authentication):** Yêu cầu xác thực khóa SSH tại tầng mạng và `Bearer API Key` tại tầng ứng dụng vLLM/Llama-server.

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

### 4.2. Initialize `.env` & Docker Secrets Configuration
Copy the template `.env.example` to `.env` and fill in your details:

```bash
cp .env.example .env
```

Key environment parameters:
```env
# 1. Administrator Dashboard Credentials
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_super_secret_password
ADMIN_TOKEN=your_super_secret_admin_token

# 2. HPC Supervision Settings (Secured via Docker Secrets)
HPC_SSH_HOST=10.1.1.239
HPC_SSH_USER=ducledinh
HPC_HOST_SSH_KEY=/root/.ssh/id_ed25519
HPC_SSH_KEY=/run/secrets/hpc_ssh_key
HPC_REMOTE_DIR=/home/ducledinh/dev/local-llm/infra
HPC_SLURM_ACCOUNT=summer-school
```

> [!TIP]
> **Security Note:** Instead of mounting the entire `~/.ssh` directory into the container (which risks leaking all host private keys), `docker-compose.yml` uses **Docker Secrets** (`secrets: [hpc_ssh_key]`). Only the designated key is mounted read-only into `/run/secrets/hpc_ssh_key`.

### 4.3. Launch the Gateway
Start the system using Docker Compose:

```bash
docker compose up -d --build
```
*(Or natively using `./scripts/run.sh` inside the `app/` directory if not running in Docker).*

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
