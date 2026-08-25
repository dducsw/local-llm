import json
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException

from app.config import MODELS, RECENT_LOGS
from app.database import db
from app.schemas import CreateKeyRequest
from app.services.auth_service import require_admin, sha256
from app.services.slurm_service import run_slurm_cli
from app.services.tunnel_service import TUNNEL_MANAGER

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)], tags=["Admin"])


@router.post("/keys")
def create_key(body: CreateKeyRequest):
    for m in body.allowed_models:
        if m != "*" and m not in MODELS:
            raise HTTPException(status_code=400, detail=f"Unknown model: {m}")

    raw = "sk-hpc-" + secrets.token_urlsafe(32)
    prefix = raw[:16]

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO api_keys
                (key_hash, prefix, name, allowed_models, rpm, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                sha256(raw),
                prefix,
                body.name,
                json.dumps(body.allowed_models),
                body.rpm,
                int(time.time()),
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
        "note": "Save this key now. The raw key is not stored and cannot be shown again.",
    }


@router.get("/keys")
def list_keys():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, prefix, name, allowed_models, rpm, enabled, created_at
            FROM api_keys ORDER BY id DESC
            """
        ).fetchall()

    return {
        "data": [
            {
                "id": r["id"],
                "prefix": r["prefix"],
                "name": r["name"],
                "allowed_models": json.loads(r["allowed_models"]),
                "rpm": r["rpm"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.delete("/keys/{key_id}")
def revoke_key(key_id: int):
    with db() as conn:
        cur = conn.execute("UPDATE api_keys SET enabled = 0 WHERE id = ?", (key_id,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"id": key_id, "revoked": True}


@router.get("/telemetry")
def get_telemetry():
    with db() as conn:
        stats = conn.execute(
            """
            SELECT 
                COUNT(*) as total_requests,
                SUM(prompt_tokens) as total_prompt,
                SUM(completion_tokens) as total_completion,
                SUM(total_tokens) as total_tokens
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
            "total_requests": stats["total_requests"] or 0,
            "total_prompt": stats["total_prompt"] or 0,
            "total_completion": stats["total_completion"] or 0,
            "total_tokens": stats["total_tokens"] or 0,
        },
        "current_metrics": {
            "speed": round(current_speed, 1),
            "ttft_ms": round(current_ttft, 1)
        },
        "timeseries": timeseries,
        "recent_logs": list(RECENT_LOGS)[:20]
    }


@router.get("/slurm/status")
async def get_slurm_status():
    from app.routers.slurm import get_slurm_jobs, get_slurm_nodes
    nodes_res = await get_slurm_nodes()
    jobs_res = await get_slurm_jobs()
    return {
        "status": "live",
        "nodes": nodes_res.get("nodes", []),
        "jobs": jobs_res.get("jobs", []),
        "tunnel": TUNNEL_MANAGER.get_info(),
    }
