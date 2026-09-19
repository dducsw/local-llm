import httpx
from fastapi import APIRouter, Depends, Header, Request

from app.config import load_models
from app.schemas import Identity
from app.services.auth_service import require_api_key
from app.services.proxy_service import proxy_openai

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible"])


@router.get("/models")
async def models():
    current_models = load_models()

    # Check live reachability of each upstream model backend
    backend_status: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=1.5) as client:
        for model_id, cfg in current_models.items():
            try:
                base_url = cfg["base_url"].rstrip("/")
                headers = {}
                if cfg.get("api_key"):
                    headers["Authorization"] = f"Bearer {cfg['api_key']}"
                r = await client.get(f"{base_url}/models", headers=headers)
                backend_status[model_id] = (r.status_code == 200)
            except Exception:
                backend_status[model_id] = False

    data = []
    for model_id, cfg in current_models.items():
        is_online = backend_status.get(model_id, False)
        data.append(
            {
                "id": model_id,
                "object": "model",
                "status": "online" if is_online else "offline",
                "owned_by": cfg.get("owned_by", "hpc-cluster"),
                "upstream_model": cfg.get("upstream_model", model_id),
            }
        )
    return {"object": "list", "data": data}


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    identity: Identity = Depends(require_api_key),
    x_request_id: str | None = Header(default=None),
):
    return await proxy_openai(request, "/chat/completions", identity, x_request_id)


@router.post("/completions")
async def completions(
    request: Request,
    identity: Identity = Depends(require_api_key),
    x_request_id: str | None = Header(default=None),
):
    return await proxy_openai(request, "/completions", identity, x_request_id)
