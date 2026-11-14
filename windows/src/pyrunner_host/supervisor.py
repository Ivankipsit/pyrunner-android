"""Run scripts as real subprocesses so one can be killed without the others."""

from __future__ import annotations

import codecs
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

WINDOWS_SITE = """\
import signal
import sys

if sys.platform == "win32":
    signal.signal(signal.SIGBREAK, signal.default_int_handler)
"""


def _now() -> int:
    return int(time.time() * 1000)


@dataclass
class ManagedRun:
    id: str
    name: str
    script_id: str | None
    status: str
    created_at: int
    work_dir: Path
    script_path: Path
    log_path: Path
    started_at: int | None = None
    finished_at: int | None = None
    exit_code: int | None = None
    error: str | None = None
    origin_dir: str | None = None
    seq: int = 0
    process: subprocess.Popen | None = None
    readers: list[threading.Thread] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scriptId": self.script_id,
            "status": self.status,
            "exitCode": self.exit_code,
            "error": self.error,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


class Supervisor:
    def __init__(
        self,
        root: Path,
        python: str | None = None,
        max_slots: int = 8,
        on_event: Callable[[dict], None] | None = None,
        run_timeout_sec: int = 12 * 3600,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.python = python or sys.executable
        self.max_slots = max_slots
        self.on_event = on_event or (lambda _event: None)
        self.run_timeout_sec = run_timeout_sec
        self._lock = threading.Lock()
        self._runs: dict[str, ManagedRun] = {}
        self._closed = False
        self._events: queue.Queue = queue.Queue()
        self._emitter = threading.Thread(target=self._emit_loop, name="pyrunner-events", daemon=True)
        self._emitter.start()
        self._timer = threading.Thread(target=self._timeout_loop, name="pyrunner-timeout", daemon=True)
        self._timer.start()

    def start(
        self,
        name: str,
        source: str,
        script_id: str | None = None,
        origin_dir: str | None = None,
    ) -> dict:
        if not isinstance(source, str):
            raise ValueError("source is required")
        if len(source) > 2_000_000:
            raise ValueError("Script is larger than 2 MB")
        from pyrunner_host.library import normalize_name

        safe = normalize_name(name)
        run_id = uuid.uuid4().hex[:12]
        run_dir = self.root / "runs" / run_id
        work = run_dir / "work"
        work.mkdir(parents=True)
        script_path = work / "main.py"
        script_path.write_text(source, encoding="utf-8")
        (run_dir / "log.txt").write_text("", encoding="utf-8")
        if os.name == "nt":
            (work / "sitecustomize.py").write_text(WINDOWS_SITE, encoding="utf-8")
        run = ManagedRun(
            id=run_id,
            name=safe,
            script_id=script_id,
            status="queued",
            created_at=_now(),
            work_dir=work,
            script_path=script_path,
            log_path=run_dir / "log.txt",
            origin_dir=origin_dir if _is_dir(origin_dir) else None,
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("host is shutting down")
            self._runs[run_id] = run
            self._emit_status(run)
            self._pump_locked()
        return self._public(run_id)

    def stop(self, run_id: str) -> dict:
        with self._lock:
            run = self._get(run_id)
            if run.status == "queued":
                self._finish_locked(run, "stopped", 130, None)
                self._pump_locked()
                return run.public()
            if run.status != "running":
                return run.public()
            run.status = "stopping"
            run.error = None
            self._emit_status(run)
            proc = run.process
        if proc is not None and proc.poll() is None:
            _signal_stop(proc)
        threading.Thread(target=self._confirm_stop, args=(run_id,), daemon=True).start()
        return self._public(run_id)

    def kill(self, run_id: str) -> dict:
        with self._lock:
            run = self._get(run_id)
            if run.status in ("finished", "failed", "stopped", "killed"):
                return run.public()
            proc = run.process
            self._finish_locked(run, "killed", None, run.error)
            self._pump_locked()
        if proc is not None and proc.poll() is None:
            _kill_process(proc)
        return self._public(run_id)

    def list_runs(self) -> list[dict]:
        with self._lock:
            runs = [run.public() for run in self._runs.values()]
        runs.sort(key=lambda item: item["createdAt"], reverse=True)
        return runs

    def read_log(self, run_id: str, max_chars: int = 200_000) -> dict:
        with self._lock:
            run = self._get(run_id)
            text = run.log_path.read_text(encoding="utf-8") if run.log_path.exists() else ""
            next_seq = run.seq
        truncated = len(text) > max_chars
        if truncated:
            text = text[-max_chars:]
        return {"text": text, "nextSeq": next_seq, "truncated": truncated}

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            ids = [run.id for run in self._runs.values() if run.status in ("running", "stopping", "queued")]
        for run_id in ids:
            try:
                self.kill(run_id)
            except Exception:
                pass

    def isolation_probe(self) -> dict:
        """Prove one script can be killed while a second script keeps running.

        Script A catches KeyboardInterrupt, so a cooperative stop cannot end it.
        """
        script_a = (
            "import time\n"
            "print('TOKEN_A1', flush=True)\n"
            "while True:\n"
            "    try:\n"
            "        time.sleep(0.4)\n"
            "    except KeyboardInterrupt:\n"
            "        pass\n"
        )
        script_b = (
            "import time\n"
            "print('TOKEN_B1', flush=True)\n"
            "time.sleep(2.0)\n"
            "print('TOKEN_B2', flush=True)\n"
        )
        first = self.start("probe_a.py", script_a)
        second = self.start("probe_b.py", script_b)
        saw_a = _wait_log(self, first["id"], "TOKEN_A1", 20)
        saw_b = _wait_log(self, second["id"], "TOKEN_B1", 20)
        self.kill(first["id"])
        saw_b2 = _wait_log(self, second["id"], "TOKEN_B2", 20)
        status_a = _wait_status(self, first["id"], {"killed"}, 10)
        self.kill(second["id"])
        ok = bool(saw_a and saw_b and saw_b2 and status_a == "killed")
        return {
            "ok": ok,
            "mode": "subprocess",
            "detail": f"A1={saw_a} B1={saw_b} B2={saw_b2} Astatus={status_a}",
        }

    def _confirm_stop(self, run_id: str) -> None:
        time.sleep(1.5)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.status != "stopping":
                return
            proc = run.process
            if proc is not None and proc.poll() is None:
                run.status = "running"
                run.error = "Script caught the stop request and kept running"
                self._emit_status(run)

    def _timeout_loop(self) -> None:
        while not self._closed:
            time.sleep(30)
            if self._closed:
                return
            self._enforce_timeouts()

    def _enforce_timeouts(self) -> None:
        now = _now()
        limit = self.run_timeout_sec * 1000
        victims: list[str] = []
        with self._lock:
            for run in self._runs.values():
                if run.status == "running" and run.started_at and now - run.started_at > limit:
                    victims.append(run.id)
        for run_id in victims:
            try:
                self.kill(run_id)
            except Exception:
                pass

    def _pump_locked(self) -> None:
        if self._closed:
            return
        for run in list(self._runs.values()):
            if run.status != "queued":
                continue
            if self._running_count() >= self.max_slots:
                return
            self._launch_locked(run)

    def _running_count(self) -> int:
        return sum(1 for run in self._runs.values() if run.status in ("running", "stopping"))

    def _launch_locked(self, run: ManagedRun) -> None:
        origin_dir = run.origin_dir
        cwd = origin_dir if _is_dir(origin_dir) else str(run.work_dir)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYRUNNER_WORKDIR"] = cwd
        parts: list[str] = []
        if os.name == "nt":
            parts.append(str(run.work_dir))
        if _is_dir(origin_dir):
            parts.append(origin_dir or "")
        existing = env.get("PYTHONPATH")
        if existing:
            parts.append(existing)
        if parts:
            env["PYTHONPATH"] = os.pathsep.join(parts)
        command = [self.python, "-u", str(run.script_path)]
        kwargs: dict = {
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        run.process = subprocess.Popen(command, **kwargs)
        run.status = "running"
        run.started_at = _now()
        self._emit_status(run)
        waiter = threading.Thread(target=self._wait, args=(run,), name=f"run-{run.id}", daemon=True)
        waiter.start()

    def _wait(self, run: ManagedRun) -> None:
        proc = run.process
        if proc is None:
            return
        pumps = [
            threading.Thread(target=self._pump_pipe, args=(run, proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=self._pump_pipe, args=(run, proc.stderr, "stderr"), daemon=True),
        ]
        for thread in pumps:
            thread.start()
        code = proc.wait()
        for thread in pumps:
            thread.join(timeout=5)
        with self._lock:
            if run.status == "killed":
                run.exit_code = code
                self._emit_status(run)
            elif run.status == "stopping":
                self._finish_locked(run, "stopped", code, None)
            elif code == 0:
                self._finish_locked(run, "finished", 0, None)
            elif code < 0 or code == 130:
                self._finish_locked(run, "killed", code, run.error)
            else:
                self._finish_locked(run, "failed", code, run.error or f"exit {code}")
            run.process = None
            self._pump_locked()

    def _pump_pipe(self, run: ManagedRun, pipe, stream: str) -> None:
        if pipe is None:
            return
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                # read() blocks until the buffer is full. read1 returns the first chunk.
                chunk = pipe.read1(4096)
                if not chunk:
                    tail = decoder.decode(b"", final=True)
                    if tail:
                        self._append(run, stream, tail)
                    break
                text = decoder.decode(chunk)
                if text:
                    self._append(run, stream, text)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _append(self, run: ManagedRun, stream: str, text: str) -> None:
        with self._lock:
            with run.log_path.open("a", encoding="utf-8") as handle:
                handle.write(text)
            seq = run.seq
            run.seq += 1
        self._emit(
            {
                "event": "output",
                "runId": run.id,
                "stream": stream,
                "seq": seq,
                "text": text,
            }
        )

    def _finish_locked(self, run: ManagedRun, status: str, code: int | None, error: str | None) -> None:
        run.status = status
        run.exit_code = code
        run.error = error
        run.finished_at = _now()
        self._emit_status(run)

    def _emit_status(self, run: ManagedRun) -> None:
        self._emit({"event": "status", "run": run.public()})

    def _emit(self, event: dict) -> None:
        self._events.put(event)

    def _emit_loop(self) -> None:
        while True:
            event = self._events.get()
            try:
                self.on_event(event)
            except Exception:
                pass

    def _get(self, run_id: str) -> ManagedRun:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _public(self, run_id: str) -> dict:
        with self._lock:
            return self._get(run_id).public()


def _is_dir(path: str | None) -> bool:
    return bool(path) and os.path.isdir(path)


def _signal_stop(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGINT)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _wait_log(supervisor: Supervisor, run_id: str, token: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if token in supervisor.read_log(run_id)["text"]:
            return True
        time.sleep(0.05)
    return False


def _wait_status(supervisor: Supervisor, run_id: str, wanted: set[str], timeout: float) -> str:
    deadline = time.time() + timeout
    status = ""
    while time.time() < deadline:
        for run in supervisor.list_runs():
            if run["id"] == run_id:
                status = run["status"]
                break
        if status in wanted:
            return status
        time.sleep(0.05)
    return status


def loads_public(run: dict) -> str:
    return json.dumps(run)
