import os
from typing import Any
from app.config import log

LANGFUSE_ENABLE = os.getenv("LANGFUSE_ENABLE", "false").lower() in ("true", "1", "yes")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

_langfuse_client = None


def get_langfuse() -> Any | None:
    global _langfuse_client
    if not LANGFUSE_ENABLE:
        return None
    if _langfuse_client is None and LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
        try:
            from langfuse import Langfuse
            _langfuse_client = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=LANGFUSE_HOST,
            )
            log.info("Langfuse tracing client initialized (%s)", LANGFUSE_HOST)
        except Exception as exc:
            log.warning("Could not initialize Langfuse SDK: %s", exc)
            return None
    return _langfuse_client


def log_generation_trace(
    request_id: str,
    model: str,
    input_data: Any,
    output_text: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    latency_ms: float,
    ttft_ms: float | None,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Non-blocking fire-and-forget generation trace logger to Langfuse."""
    client = get_langfuse()
    if not client:
        return

    try:
        trace = client.trace(
            id=request_id,
            name="chat-completion",
            user_id=user_id,
            metadata=metadata or {},
        )
        trace.generation(
            id=f"gen_{request_id}",
            name=model,
            model=model,
            input=input_data,
            output=output_text,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            metadata={
                "latency_ms": round(latency_ms, 1),
                "ttft_ms": round(ttft_ms, 1) if ttft_ms else None,
                **(metadata or {}),
            },
        )
    except Exception as exc:
        log.debug("Langfuse trace background logging error: %s", exc)
