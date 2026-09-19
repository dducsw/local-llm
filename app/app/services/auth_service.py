import hashlib
import json
import secrets
import time
from fastapi import Header, HTTPException

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_TOKEN,
    VIEWER_PASSWORD,
    VIEWER_USERNAME,
    WINDOWS,
)
from app.state import ADMIN_SESSIONS
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


def _extract_token(
    x_admin_token: str | None = None,
    x_admin_session: str | None = None,
    authorization: str | None = None,
) -> str | None:
    token = x_admin_session or x_admin_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    return token.strip() if token else None


def require_admin(
    x_admin_token: str | None = Header(default=None),
    x_admin_session: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    token_to_check = _extract_token(x_admin_token, x_admin_session, authorization)

    if not token_to_check:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Administrator authentication required",
                    "type": "authentication_error",
                }
            },
        )

    # 1. Check active session token
    if token_to_check in ADMIN_SESSIONS:
        sess = ADMIN_SESSIONS[token_to_check]
        exp = sess["expires_at"] if isinstance(sess, dict) else sess
        username = sess.get("username", "admin") if isinstance(sess, dict) else "admin"
        role = sess.get("role", "admin") if isinstance(sess, dict) else "admin"

        if time.time() < exp:
            if role != "admin":
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": {
                            "message": "Action requires Administrator privileges",
                            "type": "permission_denied",
                        }
                    },
                )
            return username
        else:
            ADMIN_SESSIONS.pop(token_to_check, None)
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "Administrator session has expired",
                        "type": "authentication_error",
                    }
                },
            )

    # 2. Check direct master password / admin token
    if (ADMIN_PASSWORD and secrets.compare_digest(token_to_check, ADMIN_PASSWORD)) or (
        ADMIN_TOKEN and secrets.compare_digest(token_to_check, ADMIN_TOKEN)
    ):
        return "admin"

    # If viewer token provided to admin-only endpoint
    if VIEWER_PASSWORD and secrets.compare_digest(token_to_check, VIEWER_PASSWORD):
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "message": "Action requires Administrator privileges",
                    "type": "permission_denied",
                }
            },
        )

    raise HTTPException(
        status_code=401,
        detail={
            "error": {
                "message": "Invalid administrator authentication credentials",
                "type": "authentication_error",
            }
        },
    )


def require_viewer_or_admin(
    x_admin_token: str | None = Header(default=None),
    x_admin_session: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    token_to_check = _extract_token(x_admin_token, x_admin_session, authorization)

    if not token_to_check:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Authentication required",
                    "type": "authentication_error",
                }
            },
        )

    # 1. Check active session token
    if token_to_check in ADMIN_SESSIONS:
        sess = ADMIN_SESSIONS[token_to_check]
        exp = sess["expires_at"] if isinstance(sess, dict) else sess
        username = sess.get("username", "user") if isinstance(sess, dict) else "user"

        if time.time() < exp:
            return username
        else:
            ADMIN_SESSIONS.pop(token_to_check, None)
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "Session has expired, please log in again",
                        "type": "authentication_error",
                    }
                },
            )

    # 2. Check direct credentials
    if (ADMIN_PASSWORD and secrets.compare_digest(token_to_check, ADMIN_PASSWORD)) or (
        ADMIN_TOKEN and secrets.compare_digest(token_to_check, ADMIN_TOKEN)
    ):
        return "admin"

    if VIEWER_PASSWORD and secrets.compare_digest(token_to_check, VIEWER_PASSWORD):
        return VIEWER_USERNAME

    raise HTTPException(
        status_code=401,
        detail={
            "error": {
                "message": "Invalid authentication credentials",
                "type": "authentication_error",
            }
        },
    )


def require_api_key(
    authorization: str | None = Header(default=None),
    x_admin_session: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> Identity:
    raw = _extract_token(x_admin_token, x_admin_session, authorization)

    if not raw:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing API key in Authorization header (Bearer <api_key>)",
                    "type": "authentication_error",
                }
            },
        )

    # 1. Check Admin Master Token
    if (ADMIN_PASSWORD and secrets.compare_digest(raw, ADMIN_PASSWORD)) or (
        ADMIN_TOKEN and secrets.compare_digest(raw, ADMIN_TOKEN)
    ):
        return Identity(
            id=0,
            prefix="admin",
            name="Administrator",
            allowed_models=["*"],
            rpm=10000,
        )

    # Check Viewer Direct Token
    if VIEWER_PASSWORD and secrets.compare_digest(raw, VIEWER_PASSWORD):
        return Identity(
            id=-1,
            prefix="viewer",
            name="Viewer Token",
            allowed_models=["*"],
            rpm=120,
        )

    # 2. Check Active Session
    if raw in ADMIN_SESSIONS:
        sess = ADMIN_SESSIONS[raw]
        exp = sess["expires_at"] if isinstance(sess, dict) else sess
        role = sess.get("role", "admin") if isinstance(sess, dict) else "admin"
        username = sess.get("username", "user") if isinstance(sess, dict) else "user"

        if time.time() < exp:
            rpm = 10000 if role == "admin" else 120
            return Identity(
                id=0 if role == "admin" else -1,
                prefix=role,
                name=f"{username.capitalize()} Session",
                allowed_models=["*"],
                rpm=rpm,
            )
        else:
            ADMIN_SESSIONS.pop(raw, None)
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "Session expired, please log in again",
                        "type": "authentication_error",
                    }
                },
            )

    # 3. Check Database API Keys
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, prefix, name, allowed_models, rpm, COALESCE(expires_at, 0) as expires_at
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
                    "message": "Invalid or inactive API key",
                    "type": "authentication_error",
                }
            },
        )

    if row["expires_at"] and row["expires_at"] > 0 and time.time() > row["expires_at"]:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "API key has expired",
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
