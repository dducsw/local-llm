import json
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException

from app.config import load_models
from app.state import RECENT_LOGS
from app.database import db
from app.schemas import CreateKeyRequest
from app.services.auth_service import require_admin, require_viewer_or_admin, sha256
from app.services.slurm_service import run_slurm_cli_async
from app.services.tunnel_service import TUNNEL_MANAGER

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/keys")
def create_key(body: CreateKeyRequest, current_user: str = Depends(require_admin)):
    available_models = load_models()
    for m in body.allowed_models:
        if m != "*" and m not in available_models:
            raise HTTPException(status_code=400, detail=f"Unknown model: {m}")

    raw = "sk-hpc-" + secrets.token_urlsafe(32)
    prefix = raw[:16]
    now = int(time.time())

    durations = {
        "1d": 86400,
        "7d": 7 * 86400,
        "30d": 30 * 86400,
        "90d": 90 * 86400,
    }
    expires_at = now + durations[body.duration] if body.duration in durations else 0

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO api_keys
                (key_hash, prefix, name, allowed_models, rpm, created_by, enabled, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                sha256(raw),
                prefix,
                body.name,
                json.dumps(body.allowed_models),
                body.rpm,
                current_user,
                now,
                expires_at,
            ),
        )
        conn.commit()
        key_id = cur.lastrowid

    return {
        "id": key_id,
        "api_key": raw,
        "prefix": prefix,
        "name": body.name,
        "allowed_models": body.allowed_models,
        "rpm": body.rpm,
        "created_by": current_user,
        "expires_at": expires_at,
        "note": "Save this key now. The raw key is not stored and cannot be shown again.",
    }


@router.get("/keys")
def list_keys(current_user: str = Depends(require_viewer_or_admin)):
    now = int(time.time())
    with db() as conn:
        query = """
            SELECT k.id, k.prefix, k.name, k.allowed_models, k.rpm,
                   COALESCE(k.created_by, 'admin') as created_by,
                   k.enabled, k.created_at,
                   COALESCE(k.expires_at, 0) as expires_at,
                   COUNT(l.id) as usage_requests,
                   COALESCE(SUM(l.total_tokens), 0) as usage_tokens
            FROM api_keys k
            LEFT JOIN inference_logs l ON l.key_prefix = k.prefix
            GROUP BY k.id
            ORDER BY k.id DESC
        """
        rows = conn.execute(query).fetchall()

    return {
        "data": [
            {
                "id": r["id"],
                "prefix": r["prefix"],
                "name": r["name"],
                "allowed_models": json.loads(r["allowed_models"]),
                "rpm": r["rpm"],
                "created_by": r["created_by"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
                "expires_at": r["expires_at"],
                "is_expired": bool(r["expires_at"] > 0 and now > r["expires_at"]),
                "usage_requests": r["usage_requests"],
                "usage_tokens": r["usage_tokens"],
            }
            for r in rows
        ]
    }


@router.post("/keys/{key_id}/toggle")
def toggle_key(key_id: int, current_user: str = Depends(require_admin)):
    with db() as conn:
        row = conn.execute(
            "SELECT enabled, COALESCE(created_by, 'admin') as created_by FROM api_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Key not found")
        new_state = 0 if row["enabled"] else 1
        conn.execute("UPDATE api_keys SET enabled = ? WHERE id = ?", (new_state, key_id))
        conn.commit()
    return {"id": key_id, "enabled": bool(new_state)}


@router.delete("/keys/{key_id}")
def revoke_key(key_id: int, current_user: str = Depends(require_admin)):
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM api_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Key not found")
        conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.commit()
    return {"id": key_id, "deleted": True, "revoked": True}


@router.get("/telemetry")
def get_telemetry(current_user: str = Depends(require_viewer_or_admin)):
    with db() as conn:
        stats = conn.execute(
            """
            SELECT 
                COUNT(*) as total_requests,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                COALESCE(SUM(completion_tokens), 0) as total_completion,
                COALESCE(SUM(total_tokens), 0) as total_tokens
            FROM inference_logs
            """
        ).fetchone()

        fifteen_mins_ago = int(time.time()) - (15 * 60)
        ts_rows = conn.execute(
            """
            SELECT 
                (created_at / 60) * 60 as minute_ts,
                SUM(prompt_tokens) as p_toks,
                SUM(completion_tokens) as c_toks
            FROM inference_logs
            WHERE created_at >= ?
            GROUP BY minute_ts
            ORDER BY minute_ts ASC
            """,
            (fifteen_mins_ago,)
        ).fetchall()

        timeseries = [
            {
                "timestamp": r["minute_ts"],
                "prompt_tokens": r["p_toks"] or 0,
                "completion_tokens": r["c_toks"] or 0
            }
            for r in ts_rows
        ]

    current_speed = 0.0
    current_ttft = 0.0
    valid_speeds = [l["tok_per_sec"] for l in RECENT_LOGS if l.get("tok_per_sec", 0) > 0]
    valid_ttfts = [l["ttft_ms"] for l in RECENT_LOGS if l.get("ttft_ms")]

    if valid_speeds:
        current_speed = sum(valid_speeds) / len(valid_speeds)
    if valid_ttfts:
        current_ttft = sum(valid_ttfts) / len(valid_ttfts)

    return {
        "stats": {
            "total_requests": stats["total_requests"] if stats else 0,
            "total_prompt": stats["total_prompt"] if stats else 0,
            "total_completion": stats["total_completion"] if stats else 0,
            "total_tokens": stats["total_tokens"] if stats else 0,
        },
        "current_metrics": {
            "speed": round(current_speed, 1),
            "ttft_ms": round(current_ttft, 1)
        },
        "timeseries": timeseries,
        "recent_logs": list(RECENT_LOGS)[:20]
    }


@router.get("/slurm/status")
async def get_slurm_status(current_user: str = Depends(require_admin)):
    """Legacy admin status endpoint - delegates to modular Slurm router functions (DRY)."""
    from app.routers.slurm import get_slurm_jobs, get_slurm_nodes
    nodes_res = await get_slurm_nodes()
    jobs_res = await get_slurm_jobs()
    return {
        "status": "live",
        "nodes": nodes_res.get("nodes", []),
        "jobs": jobs_res.get("jobs", []),
        "tunnel": TUNNEL_MANAGER.get_info(),
    }
