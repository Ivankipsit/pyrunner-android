"""Saved-script library. Files live under the data directory, indexed by JSON."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]*\.py$")


def normalize_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name:
        raise ValueError("Name is empty")
    if not name.endswith(".py"):
        name += ".py"
    if len(name) > 80:
        raise ValueError("Name is too long")
    if ".." in name or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("Name is not allowed")
    if not _NAME.match(name):
        raise ValueError("Use letters, numbers, spaces, dot, dash, or underscore")
    return name


class ScriptLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / "scripts"
        self.index_path = self.root / "index.json"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def list_scripts(self) -> list[dict]:
        with self._lock:
            items = self._read()
        items.sort(key=lambda item: item.get("updatedAt", 0), reverse=True)
        return items

    def get(self, script_id: str) -> dict:
        with self._lock:
            item = self._find(script_id)
            source = self._path(script_id).read_text(encoding="utf-8")
        return {**item, "source": source}

    def save(self, script_id: str | None, name: str, source: str) -> dict:
        if not isinstance(source, str):
            raise ValueError("source is required")
        if len(source) > 2_000_000:
            raise ValueError("Script is larger than 2 MB")
        name = normalize_name(name)
        with self._lock:
            return self._save_unlocked(script_id, name, source)

    def rename(self, script_id: str, name: str) -> dict:
        name = normalize_name(name)
        with self._lock:
            items = self._read()
            item = self._find_in(items, script_id)
            self._ensure_unique(items, name, script_id)
            item["name"] = name
            item["updatedAt"] = _now()
            self._write(items)
            return dict(item)

    def delete(self, script_id: str) -> None:
        with self._lock:
            items = self._read()
            self._find_in(items, script_id)
            kept = [item for item in items if item["id"] != script_id]
            path = self._path(script_id)
            if path.exists():
                path.unlink()
            self._write(kept)

    def seed_if_empty(self, files: list[Path]) -> None:
        with self._lock:
            if self._read():
                return
            for file in files:
                if file.is_file() and file.suffix == ".py":
                    self._save_unlocked(None, file.name, file.read_text(encoding="utf-8"))

    def _save_unlocked(self, script_id: str | None, name: str, source: str) -> dict:
        items = self._read()
        now = _now()
        if script_id:
            item = self._find_in(items, script_id)
            self._ensure_unique(items, name, script_id)
            item["name"] = name
            item["updatedAt"] = now
        else:
            self._ensure_unique(items, name, None)
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": name,
                "createdAt": now,
                "updatedAt": now,
            }
            items.append(item)
        self._path(item["id"]).write_text(source, encoding="utf-8")
        self._write(items)
        return dict(item)

    def _ensure_unique(self, items: list[dict], name: str, script_id: str | None) -> None:
        for item in items:
            if item["name"] == name and item["id"] != script_id:
                raise ValueError(f"A script named {name} is already in the library")

    def _find(self, script_id: str) -> dict:
        return self._find_in(self._read(), script_id)

    def _find_in(self, items: list[dict], script_id: str) -> dict:
        for item in items:
            if item["id"] == script_id:
                return item
        raise KeyError(script_id)

    def _path(self, script_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{8,32}", script_id):
            raise KeyError(script_id)
        return self.dir / f"{script_id}.py"

    def _read(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        items = data.get("scripts", [])
        if not isinstance(items, list):
            return []
        return items

    def _write(self, items: list[dict]) -> None:
        payload = json.dumps({"scripts": items}, indent=2)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.index_path)


def _now() -> int:
    return int(time.time() * 1000)
