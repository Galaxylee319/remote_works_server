"""Authentication for remote-works-server."""
from __future__ import annotations

import bcrypt
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import config

# Session token stored in a simple cookie
SESSION_COOKIE = "rws_session"
SESSION_TOKEN = "authenticated"


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks auth unless accessing login page or static files."""

    async def dispatch(self, request: Request, call_next):
        if not config["auth"]["enabled"]:
            return await call_next(request)

        # Paths that don't require auth
        public_paths = {"/login", "/static", "/favicon.ico"}
        if any(request.url.path.startswith(p) for p in public_paths):
            return await call_next(request)

        # Check session cookie
        session = request.cookies.get(SESSION_COOKIE)
        if session == SESSION_TOKEN:
            return await call_next(request)

        # Not authenticated - redirect to login
        if request.url.path == "/api/login":
            return await call_next(request)

        # API calls get 401, page requests get redirect
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        return RedirectResponse(url="/login", status_code=302)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    if not password_hash:
        # No password set yet — create default
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Generate bcrypt hash for a password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
