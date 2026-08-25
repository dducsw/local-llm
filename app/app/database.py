import json
import sqlite3
import time
from typing import Any
from app.config import DB_PATH, RECENT_LOGS, log


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

    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO inference_logs (
                    request_id, model, prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, ttft_ms, tok_per_sec, status, key_prefix, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                ),
            )
            conn.commit()
    except Exception as exc:
        log.warning("failed to persist inference telemetry: %s", exc)
