import asyncio
import json
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import (
    HPC_REMOTE_DIR,
    HPC_LOG_DIR,
    HPC_SLURM_ACCOUNT,
    HPC_SSH_HOST,
    HPC_SSH_USER,
    ROOT_DIR,
)
from app.state import ACTIVE_SLURM_JOBS, SLURM_JOBS_LOCK
from app.schemas import StartTunnelRequest, SubmitJobRequest
from app.services.auth_service import require_admin
from app.services.slurm_service import get_cluster_status, run_slurm_cli, run_slurm_cli_async
from app.services.tunnel_service import TUNNEL_MANAGER, watch_and_tunnel_job

router = APIRouter(
    prefix="/api/slurm",
    dependencies=[Depends(require_admin)],
    tags=["Slurm & Compute"],
)


@router.get("/status")
async def cluster_info():
    """Return connectivity and operation status of the Slurm cluster."""
    return get_cluster_status()


@router.get("/tunnel")
async def get_tunnel_status():
    """Return live status of the background SSH port-forwarding tunnel."""
    return TUNNEL_MANAGER.get_info()


@router.post("/tunnel/start")
async def start_tunnel_manual(body: StartTunnelRequest):
    """Manually start or re-route SSH tunnel to a specific compute node."""
    ok = TUNNEL_MANAGER.start(
        target_node=body.node,
        local_port=body.local_port,
        remote_port=body.remote_port,
    )
    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start SSH tunnel: {TUNNEL_MANAGER.last_error or 'unknown error'}",
        )
    return {"status": "running", "tunnel": TUNNEL_MANAGER.get_info()}


@router.post("/tunnel/stop")
async def stop_tunnel_manual():
    """Manually terminate the background SSH tunnel."""
    TUNNEL_MANAGER.stop()
    return {"status": "stopped", "tunnel": TUNNEL_MANAGER.get_info()}


@router.post("/tunnel/restart")
async def restart_tunnel_manual():
    """Manually cycle and restart the background SSH tunnel."""
    ok = TUNNEL_MANAGER.restart()
    return {"status": "running" if ok else "error", "tunnel": TUNNEL_MANAGER.get_info()}


@router.get("/nodes")
async def get_slurm_nodes():
    """Return cluster node states via sinfo (NODELIST, STATE, CPUS, MEMORY, GRES, PARTITION)."""
    code, stdout, _ = await run_slurm_cli_async(
        ["sinfo", "-N", "-p", "gpu-v100,gpu-queue", "-o", "%N|%T|%C|%m|%G|%P", "--noheader"]
    )
    if code != 0:
        code, stdout, _ = await run_slurm_cli_async(
            ["sinfo", "-N", "-o", "%N|%T|%C|%m|%G|%P", "--noheader"]
        )

    nodes = []
    if code == 0 and stdout:
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("NODELIST"):
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                node_name = parts[0].strip()
                state = parts[1].strip()
                cpus = parts[2].strip()
                mem = parts[3].strip()
                gres = parts[4].strip()
                partition = parts[5].strip() if len(parts) > 5 else "gpu-queue"
                nodes.append({
                    "node": node_name,
                    "state": state,
                    "cpus": cpus,
                    "memory": mem,
                    "gres": gres,
                    "partition": partition,
                })
        return {"nodes": nodes}

    return {"nodes": []}


@router.get("/jobs")
async def get_slurm_jobs(all_users: bool = False, partition: str | None = None):
    """Return active and recent Slurm job status and logs."""
    cmd = ["squeue", "--format=%i|%j|%P|%T|%M|%R|%b|%u", "--noheader"]
    if partition and partition != "all":
        cmd.extend(["-p", partition])
    if not all_users and HPC_SSH_USER:
        cmd.extend(["-u", HPC_SSH_USER])

    code, stdout, _ = await run_slurm_cli_async(cmd, use_cache=False)

    jobs = []
    if code == 0:
        if stdout and stdout.strip():
            for line in stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|")
                if len(parts) >= 6:
                    jobs.append({
                        "job_id": parts[0].strip(),
                        "name": parts[1].strip(),
                        "partition": parts[2].strip(),
                        "status": parts[3].strip(),
                        "time": parts[4].strip(),
                        "node": parts[5].strip(),
                        "gres": parts[6].strip() if len(parts) > 6 else "gpu:1",
                        "user": parts[7].strip() if len(parts) > 7 else (HPC_SSH_USER or "user"),
                    })
        return {"jobs": jobs}

    # If CLI failed or not connected: return in-memory jobs submitted via Web UI
    with SLURM_JOBS_LOCK:
        jobs = [j for j in ACTIVE_SLURM_JOBS if j.get("status") in ("RUNNING", "PENDING")]
    return {"jobs": jobs}


