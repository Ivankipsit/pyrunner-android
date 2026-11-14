"""Loopback API so a coding agent on this PC can propose a script.

The server listens on 127.0.0.1 only. A run starts only after the person
approves that proposal in the PyRunner window.
"""

from __future__ import annotations

import json
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from pyrunner_host.library import normalize_name
from pyrunner_host.supervisor import Supervisor

MAX_BODY = 2_000_000


class AgentBridge:
    def __init__(self, root: Path, supervisor: Supervisor, on_event: Callable[[dict], None] | None = None):
        self.root = Path(root)
        self.supervisor = supervisor
        self.on_event = on_event or (lambda _event: None)
        self.token = secrets.token_urlsafe(24)
        self.script = {"name": "untitled.py", "source": ""}
        self._lock = threading.Lock()
        self._proposals: dict[str, dict] = {}
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.info_path = self.root / "agent-bridge.json"

    def start(self) -> dict:
        if self._httpd is not None:
            return self.public()
        handler = _handler_factory(self)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        if server.server_address[0] != "127.0.0.1":
            server.server_close()
            raise RuntimeError("The agent bridge must stay on 127.0.0.1")
        self._httpd = server
        self._thread = threading.Thread(target=server.serve_forever, name="pyrunner-bridge", daemon=True)
        self._thread.start()
        self.root.mkdir(parents=True, exist_ok=True)
        self.info_path.write_text(
            json.dumps({"host": "127.0.0.1", "port": server.server_address[1], "token": self.token}),
            encoding="utf-8",
        )
        return self.public()

    def stop(self) -> None:
        server = self._httpd
        self._httpd = None
        if server is not None:
            server.shutdown()
            server.server_close()
        try:
            self.info_path.unlink()
        except OSError:
            return

    def public(self) -> dict:
        port = self._httpd.server_address[1] if self._httpd is not None else 0
        return {"enabled": self._httpd is not None, "host": "127.0.0.1", "port": port}

    def sync(self, name: str, source: str) -> dict:
        if len(source) > MAX_BODY:
            raise ValueError("Script is larger than 2 MB")
        with self._lock:
            self.script = {"name": normalize_name(name or "untitled.py"), "source": source}
            return dict(self.script)

    def current(self) -> dict:
        with self._lock:
            return dict(self.script)

    def propose(self, name: str, source: str) -> dict:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source is required")
        if len(source) > MAX_BODY:
            raise ValueError("Script is larger than 2 MB")
        proposal = {
            "id": uuid.uuid4().hex[:12],
            "name": normalize_name(name or "untitled.py"),
            "source": source,
            "status": "pending",
        }
        with self._lock:
            self._proposals[proposal["id"]] = proposal
        self.on_event({"event": "proposal", "proposal": {"id": proposal["id"], "name": proposal["name"], "source": source}})
        return {"id": proposal["id"], "name": proposal["name"], "status": "pending"}

    def proposal(self, proposal_id: str) -> dict:
        with self._lock:
            found = self._proposals.get(proposal_id)
            if found is None:
                raise KeyError(proposal_id)
            return {"id": found["id"], "name": found["name"], "status": found["status"]}

    def resolve(self, proposal_id: str, approved: bool) -> dict:
        with self._lock:
            found = self._proposals.get(proposal_id)
            if found is None:
                raise KeyError(proposal_id)
            found["status"] = "approved" if approved else "rejected"
            if approved:
                self.script = {"name": found["name"], "source": found["source"]}
            return {"id": found["id"], "name": found["name"], "status": found["status"]}

    def run_approved(self, proposal_id: str) -> dict:
        with self._lock:
            found = self._proposals.get(proposal_id)
            if found is None or found["status"] != "approved":
                raise PermissionError("Approve the script in PyRunner before it can run")
            name = found["name"]
            source = found["source"]
        return self.supervisor.start(name, source)


def _handler_factory(bridge: AgentBridge):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not self._allowed():
                return
            if self.path == "/v1/script":
                self._send(200, bridge.current())
                return
            if self.path.startswith("/v1/proposal/"):
                proposal_id = self.path.rsplit("/", 1)[-1]
                try:
                    self._send(200, bridge.proposal(proposal_id))
                except KeyError:
                    self._send(404, {"error": "Unknown proposal"})
                return
            self._send(404, {"error": "Unknown path"})

        def do_POST(self):
            if not self._allowed():
                return
            try:
                body = self._json()
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                if self.path == "/v1/propose":
                    self._send(200, bridge.propose(str(body.get("name") or ""), str(body.get("source") or "")))
                    return
                if self.path == "/v1/run":
                    self._send(200, bridge.run_approved(str(body.get("proposalId") or "")))
                    return
            except PermissionError as exc:
                self._send(403, {"error": str(exc)})
                return
            except (KeyError, ValueError) as exc:
                self._send(400, {"error": str(exc)})
                return
            self._send(404, {"error": "Unknown path"})

        def _allowed(self) -> bool:
            header = self.headers.get("Authorization") or ""
            token = header[7:] if header.startswith("Bearer ") else ""
            if len(token) != len(bridge.token) or not secrets.compare_digest(token, bridge.token):
                self._send(401, {"error": "Unauthorized"})
                return False
            return True

        def _json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY + 10_000:
                raise ValueError("Body is too large")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Body must be an object")
            return payload

        def _send(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler
