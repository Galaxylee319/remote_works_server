"""Configuration management for remote-works-server."""
from __future__ import annotations

import os
import yaml
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load YAML config, falling back to sensible defaults."""
    defaults = {
        "root_dir": os.path.expanduser("~/remote_works"),
        "cache_dir": os.path.expanduser("~/.cache/remote_works_server"),
        "host": "127.0.0.1",
        "port": 8088,
        "auth": {
            "enabled": True,
            "username": "admin",
            "password_hash": "",
        },
        "markdown": {
            "math": True,
            "mermaid": True,
            "toc": True,
            "code_highlight": True,
        },
        "pdf": {
            "enabled": True,
            "engine": "playwright",
            "cache": True,
        },
        "file_watcher": {
            "enabled": True,
            "interval_seconds": 5,
        },
    }

    cfg_path = config_path or DEFAULT_CONFIG_PATH
    if os.path.exists(cfg_path):
        with open(cfg_path, "r") as f:
            user_cfg = yaml.safe_load(f) or {}
        # Deep merge
        merged = defaults.copy()
        merged.update(user_cfg)
        for key in ("auth", "markdown", "pdf", "file_watcher"):
            if key in user_cfg and isinstance(user_cfg[key], dict):
                merged[key].update(user_cfg[key])
        cfg = merged
    else:
        cfg = defaults

    # Resolve ~ in paths
    cfg["root_dir"] = os.path.abspath(os.path.expanduser(cfg["root_dir"]))
    cfg["cache_dir"] = os.path.abspath(os.path.expanduser(cfg["cache_dir"]))

    # Ensure cache dir exists
    os.makedirs(cfg["cache_dir"], exist_ok=True)

    return cfg


config = load_config()
