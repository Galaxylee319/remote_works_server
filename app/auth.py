"""Authentication: bcrypt password hashing, random session tokens, rate limiting."""
from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

import bcrypt
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import config


SESSION_COOKIE = "rws_session"

# Paths that never require authentication.
PUBLIC_PREFIXES = ("/login", "/static", "/favicon.ico", "/api/health")


def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password``."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish bcrypt check; never raises on bad input."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class SessionStore:
    """In-memory random-token session store with expiry and cleanup."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = int(ttl_seconds)
        self._sessions: Dict[str, float] = {}  # token -> expiry ts
        self._lock = threading.Lock()

    def create(self) -> str:
        token = secrets.token_urlsafe(48)
        with self._lock:
            self._cleanup_locked()
            self._sessions[token] = time.time() + self._ttl
        return token

    def validate(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None:
                return False
            if time.time() > expiry:
                self._sessions.pop(token, None)
                return False
            return True

    def destroy(self, token: Optional[str]) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [t for t, exp in self._sessions.items() if now > exp]
        for t in expired:
            self._sessions.pop(t, None)


class LoginRateLimiter:
    """Sliding-window per-(ip, username) login attempt limiter."""

    def __init__(self, max_attempts: int, lockout_seconds: int) -> None:
        self._max_attempts = int(max_attempts)
        self._lockout = int(lockout_seconds)
        self._failures: Dict[Tuple[str, str], list] = {}
        self._lock = threading.Lock()

    def is_blocked(self, ip: str, username: str) -> bool:
        key = (ip, username)
        now = time.time()
        with self._lock:
            stamps = self._failures.get(key, [])
            stamps = [s for s in stamps if now - s < self._lockout]
            self._failures[key] = stamps
            return len(stamps) >= self._max_attempts

    def record_failure(self, ip: str, username: str) -> None:
        key = (ip, username)
        now = time.time()
        with self._lock:
            stamps = self._failures.get(key, [])
            stamps = [s for s in stamps if now - s < self._lockout]
            stamps.append(now)
            self._failures[key] = stamps

    def reset(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop((ip, username), None)


# Module-level singletons (single worker process).
sessions = SessionStore(ttl_seconds=config["auth"]["session_ttl_days"] * 86400)
rate_limiter = LoginRateLimiter(
    max_attempts=config["auth"]["max_login_attempts"],
    lockout_seconds=config["auth"]["login_lockout_seconds"],
)


def client_ip(request: Request) -> str:
    """Best-effort client IP (X-Forwarded-For only when proxied)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def persist_password_hash(password_hash: str) -> None:
    """Atomically write the new password hash into config.yaml."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
    )
    if not os.path.exists(config_path):
        return
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    auth = data.setdefault("auth", {})
    auth["password_hash"] = password_hash
    tmp_path = config_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    os.replace(tmp_path, config_path)
    config["auth"]["password_hash"] = password_hash


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests; redirect browsers to /login."""

    async def dispatch(self, request: Request, call_next):
        if not config["auth"]["enabled"]:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        if sessions.validate(token):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse(
                status_code=401, content={"error": "Not authenticated"}
            )
        return RedirectResponse(url=f"/login?next={path}", status_code=302)
