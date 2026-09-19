import asyncio
import json
import time
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import load_models
from app.state import RECENT_LOGS
from app.database import db
from app.services.metrics_service import get_live_gpu_telemetry

router = APIRouter(tags=["Telemetry & Metrics"])

_TIMESERIES_CACHE: dict[str, tuple[float, dict]] = {}
_REALTIME_CACHE: dict[str, tuple[float, dict]] = {}


@router.get("/api/metrics/realtime")
async def get_realtime_metrics():
    """Return real-time telemetry summary with 2s in-memory caching."""
    now = time.time()
    if "data" in _REALTIME_CACHE:
        cached_ts, cached_val = _REALTIME_CACHE["data"]
        if now - cached_ts < 2.0:
            return cached_val

    with db() as conn:
        row = conn.execute(
            """
            SELECT 
                COUNT(*) as total_requests,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
                COALESCE(AVG(ttft_ms), 0) as avg_ttft_ms,
                COALESCE(AVG(tok_per_sec), 0) as avg_tok_per_sec
            FROM inference_logs
            """
        ).fetchone()

    # Calculate recent 5-minute throughput
    recent_5m = [log for log in RECENT_LOGS if now - log["created_at"] <= 300]
    recent_tok_s = round(sum(log["tok_per_sec"] for log in recent_5m) / len(recent_5m), 1) if recent_5m else 0.0
    last_ttft = round(recent_5m[0]["ttft_ms"], 1) if recent_5m and recent_5m[0].get("ttft_ms") else 0.0

    gpu_telemetry = await get_live_gpu_telemetry()
    models = load_models()

    val = {
        "model": list(models.keys())[0] if models else "qwen3.5-9b",
        "total_requests": row["total_requests"] if row else len(RECENT_LOGS),
        "total_prompt_tokens": row["total_prompt_tokens"] if row else 0,
        "total_completion_tokens": row["total_completion_tokens"] if row else 0,
        "total_tokens": row["total_tokens"] if row else 0,
        "current_tok_per_sec": recent_tok_s or (round(row["avg_tok_per_sec"], 1) if row else 0.0),
        "last_ttft_ms": last_ttft or (round(row["avg_ttft_ms"], 1) if row else 0.0),
        "avg_latency_ms": round(row["avg_latency_ms"], 1) if row else 0.0,
        "vram_used_gb": gpu_telemetry.get("vram_used_gb", 0.0),
        "vram_total_gb": gpu_telemetry.get("vram_total_gb", 16.0),
        "vram_used_pct": gpu_telemetry.get("vram_used_pct", 0.0),
        "gpu_name": gpu_telemetry.get("device_name", "NVIDIA Tesla V100-SXM2-16GB"),
        "gpu_utilization_pct": gpu_telemetry.get("gpu_utilization_pct", 0),
        "gpu_temperature_c": gpu_telemetry.get("gpu_temperature_c"),
        "gpu_power_w": gpu_telemetry.get("gpu_power_w"),
        "kv_cache_free_pct": gpu_telemetry.get("kv_cache_free_pct", 100.0),
        "kv_cache_used_pct": gpu_telemetry.get("kv_cache_used_pct", 0.0),
        "vllm_running_reqs": gpu_telemetry.get("vllm_running_reqs", 0),
        "vllm_waiting_reqs": gpu_telemetry.get("vllm_waiting_reqs", 0),
        "status": gpu_telemetry.get("status", "STANDBY"),
        "backend_type": gpu_telemetry.get("backend_type", "vLLM Engine"),
        "active_node": gpu_telemetry.get("active_node"),
        "active_job_id": gpu_telemetry.get("active_job_id"),
        "upstream_target": models[list(models.keys())[0]].get("base_url", "http://127.0.0.1:18000") if models else "http://127.0.0.1:18000",
    }
    _REALTIME_CACHE["data"] = (now, val)
    return val


