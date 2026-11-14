"""Open the shared UI in a native window. No listening socket is started here."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from pyrunner_host.api import HostApi, desktop_platform
from pyrunner_host.library import ScriptLibrary
from pyrunner_host.paths import data_dir, examples_dir, ui_dir
from pyrunner_host.supervisor import Supervisor


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--script"] and len(args) >= 2:
        from pyrunner_host.child import run_script

        return run_script(args[1])
    if args[:1] == ["selftest"]:
        from pyrunner_host.selftest import run

        return run()
    try:
        return _run_window()
    except Exception:
        text = traceback.format_exc()
        _write_host_log(text)
        _alert(text)
        raise


def _run_window() -> int:
    import webview

    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    library = ScriptLibrary(root / "library")
    _seed(library)
    supervisor = Supervisor(root, max_slots=8)
    holder: dict = {}

    def emit(event: dict) -> None:
        window = holder.get("window")
        if window is None:
            return
        payload = json.dumps(event)
        window.evaluate_js(f"window.pyrunner && window.pyrunner.receive({payload})")

    supervisor.on_event = emit
    api = HostApi(
        library=library,
        supervisor=supervisor,
        open_file=lambda: _pick_file(holder["window"]),
        platform_name=desktop_platform(),
    )
    index = ui_dir() / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"UI not found at {index}")
    window = webview.create_window(
        "PyRunner",
        url=index.resolve().as_uri(),
        js_api=api,
        width=1120,
        height=780,
        min_size=(380, 600),
        background_color="#14160F",
    )
    holder["window"] = window
    try:
        # pywebview serves the local UI on 127.0.0.1 (Bottle's default). Do not
        # enable debug, which is the switch that opens an inspector.
        webview.start(private_mode=True, debug=False, http_server=False)
    finally:
        supervisor.shutdown()
    return 0


def _seed(library: ScriptLibrary) -> None:
    examples = examples_dir()
    files = sorted(path for path in examples.glob("*.py") if path.is_file())
    desktop = examples / "desktop"
    if desktop.is_dir():
        files.extend(sorted(desktop.glob("*.py")))
    library.seed_if_empty(files)


def _pick_file(window) -> dict | None:
    import webview

    dialog = getattr(webview, "FileDialog", None)
    kind = dialog.OPEN if dialog is not None else webview.OPEN_DIALOG
    try:
        chosen = window.create_file_dialog(
            kind,
            allow_multiple=False,
            file_types=("Python (*.py)",),
        )
    except TypeError:
        chosen = window.create_file_dialog(kind, allow_multiple=False)
    if not chosen:
        return None
    path = Path(chosen[0])
    size = path.stat().st_size
    if size > 2_000_000:
        raise ValueError("File is larger than 2 MB")
    return {
        "name": path.name,
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "originDir": str(path.parent),
    }


def _alert(text: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text[-1500:], "PyRunner", 0x10)
    except Exception:
        return


def _write_host_log(text: str) -> None:
    try:
        folder = data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "host.log").open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
    except Exception:
        return
