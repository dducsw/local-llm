import asyncio
from collections import defaultdict
import json
import secrets
import time
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import (
    MAX_CONCURRENT_PER_KEY,
    MAX_CONCURRENT_REQUESTS,
    UPSTREAM_TIMEOUT,
    load_models,
    log,
)
from app.database import record_telemetry
from app.schemas import Identity
from app.services.auth_service import allowed, enforce_rpm
from app.services.langfuse_service import log_generation_trace
from app.services.metrics_service import (
    LLM_ACTIVE_REQUESTS,
    LLM_LATENCY_SECONDS,
    LLM_REQUESTS_TOTAL,
    LLM_TOKENS_PER_SEC,
    LLM_TOKENS_TOTAL,
    LLM_TTFT_SECONDS,
    LLM_UPSTREAM_ERRORS_TOTAL,
)

_CLIENT: httpx.AsyncClient | None = None
_GLOBAL_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
_KEY_SEMAPHORES: dict[int, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(MAX_CONCURRENT_PER_KEY))
_ACTIVE_KEY_REQUESTS: dict[int, int] = defaultdict(int)


class ConcurrencyGuard:
    """Async context manager to safely acquire and release global & per-key concurrency slots."""

    def __init__(self, identity: Identity):
        self.identity = identity
        self.global_acquired = False
        self.key_acquired = False

    async def acquire(self):
        key_sem = _KEY_SEMAPHORES[self.identity.id]

        try:
            await asyncio.wait_for(_GLOBAL_SEMAPHORE.acquire(), timeout=0.1)
            self.global_acquired = True
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "message": f"Gateway capacity reached ({MAX_CONCURRENT_REQUESTS} max concurrent requests). Please retry in a few seconds.",
                        "type": "concurrency_limit_error",
                    }
                },
                headers={"Retry-After": "2"},
            )

        try:
            await asyncio.wait_for(key_sem.acquire(), timeout=0.1)
            self.key_acquired = True
            _ACTIVE_KEY_REQUESTS[self.identity.id] += 1
        except asyncio.TimeoutError:
            self.release()
            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "message": f"API key concurrency limit reached ({MAX_CONCURRENT_PER_KEY} max concurrent requests for key {self.identity.prefix}). Please wait for active queries to complete.",
                        "type": "concurrency_limit_error",
                    }
                },
                headers={"Retry-After": "2"},
            )

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def release(self):
        if self.key_acquired:
            self.key_acquired = False
            _ACTIVE_KEY_REQUESTS[self.identity.id] = max(0, _ACTIVE_KEY_REQUESTS[self.identity.id] - 1)
            try:
                _KEY_SEMAPHORES[self.identity.id].release()
            except ValueError:
                pass

        if self.global_acquired:
            self.global_acquired = False
            try:
                _GLOBAL_SEMAPHORE.release()
            except ValueError:
                pass


def get_upstream_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
            timeout=httpx.Timeout(UPSTREAM_TIMEOUT, connect=10.0),
        )
    return _CLIENT


