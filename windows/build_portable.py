"""Assemble a folder that runs on Windows without a system Python install.

The script is cross-platform so it can be smoke-tested on the dev host. The
GitHub workflow runs it on windows-latest and uploads the zip.
"""

from __future__ import annotations

import shutil
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

CMD = """@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONPATH=%ROOT%site-packages;%ROOT%src"
set "PYRUNNER_UI=%ROOT%ui"
set "PYRUNNER_EXAMPLES=%ROOT%examples"
set "PY=%ROOT%python\\pythonw.exe"
if not exist "%PY%" set "PY=%ROOT%python\\python.exe"
cd /d "%ROOT%"
if "%1"=="console" (
  "%ROOT%python\\python.exe" -m pyrunner_host %*
) else (
  if exist "%ROOT%python\\pythonw.exe" (
    start "" "%ROOT%python\\pythonw.exe" -m pyrunner_host
  ) else (
    "%PY%" -m pyrunner_host
  )
)
"""


def _ignore(_dir: str, names: list[str]) -> set[str]:
    skip = {"__pycache__", "node_modules", "editor", "package.json", "package-lock.json", ".pytest_cache"}
    return {name for name in names if name in skip or name.endswith(".pyc")}


def main() -> int:
    dest_root = ROOT / "dist"
    folder = dest_root / "PyRunner"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    python_home = Path(sys.base_prefix)
    shutil.copytree(python_home, folder / "python", symlinks=False, ignore=_ignore)
    site_dir = next(Path(path) for path in site.getsitepackages() if path.endswith("site-packages"))
    shutil.copytree(site_dir, folder / "site-packages", symlinks=False, ignore=_ignore)
    shutil.copytree(ROOT / "src", folder / "src", ignore=_ignore)
    shutil.copytree(REPO / "ui", folder / "ui", ignore=_ignore)
    shutil.copytree(REPO / "examples", folder / "examples", ignore=_ignore)
    (folder / "PyRunner.cmd").write_text(CMD.replace("\n", "\r\n"), encoding="utf-8")
    archive = dest_root / "PyRunner-windows"
    if archive.with_suffix(".zip").exists():
        archive.with_suffix(".zip").unlink()
    shutil.make_archive(str(archive), "zip", dest_root, "PyRunner")
    print(archive.with_suffix(".zip"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
