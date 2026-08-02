"""File indexing and scanning for ~/remote_works/ directory."""

import fnmatch
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml


class FileEntry:
    """Represents a file or directory entry."""

    def __init__(self, path: Path, root_dir: Path):
        self.path = path
        self.rel_path = path.relative_to(root_dir)
        self.name = path.name
        self.is_dir = path.is_dir()
        try:
            stat = path.stat()
            self.size = stat.st_size
            self.mtime = stat.st_mtime
            self.mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        except OSError:
            self.size = 0
            self.mtime = 0
            self.mtime_str = "unknown"

        self.extension = path.suffix.lower() if not self.is_dir else ""
        self.type = self._guess_type()

    def _guess_type(self) -> str:
        if self.is_dir:
            return "directory"
        ext_map = {
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
            ".cpp": "code",
            ".h": "code",
            ".hpp": "code",
            ".c": "code",
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
        return ext_map.get(self.extension, "file")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.rel_path),
            "is_dir": self.is_dir,
            "size": self.size,
            "size_str": self._format_size(self.size),
            "mtime": self.mtime_str,
            "mtime_ts": self.mtime,
            "type": self.type,
            "extension": self.extension,
        }

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class FileIndex:
    """Indexes files in the root directory with search and listing capabilities."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        paths = config.get("paths", {})
        self.root_dir = Path(paths.get("root_dir", os.path.expanduser("~/remote_works"))).resolve()
        self.max_files = config.get("search", {}).get("max_files", 10000)
        self.exclude_patterns = config.get("search", {}).get("exclude", [".*"])

    def list_directory(self, rel_path: str = "") -> List[FileEntry]:
        """List files in a directory relative to root_dir."""
        target = self._resolve_path(rel_path)
        if target is None or not target.is_dir():
            return []

        entries = []
        try:
            for child in sorted(target.iterdir()):
                if self._is_excluded(child.name):
                    continue
                entries.append(FileEntry(child, self.root_dir))
        except PermissionError:
            pass

        # Sort: directories first, then by mtime (newest first)
        entries.sort(key=lambda e: (not e.is_dir, -e.mtime))
        return entries

    def get_file_info(self, rel_path: str) -> Optional[FileEntry]:
        """Get info for a single file."""
        target = self._resolve_path(rel_path)
        if target is None or not target.exists():
            return None
        return FileEntry(target, self.root_dir)

    def search(self, query: str) -> List[FileEntry]:
        """Search for files matching the query."""
        results = []
        query_lower = query.lower()

        for root, dirs, files in os.walk(str(self.root_dir)):
            # Filter excluded dirs
            dirs[:] = [d for d in dirs if not self._is_excluded(d)]

            rel_root = Path(root).relative_to(self.root_dir)

            for name in dirs + files:
                if self._is_excluded(name):
                    continue
                if query_lower in name.lower():
                    full_path = Path(root) / name
                    results.append(FileEntry(full_path, self.root_dir))

            if len(results) >= self.max_files:
                break

        results.sort(key=lambda e: -e.mtime)
        return results[:100]  # Return top 100

    def recent_files(self, limit: int = 50) -> List[FileEntry]:
        """Get recently modified files."""
        entries = []
        for root, dirs, files in os.walk(str(self.root_dir)):
            dirs[:] = [d for d in dirs if not self._is_excluded(d)]
            for name in files:
                if self._is_excluded(name):
                    continue
                full_path = Path(root) / name
                entries.append(FileEntry(full_path, self.root_dir))
            if len(entries) >= self.max_files:
                break

        entries.sort(key=lambda e: -e.mtime)
        return entries[:limit]

    def read_file(self, rel_path: str) -> Optional[str]:
        """Read a file's contents safely."""
        target = self._resolve_path(rel_path)
        if target is None or not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            return None

    def read_file_bytes(self, rel_path: str) -> Optional[bytes]:
        """Read a file's binary contents safely."""
        target = self._resolve_path(rel_path)
        if target is None or not target.is_file():
            return None
        try:
            return target.read_bytes()
        except (PermissionError, OSError):
            return None

    def _resolve_path(self, rel_path: str) -> Optional[Path]:
        """Resolve a relative path, preventing path traversal."""
        # Normalize the path: remove .. and .
        rel = rel_path.lstrip("/")
        target = (self.root_dir / rel).resolve()

        # Ensure target is within root_dir
        try:
            target.relative_to(self.root_dir)
        except ValueError:
            return None

        return target

    def _is_excluded(self, name: str) -> bool:
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False


# Singleton
file_index: Optional[FileIndex] = None


def get_index() -> FileIndex:
    global file_index
    if file_index is None:
        file_index = FileIndex()
    return file_index
