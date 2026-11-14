"""Local coding models through Ollama on 127.0.0.1 only.

The built-in helper does not use this module. Download, delete, and ask
go to Ollama on this machine. The host address is fixed.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG = (
    "qwen2.5-coder:3b",
    "qwen2.5-coder:7b",
    "qwen2.5-coder:14b",
)


class AgentClient:
    def __init__(self, root: Path, base_url: str = "http://127.0.0.1:11434"):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.hostname != "127.0.0.1":
            raise ValueError("Models stay on 127.0.0.1")
        self.base_url = base_url.rstrip("/")
        self.path = Path(root) / "agent.json"
        self._lock = threading.Lock()
        self._pull: dict | None = None

    def status(self) -> dict:
        installed, online = self._installed()
        with self._lock:
            selected = self._selected()
            pulling = dict(self._pull) if self._pull else None
        if selected != "builtin" and selected not in installed and not (pulling and pulling.get("id") == selected):
            selected = "builtin"
        return {
            "ollama": online,
            "selected": selected,
            "installed": installed,
            "pulling": pulling,
        }

    def select(self, model_id: str) -> dict:
        model_id = _known(model_id)
        with self._lock:
            self._write(model_id)
        return self.status()

    def pull(self, model_id: str) -> dict:
        model_id = _known(model_id)
        if model_id == "builtin":
            raise ValueError("The built-in helper is already on this device")
        with self._lock:
            if self._pull and self._pull.get("status") == "running":
                return self.status()
            self._pull = {"id": model_id, "status": "running", "error": ""}
            self._write(model_id)

        def work() -> None:
            try:
                self._request("POST", "/api/pull", {"name": model_id, "stream": False}, timeout=3600)
                with self._lock:
                    self._pull = {"id": model_id, "status": "done", "error": ""}
            except Exception as exc:
                with self._lock:
                    self._pull = {"id": model_id, "status": "failed", "error": str(exc)}

        threading.Thread(target=work, name="pyrunner-model", daemon=True).start()
        return self.status()

    def delete(self, model_id: str) -> dict:
        model_id = _known(model_id)
        if model_id == "builtin":
            raise ValueError("The built-in helper stays on this device")
        self._request("DELETE", "/api/delete", {"name": model_id}, timeout=60)
        with self._lock:
            if self._selected() == model_id:
                self._write("builtin")
        return self.status()

    def ask(self, model_id: str, prompt: str, script: str) -> dict:
        model_id = _known(model_id)
        if model_id == "builtin":
            raise ValueError("The built-in helper answers in the app")
        if not prompt.strip():
            raise ValueError("Ask a question first")
        result = self._request(
            "POST",
            "/api/chat",
            {
                "model": model_id,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You help write Python scripts for a local runner. "
                            "Reply with a short explanation and one python code block when code helps. "
                            "Do not tell the user to call a cloud model."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt.strip() + "\n\nCurrent script:\n" + (script or "")[:8000],
                    },
                ],
            },
            timeout=180,
        )
        message = result.get("message") or {}
        return {"text": str(message.get("content") or "")}

    def _installed(self) -> tuple[list[str], bool]:
        try:
            payload = self._request("GET", "/api/tags", None, timeout=0.6)
        except Exception:
            return [], False
        names = []
        for row in payload.get("models") or []:
            name = str(row.get("name") or "")
            if name in CATALOG:
                names.append(name)
        return names, True

    def _request(self, method: str, path: str, payload: dict | None, timeout: float) -> dict:
        url = self.base_url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail.strip() or f"Ollama returned {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Ollama is not running at 127.0.0.1:11434") from exc
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _selected(self) -> str:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            model_id = str(saved.get("selected") or "builtin")
        except Exception:
            return "builtin"
        if model_id != "builtin" and model_id not in CATALOG:
            return "builtin"
        return model_id

    def _write(self, model_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"selected": model_id}), encoding="utf-8")


def _known(model_id: str) -> str:
    model_id = (model_id or "builtin").strip()
    if model_id != "builtin" and model_id not in CATALOG:
        raise ValueError("Choose a model from the list")
    return model_id
