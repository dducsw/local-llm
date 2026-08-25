import secrets
import time
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_SESSIONS,
    ADMIN_TOKEN,
    ADMIN_USERNAME,
    LOGIN_ATTEMPTS,
)
from app.schemas import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login")
def login(body: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Rate limit check (5 attempts per minute)
    attempts = LOGIN_ATTEMPTS[ip]
    attempts[:] = [t for t in attempts if now - t < 60]
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")

    LOGIN_ATTEMPTS[ip].append(now)

    valid_user = secrets.compare_digest(body.username, ADMIN_USERNAME)
    valid_pass = (ADMIN_PASSWORD and secrets.compare_digest(body.password, ADMIN_PASSWORD)) or (
        ADMIN_TOKEN and secrets.compare_digest(body.password, ADMIN_TOKEN)
    )

    if not valid_user or not valid_pass:
        raise HTTPException(
            status_code=401,
            detail="Invalid administrator username or password",
        )

    session_token = "sess_" + secrets.token_urlsafe(32)
    ADMIN_SESSIONS[session_token] = time.time() + 86400 * 7  # 7 days session

    return {
        "status": "ok",
        "token": session_token,
        "username": ADMIN_USERNAME,
        "expires_in": 86400 * 7,
    }


@router.post("/logout")
def logout(
    x_admin_session: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    token = x_admin_session or x_admin_token
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
        if token in ADMIN_SESSIONS and time.time() < ADMIN_SESSIONS[token]:
            return {"authenticated": True, "username": ADMIN_USERNAME}
        if (ADMIN_PASSWORD and secrets.compare_digest(token, ADMIN_PASSWORD)) or (
            ADMIN_TOKEN and secrets.compare_digest(token, ADMIN_TOKEN)
        ):
            return {"authenticated": True, "username": ADMIN_USERNAME}

    return {"authenticated": False, "username": None}
