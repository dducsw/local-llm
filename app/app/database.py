import asyncio
import sqlite3
import time
from typing import Any
from app.config import DB_PATH, RECENT_LOGS, log

TELEMETRY_QUEUE: asyncio.Queue[tuple] = asyncio.Queue(maxsize=5000)


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL UNIQUE,
                prefix TEXT NOT NULL,
                name TEXT NOT NULL,
                allowed_models TEXT NOT NULL,
                rpm INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inference_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                ttft_ms REAL,
                tok_per_sec REAL,
                status TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON inference_logs(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at_model ON inference_logs(created_at, model);")
        conn.commit()


def record_telemetry(
    request_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    latency_ms: float,
    ttft_ms: float | None,
    tok_per_sec: float,
    status: str,
    key_prefix: str,
) -> None:
    now_ts = int(time.time())
    entry = {
        "id": request_id,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens": completion_tokens or total_tokens,
        "latency": str(int(latency_ms)),
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "speed": str(tok_per_sec),
        "tok_per_sec": tok_per_sec,
        "status": status,
        "key_prefix": key_prefix,
        "created_at": now_ts,
        "time": time.strftime("%H:%M:%S", time.localtime(now_ts)),
    }
    RECENT_LOGS.appendleft(entry)

    row_data = (
        request_id,
        model,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        latency_ms,
        ttft_ms,
        tok_per_sec,
        status,
        key_prefix,
        now_ts,
    )

    try:
        TELEMETRY_QUEUE.put_nowait(row_data)
    except Exception:
        # Fallback sync insert if queue is full
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO inference_logs (
                        request_id, model, prompt_tokens, completion_tokens, total_tokens,
                        latency_ms, ttft_ms, tok_per_sec, status, key_prefix, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row_data,
                )
                conn.commit()
        except Exception as exc:
            log.warning("failed to persist inference telemetry: %s", exc)


async def telemetry_flush_worker():
    """Background worker to batch-insert telemetry logs from async queue to SQLite."""
    while True:
        try:
            batch = []
            # Wait for at least one item
            item = await TELEMETRY_QUEUE.get()
            batch.append(item)
            TELEMETRY_QUEUE.task_done()

            # Drain any additional pending items up to 50
            while len(batch) < 50:
                try:
                    item = TELEMETRY_QUEUE.get_nowait()
                    batch.append(item)
                    TELEMETRY_QUEUE.task_done()
                except asyncio.QueueEmpty:
                    break

            if batch:
                try:
                    with db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO inference_logs (
                                request_id, model, prompt_tokens, completion_tokens, total_tokens,
                                latency_ms, ttft_ms, tok_per_sec, status, key_prefix, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            batch,
                        )
                        conn.commit()
                except Exception as exc:
                    log.warning("Batch telemetry insertion failed: %s", exc)

            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            # Drain remaining before stopping
            remaining = []
            while not TELEMETRY_QUEUE.empty():
                try:
                    remaining.append(TELEMETRY_QUEUE.get_nowait())
                    TELEMETRY_QUEUE.task_done()
                except asyncio.QueueEmpty:
                    break
            if remaining:
                try:
                    with db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO inference_logs (
                                request_id, model, prompt_tokens, completion_tokens, total_tokens,
                                latency_ms, ttft_ms, tok_per_sec, status, key_prefix, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            remaining,
                        )
                        conn.commit()
                except Exception:
                    pass
            break
        except Exception as exc:
            log.debug("Telemetry worker loop exception: %s", exc)
            await asyncio.sleep(1.0)

