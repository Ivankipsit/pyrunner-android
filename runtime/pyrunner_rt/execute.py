"""Run one script with streamed output and cooperative cancellation.

Stop is cooperative: it raises KeyboardInterrupt in the script thread and
makes time.sleep return early. A script that catches that interrupt and keeps
going is still running. Ending that script requires killing its process, which
the Android slot processes and the desktop subprocess host can do.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

_tls = threading.local()
_patch_lock = threading.Lock()
_patched = False
_original_sleep: Callable[..., Any] | None = None


def _cancelled(cancel: Any) -> bool:
    if cancel is None:
        return False
    if isinstance(cancel, threading.Event):
        return cancel.is_set()
    is_set = getattr(cancel, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    is_cancelled = getattr(cancel, "isCancelled", None)
    if callable(is_cancelled):
        return bool(is_cancelled())
    if callable(cancel):
        return bool(cancel())
    return False


def raise_in_thread(tid: int | None, exc: type[BaseException]) -> bool:
    """Ask CPython to raise `exc` in another thread. Returns False if it could not."""
    if tid is None:
        return False
    try:
        import ctypes
    except Exception:
        return False
    api = ctypes.pythonapi
    api.PyThreadState_SetAsyncExc.restype = ctypes.c_int
    for ctype in (ctypes.c_ulong, ctypes.c_long):
        try:
            api.PyThreadState_SetAsyncExc.argtypes = [ctype, ctypes.py_object]
            count = api.PyThreadState_SetAsyncExc(ctype(tid), exc)
        except Exception:
            continue
        if count == 1:
            return True
        if count > 1:
            api.PyThreadState_SetAsyncExc(ctype(tid), None)
            return False
    return False


def _cooperative_sleep(seconds: float) -> None:
    original = _original_sleep
    if original is None:
        time.sleep(seconds)  # pragma: no cover - patch installs the original first
        return
    cancel = getattr(_tls, "cancel", None)
    if cancel is None:
        original(seconds)
        return
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        original(seconds)
        return
    if total <= 0:
        original(0)
        return
    deadline = time.monotonic() + total
    while True:
        if _cancelled(cancel):
            raise KeyboardInterrupt("PyRunner stop")
        left = deadline - time.monotonic()
        if left <= 0:
            return
        original(0.05 if left > 0.05 else left)


def _ensure_sleep_patch() -> None:
    global _patched, _original_sleep
    with _patch_lock:
        if _patched:
            return
        _original_sleep = time.sleep
        time.sleep = _cooperative_sleep  # type: ignore[assignment]
        _patched = True


class _Dispatch(io.TextIOBase):
    def __init__(self, previous: Any, slot: str):
        self.previous = previous
        self.slot = slot

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if not s:
            return 0
        callback = getattr(_tls, self.slot, None)
        if callback is not None:
            callback(s)
            return len(s)
        previous = self.previous
        if previous is not None:
            return previous.write(s)
        return len(s)

    def flush(self) -> None:
        if getattr(_tls, self.slot, None) is not None:
            return
        previous = self.previous
        if previous is not None:
            previous.flush()


_stdio_lock = threading.Lock()
_stdio_depth = 0
_saved_stdout: Any = None
_saved_stderr: Any = None
_dispatch_out = _Dispatch(None, "stdout")
_dispatch_err = _Dispatch(None, "stderr")


def _enter_stdio() -> None:
    global _stdio_depth, _saved_stdout, _saved_stderr
    with _stdio_lock:
        if _stdio_depth == 0:
            _saved_stdout = sys.stdout
            _saved_stderr = sys.stderr
            _dispatch_out.previous = _saved_stdout
            _dispatch_err.previous = _saved_stderr
            sys.stdout = _dispatch_out
            sys.stderr = _dispatch_err
        _stdio_depth += 1


def _leave_stdio() -> None:
    global _stdio_depth
    with _stdio_lock:
        _stdio_depth = max(0, _stdio_depth - 1)
        if _stdio_depth == 0:
            if _saved_stdout is not None:
                sys.stdout = _saved_stdout
            if _saved_stderr is not None:
                sys.stderr = _saved_stderr


def _propagate_to_child_threads() -> None:
    """Copy the runner's stdout hooks onto threads the script starts."""
    if getattr(threading.Thread.start, "_pyrunner_wrapped", False):
        return
    original = threading.Thread.start

    def start(self: threading.Thread, *args: Any, **kwargs: Any) -> None:
        parent_out = getattr(_tls, "stdout", None)
        parent_err = getattr(_tls, "stderr", None)
        parent_cancel = getattr(_tls, "cancel", None)
        run = self.run

        def wrapped() -> None:
            if parent_out is not None:
                _tls.stdout = parent_out
            if parent_err is not None:
                _tls.stderr = parent_err
            if parent_cancel is not None:
                _tls.cancel = parent_cancel
            run()

        self.run = wrapped  # type: ignore[method-assign]
        original(self, *args, **kwargs)

    start._pyrunner_wrapped = True  # type: ignore[attr-defined]
    threading.Thread.start = start  # type: ignore[method-assign]


