"""Locate the UI, examples, and the per-user data directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    """Directory that contains `src/` (the repo's windows/ folder, or a portable folder)."""
    return Path(__file__).resolve().parents[2]


def _bundled_or_sibling(name: str, env_var: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override)
    bundled = app_root() / name
    if bundled.is_dir():
        return bundled
    return app_root().parent / name


def ui_dir() -> Path:
    return _bundled_or_sibling("ui", "PYRUNNER_UI")


def examples_dir() -> Path:
    return _bundled_or_sibling("examples", "PYRUNNER_EXAMPLES")


def data_dir() -> Path:
    override = os.environ.get("PYRUNNER_DATA")
    if override:
        return Path(override)
    if os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home())
        return Path(root) / "PyRunner"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PyRunner"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "PyRunner"
