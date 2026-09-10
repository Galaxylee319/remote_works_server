"""Configuration management for remote-works-server (v2).

Unified config loader:
- Top-level keys are canonical: ``root_dir``, ``cache_dir``, ``host``, ``port``.
- Legacy ``paths.root_dir`` / ``paths.cache_dir`` and ``server.host`` / ``server.port``
  are still honoured for backward compatibility.
- ``~`` is expanded and paths are made absolute.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import yaml


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)

DEFAULTS: Dict[str, Any] = {
    "root_dir": os.path.expanduser("~/remote_works"),
    "cache_dir": os.path.expanduser("~/.cache/remote_works_server"),
    "host": "0.0.0.0",
    "port": 8088,
    "auth": {
        "enabled": True,
        "username": "admin",
        "password_hash": "",
        "session_ttl_days": 30,
        "cookie_secure": False,
        "max_login_attempts": 5,
        "login_lockout_seconds": 300,
    },
    "markdown": {
        "math": True,
        "mermaid": True,
        "toc": True,
        "highlight": True,
    },
    "pdf": {
        "enabled": True,
        "engine": "playwright",
        "cache": True,
        "page_format": "A4",
    },
    "search": {
        "exclude_dirs": ["data", "typeI_logs", ".git"],
        "exclude_patterns": ["__pycache__", "*.pyc"],
        "max_files": 50000,
        "max_results": 100,
    },
    "zip": {
        "enabled": True,
        "max_files": 5000,
        "max_bytes": 2147483648,  # 2 GiB
    },
    "server": {
        "title": "Remote Works",
        "version": "2.0.0",
    },
    "sync_dirs": {},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into ``base``."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load YAML config, deep-merged over defaults.

    ``config_path`` may be overridden by the ``RWS_CONFIG`` environment
    variable (useful for staging instances).
    """
    if config_path is None:
        config_path = os.environ.get("RWS_CONFIG", DEFAULT_CONFIG_PATH)
    cfg = dict(DEFAULTS)
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user_cfg)

    # ---- Legacy key compatibility ----
    paths = user_cfg.get("paths") if os.path.exists(config_path) else None
    if paths and isinstance(paths, dict):
        cfg["root_dir"] = paths.get("root_dir", cfg["root_dir"])
        cfg["cache_dir"] = paths.get("cache_dir", cfg["cache_dir"])
    server = user_cfg.get("server") if os.path.exists(config_path) else None
    if server and isinstance(server, dict):
        cfg["host"] = server.get("host", cfg["host"])
        cfg["port"] = server.get("port", cfg["port"])

    # ---- Normalise paths ----
    cfg["root_dir"] = os.path.abspath(os.path.expanduser(cfg["root_dir"]))
    cfg["cache_dir"] = os.path.abspath(os.path.expanduser(cfg["cache_dir"]))
    cfg["sync_dirs"] = {
        str(name): os.path.abspath(os.path.expanduser(src))
        for name, src in cfg.get("sync_dirs", {}).items()
        if src
    }

    # ---- Type sanity ----
    cfg["port"] = int(cfg["port"])
    for key in ("session_ttl_days", "max_login_attempts", "login_lockout_seconds"):
        cfg["auth"][key] = int(cfg["auth"][key])
    for key in ("max_files", "max_results"):
        cfg["search"][key] = int(cfg["search"][key])
    for key in ("max_files", "max_bytes"):
        cfg["zip"][key] = int(cfg["zip"][key])

    return cfg


config = load_config()
