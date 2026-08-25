import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import DB_PATH, MODELS, log
from app.database import init_db
from app.routers import (
    admin,
    auth,
    openai,
    slurm,
    system,
    telemetry,
)
from app.services.tunnel_service import TUNNEL_MANAGER, auto_tunnel_monitor_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1. Initialize SQLite Database schemas & migrations
    init_db()
    log.info("Gateway started. db=%s models=%s", DB_PATH, list(MODELS.keys()))

    # 2. Start background Auto-Tunnel monitor loop for Slurm cluster
    monitor_task = asyncio.create_task(auto_tunnel_monitor_loop())

    yield

    # 3. Clean shutdown on server termination
    monitor_task.cancel()
    TUNNEL_MANAGER.stop()
    log.info("Gateway shutdown complete.")


app = FastAPI(
    title="Local HPC LLM Gateway",
    version="2.0.0",
    description="Unified API Gateway and Slurm Supervision Dashboard for Local LLM Inference on HPC",
    lifespan=lifespan,
)

# Mount all modular application routers
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(openai.router)
app.include_router(slurm.router)
app.include_router(telemetry.router)

# Mount static UI assets (CSS & JS)
from fastapi.staticfiles import StaticFiles
from app.config import APP_DIR
ui_dir = APP_DIR / "ui"
if (ui_dir / "css").is_dir():
    app.mount("/css", StaticFiles(directory=ui_dir / "css"), name="css")
if (ui_dir / "js").is_dir():
    app.mount("/js", StaticFiles(directory=ui_dir / "js"), name="js")
if ui_dir.is_dir():
    app.mount("/static", StaticFiles(directory=ui_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=9000, reload=True)