@router.get("/api/metrics/live-stream")
async def stream_live_metrics(request: Request):
    """Server-Sent Events (SSE) stream pushing real-time metrics every 1.5s."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await get_realtime_metrics()
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.CancelledError:
                break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/metrics/timeseries")
async def get_timeseries_metrics():
    """Return three-minute time-series sampled in three-second intervals with O(N) bucketing."""
    now_f = time.time()
    now = int(now_f)

    if "data" in _TIMESERIES_CACHE:
        cached_ts, cached_val = _TIMESERIES_CACHE["data"]
        if now_f - cached_ts < 2.0:
            return cached_val

    # Generate 60 buckets of 3-seconds each (180s total)
    buckets = []
    for i in range(59, -1, -1):
        bucket_end = now - i * 3
        label = time.strftime("%H:%M:%S", time.localtime(bucket_end))
        buckets.append({
            "time": label,
            "timestamp": bucket_end,
            "tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
            "tok_per_sec": 0.0,
        })

    window_start = now - 180

    with db() as conn:
        rows = conn.execute(
            """
            SELECT prompt_tokens, completion_tokens, tok_per_sec, created_at
            FROM inference_logs
            WHERE created_at >= ?
            ORDER BY created_at ASC
            """,
            (window_start,),
        ).fetchall()

    # O(N) indexing directly into the appropriate bucket
    for r in rows:
        created = r["created_at"]
        diff = now - created
        if 0 <= diff < 180:
            bucket_idx = 59 - (diff // 3)
            if 0 <= bucket_idx < 60:
                b = buckets[bucket_idx]
                b["prompt_tokens"] += r["prompt_tokens"]
                b["completion_tokens"] += r["completion_tokens"]
                b["tokens"] += r["completion_tokens"]
                b["requests"] += 1
                if r["tok_per_sec"] > b["tok_per_sec"]:
                    b["tok_per_sec"] = r["tok_per_sec"]

    has_data = any(b["tokens"] > 0 for b in buckets)
    if not has_data and RECENT_LOGS:
        for idx, log_item in enumerate(list(RECENT_LOGS)[:15]):
            if idx < len(buckets):
                pos = len(buckets) - 1 - idx
                buckets[pos]["tokens"] = log_item.get("completion_tokens", 0)
                buckets[pos]["requests"] = 1
                buckets[pos]["tok_per_sec"] = log_item.get("tok_per_sec", 0.0)

    labels = [b["time"] for b in buckets]
    tokens_series = [b["tokens"] for b in buckets]
    speed_series = [b["tok_per_sec"] for b in buckets]

    tokens_per_minute = [round(val * 20, 1) for val in tokens_series]
    cumulative = []
    total = 0
    for val in tokens_series:
        total += val
        cumulative.append(total)

    result = {
        "labels": labels,
        "tokens_per_minute": tokens_per_minute,
        "cumulative_tokens": cumulative,
        "throughput_series": speed_series,
    }
    _TIMESERIES_CACHE["data"] = (now_f, result)
    return result


@router.get("/api/metrics/logs")
async def get_metrics_logs(limit: int = 50):
    """Return recent inference request logs for the audit ledger."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, request_id, model, prompt_tokens, completion_tokens, total_tokens,
                   latency_ms, ttft_ms, tok_per_sec, status, key_prefix, created_at
            FROM inference_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    logs = []
    for r in rows:
        logs.append({
            "id": r["request_id"],
            "model": r["model"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "tokens": r["completion_tokens"] or r["total_tokens"],
            "latency": str(int(r["latency_ms"])),
            "latency_ms": r["latency_ms"],
            "ttft_ms": r["ttft_ms"],
            "speed": str(r["tok_per_sec"]),
            "tok_per_sec": r["tok_per_sec"],
            "status": r["status"],
            "key_prefix": r["key_prefix"],
            "time": time.strftime("%H:%M:%S", time.localtime(r["created_at"])),
        })

    if not logs:
        logs = list(RECENT_LOGS)[:limit]

    return {"logs": logs}


@router.get("/api/gpu/telemetry")
async def get_gpu_telemetry():
    """Return GPU hardware telemetry."""
    return await get_live_gpu_telemetry()