async def close_upstream_client() -> None:
    global _CLIENT
    if _CLIENT is not None and not _CLIENT.is_closed:
        try:
            await _CLIENT.aclose()
        except Exception:
            pass
        _CLIENT = None


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
    if stream and "stream_options" not in upstream_payload:
        upstream_payload["stream_options"] = {"include_usage": True}

    upstream_url = cfg["base_url"].rstrip("/") + endpoint
    headers = {"Content-Type": "application/json", "X-Request-ID": rid}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    started = time.perf_counter()
    log.info(
        "start request_id=%s key=%s model=%s endpoint=%s stream=%s",
        rid, identity.prefix, public_model, endpoint, stream,
    )

    client = get_upstream_client()
    guard = ConcurrencyGuard(identity)
    await guard.acquire()

    if not stream:
        try:
            try:
                resp = await client.post(
                    upstream_url,
                    json=upstream_payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                LLM_UPSTREAM_ERRORS_TOTAL.labels(model=public_model, error_type=type(exc).__name__).inc()
                LLM_REQUESTS_TOTAL.labels(model=public_model, status="502", key_prefix=identity.prefix, stream="False").inc()
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
            elapsed_s = elapsed / 1000.0
            LLM_LATENCY_SECONDS.labels(model=public_model, stream="False").observe(elapsed_s)
            LLM_REQUESTS_TOTAL.labels(model=public_model, status=str(resp.status_code), key_prefix=identity.prefix, stream="False").inc()

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
            messages = upstream_payload.get("messages", [])
            p_text = json.dumps(messages) if messages else upstream_payload.get("prompt", "")
            fallback_p = max(1, len(str(p_text)) // 4)
            p_tok = int(usage.get("prompt_tokens", fallback_p))
            c_tok = int(usage.get("completion_tokens", len(json.dumps(body)) // 4))
            t_tok = p_tok + c_tok
            tok_s = round(c_tok / (elapsed / 1000.0), 1) if elapsed > 0 else 0.0

            LLM_TOKENS_TOTAL.labels(model=public_model, type="prompt", key_prefix=identity.prefix).inc(p_tok)
            LLM_TOKENS_TOTAL.labels(model=public_model, type="completion", key_prefix=identity.prefix).inc(c_tok)
            if tok_s > 0:
                LLM_TOKENS_PER_SEC.labels(model=public_model).observe(tok_s)

            record_telemetry(rid, public_model, p_tok, c_tok, t_tok, elapsed, None, tok_s, f"{resp.status_code} OK", identity.prefix)

            # Fire-and-forget Langfuse trace
            extracted_output = ""
            if isinstance(body, dict):
                choices = body.get("choices", [])
                if choices and isinstance(choices, list):
                    msg = choices[0].get("message", {})
                    extracted_output = msg.get("content", "") if isinstance(msg, dict) else choices[0].get("text", "")

            log_generation_trace(
                request_id=rid,
                model=public_model,
                input_data=payload.get("messages") or payload.get("prompt"),
                output_text=extracted_output,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=elapsed,
                ttft_ms=None,
                user_id=identity.prefix,
                metadata={"stream": False, "status_code": resp.status_code},
            )

            return JSONResponse(
                status_code=resp.status_code,
                headers={"X-Request-ID": rid},
                content=body,
            )
        finally:
            guard.release()

    # Streaming mode
    try:
        upstream_request = client.build_request(
            "POST", upstream_url, json=upstream_payload, headers=headers
        )
        try:
            resp = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            guard.release()
            LLM_UPSTREAM_ERRORS_TOTAL.labels(model=public_model, error_type=type(exc).__name__).inc()
            LLM_REQUESTS_TOTAL.labels(model=public_model, status="502", key_prefix=identity.prefix, stream="True").inc()
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
            guard.release()
            content = await resp.aread()
            await resp.aclose()
            elapsed = (time.perf_counter() - started) * 1000
            LLM_REQUESTS_TOTAL.labels(model=public_model, status=str(resp.status_code), key_prefix=identity.prefix, stream="True").inc()
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
    except Exception:
        guard.release()
        raise

    first_chunk_ts: float | None = None
    stream_buffer = ""
    prompt_tokens_exact: int | None = None
    completion_tokens_exact: int | None = None
    delta_text_chars = 0
    full_stream_text = ""

    async def stream_iter():
        nonlocal first_chunk_ts, stream_buffer, prompt_tokens_exact, completion_tokens_exact, delta_text_chars, full_stream_text
        try:
            async for chunk in resp.aiter_raw():
                if await request.is_disconnected():
                    log.info("Client disconnected, aborting upstream request_id=%s", rid)
                    break
                if chunk:
                    if first_chunk_ts is None:
                        first_chunk_ts = time.perf_counter()
                        ttft_s = first_chunk_ts - started
                        LLM_TTFT_SECONDS.labels(model=public_model).observe(ttft_s)

                    try:
                        stream_buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in stream_buffer:
                            line, stream_buffer = stream_buffer.split("\n", 1)
                            line = line.strip()
                            if line.startswith("data: ") and line != "data: [DONE]":
                                data_str = line[6:]
                                try:
                                    parsed = json.loads(data_str)
                                    if isinstance(parsed, dict):
                                        usage = parsed.get("usage")
                                        if isinstance(usage, dict):
                                            if "prompt_tokens" in usage and usage["prompt_tokens"] is not None:
                                                prompt_tokens_exact = int(usage["prompt_tokens"])
                                            if "completion_tokens" in usage and usage["completion_tokens"] is not None:
                                                completion_tokens_exact = int(usage["completion_tokens"])
                                        choices = parsed.get("choices", [])
                                        if choices and isinstance(choices, list):
                                            delta = choices[0].get("delta", {})
                                            content = delta.get("content", "")
                                            if content:
                                                delta_text_chars += len(content)
                                                full_stream_text += content
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    yield chunk
        finally:
            guard.release()
            await resp.aclose()
            total_elapsed = (time.perf_counter() - started) * 1000
            total_elapsed_s = total_elapsed / 1000.0
            LLM_LATENCY_SECONDS.labels(model=public_model, stream="True").observe(total_elapsed_s)
            LLM_REQUESTS_TOTAL.labels(model=public_model, status=str(resp.status_code), key_prefix=identity.prefix, stream="True").inc()

            ttft = ((first_chunk_ts - started) * 1000) if first_chunk_ts else None

            if prompt_tokens_exact is not None:
                p_tok = prompt_tokens_exact
            else:
                messages = upstream_payload.get("messages", [])
                p_text = json.dumps(messages) if messages else upstream_payload.get("prompt", "")
                p_tok = max(1, len(str(p_text)) // 4)

            if completion_tokens_exact is not None:
                c_tok = completion_tokens_exact
            elif delta_text_chars > 0:
                c_tok = max(1, delta_text_chars // 4)
            else:
                c_tok = 1

            tok_s = round(c_tok / (total_elapsed / 1000.0), 1) if total_elapsed > 0 else 0.0

            LLM_TOKENS_TOTAL.labels(model=public_model, type="prompt", key_prefix=identity.prefix).inc(p_tok)
            LLM_TOKENS_TOTAL.labels(model=public_model, type="completion", key_prefix=identity.prefix).inc(c_tok)
            if tok_s > 0:
                LLM_TOKENS_PER_SEC.labels(model=public_model).observe(tok_s)

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

            # Fire-and-forget Langfuse trace
            log_generation_trace(
                request_id=rid,
                model=public_model,
                input_data=upstream_payload.get("messages") or upstream_payload.get("prompt"),
                output_text=full_stream_text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=p_tok + c_tok,
                latency_ms=total_elapsed,
                ttft_ms=ttft,
                user_id=identity.prefix,
                metadata={"stream": True, "status_code": resp.status_code},
            )

            log.info(
                "end stream request_id=%s key=%s model=%s tokens=%d/%d latency_ms=%.1f ttft_ms=%s tok_s=%.1f",
                rid, identity.prefix, public_model, p_tok, c_tok, total_elapsed,
                f"{ttft:.1f}" if ttft else "None", tok_s,
            )

    return StreamingResponse(
        stream_iter(),
        status_code=resp.status_code,
        headers={
            "X-Request-ID": rid,
            "Content-Type": resp.headers.get("content-type", "text/event-stream"),
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
        media_type=resp.headers.get("content-type", "text/event-stream"),
    )
