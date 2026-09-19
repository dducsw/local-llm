import asyncio
import re
import time
import httpx
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

from app.config import HPC_SSH_USER, load_models, log
from app.services.slurm_service import run_slurm_cli_async

# 1. Traffic & Request Metrics
LLM_REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "Total count of LLM inference requests received",
    ["model", "status", "key_prefix", "stream"],
)

LLM_ACTIVE_REQUESTS = Gauge(
    "llm_active_requests",
    "Number of active in-flight LLM requests currently being processed",
    ["model"],
)

# 2. Latency & Performance Histograms
LLM_TTFT_SECONDS = Histogram(
    "llm_time_to_first_token_seconds",
    "Time to first token (TTFT) in seconds for streaming responses",
    ["model"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

LLM_LATENCY_SECONDS = Histogram(
    "llm_request_duration_seconds",
    "End-to-end request duration in seconds",
    ["model", "stream"],
    buckets=[0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

LLM_TOKENS_PER_SEC = Histogram(
    "llm_tokens_per_second",
    "Inference throughput in tokens per second on GPU cluster",
    ["model"],
    buckets=[10, 25, 50, 75, 90, 100, 125, 150, 200],
)

# 3. Token Accounting Counters
LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total token count processed by model and token type",
    ["model", "type", "key_prefix"],
)

# 4. Reliability & Infrastructure Metrics
LLM_UPSTREAM_ERRORS_TOTAL = Counter(
    "llm_upstream_errors_total",
    "Total count of errors encountered contacting HPC upstream",
    ["model", "error_type"],
)

LLM_SSH_TUNNEL_UP = Gauge(
    "llm_ssh_tunnel_up",
    "State of the SSH port-forwarding tunnel to HPC cluster (1=UP, 0=DOWN)",
)


def export_prometheus_metrics() -> tuple[bytes, str]:
    """Generate and return current Prometheus metrics scrape payload."""
    return generate_latest(), CONTENT_TYPE_LATEST


# 5. Live GPU & Engine Telemetry Scraper
_GPU_CACHE: dict[str, tuple[float, dict]] = {}
_GPU_CACHE_TTL = 3.0  # seconds
_GPU_CACHE_LOCK = asyncio.Lock()


def _parse_nvidia_smi(stdout: str) -> dict | None:
    """Helper to parse CSV output of nvidia-smi."""
    if not stdout or not stdout.strip():
        return None
    try:
        line = stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            used_mb = float(parts[1])
            total_mb = float(parts[2])
            parsed = {
                "device_name": parts[0],
                "vram_used_mb": int(used_mb),
                "vram_total_mb": int(total_mb),
                "vram_free_mb": int(total_mb - used_mb),
                "vram_used_gb": round(used_mb / 1024.0, 1),
                "vram_total_gb": round(total_mb / 1024.0, 1),
                "vram_used_pct": round((used_mb / total_mb) * 100.0, 1) if total_mb > 0 else 0.0,
                "gpu_utilization_pct": int(float(parts[3])),
                "gpu_temperature_c": int(float(parts[4])),
                "gpu_power_w": round(float(parts[5]), 1),
            }
            if len(parts) >= 7:
                parsed["driver_version"] = parts[6]
            return parsed
    except Exception as exc:
        log.debug("Error parsing nvidia-smi output: %s", exc)
    return None


async def get_live_gpu_telemetry() -> dict:
    """Fetch real-time GPU hardware telemetry from nvidia-smi, vLLM / llama.cpp engines."""
    now = time.time()
    if "data" in _GPU_CACHE:
        cached_ts, cached_data = _GPU_CACHE["data"]
        if now - cached_ts < _GPU_CACHE_TTL:
            return cached_data

    async with _GPU_CACHE_LOCK:
        if "data" in _GPU_CACHE:
            cached_ts, cached_data = _GPU_CACHE["data"]
            if now - cached_ts < _GPU_CACHE_TTL:
                return cached_data

        result = {
            "status": "STANDBY",
            "backend_type": "vLLM",
            "device_name": "NVIDIA Tesla V100-SXM2",
            "architecture": "Volta (SM70)",
            "vram_total_mb": 16384,
            "vram_used_mb": 0,
            "vram_free_mb": 16384,
            "vram_used_gb": 0.0,
            "vram_total_gb": 16.0,
            "vram_used_pct": 0.0,
            "gpu_utilization_pct": 0,
            "gpu_temperature_c": None,
            "gpu_power_w": None,
            "driver_version": "535.183",
            "cuda_version": "12.2",
            "kv_cache_free_pct": 100.0,
            "kv_cache_used_pct": 0.0,
            "vllm_running_reqs": 0,
            "vllm_waiting_reqs": 0,
            "nodes_count": 4,
            "active_node": None,
            "active_job_id": None,
        }

        # 1. Check active running Slurm jobs
        active_job = None
        active_node = None
        try:
            from app.services.tunnel_service import TUNNEL_MANAGER
            if TUNNEL_MANAGER.job_id:
                active_job = TUNNEL_MANAGER.job_id
                active_node = TUNNEL_MANAGER.target_node
        except Exception:
            pass

        if not active_job:
            squeue_cmd = ["squeue", "--format=%i|%j|%P|%T|%M|%R", "--noheader"]
            if HPC_SSH_USER:
                squeue_cmd.extend(["-u", HPC_SSH_USER])
            sq_code, sq_out, _ = await run_slurm_cli_async(squeue_cmd, timeout=8.0, use_cache=True)
            if sq_code == 0 and sq_out:
                for line in sq_out.strip().splitlines():
                    parts = line.strip().split("|")
                    if len(parts) >= 6:
                        st = parts[3].strip().upper()
                        nd = parts[5].strip()
                        jid = parts[0].strip()
                        if st == "RUNNING" and nd and not nd.startswith("("):
                            active_job = jid
                            active_node = nd
                            break

        result["active_job_id"] = active_job
        result["active_node"] = active_node

        if active_job:
            result["status"] = "WARMING_UP"

        # 2. Query nvidia-smi from compute node
        gpu_scraped = False
        if active_job:
            cmd = [
                "srun", f"--jobid={active_job}", "--overlap",
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,driver_version",
                "--format=csv,noheader,nounits",
            ]
            code, stdout, _ = await run_slurm_cli_async(cmd, timeout=8.0, use_cache=True)
            if code == 0 and stdout:
                parsed = _parse_nvidia_smi(stdout)
                if parsed:
                    result.update(parsed)
                    gpu_scraped = True

        if not gpu_scraped:
            cmd = [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,driver_version",
                "--format=csv,noheader,nounits",
            ]
            code, stdout, _ = await run_slurm_cli_async(cmd, timeout=5.0, use_cache=True)
            if code == 0 and stdout:
                parsed = _parse_nvidia_smi(stdout)
                if parsed:
                    result.update(parsed)
                    gpu_scraped = True

        # 3. Query Engine Metrics (vLLM Prometheus /metrics or llama.cpp /slots)
        models = load_models()
        if models:
            first_cfg = next(iter(models.values()))
            base_url = first_cfg.get("base_url", "http://127.0.0.1:18000").rstrip("/")

            # Check vLLM /metrics
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    vllm_resp = await client.get(f"{base_url}/metrics")
                    if vllm_resp.status_code == 200:
                        text = vllm_resp.text
                        result["status"] = "SERVING"
                        result["backend_type"] = "vLLM (FlashAttn V100)"

                        kv_match = re.search(r"vllm:gpu_cache_usage_factor\{?[^\}]*\}?\s+([0-9\.]+)", text)
                        if kv_match:
                            used_factor = float(kv_match.group(1))
                            result["kv_cache_used_pct"] = round(used_factor * 100.0, 1)
                            result["kv_cache_free_pct"] = round((1.0 - used_factor) * 100.0, 1)

                        running_match = re.search(r"vllm:num_requests_running\{?[^\}]*\}?\s+([0-9\.]+)", text)
                        if running_match:
                            result["vllm_running_reqs"] = int(float(running_match.group(1)))

                        waiting_match = re.search(r"vllm:num_requests_waiting\{?[^\}]*\}?\s+([0-9\.]+)", text)
                        if waiting_match:
                            result["vllm_waiting_reqs"] = int(float(waiting_match.group(1)))
                    else:
                        # Check llama.cpp /slots
                        slots_resp = await client.get(f"{base_url}/slots")
                        if slots_resp.status_code == 200:
                            result["status"] = "SERVING"
                            result["backend_type"] = "llama.cpp (GGUF CUDA)"
                            slots_data = slots_resp.json()
                            if isinstance(slots_data, list):
                                busy_slots = sum(1 for s in slots_data if s.get("is_processing"))
                                result["vllm_running_reqs"] = busy_slots
                                total_slots = len(slots_data) or 1
                                result["kv_cache_used_pct"] = round((busy_slots / total_slots) * 100.0, 1)
                                result["kv_cache_free_pct"] = round((1.0 - busy_slots / total_slots) * 100.0, 1)
            except Exception:
                pass

        _GPU_CACHE["data"] = (now, result)
        return result
