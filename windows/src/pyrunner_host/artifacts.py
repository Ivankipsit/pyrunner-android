"""Images a script saves while it runs.

Only files inside the run's work directory, or the folder the script was
opened from, are visible. The path cannot climb out of those folders.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_BYTES = 1_500_000
MAX_FILES = 24

MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def snapshot(work: Path, origin: str | None) -> dict[str, str]:
    return {name: sig for name, (_path, sig) in _collect(work, origin).items()}


def list_new(work: Path, origin: str | None, baseline: dict[str, str]) -> list[dict]:
    current = _collect(work, origin)
    found = []
    for name, (path, sig) in current.items():
        if baseline.get(name) == sig:
            continue
        size = path.stat().st_size
        found.append({"name": name, "kind": "image", "bytes": size, "mtime": path.stat().st_mtime_ns})
    found.sort(key=lambda item: item["mtime"])
    return [{"name": item["name"], "kind": item["kind"], "bytes": item["bytes"]} for item in found[:MAX_FILES]]


def read(work: Path, origin: str | None, name: str) -> dict:
    path = _locate(work, origin, name)
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("Image is larger than 1.5 MB")
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    return {"name": name, "mime": mime, "base64": base64.b64encode(data).decode("ascii")}


def _collect(work: Path, origin: str | None) -> dict[str, tuple[Path, str]]:
    found: dict[str, tuple[Path, str]] = {}
    _walk(work, "", found)
    if origin:
        root = Path(origin)
        if root.is_dir():
            _walk(root, "origin/", found)
    return found


def _walk(root: Path, prefix: str, found: dict[str, tuple[Path, str]]) -> None:
    if not root.is_dir():
        return
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != "__pycache__" and not name.startswith(".")]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() not in SUFFIXES or path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.resolve().relative_to(root).as_posix()
            name = prefix + rel
            found[name] = (path, f"{stat.st_size}:{stat.st_mtime_ns}")


def _locate(work: Path, origin: str | None, name: str) -> Path:
    if name.startswith("origin/"):
        if not origin:
            raise ValueError("bad path")
        return _safe(Path(origin), name[len("origin/") :])
    return _safe(work, name)


def _safe(root: Path, rel: str) -> Path:
    if not rel or rel.startswith(("/", "\\")) or "\\" in rel or ":" in rel:
        raise ValueError("bad path")
    parts = Path(rel).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("bad path")
    root_resolved = root.resolve()
    candidate = (root_resolved.joinpath(*parts)).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise ValueError("bad path")
    if candidate.suffix.lower() not in SUFFIXES or not candidate.is_file():
        raise ValueError("not an image")
    return candidate
