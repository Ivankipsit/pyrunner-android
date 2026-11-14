"""JSON API shared with the Android host. The UI calls one invoke() method."""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pyrunner_host import __version__
from pyrunner_host.library import ScriptLibrary
from pyrunner_host.packages import curated_packages, module_available, pip_install
from pyrunner_host.supervisor import Supervisor

METHODS = (
    "capabilities",
    "run",
    "stop",
    "kill",
    "listRuns",
    "readLog",
    "listArtifacts",
    "readArtifact",
    "listScripts",
    "getScript",
    "saveScript",
    "renameScript",
    "deleteScript",
    "openFile",
    "pipInstall",
    "concurrencyProbe",
    "setRunnerMode",
    "requestBatteryExemption",
    "agentStatus",
    "agentSelect",
    "agentPull",
    "agentDelete",
    "agentAsk",
    "agentBridgeInfo",
    "agentSync",
    "agentResolve",
    "importFiles",
    "listFiles",
    "exportFiles",
    "adoptFiles",
)


class HostApi:
    def __init__(
        self,
        library: ScriptLibrary,
        supervisor: Supervisor,
        open_file: Callable[[], dict | None],
        platform_name: str,
        distribution: str = "portable",
        bridge=None,
        pick_imports: Callable[[], list[str]] | None = None,
        pick_folder: Callable[[], str | None] | None = None,
    ):
        self.library = library
        self.supervisor = supervisor
        self.open_file = open_file
        self.platform_name = platform_name
        self.distribution = distribution
        self._probe_lock = threading.Lock()
        self._probe_running = False
        self._agent = None
        self.bridge = bridge
        self.pick_imports = pick_imports or (lambda: [])
        self.pick_folder = pick_folder or (lambda: None)

    def invoke(self, request_json: str) -> str:
        try:
            request = json.loads(request_json)
            method = request.get("method")
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            result = self.dispatch(method, params)
            return json.dumps({"ok": True, "result": result})
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

    def dispatch(self, method: str, params: dict) -> Any:
        if method == "capabilities":
            return self.capabilities()
        if method == "run":
            return self.supervisor.start(
                name=str(params.get("name") or "untitled.py"),
                source=_required_str(params, "source"),
                script_id=params.get("scriptId") or None,
                origin_dir=params.get("originDir") or None,
            )
        if method == "stop":
            return self.supervisor.stop(_required_str(params, "runId"))
        if method == "kill":
            return self.supervisor.kill(_required_str(params, "runId"))
        if method == "listRuns":
            return self.supervisor.list_runs()
        if method == "readLog":
            max_chars = params.get("maxChars") or 200_000
            return self.supervisor.read_log(_required_str(params, "runId"), int(max_chars))
        if method == "listArtifacts":
            return self.supervisor.list_artifacts(_required_str(params, "runId"))
        if method == "readArtifact":
            return self.supervisor.read_artifact(_required_str(params, "runId"), _required_str(params, "name"))
        if method == "listScripts":
            return self.library.list_scripts()
        if method == "getScript":
            return self.library.get(_required_str(params, "id"))
        if method == "saveScript":
            return self.library.save(params.get("id") or None, str(params.get("name") or ""), _required_str(params, "source"))
        if method == "renameScript":
            return self.library.rename(_required_str(params, "id"), str(params.get("name") or ""))
        if method == "deleteScript":
            self.library.delete(_required_str(params, "id"))
            return {"deleted": True}
        if method == "openFile":
            picked = self.open_file()
            if not picked:
                return {"cancelled": True}
            return {"cancelled": False, **picked}
        if method == "pipInstall":
            return pip_install(str(params.get("spec") or ""))
        if method == "concurrencyProbe":
            return self._start_probe()
        if method == "setRunnerMode":
            raise RuntimeError("Runner mode is fixed on this platform")
        if method == "requestBatteryExemption":
            raise RuntimeError("Battery exemption is an Android setting")
        if method == "agentStatus":
            return self.agent().status()
        if method == "agentSelect":
            return self.agent().select(str(params.get("id") or "builtin"))
        if method == "agentPull":
            return self.agent().pull(str(params.get("id") or ""))
        if method == "agentDelete":
            return self.agent().delete(str(params.get("id") or ""))
        if method == "agentAsk":
            return self.agent().ask(
                str(params.get("id") or ""),
                str(params.get("prompt") or ""),
                str(params.get("script") or ""),
            )
        if method == "agentBridgeInfo":
            if self.bridge is None:
                return {"enabled": False}
            return self.bridge.public()
        if method == "agentSync":
            if self.bridge is None:
                return {"enabled": False}
            return self.bridge.sync(str(params.get("name") or ""), str(params.get("source") or ""))
        if method == "agentResolve":
            if self.bridge is None:
                raise RuntimeError("A local coding agent connects on Windows only")
            return self.bridge.resolve(_required_str(params, "id"), bool(params.get("approved")))
        if method == "importFiles":
            return self._import_files(params.get("scriptId"))
        if method == "listFiles":
            return self._list_files(params.get("scriptId"))
        if method == "exportFiles":
            return self._export_files(params)
        if method == "adoptFiles":
            from pyrunner_host.filesbox import adopt

            names = adopt(self.supervisor.root, _required_str(params, "scriptId"))
            return {"names": names}
        raise ValueError(f"Unknown method: {method}")

    def capabilities(self) -> dict:
        python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        playwright = module_available("playwright")
        selenium = module_available("selenium")
        notes = [
            "Scripts run as separate processes. Stop sends an interrupt; Kill ends the process.",
            "Closing the window stops scripts that are still running.",
            "pip install is explicit and only accepts a PyPI name, not a URL.",
        ]
        if not playwright:
            notes.append("Playwright is not installed in this environment.")
        if playwright:
            notes.append("Playwright's browser binaries are not downloaded by the app. Install them yourself if a script needs them.")
        return {
            "appVersion": __version__,
            "platform": self.platform_name,
            "python": python,
            "distribution": self.distribution,
            "concurrencyMode": "subprocess",
            "runnerSlots": self.supervisor.max_slots,
            "features": {
                "liveOutput": True,
                "concurrentRuns": True,
                "hardKill": True,
                "cooperativeStop": True,
                "scriptLibrary": True,
                "filePicker": True,
                "foregroundService": False,
                "pipRuntime": not getattr(sys, "frozen", False),
                "multiprocessing": True,
                "playwright": playwright,
                "selenium": selenium,
                "localAgent": True,
                "webviewRender": False,
            },
            "packages": curated_packages(),
            "limits": {"runTimeoutSec": self.supervisor.run_timeout_sec},
            "notes": notes,
        }

    def _start_probe(self) -> dict:
        with self._probe_lock:
            if self._probe_running:
                return {"started": False, "detail": "A probe is already running"}
            self._probe_running = True

        def work() -> None:
            try:
                result = self.supervisor.isolation_probe()
                self.supervisor.on_event({"event": "probe", **result})
            except Exception as exc:
                self.supervisor.on_event(
                    {
                        "event": "probe",
                        "ok": False,
                        "mode": "subprocess",
                        "detail": str(exc),
                    }
                )
            finally:
                with self._probe_lock:
                    self._probe_running = False

        threading.Thread(target=work, name="pyrunner-probe", daemon=True).start()
        return {"started": True}

    def _import_files(self, script_id: str | None) -> dict:
        from pyrunner_host.filesbox import inbox_dir, store_file

        chosen = self.pick_imports() or []
        if not chosen:
            return {"cancelled": True, "names": []}
        folder = inbox_dir(self.supervisor.root, script_id if isinstance(script_id, str) else None)
        names = []
        for item in chosen:
            path = Path(item)
            names.append(store_file(folder, path.name, path.read_bytes()))
        return {"cancelled": False, "names": names}

    def _list_files(self, script_id: str | None) -> dict:
        from pyrunner_host.filesbox import inbox_dir, list_files

        folder = inbox_dir(self.supervisor.root, script_id if isinstance(script_id, str) else None)
        return {"names": list_files(folder)}

    def _export_files(self, params: dict) -> dict:
        from pyrunner_host.filesbox import export_to

        folder_text = self.pick_folder()
        if not folder_text:
            return {"cancelled": True, "names": []}
        extras: list[Path] = []
        run_id = params.get("runId")
        if isinstance(run_id, str) and run_id:
            try:
                work = self.supervisor.work_dir(run_id)
            except KeyError:
                work = None
            if work is not None and work.is_dir():
                extras = [path for path in work.iterdir() if path.is_file()]
        content = str(params.get("content") or "").encode("utf-8")
        names = export_to(Path(folder_text), str(params.get("name") or "notes.txt"), content, extras)
        return {"cancelled": False, "folder": folder_text, "names": names}

    def agent(self):
        if self._agent is None:
            from pyrunner_host.agent import AgentClient

            self._agent = AgentClient(self.supervisor.root)
        return self._agent


def desktop_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _required_str(params: dict, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value
