#!/usr/bin/env python3
"""Real-time mirror for remote_works_server sync_dirs.

Watches each configured source directory and mirrors changes to
<root_dir>/<name> using rsync. This works even if the running server
was started before the symlink-aware path resolution update.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("remote-works-sync")

DEBOUNCE_SECONDS = 1.0


def load_sync_dirs():
    """Return (root_dir, {display_name: source_path}) from config.yaml."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    root = os.path.abspath(
        os.path.expanduser(cfg.get("root_dir", os.path.expanduser("~/remote_works")))
    )
    sync = {}
    for name, src in (cfg.get("sync_dirs") or {}).items():
        src_abs = os.path.abspath(os.path.expanduser(str(src)))
        if os.path.isdir(src_abs):
            sync[str(name)] = src_abs
    return root, sync


def rsync_mirror(src: str, dst: str) -> None:
    """Mirror src directory into dst using rsync (delete removed files)."""
    os.makedirs(dst, exist_ok=True)
    cmd = [
        "rsync",
        "-a",
        "--delete",
        "--exclude",
        ".git",
        src.rstrip("/") + "/",
        dst.rstrip("/") + "/",
    ]
    try:
        subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("rsync failed %s -> %s: %s", src, dst, e)


class SyncHandler(FileSystemEventHandler):
    """Debounced rsync mirror on any filesystem event under a source dir."""

    def __init__(self, root: str, sync_dirs: dict):
        self.root = root
        self.sync_dirs = sync_dirs
        self._lock = threading.Lock()
        self._timers = {}

    def on_any_event(self, event):
        path = os.path.realpath(event.src_path)
        for name, src in self.sync_dirs.items():
            src_real = os.path.realpath(src)
            if path == src_real or path.startswith(src_real + os.sep):
                self._schedule(name)
                return

    def _schedule(self, name: str):
        with self._lock:
            timer = self._timers.pop(name, None)
            if timer:
                timer.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, self._sync, args=(name,))
            timer.daemon = True
            self._timers[name] = timer
            timer.start()

    def _sync(self, name: str):
        with self._lock:
            self._timers.pop(name, None)
        src = self.sync_dirs[name]
        dst = os.path.join(self.root, name)
        rsync_mirror(src, dst)
        logger.info("Mirrored %s -> %s", src, dst)


def main():
    root, sync_dirs = load_sync_dirs()
    if not sync_dirs:
        logger.warning("No sync_dirs configured, exiting")
        return

    # Initial mirror, then watch for changes.
    for name, src in sync_dirs.items():
        dst = os.path.join(root, name)
        rsync_mirror(src, dst)
        logger.info("Initial mirror %s -> %s", src, dst)

    observer = Observer()
    handler = SyncHandler(root, sync_dirs)
    for src in sync_dirs.values():
        observer.schedule(handler, src, recursive=True)
    observer.daemon = True
    observer.start()
    logger.info("Watching %d sync dir(s): %s", len(sync_dirs), ", ".join(sync_dirs))

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()