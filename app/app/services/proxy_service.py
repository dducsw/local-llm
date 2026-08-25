import json
import secrets
import time
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import MODELS, UPSTREAM_TIMEOUT, load_models, log
from app.database import record_telemetry
from app.schemas import Identity
from app.services.auth_service import allowed, enforce_rpm


async def proxy_openai(
    request: Request,
    endpoint: str,
    identity: Identity,
    x_request_id: str | None,
):
    enforce_rpm(identity)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    current_models = load_models()
    public_model = payload.get("model")
    if not public_model or public_model not in current_models:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"Unknown model: {public_model}",
                    "type": "invalid_request_error",
                }
            },
        )
    if not allowed(identity, public_model):
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "message": f"API key cannot access model '{public_model}'",
                    "type": "permission_error",
                }
            },
        )

    cfg = current_models[public_model]
    rid = x_request_id or f"req_{secrets.token_hex(12)}"
    upstream_payload = dict(payload)
    upstream_payload["model"] = cfg["upstream_model"]
    stream = bool(payload.get("stream", False))

    upstream_url = cfg["base_url"].rstrip("/") + endpoint
    headers = {"Content-Type": "application/json", "X-Request-ID": rid}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    started = time.perf_counter()
    log.info(
        "start request_id=%s key=%s model=%s endpoint=%s stream=%s",
        rid, identity.prefix, public_model, endpoint, stream,
    )

    if not stream:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            try:
                resp = await client.post(
                    upstream_url,
                    json=upstream_payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                record_telemetry(rid, public_model, 0, 0, 0, elapsed, None, 0.0, "502 Upstream Error", identity.prefix)
                return JSONResponse(
                    status_code=502,
                    headers={"X-Request-ID": rid},
                    content={
                        "error": {
                            "message": f"Upstream unavailable: {type(exc).__name__}",
                            "type": "upstream_error",
                        }
                    },
                )

        elapsed = (time.perf_counter() - started) * 1000
        log.info(
            "end request_id=%s key=%s model=%s status=%s latency_ms=%.1f",
            rid, identity.prefix, public_model, resp.status_code, elapsed,
        )

        try:
            body = resp.json()
        except Exception:
            body = {
                "error": {
                    "message": resp.text,
                    "type": "upstream_error",
                }
            }

        if isinstance(body, dict) and body.get("model"):
            body["model"] = public_model

        # Extract token usage and record telemetry
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        p_tok = int(usage.get("prompt_tokens", len(json.dumps(upstream_payload)) // 4))
        c_tok = int(usage.get("completion_tokens", len(json.dumps(body)) // 4))
        t_tok = p_tok + c_tok
        tok_s = round(c_tok / (elapsed / 1000.0), 1) if elapsed > 0 else 0.0
        record_telemetry(rid, public_model, p_tok, c_tok, t_tok, elapsed, None, tok_s, f"{resp.status_code} OK", identity.prefix)

        return JSONResponse(
            status_code=resp.status_code,
            headers={"X-Request-ID": rid},
            content=body,
        )

    # Streaming mode
    client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)
    upstream_request = client.build_request(
        "POST", upstream_url, json=upstream_payload, headers=headers
    )
    try:
        resp = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        elapsed = (time.perf_counter() - started) * 1000
        record_telemetry(rid, public_model, 0, 0, 0, elapsed, None, 0.0, "502 Upstream Error", identity.prefix)
        return JSONResponse(
            status_code=502,
            headers={"X-Request-ID": rid},
            content={
                "error": {
                    "message": f"Upstream unavailable: {type(exc).__name__}",
                    "type": "upstream_error",
                }
            },
        )

    if resp.status_code >= 400:
        content = await resp.aread()
        await resp.aclose()
        await client.aclose()
        elapsed = (time.perf_counter() - started) * 1000
        record_telemetry(rid, public_model, 0, 0, 0, elapsed, None, 0.0, f"{resp.status_code} Error", identity.prefix)
        return JSONResponse(
            status_code=resp.status_code,
            headers={"X-Request-ID": rid},
            content={
                "error": {
                    "message": content.decode(errors="replace"),
                    "type": "upstream_error",
                }
            },
        )

    first_chunk_ts: float | None = None
    stream_chunks_count = 0

    async def stream_iter():
        nonlocal first_chunk_ts, stream_chunks_count
        try:
            async for chunk in resp.aiter_raw():
                if chunk:
                    if first_chunk_ts is None:
                        first_chunk_ts = time.perf_counter()
                    stream_chunks_count += 1
                    yield chunk
        finally:
            await resp.aclose()
            await client.aclose()
            total_elapsed = (time.perf_counter() - started) * 1000
            ttft = ((first_chunk_ts - started) * 1000) if first_chunk_ts else None
            p_tok = len(json.dumps(upstream_payload)) // 4
            c_tok = max(1, stream_chunks_count)
            tok_s = round(c_tok / (total_elapsed / 1000.0), 1) if total_elapsed > 0 else 0.0
            record_telemetry(
                rid,
                public_model,
                p_tok,
                c_tok,
                p_tok + c_tok,
                total_elapsed,
                ttft,
                tok_s,
                f"{resp.status_code} Stream OK",
                identity.prefix,
            )
            log.info(
                "end stream request_id=%s key=%s model=%s latency_ms=%.1f ttft_ms=%s tok_s=%.1f",
                rid, identity.prefix, public_model, total_elapsed,
                f"{ttft:.1f}" if ttft else "None", tok_s,
            )

    return StreamingResponse(
        stream_iter(),
        status_code=resp.status_code,
        headers={"X-Request-ID": rid, "Content-Type": resp.headers.get("content-type", "text/event-stream")},
        media_type=resp.headers.get("content-type", "text/event-stream"),
    )
