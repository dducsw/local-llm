import asyncio
import os
import shlex
import shutil
import subprocess
import time
from app.config import (
    HPC_SSH_HOST,
    HPC_SSH_KEY,
    HPC_SSH_USER,
    log,
)

_CACHE: dict[str, tuple[float, tuple[int, str, str]]] = {}
_CACHE_TTL = 2.5  # seconds for read queries (sinfo, squeue)


def get_cluster_status() -> dict:
    """Check connectivity and operational mode of Slurm cluster."""
    has_local = bool(shutil.which("sinfo"))
    has_ssh = bool(HPC_SSH_HOST and HPC_SSH_HOST != "your-host")
    mode = "local" if has_local else ("ssh" if has_ssh else "mock")
    return {
        "configured": has_local or has_ssh,
        "mode": mode,
        "target": f"{HPC_SSH_USER}@{HPC_SSH_HOST}" if has_ssh else ("localhost" if has_local else "mock"),
    }


def run_slurm_cli(
    cmd_args: list[str],
    timeout: float = 8.0,
    work_dir: str | None = None,
    use_cache: bool = False,
    remote_only: bool = False,
) -> tuple[int, str, str]:
    """Execute Slurm command locally if tools exist, or over SSH if running on remote VM."""
    binary = cmd_args[0]
    cache_key = ""

    if use_cache and binary in ("sinfo", "squeue"):
        cache_key = f"{HPC_SSH_HOST}:{' '.join(cmd_args)}" + (f"@{work_dir}" if work_dir else "")
        now = time.time()
        if cache_key in _CACHE:
            cached_time, cached_res = _CACHE[cache_key]
            if now - cached_time < _CACHE_TTL:
                return cached_res

    # Clean old cache entries occasionally
    if len(_CACHE) > 50:
        now = time.time()
        stale_keys = [k for k, (t, _) in _CACHE.items() if now - t > 30.0]
        for k in stale_keys:
            _CACHE.pop(k, None)

    # 1. Local execution if binary installed
    if shutil.which(binary) and not remote_only:
        try:
            res = subprocess.run(cmd_args, cwd=work_dir, capture_output=True, text=True, timeout=timeout)
            if res.returncode != 0:
                log.warning("Local %s failed (code %s): %s", binary, res.returncode, res.stderr.strip())
            result = (res.returncode, res.stdout, res.stderr)
            if cache_key and res.returncode == 0:
                _CACHE[cache_key] = (time.time(), result)
            return result
        except Exception as e:
            log.warning("Local %s exception: %s", binary, e)
            return 1, "", str(e)

    # 2. Remote SSH execution if HPC_SSH_HOST configured (VM -> HPC)
    if HPC_SSH_HOST and HPC_SSH_HOST != "your-host":
        try:
            cmd_str = " ".join(shlex.quote(arg) for arg in cmd_args)
            if work_dir:
                remote_cmd_str = f"cd {shlex.quote(work_dir)} && {cmd_str}"
            else:
                remote_cmd_str = cmd_str
            ssh_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                "-o", "ServerAliveInterval=15",
                "-o", "ServerAliveCountMax=3",
            ]
            if HPC_SSH_KEY and os.path.exists(os.path.expanduser(HPC_SSH_KEY)):
                ssh_cmd.extend(["-i", os.path.expanduser(HPC_SSH_KEY)])
            target = f"{HPC_SSH_USER}@{HPC_SSH_HOST}" if HPC_SSH_USER else HPC_SSH_HOST
            ssh_cmd.extend([target, remote_cmd_str])
            res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
            if res.returncode != 0:
                log.warning("SSH to %s failed (code %s): %s", target, res.returncode, res.stderr.strip())
            result = (res.returncode, res.stdout, res.stderr)
            if cache_key and res.returncode == 0:
                _CACHE[cache_key] = (time.time(), result)
            return result
        except Exception as e:
            log.warning("SSH to %s exception: %s", HPC_SSH_HOST, e)
            return 1, "", str(e)

    return 127, "", f"Command '{binary}' not found and HPC_SSH_HOST not configured"


async def run_slurm_cli_async(
    cmd_args: list[str],
    timeout: float = 8.0,
    work_dir: str | None = None,
    use_cache: bool = True,
    remote_only: bool = False,
) -> tuple[int, str, str]:
    """Execute Slurm CLI in an asyncio threadpool to avoid blocking the main server loop."""
    return await asyncio.to_thread(run_slurm_cli, cmd_args, timeout, work_dir, use_cache, remote_only)
