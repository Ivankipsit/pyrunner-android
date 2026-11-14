"""Runtime package install for the desktop host.

Installs are explicit and go to PyPI through pip. Specifiers cannot be URLs,
paths, or VCS links.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import subprocess
import sys

_SPEC = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}"
    r"(\[[A-Za-z0-9,._-]+\])?"
    r"((==|!=|~=|>=|<=|>|<)[A-Za-z0-9*._+!]{1,40})?$"
)

CURATED = [
    "requests",
    "httpx",
    "beautifulsoup4",
    "lxml",
    "pandas",
    "numpy",
    "aiohttp",
    "python-dotenv",
    "tenacity",
    "tqdm",
    "playwright",
    "selenium",
    "pip",
]


def validate_spec(spec: str) -> str:
    text = (spec or "").strip()
    if not _SPEC.match(text):
        raise ValueError("Package spec must be a plain PyPI name, optionally with ==, >=, or extras")
    return text


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def curated_packages() -> list[dict]:
    found: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            found[name.lower().replace("_", "-")] = dist.version
    rows = []
    for name in CURATED:
        key = name.lower().replace("_", "-")
        version = found.get(key)
        rows.append(
            {
                "name": name,
                "version": version or "",
                "installed": version is not None,
                "source": "venv" if version else "missing",
            }
        )
    return rows


def pip_install(spec: str, python: str | None = None) -> dict:
    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "PyRunner.exe already includes its scraping packages. Installing another package needs a new build."
        )
    spec = validate_spec(spec)
    executable = python or sys.executable
    proc = subprocess.run(
        [executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", spec],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    output = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-8000:]
    if proc.returncode != 0:
        raise RuntimeError(output.strip() or "pip failed")
    return {"spec": spec, "output": output}
