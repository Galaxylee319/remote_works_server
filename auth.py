"""Authentication module using bcrypt hashed passwords and session cookies."""

import hashlib
import secrets
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import bcrypt
import yaml


class AuthManager:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        auth_cfg = config.get("auth", {})
        self.enabled = auth_cfg.get("enabled", True)
        self.username = auth_cfg.get("username", "admin")
        self.password_hash = auth_cfg.get("password_hash", "").encode()

        self.server_cfg = config.get("server", {})
        self.secret_key = self.server_cfg.get("secret_key", "default-secret")

        # In-memory session store: token -> (username, expiry)
        self._sessions: Dict[str, Tuple[str, float]] = {}
        self._session_timeout = 86400 * 7  # 7 days

    def verify_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode(), self.password_hash)

    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(48)
        expiry = time.time() + self._session_timeout
        self._sessions[token] = (username, expiry)
        # Clean up expired sessions occasionally
        if len(self._sessions) > 1000:
            self._cleanup()
        return token

    def validate_session(self, token: str) -> Optional[str]:
        entry = self._sessions.get(token)
        if entry is None:
            return None
        username, expiry = entry
        if time.time() > expiry:
            del self._sessions[token]
            return None
        return username

    def destroy_session(self, token: str) -> None:
        self._sessions.pop(token, None)

    def is_authenticated(self, request) -> bool:
        if not self.enabled:
            return True
        token = request.cookies.get("rws_session")
        if not token:
            return False
        return self.validate_session(token) is not None

    def _cleanup(self):
        now = time.time()
        expired = [t for t, (_, e) in self._sessions.items() if now > e]
        for t in expired:
            del self._sessions[t]

    def needs_auth(self) -> bool:
        return self.enabled and bool(self.password_hash)

    def set_password(self, password: str) -> None:
        """Update password hash and save to config."""
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        config_path = Path(__file__).parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["auth"]["password_hash"] = self.password_hash.decode()
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)


# Singleton
auth_manager: Optional[AuthManager] = None


def get_auth() -> AuthManager:
    global auth_manager
    if auth_manager is None:
        auth_manager = AuthManager()
    return auth_manager
