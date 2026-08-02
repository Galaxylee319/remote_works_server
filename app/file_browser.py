"""File browsing with safe path resolution and type detection (v2)."""
from __future__ import annotations

import fnmatch
import os
import stat
import time
from typing import Dict, List, Optional, Tuple

from app.config import config


EXT_MAP = {
    ".md": "markdown",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".webp": "image",
    ".csv": "data",
    ".txt": "text",
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".bz2": "archive",
    ".xz": "archive",
    ".py": "code",
    ".ipynb": "code",
    ".cpp": "code",
    ".h": "code",
    ".hpp": "code",
    ".c": "code",
    ".cc": "code",
    ".json": "data",
    ".yaml": "data",
    ".yml": "data",
    ".xml": "data",
    ".html": "web",
    ".css": "web",
    ".js": "code",
    ".ts": "code",
    ".log": "text",
    ".bag": "rosbag",
    ".launch": "ros",
    ".urdf": "ros",
    ".sdf": "ros",
    ".pcd": "pointcloud",
    ".ply": "pointcloud",
    ".stl": "mesh",
    ".obj": "mesh",
}

PREVIEW_EXTS = (
    ".md",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".txt",
    ".csv",
    ".log",
    ".py",
    ".cpp",
    ".h",
    ".hpp",
    ".c",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".js",
)


def resolve_safe_path(root_dir: str, request_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve ``request_path`` against ``root_dir``.

    Returns ``(abs_path, None)`` on success or ``(None, error_message)`` on
    failure. Symlinks are resolved with ``realpath`` so links escaping the root
    are rejected.
    """
    if request_path is None:
        request_path = ""
    try:
        clean = str(request_path).lstrip("/")
        if "\x00" in clean:
            return None, "非法路径"
        abs_path = os.path.abspath(os.path.join(root_dir, clean))
        abs_real = os.path.realpath(abs_path)
    except (ValueError, OSError):
        return None, "路径解析失败"

    root_real = os.path.realpath(root_dir)
    if abs_real != root_real and not abs_real.startswith(root_real + os.sep):
        return None, "路径超出允许目录"
    if not os.path.exists(abs_real):
        return None, "路径不存在"
    return abs_real, None


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _matches_any(name: str, patterns: List[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _entry_dict(full: str, root_dir: str, is_dir: bool) -> Optional[Dict]:
    try:
        st = os.stat(full)
    except OSError:
        return None
    rel = os.path.relpath(full, root_dir)
    ext = os.path.splitext(full)[1].lower() if not is_dir else ""
    return {
        "name": os.path.basename(full),
        "path": rel,
        "is_dir": is_dir,
        "size": st.st_size,
        "size_str": human_size(st.st_size),
        "mtime": st.st_mtime,
        "mtime_str": format_time(st.st_mtime),
        "extension": ext,
        "type": get_type_label(is_dir, ext),
        "preview": (not is_dir) and ext in PREVIEW_EXTS,
    }


def list_directory(abs_path: str, root_dir: str) -> List[Dict]:
    """List one directory, directories first, then by name."""
    entries = []
    try:
        names = os.listdir(abs_path)
    except (PermissionError, FileNotFoundError):
        return [{"error": "无法读取目录"}]

    for name in names:
        if _is_hidden(name):
            continue
        full = os.path.join(abs_path, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        is_dir = stat.S_ISDIR(st.st_mode)
        entry = _entry_dict(full, root_dir, is_dir)
        if entry is not None:
            entries.append(entry)

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries


def get_file_info(abs_path: str, root_dir: str) -> Optional[Dict]:
    """Info dict for a single file/directory."""
    try:
        st = os.stat(abs_path)
    except OSError:
        return None
    is_dir = stat.S_ISDIR(st.st_mode)
    return _entry_dict(abs_path, root_dir, is_dir)


def _walk_filtered(root_dir: str):
    """Yield (full_path, rel_path, is_dir) walking the root with excludes."""
    exclude_dirs = set(config["search"].get("exclude_dirs", []))
    exclude_patterns = config["search"].get("exclude_patterns", [])
    max_files = config["search"].get("max_files", 50000)
    count = 0

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [
            d
            for d in dirs
            if not _is_hidden(d)
            and d not in exclude_dirs
            and not _matches_any(d, exclude_patterns)
        ]
        for name in files:
            if _is_hidden(name) or _matches_any(name, exclude_patterns):
                continue
            full = os.path.join(root, name)
            yield full, os.path.relpath(full, root_dir), False
            count += 1
            if count >= max_files:
                return


def search_files(root_dir: str, query: str, limit: Optional[int] = None) -> List[Dict]:
    """Case-insensitive filename search, newest first."""
    if limit is None:
        limit = config["search"].get("max_results", 100)
    query_lower = query.lower()
    results = []
    for full, rel, _ in _walk_filtered(root_dir):
        if query_lower in os.path.basename(full).lower():
            entry = _entry_dict(full, root_dir, False)
            if entry is not None:
                results.append(entry)
            if len(results) >= limit:
                break
    results.sort(key=lambda e: e["mtime"], reverse=True)
    return results[:limit]


def get_recent_files(root_dir: str, limit: int = 20) -> List[Dict]:
    """Most recently modified files, newest first."""
    recent = []
    for full, rel, _ in _walk_filtered(root_dir):
        entry = _entry_dict(full, root_dir, False)
        if entry is not None:
            recent.append(entry)
    recent.sort(key=lambda e: e["mtime"], reverse=True)
    return recent[:limit]


def get_type_label(is_dir: bool, ext: str) -> str:
    if is_dir:
        return "directory"
    return EXT_MAP.get(ext, "file")


def can_preview(ext: str) -> bool:
    return ext in PREVIEW_EXTS


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

