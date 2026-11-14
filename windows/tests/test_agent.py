import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from pyrunner_host.agent import AgentClient


def test_guide_finds_packages_and_explains_scraping():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = Path(__file__).resolve().parents[2] / "ui" / "js" / "guide.js"
    program = r"""
const fs = require("fs");
eval(fs.readFileSync(process.argv[1], "utf8"));
const guide = globalThis.PyRunnerGuide;
const pkgs = guide.scriptPackages("import os\nimport requests\nfrom bs4 import BeautifulSoup\n");
if (JSON.stringify(pkgs) !== JSON.stringify(["requests", "beautifulsoup4"])) {
  console.error(JSON.stringify(pkgs));
  process.exit(1);
}
const reply = guide.builtinReply("how do I scrape links on a page?");
if (!reply.text.includes("127.0.0.1") || !reply.code.includes("requests.get")) {
  console.error(reply.text);
  process.exit(1);
}
"""
    result = subprocess.run([node, "-e", program, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout


def test_models_stay_on_localhost_and_can_be_switched(tmp_path: Path):
    installed: set[str] = set()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            self._send({"models": [{"name": name} for name in sorted(installed)]})

        def do_POST(self):
            body = self._body()
            if self.path == "/api/pull":
                installed.add(body["name"])
                self._send({"status": "success"})
            elif self.path == "/api/chat":
                self._send({"message": {"content": "print('ok')\n"}})
            else:
                self._send({})

        def do_DELETE(self):
            body = self._body()
            installed.discard(body.get("name"))
            self._send({})

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with pytest.raises(ValueError):
            AgentClient(tmp_path, "http://example.com:11434")
        client = AgentClient(tmp_path, f"http://127.0.0.1:{port}")
        assert client.status()["ollama"] is True
        assert client.status()["selected"] == "builtin"
        with pytest.raises(ValueError):
            client.pull("other:latest")
        client.pull("qwen2.5-coder:7b")
        status = {}
        deadline = time.time() + 5
        while time.time() < deadline:
            status = client.status()
            if "qwen2.5-coder:7b" in status["installed"]:
                break
            time.sleep(0.05)
        assert "qwen2.5-coder:7b" in status["installed"]
        assert status["selected"] == "qwen2.5-coder:7b"
        answer = client.ask("qwen2.5-coder:7b", "print hello", "print(1)\n")
        assert "print" in answer["text"]
        client.delete("qwen2.5-coder:7b")
        after = client.status()
        assert "qwen2.5-coder:7b" not in after["installed"]
        assert after["selected"] == "builtin"
    finally:
        server.shutdown()