@router.get("/queue")
async def get_slurm_gpu_queue(partition: str = "gpu-queue"):
    """Return live squeue output for specified partition across all users (e.g. squeue -p gpu-queue)."""
    cmd = ["squeue"]
    if partition and partition != "all":
        cmd.extend(["-p", partition])
    cmd.extend(["--format=%i|%P|%j|%u|%t|%M|%D|%R|%b", "--noheader"])

    code, stdout, stderr = await run_slurm_cli_async(cmd, use_cache=False)
    queue = []
    if code == 0 and stdout:
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 8:
                queue.append({
                    "job_id": parts[0].strip(),
                    "partition": parts[1].strip(),
                    "name": parts[2].strip(),
                    "user": parts[3].strip(),
                    "status": parts[4].strip(),  # R, PD, CG, CD
                    "time": parts[5].strip(),
                    "nodes": parts[6].strip(),
                    "reason": parts[7].strip(),  # nodelist or reason e.g. (JobArrayTaskLimit)
                    "gres": parts[8].strip() if len(parts) > 8 else "-",
                })
    return {
        "status": "ok",
        "partition": partition,
        "total": len(queue),
        "running": len([q for q in queue if q["status"] == "R"]),
        "pending": len([q for q in queue if q["status"] == "PD"]),
        "jobs": queue,
    }


