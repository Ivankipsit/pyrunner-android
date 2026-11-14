"""Run one script file inside this process.

The Windows .exe uses this for every script. A frozen app has no separate
python.exe, so the same PyRunner.exe is started again with --script.
"""

from __future__ import annotations

import os
import runpy
import sys
import threading
import time
import traceback
from pathlib import Path


def run_script(script: str) -> int:
    path = Path(script)
    sys.argv = [str(path)]
    _install_windows_break()
    _start_cancel_watcher()
    try:
        runpy.run_path(str(path), run_name="__main__")
    except KeyboardInterrupt:
        sys.stderr.write("\nKeyboardInterrupt: stopped\n")
        return 130
    except SystemExit as exc:
        code = exc.code
        if code is None or code == 0:
            return 0
        if isinstance(code, int):
            return code
        sys.stderr.write(str(code) + "\n")
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    return 0


def _raise_in_thread(tid: int | None, exc: type[BaseException]) -> None:
    if tid is None:
        return
    try:
        import ctypes

        api = ctypes.pythonapi
        api.PyThreadState_SetAsyncExc.restype = ctypes.c_int
        api.PyThreadState_SetAsyncExc.argtypes = [ctypes.c_ulong, ctypes.py_object]
        count = api.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), exc)
        if count > 1:
            api.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
    except Exception:
        return


def _install_windows_break() -> None:
    if sys.platform != "win32":
        return
    import signal

    signal.signal(signal.SIGBREAK, signal.default_int_handler)


def _start_cancel_watcher() -> None:
    cancel = os.environ.get("PYRUNNER_CANCEL")
    if not cancel:
        return

    def loop() -> None:
        tid = threading.main_thread().ident
        while True:
            if os.path.exists(cancel):
                _raise_in_thread(tid, KeyboardInterrupt)
            time.sleep(0.2)

    threading.Thread(target=loop, name="pyrunner-cancel", daemon=True).start()
