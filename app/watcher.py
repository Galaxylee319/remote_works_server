"""File system watcher that keeps the index updated."""
from __future__ import annotations

import os
import stat
import time
import threading
from typing import List, Dict

from app.config import config
from app import cache_utils


class FileWatcher(threading.Thread):
    """Background thread that periodically scans root_dir and updates the index."""

    def __init__(self, interval: float = 5.0):
        super().__init__(daemon=True)
        self.interval = interval
        self.root_dir = config["root_dir"]
        self._running = False
        self._last_scan: Dict[str, float] = {}
        self._scan_count = 0

    def run(self):
        self._running = True
        # Initial full scan
        self._full_scan()
        while self._running:
            time.sleep(self.interval)
            try:
                self._incremental_scan()
            except Exception as e:
                print(f"[Watcher] Scan error: {e}")

    def stop(self):
        self._running = False

    def _full_scan(self):
        """Do a full scan of root_dir and build the initial index."""
        if not os.path.isdir(self.root_dir):
            return

        files = []
        now = time.time()
        tracked: Dict[str, float] = {}

        for root, dirs, names in os.walk(self.root_dir):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                full = os.path.join(root, name)
                try:
                    st = os.stat(full)
                    rel = os.path.relpath(full, self.root_dir)
                    ext = os.path.splitext(name)[1].lower()
                    tracked[rel] = st.st_mtime
                    files.append({
                        "path": rel,
                        "name": name,
                        "ext": ext,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "is_dir": False,
                    })
                except OSError:
                    continue
            for d in dirs:
                full = os.path.join(root, d)
                try:
                    rel = os.path.relpath(full, self.root_dir)
                    st = os.stat(full)
                    tracked[rel + "/"] = st.st_mtime
                except OSError:
                    continue

        if files:
            cache_utils.update_file_index(files)

        self._last_scan = tracked
        self._scan_count += 1
        print(f"[Watcher] Full scan complete: {len(files)} files indexed")

    def _incremental_scan(self):
        """Scan for changes since last scan."""
        if not os.path.isdir(self.root_dir):
            return

        current: Dict[str, float] = {}
        new_files = []
        modified_files = []

        for root, dirs, names in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                full = os.path.join(root, name)
                try:
                    st = os.stat(full)
                    rel = os.path.relpath(full, self.root_dir)
                    current[rel] = st.st_mtime

                    last_mtime = self._last_scan.get(rel)
                    if last_mtime is None:
                        # New file
                        ext = os.path.splitext(name)[1].lower()
                        new_files.append({
                            "path": rel,
                            "name": name,
                            "ext": ext,
                            "size": st.st_size,
                            "mtime": st.st_mtime,
                            "is_dir": False,
                        })
                    elif st.st_mtime > last_mtime and st.st_mtime > time.time() - self.interval * 2:
                        # Modified recently
                        ext = os.path.splitext(name)[1].lower()
                        modified_files.append({
                            "path": rel,
                            "name": name,
                            "ext": ext,
                            "size": st.st_size,
                            "mtime": st.st_mtime,
                            "is_dir": False,
                        })
                        # Invalidate cache
                        cache_utils.invalidate_cache_for_file(rel)
                except OSError:
                    continue

        # Detect deleted files
        for rel in self._last_scan:
            if rel not in current and not rel.endswith("/"):
                cache_utils.remove_from_index(rel)

        if new_files:
            cache_utils.update_file_index(new_files)
        if modified_files:
            cache_utils.update_file_index(modified_files)

        self._last_scan = current
        self._scan_count += 1

        if new_files or modified_files:
            changed = len(new_files) + len(modified_files)
            print(f"[Watcher] {changed} changes detected ({len(new_files)} new, {len(modified_files)} modified)")
