import asyncio
import os
import subprocess
import time
from typing import Any

from app.config import (
    HPC_SSH_HOST,
    HPC_SSH_KEY,
    HPC_SSH_USER,
    log,
)
from app.services.metrics_service import LLM_SSH_TUNNEL_UP
from app.services.slurm_service import run_slurm_cli, run_slurm_cli_async


class SSHTunnelManager:
    """Manages background SSH port-forwarding tunnel from VM Gateway to HPC Cluster."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.target_node: str = ""
        self.job_id: str = ""
        self.local_port: int = int(os.getenv("TUNNEL_LOCAL_PORT", "18000"))
        self.remote_port: int = int(os.getenv("TUNNEL_REMOTE_PORT", "18000"))
        self.status: str = "STOPPED"
        self.last_error: str = ""
        self.connected_at: float = 0.0
        LLM_SSH_TUNNEL_UP.set(0)

    def is_alive(self) -> bool:
        if self.process is not None:
            if self.process.poll() is None:
                LLM_SSH_TUNNEL_UP.set(1)
                return True
            self.process = None
            if self.status == "RUNNING":
                self.status = "DISCONNECTED"
        LLM_SSH_TUNNEL_UP.set(0)
        return False

    def _ensure_remote_reverse_tunnel(self, job_id: str, target_node: str, remote_port: int):
        """Ensure the compute node running the Slurm job is reverse-tunneling port 8000 to headnode:remote_port."""
        if not HPC_SSH_HOST or not job_id:
            return
        try:
            # Check if reverse tunnel is already active on headnode
            check_cmd = f"curl -s -m 1 http://127.0.0.1:{remote_port}/health >/dev/null 2>&1 || curl -s -m 1 http://127.0.0.1:{remote_port}/v1/models >/dev/null 2>&1"
            res = run_slurm_cli(["bash", "-c", check_cmd], timeout=3.0, remote_only=True)
            if res[0] == 0:
                log.info("HPC reverse tunnel to %s on port %s is already active.", target_node, remote_port)
                return

            log.info("Starting background reverse SSH tunnel for Slurm job %s (%s) on HPC headnode...", job_id, target_node)
            launch_cmd = (
                f"setsid srun --jobid={job_id} --overlap "
                f"ssh -N -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o ServerAliveInterval=15 "
                f"-R {remote_port}:127.0.0.1:8000 {HPC_SSH_HOST} </dev/null >/dev/null 2>&1 &"
            )
            run_slurm_cli(["bash", "-c", launch_cmd], timeout=5.0, remote_only=True)
            time.sleep(0.8)
        except Exception as exc:
            log.warning("Could not auto-start HPC reverse tunnel via srun: %s", exc)

    def start(
        self,
        target_node: str = "",
        job_id: str = "",
        local_port: int | None = None,
        remote_port: int | None = None,
    ) -> bool:
        if not HPC_SSH_HOST or HPC_SSH_HOST == "your-host":
            self.status = "ERROR"
            self.last_error = "HPC_SSH_HOST is not configured"
            return False

        lp = local_port or self.local_port
        rp = remote_port or self.remote_port
        node = target_node.strip() if target_node else "127.0.0.1"

        if job_id:
            self._ensure_remote_reverse_tunnel(job_id, node, rp)

        if self.is_alive() and self.target_node == node and self.local_port == lp:
            return True

        self.stop()

        self.target_node = node
        self.job_id = job_id
        self.local_port = lp
        self.remote_port = rp
        self.status = "STARTING"
        self.last_error = ""

        # The compute node reverses port 8000 to headnode:rp (127.0.0.1:18000).
        # We forward Gateway local_port -> headnode:127.0.0.1:rp
        forward_rule = f"{lp}:127.0.0.1:{rp}"

        cmd = [
            "ssh",
            "-N",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-L", forward_rule,
        ]
        if HPC_SSH_KEY and os.path.exists(os.path.expanduser(HPC_SSH_KEY)):
            cmd.extend(["-i", os.path.expanduser(HPC_SSH_KEY)])

        target = f"{HPC_SSH_USER}@{HPC_SSH_HOST}" if HPC_SSH_USER else HPC_SSH_HOST
        cmd.append(target)

        try:
            log.info("Starting background SSH tunnel: %s (forwarding %s)", " ".join(cmd), forward_rule)
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.6)
            if self.process.poll() is not None:
                _, stderr = self.process.communicate()
                self.status = "ERROR"
                self.last_error = stderr.strip() or f"SSH tunnel exited with code {self.process.returncode}"
                log.error("SSH tunnel failed immediately: %s", self.last_error)
                self.process = None
                return False

            self.status = "RUNNING"
            self.connected_at = time.time()
            LLM_SSH_TUNNEL_UP.set(1)
            log.info("SSH tunnel established: 127.0.0.1:%s -> %s via %s (target node: %s)", lp, forward_rule, target, node)
            return True
        except Exception as exc:
            self.status = "ERROR"
            self.last_error = str(exc)
            LLM_SSH_TUNNEL_UP.set(0)
            log.error("Exception starting SSH tunnel: %s", exc)
            self.process = None
            return False

    def stop(self):
        LLM_SSH_TUNNEL_UP.set(0)
        if self.process is not None:
            try:
                log.info("Terminating SSH tunnel to %s", self.target_node)
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None
        self.status = "STOPPED"
        self.connected_at = 0.0

    def restart(self) -> bool:
        """Cleanly cycle and re-establish the SSH tunnel."""
        target = self.target_node
        jid = self.job_id
        lp = self.local_port
        rp = self.remote_port
        self.stop()
        time.sleep(0.5)
        return self.start(target_node=target, job_id=jid, local_port=lp, remote_port=rp)

    def check_upstream_health(self) -> dict[str, Any]:
        """Probes the local tunnel endpoint for upstream HTTP server responsiveness."""
        if not self.is_alive():
            return {"healthy": False, "status": "DISCONNECTED", "latency_ms": 0}

        import urllib.request
        start = time.time()
        for endpoint in ("/health", "/v1/models", "/"):
            try:
                url = f"http://127.0.0.1:{self.local_port}{endpoint}"
                req = urllib.request.Request(url, headers={"User-Agent": "GatewayTunnelHealthCheck"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status in (200, 204):
                        latency = int((time.time() - start) * 1000)
                        return {"healthy": True, "status": "ONLINE", "latency_ms": latency}
            except Exception:
                continue
        return {"healthy": False, "status": "WARMING_UP", "latency_ms": int((time.time() - start) * 1000)}

    def get_info(self) -> dict[str, Any]:
        alive = self.is_alive()
        health = self.check_upstream_health() if alive else {"healthy": False, "status": "DISCONNECTED", "latency_ms": 0}
        return {
            "status": "RUNNING" if alive else self.status,
            "alive": alive,
            "target_node": self.target_node,
            "job_id": self.job_id,
            "local_port": self.local_port,
            "remote_port": self.remote_port,
            "connected_at": self.connected_at,
            "uptime_seconds": int(time.time() - self.connected_at) if (alive and self.connected_at > 0) else 0,
            "last_error": self.last_error,
            "upstream_healthy": health["healthy"],
            "upstream_status": health["status"],
            "upstream_latency_ms": health["latency_ms"],
            "route": f"127.0.0.1:{self.local_port} -> {HPC_SSH_HOST or 'headnode'}:{self.remote_port} -> {self.target_node or 'compute'}:8000",
        }


TUNNEL_MANAGER = SSHTunnelManager()


async def auto_tunnel_monitor_loop():
    """Background task to continuously monitor Slurm jobs and automatically maintain the SSH tunnel."""
    while True:
        try:
            if HPC_SSH_HOST and HPC_SSH_HOST != "your-host":
                cmd = ["squeue", "--format=%i|%j|%P|%T|%M|%R|%b", "--noheader"]
                if HPC_SSH_USER:
                    cmd.extend(["-u", HPC_SSH_USER])
                code, stdout, _ = await run_slurm_cli_async(cmd, timeout=5.0)
                if code == 0 and stdout:
                    running_node = None
                    running_job_id = None
                    for line in stdout.strip().splitlines():
                        parts = line.strip().split("|")
                        if len(parts) >= 6:
                            job_status = parts[3].strip().upper()
                            job_node = parts[5].strip()
                            job_id = parts[0].strip()
                            if job_status == "RUNNING" and job_node and not job_node.startswith("("):
                                running_node = job_node
                                running_job_id = job_id
                                break
                    if running_node:
                        if not TUNNEL_MANAGER.is_alive() or TUNNEL_MANAGER.target_node != running_node:
                            log.info("Auto-Tunnel: Active Slurm node '%s' (Job %s) detected, connecting tunnel...", running_node, running_job_id)
                            TUNNEL_MANAGER.start(target_node=running_node, job_id=running_job_id or "")
        except Exception as exc:
            log.debug("Auto-tunnel loop check exception: %s", exc)
        await asyncio.sleep(10)


async def watch_and_tunnel_job(job_id: str):
    """Wait for newly submitted job to transition to RUNNING, then immediately establish the tunnel."""
    for _ in range(60):  # poll every 3s for up to 3 minutes
        await asyncio.sleep(3)
        cmd = ["squeue", "-j", str(job_id), "--format=%T|%R", "--noheader"]
        code, stdout, _ = await run_slurm_cli_async(cmd, timeout=4.0, use_cache=False)
        if code == 0 and stdout.strip():
            parts = stdout.strip().split("|")
            status = parts[0].strip().upper()
            node = parts[1].strip() if len(parts) > 1 else ""
            if status == "RUNNING" and node and not node.startswith("("):
                log.info("Job %s is now RUNNING on node %s. Establishing tunnel immediately.", job_id, node)
                TUNNEL_MANAGER.start(target_node=node, job_id=str(job_id))
                break
            elif status in ("FAILED", "CANCELLED", "COMPLETED"):
                break

