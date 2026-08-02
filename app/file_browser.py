"""File browsing and safe path resolution for remote-works-server."""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def resolve_safe_path(root_dir: str, request_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a request path against root_dir, returning (safe_abs_path, error).

    Returns (safe_abs_path, None) on success, or (None, error_message) on failure.
    Prevents path traversal attacks.
    """
    # Normalise and resolve the requested path
    try:
        # Strip leading slash and join
        clean = request_path.lstrip("/")
        abs_path = os.path.abspath(os.path.join(root_dir, clean))
    except (ValueError, OSError):
        return None, "Invalid path"

    root_real = os.path.realpath(root_dir)

    # Resolve symlinks, .. etc.
    try:
        abs_real = os.path.realpath(abs_path)
    except (ValueError, OSError):
        return None, "Path resolution error"

    # Must be within root_dir
    if not abs_real.startswith(root_real + "/") and abs_real != root_real:
        return None, "Path is outside the allowed directory"

    return abs_real, None


def list_directory(abs_path: str, root_dir: str) -> List[Dict]:
    """List contents of a directory. Returns sorted list of file info dicts."""
    entries = []
    try:
        names = os.listdir(abs_path)
    except PermissionError:
        return [{"error": "Permission denied"}]
    except FileNotFoundError:
        return [{"error": "Directory not found"}]

    for name in names:
        full = os.path.join(abs_path, name)
        try:
            st = os.stat(full)
            is_dir = stat.S_ISDIR(st.st_mode)
            size = st.st_size
            mtime = st.st_mtime
            ext = os.path.splitext(name)[1].lower() if not is_dir else ""
        except OSError:
            continue

        # Relative path for linking
        rel = os.path.relpath(full, root_dir)

        entries.append({
            "name": name,
            "path": rel,
            "is_dir": is_dir,
            "size": size,
            "size_hr": human_size(size),
            "mtime": mtime,
            "mtime_hr": format_time(mtime),
            "ext": ext,
            "type_label": get_type_label(is_dir, ext),
            "preview": can_preview(ext) if not is_dir else False,
        })

    # Sort: directories first, then by name
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries


def get_file_info(abs_path: str, root_dir: str) -> Optional[Dict]:
    """Get info for a single file."""
    try:
        st = os.stat(abs_path)
        is_dir = stat.S_ISDIR(st.st_mode)
        ext = os.path.splitext(abs_path)[1].lower() if not is_dir else ""
        rel = os.path.relpath(abs_path, root_dir)
        return {
            "name": os.path.basename(abs_path),
            "path": rel,
            "abs_path": abs_path,
            "is_dir": is_dir,
            "size": st.st_size,
            "size_hr": human_size(st.st_size),
            "mtime": st.st_mtime,
            "mtime_hr": format_time(st.st_mtime),
            "ext": ext,
            "type_label": get_type_label(is_dir, ext),
        }
    except OSError:
        return None


def search_files(root_dir: str, query: str) -> List[Dict]:
    """Search files by name (case-insensitive). Returns up to 50 results."""
    results = []
    query_lower = query.lower()
    try:
        for root, dirs, files in os.walk(root_dir):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if query_lower in f.lower():
                    full = os.path.join(root, f)
                    try:
                        st = os.stat(full)
                        ext = os.path.splitext(f)[1].lower()
                        rel = os.path.relpath(full, root_dir)
                        results.append({
                            "name": f,
                            "path": rel,
                            "is_dir": False,
                            "size": st.st_size,
                            "size_hr": human_size(st.st_size),
                            "mtime": st.st_mtime,
                            "mtime_hr": format_time(st.st_mtime),
                            "ext": ext,
                            "type_label": get_type_label(False, ext),
                            "preview": can_preview(ext),
                        })
                    except OSError:
                        continue
                if len(results) >= 50:
                    break
            if len(results) >= 50:
                break
    except Exception:
        pass
    return results


def get_recent_files(root_dir: str, limit: int = 20) -> List[Dict]:
    """Get most recently modified files."""
    recent = []
    try:
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                full = os.path.join(root, f)
                try:
                    st = os.stat(full)
                    ext = os.path.splitext(f)[1].lower()
                    rel = os.path.relpath(full, root_dir)
                    recent.append({
                        "name": f,
                        "path": rel,
                        "size": st.st_size,
                        "size_hr": human_size(st.st_size),
                        "mtime": st.st_mtime,
                        "mtime_hr": format_time(st.st_mtime),
                        "ext": ext,
                        "type_label": get_type_label(False, ext),
                        "preview": can_preview(ext),
                    })
                except OSError:
                    continue
    except Exception:
        pass
    recent.sort(key=lambda e: e["mtime"], reverse=True)
    return recent[:limit]


def can_preview(ext: str) -> bool:
    return ext in (".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def get_type_label(is_dir: bool, ext: str) -> str:
    if is_dir:
        return "directory"
    labels = {
        ".md": "Markdown",
        ".pdf": "PDF",
        ".png": "Image",
        ".jpg": "Image",
        ".jpeg": "Image",
        ".gif": "Image",
        ".svg": "Image",
        ".webp": "Image",
        ".csv": "CSV",
        ".txt": "Text",
        ".json": "JSON",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".zip": "Archive",
        ".tar": "Archive",
        ".gz": "Archive",
        ".py": "Python",
        ".ipynb": "Notebook",
    }
    return labels.get(ext, "File")


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"


def format_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
