import httpx
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from app.config import APP_DIR, GATEWAY_VERSION, load_models
from app.services.metrics_service import LLM_SSH_TUNNEL_UP, export_prometheus_metrics
from app.services.tunnel_service import TUNNEL_MANAGER

router = APIRouter(tags=["System"])

DASHBOARD_FALLBACK_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Local Gateway</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 1050px; margin: 32px auto; padding: 0 18px; background:#fafafa; color:#111; }
.card { background:white; border:1px solid #ddd; border-radius:12px; padding:18px; margin-bottom:18px; }
pre { white-space:pre-wrap; word-break:break-word; background:#f3f3f3; padding:14px; border-radius:8px; }
</style>
</head>
<body>
<h1>AI Local Gateway</h1>
<p>Gateway running on local server, inference on HPC via SSH tunnel.</p>
</body>
</html>"""


@router.get("/healthz")
@router.get("/health")
def healthz():
    return {"status": "ok"}


@router.get("/version")
def version():
    return {"version": GATEWAY_VERSION, "status": "running"}


@router.get("/readyz")
async def readyz():
    results = {}
    current_models = load_models()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for model_id, cfg in current_models.items():
                try:
                    r = await client.get(cfg["base_url"].rstrip("/") + "/models")
                    results[model_id] = {
                        "reachable": r.status_code == 200,
                        "status_code": r.status_code,
                    }
                except Exception as exc:
                    results[model_id] = {
                        "reachable": False,
                        "error": type(exc).__name__,
                    }
    except Exception as exc:
        return {"status": "degraded", "error": str(exc), "backends": results}

    all_ready = any(b.get("reachable") for b in results.values()) if results else True
    return {
        "status": "ready" if all_ready else "waiting_upstream",
        "backends": results,
    }


@router.get("/metrics")
def prometheus_metrics():
    """Expose Prometheus formatted metrics for scrapers (Grafana/Prometheus)."""
    LLM_SSH_TUNNEL_UP.set(1 if TUNNEL_MANAGER.is_alive() else 0)
    data, content_type = export_prometheus_metrics()
    return Response(content=data, media_type=content_type)


@router.get("/", response_class=HTMLResponse)
def dashboard():
    ui_file = APP_DIR / "ui" / "index.html"
    if ui_file.is_file():
        return HTMLResponse(
            content=ui_file.read_text(encoding="utf-8"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return DASHBOARD_FALLBACK_HTML
