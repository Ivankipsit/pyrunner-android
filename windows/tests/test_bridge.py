import json
import urllib.error
import urllib.request
from pathlib import Path

from pyrunner_host.bridge import AgentBridge
from pyrunner_host.supervisor import Supervisor


def _request(bridge: AgentBridge, method: str, path: str, payload: dict | None = None, token: str | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{bridge.public()['port']}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (bridge.token if token is None else token),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_local_agent_must_be_approved_before_a_run(tmp_path: Path):
    supervisor = Supervisor(tmp_path / "runs", max_slots=2)
    bridge = AgentBridge(tmp_path, supervisor)
    try:
        info = bridge.start()
        assert info["host"] == "127.0.0.1"
        assert info["port"] > 0
        saved = json.loads((tmp_path / "agent-bridge.json").read_text(encoding="utf-8"))
        assert saved["host"] == "127.0.0.1"
        assert saved["token"] == bridge.token

        status, body = _request(bridge, "GET", "/v1/script", token="nope")
        assert status == 401

        bridge.sync("draft.py", "print('draft', flush=True)\n")
        status, body = _request(bridge, "GET", "/v1/script")
        assert body["source"].startswith("print('draft'")

        status, proposed = _request(bridge, "POST", "/v1/propose", {
            "name": "scrape.py",
            "source": "print('go', flush=True)\n",
        })
        assert status == 200
        assert proposed["status"] == "pending"
        status, denied = _request(bridge, "POST", "/v1/run", {"proposalId": proposed["id"]})
        assert status == 403

        approved = bridge.resolve(proposed["id"], True)
        assert approved["status"] == "approved"
        status, started = _request(bridge, "POST", "/v1/run", {"proposalId": proposed["id"]})
        assert status == 200
        assert started["name"] == "scrape.py"
        assert started["status"] in {"queued", "running", "finished"}
    finally:
        bridge.stop()
        supervisor.shutdown()
        assert not (tmp_path / "agent-bridge.json").exists()


def test_phone_layout_keeps_names_and_hides_desktop_models():
    ui = Path(__file__).resolve().parents[2] / "ui"
    css = (ui / "css" / "app.css").read_text(encoding="utf-8")
    script = (ui / "js" / "app.js").read_text(encoding="utf-8")
    assert ".lib-row {\n  flex-direction: column;" in css
    assert "white-space: normal" in css
    assert '!android || model.id === "builtin"' in script
    assert "agent-bridge.json" in script
    assert "Nothing runs until you approve" in script