@router.post("/jobs/submit")
async def submit_slurm_job(body: SubmitJobRequest):
    """Submit new serving sbatch job (llama.cpp, 1Cat-vLLM, or standard vLLM) on Slurm cluster and auto-connect SSH tunnel."""
    model_str = (body.model or "").lower()

    if "llama" in model_str or model_str.endswith(".gguf") or "gguf" in model_str:
        script_rel = "llama-cpp/run_qwen_server.sbatch"
    elif "1cat" in model_str or "awq" in model_str:
        if body.tp > 1:
            script_rel = "1cat-vllm/slurm/serving/vllm-1cat-multigpu.sbatch"
        else:
            script_rel = "1cat-vllm/slurm/serving/vllm-1cat-singlegpu.sbatch"
    else:
        script_rel = "vllm/slurm/serving/vllm-singlegpu.sbatch"

    time_limit = body.time_limit.strip() if body.time_limit else "01:00:00"

    # Resolve remote directories and ensure logs folder exists
    remote_work_dir = HPC_REMOTE_DIR or "/home/ducledinh/dev/local-llm/infra"
    remote_log_dir = f"{remote_work_dir}/logs"

    submit_cmd = [
        "sbatch",
        f"--partition={body.partition}",
        f"--time={time_limit}",
        f"--output={remote_log_dir}/%x-%j.out",
        f"--error={remote_log_dir}/%x-%j.err",
    ]
    if body.gres and body.gres.strip():
        submit_cmd.append(f"--gres={body.gres.strip()}")
    if body.partition == "gpu-queue":
        submit_cmd.append("--qos=gpu-q")
    if HPC_SLURM_ACCOUNT:
        submit_cmd.append(f"--account={HPC_SLURM_ACCOUNT}")
    submit_cmd.append(script_rel)

    # If running on VM via SSH:
    if HPC_SSH_HOST:
        # Crucial: Automatically create all required logs directories if missing on the remote cluster
        ensure_logs_cmd = [
            "bash", "-c",
            f"mkdir -p '{remote_log_dir}' '{remote_work_dir}/logs' /home/ducledinh/dev/local-llm/logs '{remote_work_dir}/llama-cpp/logs'"
        ]
        await run_slurm_cli_async(ensure_logs_cmd, timeout=5.0, use_cache=False)

        code, stdout, stderr = await run_slurm_cli_async(submit_cmd, timeout=15.0, work_dir=remote_work_dir, use_cache=False)
        if code == 0 and "Submitted batch job" in stdout:
            job_id = stdout.strip().split()[-1]
            asyncio.create_task(watch_and_tunnel_job(job_id))
            return {
                "status": "submitted",
                "job_id": job_id,
                "message": f"Job #{job_id} ({script_rel}) submitted to HPC {body.partition}. Auto-Tunnel watcher started.",
            }
        elif code != 127:
            raise HTTPException(status_code=500, detail=f"SSH sbatch failed (code {code}): {stderr or stdout}")

    # If running directly on HPC node:
    script_path = ROOT_DIR / "infra" / script_rel
    if not script_path.exists():
        script_path = ROOT_DIR / "demo" / "run_qwen_server.sbatch"

    if script_path.exists():
        local_log_dir = ROOT_DIR / "infra" / "logs"
        local_log_dir.mkdir(parents=True, exist_ok=True)
        (ROOT_DIR / "logs").mkdir(parents=True, exist_ok=True)

        direct_cmd = [
            "sbatch",
            f"--partition={body.partition}",
            f"--time={time_limit}",
            f"--output={local_log_dir}/%x-%j.out",
            f"--error={local_log_dir}/%x-%j.err",
        ]
        if body.gres and body.gres.strip():
            direct_cmd.append(f"--gres={body.gres.strip()}")
        if body.partition == "gpu-queue":
            direct_cmd.append("--qos=gpu-q")
        if HPC_SLURM_ACCOUNT:
            direct_cmd.append(f"--account={HPC_SLURM_ACCOUNT}")
        direct_cmd.append(str(script_path))

        code, stdout, stderr = await run_slurm_cli_async(direct_cmd, use_cache=False)
        if code == 0 and "Submitted batch job" in stdout:
            job_id = stdout.strip().split()[-1]
            return {
                "status": "submitted",
                "job_id": job_id,
                "message": f"Job {job_id} ({script_rel}) submitted to {body.partition}",
            }

    # Local / Mock submission fallback with non-colliding mock ID
    new_id = f"mock_{int(time.time() * 1000) % 10000000}"
    new_job = {
        "job_id": new_id,
        "name": "qwen3.5-9b-vllm",
        "partition": body.partition,
        "status": "RUNNING",
        "time": "00:00:05",
        "node": "gpunode1",
        "gres": f"gpu:v100:{body.tp}",
        "model": body.model,
        "port": 8000,
        "tp": body.tp,
    }
    with SLURM_JOBS_LOCK:
        ACTIVE_SLURM_JOBS.insert(0, new_job)

    return {
        "status": "submitted",
        "job_id": new_id,
        "message": f"Job {new_id} started successfully on gpunode1 (mock mode)",
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_slurm_job(job_id: str):
    """Cancel a running Slurm job via scancel and cleanup tunnel."""
    code, stdout, stderr = await run_slurm_cli_async(["scancel", job_id], use_cache=False)
    if code == 0:
        # Check if any other jobs running
        jobs_res = await get_slurm_jobs()
        running_jobs = [j for j in jobs_res.get("jobs", []) if j.get("status") == "RUNNING" and j.get("job_id") != job_id]
        if not running_jobs:
            TUNNEL_MANAGER.stop()
        return {"status": "cancelled", "job_id": job_id, "message": f"Job {job_id} cancelled via scancel."}

    # Mock cancellation tracking
    with SLURM_JOBS_LOCK:
        for j in ACTIVE_SLURM_JOBS:
            if j.get("job_id") == job_id:
                j["status"] = "CANCELLED"
                break

    return {"status": "cancelled", "job_id": job_id, "message": f"Job {job_id} stopped."}


@router.get("/logs/{job_id}")
async def get_slurm_job_log(job_id: str):
    """Read standard output log for a given Slurm job ID (locally or via SSH)."""
    if not job_id.isdigit() and not job_id.startswith("mock_"):
        raise HTTPException(status_code=400, detail="Invalid Slurm job ID")

    if job_id.startswith("mock_"):
        return {
            "job_id": job_id,
            "log": f"Mock Slurm job {job_id} is running simulated inference workload.",
        }

    async def tail_remote(path: str, lines: int = 200) -> str:
        code, content, _ = await run_slurm_cli_async(
            ["tail", "-n", str(lines), path], use_cache=False, remote_only=True
        )
        return content if code == 0 else ""

    remote_log_paths = [
        f"{HPC_LOG_DIR}/qwen3.5-server-{job_id}.out",
        f"{HPC_LOG_DIR}/qwen3.5-server-{job_id}.err",
        f"{HPC_LOG_DIR}/vllm-{job_id}.out",
        f"{HPC_LOG_DIR}/vllm-{job_id}.err",
    ]
    if HPC_SSH_HOST:
        stdout_log = await tail_remote(remote_log_paths[0])
        stderr_log = await tail_remote(remote_log_paths[1])
        if stdout_log or stderr_log:
            return {"job_id": job_id, "stdout": stdout_log, "stderr": stderr_log, "log": stdout_log}

    code, job_info, _ = await run_slurm_cli_async(
        ["scontrol", "show", "job", "-o", job_id],
        use_cache=False,
        remote_only=bool(HPC_SSH_HOST),
    )
    if code == 0 and job_info:
        fields = dict(
            field.split("=", 1)
            for field in job_info.strip().split()
            if "=" in field
        )
        stdout_path = fields.get("StdOut")
        work_dir = fields.get("WorkDir")
        if stdout_path:
            if not stdout_path.startswith("/") and work_dir:
                stdout_path = f"{work_dir.rstrip('/')}/{stdout_path}"
            log_code, stdout, _ = await run_slurm_cli_async(
                ["tail", "-n", "200", stdout_path],
                use_cache=False,
                remote_only=bool(HPC_SSH_HOST),
            )
            if log_code == 0 and stdout:
                return {"job_id": job_id, "log": stdout}

    if HPC_SSH_HOST:
        code, stdout, _ = await run_slurm_cli_async([
            "tail", "-n", "100", f"{HPC_LOG_DIR}/vllm-{job_id}.out"
        ], use_cache=False, remote_only=True)
        if code == 0 and stdout:
            return {"job_id": job_id, "log": stdout}

    log_candidates = [
        ROOT_DIR / "infra" / "logs" / f"vllm-{job_id}.out",
        ROOT_DIR / "infra" / "logs" / f"qwen-server-{job_id}.out",
        ROOT_DIR / "infra" / "logs" / f"slurm-{job_id}.out",
        ROOT_DIR / "logs" / f"vllm-{job_id}.out",
        ROOT_DIR / "logs" / f"qwen-server-{job_id}.out",
        ROOT_DIR / "logs" / f"slurm-{job_id}.out",
    ]
    for path in log_candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                return {"job_id": job_id, "log": content[-8000:]}
            except Exception:
                pass

    return {
        "job_id": job_id,
        "log": f"No active log file found for Slurm Job ID {job_id} in {HPC_REMOTE_DIR}/logs/.",
    }


@router.get("/logs/{job_id}/stream")
async def stream_slurm_job_log(job_id: str, request: Request):
    """Stream live Slurm job output (stdout / stderr) in real-time via Server-Sent Events (SSE)."""
    if not job_id.isdigit() and not job_id.startswith("mock_"):
        raise HTTPException(status_code=400, detail="Invalid Slurm job ID")

    async def event_generator():
        last_content = ""
        iteration = 0
        try:
            while True:
                if await request.is_disconnected():
                    break

                log_data = await get_slurm_job_log(job_id)
                current_text = log_data.get("stdout") or log_data.get("log") or ""
                stderr_text = log_data.get("stderr") or ""
                if stderr_text and not current_text:
                    current_text = f"[stderr]\n{stderr_text}"

                if current_text != last_content or iteration == 0:
                    payload = {
                        "job_id": job_id,
                        "log": current_text,
                        "stderr": stderr_text,
                        "timestamp": time.time(),
                        "status": "STREAMING",
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_content = current_text
                else:
                    yield f": heartbeat {time.time()}\n\n"

                iteration += 1
                await asyncio.sleep(1.2)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
