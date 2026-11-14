"""Copy files into a script's folder, and write them out to a folder the person picks.

Names stay a single file name. They are not forced to end in .py.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,80}$")
MAX_BYTES = 8_000_000
SKIP = {"main.py", "sitecustomize.py"}


def safe_filename(raw: str) -> str:
    name = (raw or "").strip().replace("\\", "/").split("/")[-1].strip()
    if name in ("", ".", "..") or name.startswith(".") or ".." in name or "\x00" in name:
        raise ValueError("File name is not allowed")
    if not _NAME.match(name):
        raise ValueError("Use letters, numbers, spaces, dot, dash, or underscore")
    return name


def inbox_dir(root: Path, script_id: str | None) -> Path:
    key = (script_id or "").strip() or "scratch"
    if not re.match(r"^[A-Za-z0-9_-]{1,40}$", key):
        raise ValueError("Script id is not allowed")
    folder = Path(root) / "inbox" / key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def store_file(folder: Path, name: str, data: bytes) -> str:
    safe = safe_filename(name)
    if len(data) > MAX_BYTES:
        raise ValueError("File is larger than 8 MB")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / safe).write_bytes(data)
    return safe


def list_files(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(path.name for path in folder.iterdir() if path.is_file() and path.name not in SKIP)


def copy_into(work: Path, folder: Path | None) -> None:
    if folder is None or not folder.is_dir():
        return
    work.mkdir(parents=True, exist_ok=True)
    for name in list_files(folder):
        target = work / name
        if target.name in SKIP:
            continue
        shutil.copyfile(folder / name, target)


def adopt(root: Path, script_id: str) -> list[str]:
    scratch = inbox_dir(root, None)
    dest = inbox_dir(root, script_id)
    moved = []
    for name in list_files(scratch):
        shutil.copyfile(scratch / name, dest / name)
        (scratch / name).unlink()
        moved.append(name)
    return moved


def export_to(folder: Path, name: str, content: bytes, extras: list[Path]) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for extra in extras:
        if not extra.is_file() or extra.name in SKIP:
            continue
        safe = safe_filename(extra.name)
        shutil.copyfile(extra, folder / safe)
        written.append(safe)
    safe_name = safe_filename(name)
    if len(content) > MAX_BYTES:
        raise ValueError("File is larger than 8 MB")
    (folder / safe_name).write_bytes(content)
    if safe_name not in written:
        written.append(safe_name)
    return written
