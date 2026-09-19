import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import APP_DIR, DB_PATH, GATEWAY_VERSION, load_models, log
from app.database import init_db, telemetry_flush_worker
from app.routers import (
    admin,
    auth,
    openai,
    slurm,
    system,
    telemetry,
)
from app.services.proxy_service import close_upstream_client
from app.services.tunnel_service import TUNNEL_MANAGER, auto_tunnel_monitor_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1. Initialize SQLite Database schemas & indexes
    init_db()
    models = load_models()
    log.info("Gateway v%s started. db=%s models=%s", GATEWAY_VERSION, DB_PATH, list(models.keys()))

    # 2. Start background tasks (Telemetry batching + Auto-Tunnel monitor loop + Remote Logs verification)
    telemetry_task = asyncio.create_task(telemetry_flush_worker())
    monitor_task = asyncio.create_task(auto_tunnel_monitor_loop())

    async def _ensure_cluster_environment():
        from app.config import HPC_SSH_HOST, HPC_REMOTE_DIR
        from app.services.slurm_service import run_slurm_cli_async
        if HPC_SSH_HOST and HPC_SSH_HOST != "your-host":
            try:
                work_dir = HPC_REMOTE_DIR or "/home/ducledinh/dev/local-llm/infra"
                cmd = ["bash", "-c", f"mkdir -p '{work_dir}/logs' /home/ducledinh/dev/local-llm/logs '{work_dir}/llama-cpp/logs'"]
                await run_slurm_cli_async(cmd, timeout=5.0, use_cache=False)
                log.info("HPC cluster logs directories verified & ensured.")
            except Exception as e:
                log.debug("Startup HPC logs check error: %s", e)

    asyncio.create_task(_ensure_cluster_environment())

    yield

    # 3. Clean shutdown on server termination
    monitor_task.cancel()
    telemetry_task.cancel()
    await close_upstream_client()
    TUNNEL_MANAGER.stop()
    log.info("Gateway shutdown complete.")


app = FastAPI(
    title="Local HPC LLM Gateway",
    version=GATEWAY_VERSION,
    description="Unified API Gateway and Slurm Supervision Dashboard for Local LLM Inference on HPC",
    lifespan=lifespan,
    root_path=os.getenv("ROOT_PATH", ""),
)

# Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression for responses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "Internal server error",
                "type": "internal_error",
                "detail": str(exc),
            }
        },
    )


# Mount all modular application routers
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(openai.router)
app.include_router(slurm.router)
app.include_router(telemetry.router)

# Mount static UI assets (CSS & JS)
ui_dir = APP_DIR / "ui"
if (ui_dir / "css").is_dir():
    app.mount("/css", StaticFiles(directory=ui_dir / "css"), name="css")
if (ui_dir / "js").is_dir():
    app.mount("/js", StaticFiles(directory=ui_dir / "js"), name="js")
if ui_dir.is_dir():
    app.mount("/static", StaticFiles(directory=ui_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "9001")), reload=True)
