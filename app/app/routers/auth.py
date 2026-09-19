import secrets
import time
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_TOKEN,
    ADMIN_USERNAME,
    VIEWER_PASSWORD,
    VIEWER_USERNAME,
)
from app.state import ADMIN_SESSIONS, LOGIN_ATTEMPTS, LOGIN_LOCK
from app.schemas import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login")
def login(body: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Rate limit check (5 attempts per minute per IP, thread-safe)
    with LOGIN_LOCK:
        attempts = LOGIN_ATTEMPTS[ip]
        LOGIN_ATTEMPTS[ip] = [t for t in attempts if now - t < 60]
        if len(LOGIN_ATTEMPTS[ip]) >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Please try again in a minute.",
            )
        LOGIN_ATTEMPTS[ip].append(now)

    role = None
    # Check Admin credentials
    is_admin_user = secrets.compare_digest(body.username, ADMIN_USERNAME)
    is_admin_pass = (ADMIN_PASSWORD and secrets.compare_digest(body.password, ADMIN_PASSWORD)) or (
        ADMIN_TOKEN and secrets.compare_digest(body.password, ADMIN_TOKEN)
    )
    if is_admin_user and is_admin_pass:
        role = "admin"

    # Check Viewer credentials
    if not role and VIEWER_USERNAME and VIEWER_PASSWORD:
        is_viewer_user = secrets.compare_digest(body.username, VIEWER_USERNAME)
        is_viewer_pass = secrets.compare_digest(body.password, VIEWER_PASSWORD)
        if is_viewer_user and is_viewer_pass:
            role = "viewer"

    if not role:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    session_token = "sess_" + secrets.token_urlsafe(32)
    ADMIN_SESSIONS[session_token] = {
        "expires_at": time.time() + 86400 * 7,
        "username": body.username,
        "role": role,
    }

    return {
        "status": "ok",
        "token": session_token,
        "username": body.username,
        "role": role,
        "expires_in": 86400 * 7,
    }


@router.post("/logout")
def logout(
    x_admin_session: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    token = x_admin_session or x_admin_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if token and token in ADMIN_SESSIONS:
        ADMIN_SESSIONS.pop(token, None)
    return {"status": "logged_out"}


@router.get("/me")
def auth_me(
    x_admin_session: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    token = x_admin_session or x_admin_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if token:
        if token in ADMIN_SESSIONS:
            sess = ADMIN_SESSIONS[token]
            exp = sess["expires_at"] if isinstance(sess, dict) else sess
            uname = sess.get("username", "user") if isinstance(sess, dict) else "user"
            role = sess.get("role", "admin") if isinstance(sess, dict) else "admin"
            if time.time() < exp:
                return {"authenticated": True, "username": uname, "role": role}

        if (ADMIN_PASSWORD and secrets.compare_digest(token, ADMIN_PASSWORD)) or (
            ADMIN_TOKEN and secrets.compare_digest(token, ADMIN_TOKEN)
        ):
            return {"authenticated": True, "username": ADMIN_USERNAME, "role": "admin"}

        if VIEWER_PASSWORD and secrets.compare_digest(token, VIEWER_PASSWORD):
            return {"authenticated": True, "username": VIEWER_USERNAME, "role": "viewer"}

    return {"authenticated": False, "username": None, "role": None}
