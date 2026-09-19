import asyncio
import json
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import (
    DEFAULT_SLURM_PARTITION,
    HPC_REMOTE_DIR,
    HPC_LOG_DIR,
    HPC_SLURM_ACCOUNT,
    HPC_SSH_HOST,
    HPC_SSH_USER,
    ROOT_DIR,
    SLURM_PARTITIONS_CONFIG,
)
from app.state import ACTIVE_SLURM_JOBS, SLURM_JOBS_LOCK
from app.schemas import StartTunnelRequest, SubmitJobRequest
from app.services.auth_service import require_admin, require_viewer_or_admin
from app.services.slurm_service import get_cluster_status, run_slurm_cli, run_slurm_cli_async
from app.services.tunnel_service import TUNNEL_MANAGER, watch_and_tunnel_job

router = APIRouter(
    prefix="/api/slurm",
    dependencies=[Depends(require_viewer_or_admin)],
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


@router.post("/tunnel/start", dependencies=[Depends(require_admin)])
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


@router.post("/tunnel/stop", dependencies=[Depends(require_admin)])
async def stop_tunnel_manual():
    """Manually terminate the background SSH tunnel."""
    TUNNEL_MANAGER.stop()
    return {"status": "stopped", "tunnel": TUNNEL_MANAGER.get_info()}


@router.post("/tunnel/restart", dependencies=[Depends(require_admin)])
async def restart_tunnel_manual():
    """Manually cycle and restart the background SSH tunnel."""
    ok = TUNNEL_MANAGER.restart()
    return {"status": "running" if ok else "error", "tunnel": TUNNEL_MANAGER.get_info()}


@router.get("/nodes")
async def get_slurm_nodes():
    """Return cluster node states via sinfo (NODELIST, STATE, CPUS, MEMORY, GRES, PARTITION)."""
    code, stdout, _ = await run_slurm_cli_async(
        ["sinfo", "-N", "-p", SLURM_PARTITIONS_CONFIG, "-o", "%N|%T|%C|%m|%G|%P", "--noheader"]
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
async def get_slurm_gpu_queue(partition: str = DEFAULT_SLURM_PARTITION):
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


@router.post("/jobs/submit", dependencies=[Depends(require_admin)])
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
    remote_work_dir = HPC_REMOTE_DIR
    remote_log_dir = HPC_LOG_DIR or f"{remote_work_dir}/logs"

    submit_cmd = [
        "sbatch",
        f"--partition={body.partition}",
        f"--time={time_limit}",
        f"--output={remote_log_dir}/%x-%j.out",
        f"--error={remote_log_dir}/%x-%j.err",
    ]
    if body.gres and body.gres.strip():
        submit_cmd.append(f"--gres={body.gres.strip()}")
    if body.partition == DEFAULT_SLURM_PARTITION:
        submit_cmd.append("--qos=gpu-q")
    if HPC_SLURM_ACCOUNT:
        submit_cmd.append(f"--account={HPC_SLURM_ACCOUNT}")
    submit_cmd.append(script_rel)

    # If running on VM via SSH:
    if HPC_SSH_HOST:
        ensure_logs_cmd = [
            "bash", "-c",
            f"mkdir -p '{remote_log_dir}' '{remote_work_dir}/logs' '{remote_work_dir}/llama-cpp/logs'"
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


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_admin)])
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
    """Read standard output and error logs for a given Slurm job ID (locally or via SSH)."""
    if not job_id.isdigit() and not job_id.startswith("mock_"):
        raise HTTPException(status_code=400, detail="Invalid Slurm job ID")

    if job_id.startswith("mock_"):
        return {
            "job_id": job_id,
            "stdout": f"Mock Slurm job {job_id} is running simulated inference workload.",
            "stderr": "",
            "log": f"Mock Slurm job {job_id} is running simulated inference workload.",
        }

    def combine_output(stdout_str: str, stderr_str: str) -> str:
        s_out = (stdout_str or "").strip()
        s_err = (stderr_str or "").strip()
        if s_out and s_err:
            if s_out == s_err:
                return s_out
            return f"=== STDOUT ===\n{s_out}\n\n=== STDERR ===\n{s_err}"
        return s_out or s_err or ""

    stdout_log = ""
    stderr_log = ""
    job_state = ""
    job_user = ""
    job_reason = ""

    # 1. Query job details via scontrol to locate exact StdOut and StdErr paths
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
        job_state = fields.get("JobState", "")
        job_user = fields.get("UserId", "").split("(")[0]
        job_reason = fields.get("Reason", "")
        stdout_path = fields.get("StdOut")
        stderr_path = fields.get("StdErr")
        work_dir = fields.get("WorkDir", "")

        if stdout_path and stdout_path != "/dev/null":
            if not stdout_path.startswith("/") and work_dir:
                stdout_path = f"{work_dir.rstrip('/')}/{stdout_path}"
            t_code, t_out, t_err = await run_slurm_cli_async(
                ["tail", "-n", "200", stdout_path],
                use_cache=False,
                remote_only=bool(HPC_SSH_HOST),
            )
            if t_code == 0:
                stdout_log = t_out
            elif "Permission denied" in (t_err or t_out):
                stdout_log = f"[Permission Denied] Log file belongs to cluster user '{job_user}'."

        if stderr_path and stderr_path != "/dev/null":
            if not stderr_path.startswith("/") and work_dir:
                stderr_path = f"{work_dir.rstrip('/')}/{stderr_path}"
            if stderr_path == stdout_path:
                stderr_log = ""
            else:
                t_code, t_out, t_err = await run_slurm_cli_async(
                    ["tail", "-n", "200", stderr_path],
                    use_cache=False,
                    remote_only=bool(HPC_SSH_HOST),
                )
                if t_code == 0:
                    stderr_log = t_out
                elif "Permission denied" in (t_err or t_out):
                    stderr_log = f"[Permission Denied] Log file belongs to cluster user '{job_user}'."

    if stdout_log or stderr_log:
        return {
            "job_id": job_id,
            "stdout": stdout_log,
            "stderr": stderr_log,
            "log": combine_output(stdout_log, stderr_log),
        }

    # 2. Search known remote log directories if SSH configured
    if HPC_SSH_HOST:
        remote_dirs = [
            HPC_LOG_DIR,
            f"{HPC_REMOTE_DIR}/logs",
            f"{HPC_REMOTE_DIR}/llama-cpp/logs",
        ]
        unique_dirs = list(dict.fromkeys(d for d in remote_dirs if d))
        find_cmd = [
            "bash", "-c",
            f"find {' '.join(unique_dirs)} -name '*{job_id}*' 2>/dev/null"
        ]
        f_code, f_stdout, _ = await run_slurm_cli_async(find_cmd, use_cache=False, remote_only=True)
        if f_code == 0 and f_stdout.strip():
            found_paths = [p.strip() for p in f_stdout.strip().split("\n") if p.strip()]
            for p in found_paths:
                code_tail, content_tail, _ = await run_slurm_cli_async(["tail", "-n", "200", p], use_cache=False, remote_only=True)
                if code_tail == 0 and content_tail:
                    if p.endswith(".err"):
                        stderr_log = (stderr_log + "\n" + content_tail).strip() if stderr_log else content_tail
                    else:
                        stdout_log = (stdout_log + "\n" + content_tail).strip() if stdout_log else content_tail

        if stdout_log or stderr_log:
            return {
                "job_id": job_id,
                "stdout": stdout_log,
                "stderr": stderr_log,
                "log": combine_output(stdout_log, stderr_log),
            }

    # 3. Check local directories
    local_dirs = [
        ROOT_DIR / "infra" / "logs",
        ROOT_DIR / "logs",
        ROOT_DIR / "infra" / "llama-cpp" / "logs",
    ]
    for l_dir in local_dirs:
        if l_dir.is_dir():
            for p in l_dir.glob(f"*{job_id}*"):
                if p.is_file():
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")[-12000:]
                        if p.name.endswith(".err"):
                            stderr_log = (stderr_log + "\n" + content).strip() if stderr_log else content
                        else:
                            stdout_log = (stdout_log + "\n" + content).strip() if stdout_log else content
                    except Exception:
                        pass

    if stdout_log or stderr_log:
        return {
            "job_id": job_id,
            "stdout": stdout_log,
            "stderr": stderr_log,
            "log": combine_output(stdout_log, stderr_log),
        }

    # 4. Job is pending or no logs produced yet
    if job_state in ("PENDING", "PD"):
        reason_msg = f" (Reason: {job_reason})" if job_reason and job_reason != "None" else ""
        return {
            "job_id": job_id,
            "stdout": "",
            "stderr": "",
            "log": f"[Slurm Job #{job_id}] Status is PENDING{reason_msg}. Output logs will start streaming as soon as a GPU compute node is allocated and initialized.",
        }

    return {
        "job_id": job_id,
        "stdout": "",
        "stderr": "",
        "log": f"[Slurm Job #{job_id}] No active log file found. The job may still be initializing or has already completed.",
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
                current_text = log_data.get("log") or ""
                stdout_text = log_data.get("stdout") or ""
                stderr_text = log_data.get("stderr") or ""

                if current_text != last_content or iteration == 0:
                    payload = {
                        "job_id": job_id,
                        "log": current_text,
                        "stdout": stdout_text,
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