def execute_source(
    source: str,
    filename: str,
    workdir: str,
    on_stdout: Callable[[str], None],
    on_stderr: Callable[[str], None],
    cancel: Any = None,
    chdir: bool = False,
) -> dict[str, Any]:
    """Execute `source` as __main__.

    Returns {"exitCode": int, "error": str | None}. 0 is success, 130 is a
    stop request, anything else is a failure.
    """
    _ensure_sleep_patch()
    _propagate_to_child_threads()
    _tls.stdout = on_stdout
    _tls.stderr = on_stderr
    _tls.cancel = cancel
    tid = threading.get_ident()
    stop_watch = threading.Event()

    def watch() -> None:
        while not stop_watch.wait(0.05):
            if _cancelled(cancel):
                raise_in_thread(tid, KeyboardInterrupt)

    watcher = threading.Thread(target=watch, name="pyrunner-cancel", daemon=True)
    watcher.start()
    previous_cwd = os.getcwd() if chdir else None
    previous_argv = sys.argv
    _enter_stdio()
    inserted = False
    try:
        if chdir:
            os.chdir(workdir)
        if workdir and workdir not in sys.path:
            sys.path.insert(0, workdir)
            inserted = True
        sys.argv = [filename]
        code = compile(source, filename, "exec")
        globs: dict[str, Any] = {
            "__name__": "__main__",
            "__file__": filename,
            "__builtins__": __builtins__,
        }
        exec(code, globs, globs)
        return {"exitCode": 0, "error": None}
    except KeyboardInterrupt:
        try:
            on_stderr("\nKeyboardInterrupt: stopped\n")
        except Exception:
            pass
        return {"exitCode": 130, "error": "stopped"}
    except SystemExit as exc:
        status = exc.code
        if status is None or status == 0:
            return {"exitCode": 0, "error": None}
        if isinstance(status, int):
            return {"exitCode": status, "error": None if status == 0 else f"exit {status}"}
        try:
            on_stderr(str(status) + "\n")
        except Exception:
            pass
        return {"exitCode": 1, "error": str(status)}
    except Exception as exc:
        try:
            on_stderr(traceback.format_exc())
        except Exception:
            pass
        return {"exitCode": 1, "error": str(exc)}
    finally:
        _tls.cancel = None
        _tls.stdout = None
        _tls.stderr = None
        stop_watch.set()
        watcher.join(timeout=1)
        sys.argv = previous_argv
        if inserted:
            try:
                sys.path.remove(workdir)
            except ValueError:
                pass
        if previous_cwd is not None:
            try:
                os.chdir(previous_cwd)
            except OSError:
                pass
        _leave_stdio()


def execute_source_json(
    source: str,
    filename: str,
    workdir: str,
    on_stdout: Any,
    on_stderr: Any,
    cancel: Any = None,
    chdir: bool = False,
) -> str:
    """Same as execute_source, but callbacks are objects with a write() method.

    Chaquopy calls this from Kotlin. Returning JSON avoids converting a dict
    across the Java bridge.
    """

    def stdout(text: str) -> None:
        if on_stdout is not None:
            on_stdout.write(text)

    def stderr(text: str) -> None:
        if on_stderr is not None:
            on_stderr.write(text)

    result = execute_source(
        source=source,
        filename=filename,
        workdir=workdir,
        on_stdout=stdout,
        on_stderr=stderr,
        cancel=cancel,
        chdir=bool(chdir),
    )
    return json.dumps(result)
