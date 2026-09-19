import asyncio
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any
from app.config import DB_PATH, log
from app.state import RECENT_LOGS

TELEMETRY_QUEUE: asyncio.Queue[tuple] = asyncio.Queue(maxsize=5000)
_local = threading.local()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")


class PostgresCursorWrapper:
    """Wraps psycopg cursor to provide SQLite-like interface (e.g. lastrowid, dictionary rows)."""
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None

    def execute(self, query: str, params: tuple | list | None = None):
        # Convert ? placeholders to %s for PostgreSQL
        pg_query = query.replace("?", "%s")
        # Handle SQLite lastrowid for INSERT INTO api_keys
        if "INSERT INTO api_keys" in pg_query and "RETURNING" not in pg_query.upper():
            pg_query = pg_query.rstrip(" ;") + " RETURNING id;"

        res = self._cur.execute(pg_query, params)
        if "RETURNING" in pg_query.upper():
            row = self._cur.fetchone()
            if row:
                self.lastrowid = row[0] if isinstance(row, tuple) else row.get("id")
        return self

    def executemany(self, query: str, params_seq):
        pg_query = query.replace("?", "%s")
        return self._cur.executemany(pg_query, params_seq)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class PostgresConnectionWrapper:
    """Wraps psycopg Connection to provide context manager and commit/execute API."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query: str, params: tuple | list | None = None):
        cur = PostgresCursorWrapper(self._conn.cursor())
        cur.execute(query, params)
        return cur

    def executemany(self, query: str, params_seq):
        cur = PostgresCursorWrapper(self._conn.cursor())
        cur.executemany(query, params_seq)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()


def _get_pg_connection():
    import psycopg
    from psycopg.rows import dict_row

    conn = getattr(_local, "pg_conn", None)
    if conn is not None and not conn.closed:
        try:
            conn.execute("SELECT 1;")
            return PostgresConnectionWrapper(conn)
        except Exception:
            _local.pg_conn = None

    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
    _local.pg_conn = conn
    return PostgresConnectionWrapper(conn)


def _get_sqlite_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = getattr(_local, "sqlite_conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1;")
            return conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            _local.sqlite_conn = None

    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-8000;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    _local.sqlite_conn = conn
    return conn


def db():
    """Returns database connection context wrapper (PostgreSQL or SQLite)."""
    if IS_POSTGRES:
        try:
            return _get_pg_connection()
        except Exception as exc:
            log.warning("PostgreSQL connection failed (%s), falling back to SQLite", exc)
    return _get_sqlite_connection()


def init_db() -> None:
    """Initialize tables and indexes on application start."""
    if IS_POSTGRES:
        try:
            with _get_pg_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id SERIAL PRIMARY KEY,
                        key_hash VARCHAR(64) NOT NULL UNIQUE,
                        prefix VARCHAR(32) NOT NULL,
                        name VARCHAR(120) NOT NULL,
                        allowed_models TEXT NOT NULL,
                        rpm INT NOT NULL,
                        created_by VARCHAR(64) NOT NULL DEFAULT 'admin',
                        enabled SMALLINT NOT NULL DEFAULT 1,
                        created_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL DEFAULT 0
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS inference_logs (
                        id SERIAL PRIMARY KEY,
                        request_id VARCHAR(64) NOT NULL,
                        model VARCHAR(128) NOT NULL,
                        prompt_tokens INT NOT NULL,
                        completion_tokens INT NOT NULL,
                        total_tokens INT NOT NULL,
                        latency_ms DOUBLE PRECISION NOT NULL,
                        ttft_ms DOUBLE PRECISION,
                        tok_per_sec DOUBLE PRECISION,
                        status VARCHAR(64) NOT NULL,
                        key_prefix VARCHAR(32) NOT NULL,
                        created_at BIGINT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_sessions (
                        token VARCHAR(128) PRIMARY KEY,
                        username VARCHAR(64) NOT NULL,
                        role VARCHAR(32) NOT NULL,
                        expires_at DOUBLE PRECISION NOT NULL
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON admin_sessions(expires_at);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON inference_logs(created_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at_model ON inference_logs(created_at, model);")
                conn.commit()
            log.info("PostgreSQL database schemas initialized successfully on %s", DATABASE_URL.split("@")[-1])
            return
        except Exception as exc:
            log.warning("PostgreSQL schema initialization failed: %s. Reverting to SQLite.", exc)

    # SQLite fallback
    with _get_sqlite_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL UNIQUE,
                prefix TEXT NOT NULL,
                name TEXT NOT NULL,
                allowed_models TEXT NOT NULL,
                rpm INTEGER NOT NULL,
                created_by TEXT NOT NULL DEFAULT 'admin',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL DEFAULT 0
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON admin_sessions(expires_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON inference_logs(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at_model ON inference_logs(created_at, model);")
        conn.commit()
    log.info("SQLite database initialized successfully at %s", DB_PATH)


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
    """Background worker to batch-insert telemetry logs from async queue to database."""
    while True:
        try:
            batch = []
            item = await TELEMETRY_QUEUE.get()
            batch.append(item)
            TELEMETRY_QUEUE.task_done()

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
            remaining = []
            while not TELEMETRY_QUEUE.empty() and len(remaining) < 500:
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
                except Exception as exc:
                    log.warning("Final telemetry flush on cancellation failed: %s", exc)
            break
        except Exception as exc:
            log.debug("Telemetry worker loop exception: %s", exc)
            await asyncio.sleep(1.0)


def save_session(token: str, username: str, role: str, expires_at: float) -> None:
    """Persist an authenticated user/admin session to database."""
    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO admin_sessions (token, username, role, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    username = excluded.username,
                    role = excluded.role,
                    expires_at = excluded.expires_at;
                """,
                (token, username, role, expires_at),
            )
            conn.commit()
    except Exception as exc:
        log.warning("Failed to persist session to database: %s", exc)


def get_session(token: str) -> dict[str, Any] | None:
    """Retrieve session from database if exists and not expired."""
    try:
        now = time.time()
        with db() as conn:
            cur = conn.execute(
                "SELECT token, username, role, expires_at FROM admin_sessions WHERE token = ?;",
                (token,),
            )
            row = cur.fetchone()
            if row:
                if isinstance(row, dict):
                    data = row
                else:
                    data = {
                        "token": row[0],
                        "username": row[1],
                        "role": row[2],
                        "expires_at": float(row[3]),
                    }
                if data["expires_at"] > now:
                    return data
                else:
                    # Clean expired session asynchronously or inline
                    delete_session(token)
    except Exception as exc:
        log.debug("Database session lookup error: %s", exc)
    return None


def delete_session(token: str) -> None:
    """Remove session from database upon logout or expiration."""
    try:
        with db() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?;", (token,))
            conn.commit()
    except Exception as exc:
        log.debug("Database delete session error: %s", exc)

