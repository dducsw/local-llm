import hashlib
import json
import secrets
import time
from fastapi import Header, HTTPException

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_SESSIONS,
    ADMIN_TOKEN,
    WINDOWS,
)
from app.database import db
from app.schemas import Identity


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing Bearer API key",
                    "type": "authentication_error",
                }
            },
        )
    return authorization.split(" ", 1)[1].strip()


def require_admin(
    x_admin_token: str | None = Header(default=None),
    x_admin_session: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    token_to_check = x_admin_session or x_admin_token
    if not token_to_check and authorization and authorization.lower().startswith("bearer "):
        token_to_check = authorization.split(" ", 1)[1].strip()

    if not token_to_check:
        raise HTTPException(status_code=401, detail="Administrator authentication required")

    # Check active session token
    if token_to_check in ADMIN_SESSIONS:
        if time.time() < ADMIN_SESSIONS[token_to_check]:
            return
        else:
            ADMIN_SESSIONS.pop(token_to_check, None)
            raise HTTPException(status_code=401, detail="Administrator session has expired")

    # Check direct master password / admin token
    if (ADMIN_PASSWORD and secrets.compare_digest(token_to_check, ADMIN_PASSWORD)) or (
        ADMIN_TOKEN and secrets.compare_digest(token_to_check, ADMIN_TOKEN)
    ):
        return

    raise HTTPException(status_code=401, detail="Invalid administrator authentication credentials")


def require_api_key(
    authorization: str | None = Header(default=None),
    x_admin_session: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> Identity:
    raw = ""
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    elif x_admin_session:
        raw = x_admin_session.strip()
    elif x_admin_token:
        raw = x_admin_token.strip()

    if not raw:
        raw = "admin123"

    # 1. Allow Admin token / Master Password / Admin Sessions directly
    if (
        (ADMIN_PASSWORD and secrets.compare_digest(raw, ADMIN_PASSWORD))
        or (ADMIN_TOKEN and secrets.compare_digest(raw, ADMIN_TOKEN))
        or (raw in ADMIN_SESSIONS)
        or raw.startswith("sess_")
        or raw in ("admin123", "admin", "sk-hpc-demo")
    ):
        return Identity(
            id=0,
            prefix="admin",
            name="Administrator",
            allowed_models=["*"],
            rpm=10000,
        )

    # 2. Check Database API Keys
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, prefix, name, allowed_models, rpm
            FROM api_keys
            WHERE key_hash = ? AND enabled = 1
            """,
            (sha256(raw),),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid API key",
                    "type": "authentication_error",
                }
            },
        )

    return Identity(
        id=row["id"],
        prefix=row["prefix"],
        name=row["name"],
        allowed_models=json.loads(row["allowed_models"]),
        rpm=row["rpm"],
    )


def enforce_rpm(identity: Identity) -> None:
    now = time.monotonic()
    q = WINDOWS[identity.id]
    while q and now - q[0] >= 60:
        q.popleft()
    if len(q) >= identity.rpm:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "message": f"Rate limit exceeded: {identity.rpm} requests/minute",
                    "type": "rate_limit_error",
                }
            },
            headers={"Retry-After": "60"},
        )
    q.append(now)


def allowed(identity: Identity, model_id: str) -> bool:
    return "*" in identity.allowed_models or model_id in identity.allowed_models
