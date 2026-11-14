"""Build a double-click Windows app: PyRunner.exe.

Run this on Windows. The executable opens the shared UI and reruns itself
with --script for each Python file, so the scraping packages inside the exe
are what user scripts import.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def main() -> int:
    if sys.platform != "win32":
        print("PyRunner.exe is built on Windows.", file=sys.stderr)
        return 2
    from PyInstaller.__main__ import run

    sep = os.pathsep
    entry = ROOT / "src" / "pyrunner_host" / "__main__.py"
    args = [
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        "PyRunner",
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        f"{REPO / 'ui'}{sep}ui",
        "--add-data",
        f"{REPO / 'examples'}{sep}examples",
        "--collect-all",
        "webview",
        "--collect-submodules",
        "pyrunner_host",
        "--hidden-import",
        "bottle",
        "--hidden-import",
        "requests",
        "--hidden-import",
        "httpx",
        "--hidden-import",
        "bs4",
        "--hidden-import",
        "lxml",
        "--hidden-import",
        "pandas",
        "--hidden-import",
        "numpy",
        "--hidden-import",
        "aiohttp",
        "--hidden-import",
        "dotenv",
        "--hidden-import",
        "tenacity",
        "--hidden-import",
        "tqdm",
        "--hidden-import",
        "pip",
        str(entry),
    ]
    run(args)
    exe = ROOT / "dist" / "PyRunner.exe"
    if not exe.is_file():
        print(f"missing {exe}", file=sys.stderr)
        return 1
    print(exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
