import json
from pathlib import Path

from pyrunner_host.api import METHODS, HostApi
from pyrunner_host.library import ScriptLibrary
from pyrunner_host.packages import validate_spec
from pyrunner_host.supervisor import Supervisor
import pytest


def _api(tmp_path: Path, opener=None) -> tuple[HostApi, Supervisor]:
    supervisor = Supervisor(tmp_path / "runs", max_slots=2)
    library = ScriptLibrary(tmp_path / "library")
    api = HostApi(
        library=library,
        supervisor=supervisor,
        open_file=opener or (lambda: None),
        platform_name="linux",
    )
    return api, supervisor


def test_capabilities_shape(tmp_path: Path):
    api, supervisor = _api(tmp_path)
    try:
        result = json.loads(api.invoke(json.dumps({"method": "capabilities"})))
        assert result["ok"] is True
        features = result["result"]["features"]
        assert features["hardKill"] is True
        assert features["pipRuntime"] is True
        assert features["foregroundService"] is False
        assert features["localAgent"] is False
        assert features["playwright"] in (True, False)
        for method in METHODS:
            assert isinstance(method, str)
    finally:
        supervisor.shutdown()


def test_save_and_open(tmp_path: Path):
    picked = {"name": "from_disk.py", "content": "print('disk')\n", "originDir": str(tmp_path)}

    def opener():
        return picked

    api, supervisor = _api(tmp_path, opener)
    try:
        saved = json.loads(api.invoke(json.dumps({
            "method": "saveScript",
            "params": {"name": "a", "source": "print(1)\n"},
        })))
        assert saved["ok"] is True
        listed = json.loads(api.invoke(json.dumps({"method": "listScripts"})))
        assert listed["result"][0]["name"] == "a.py"
        opened = json.loads(api.invoke(json.dumps({"method": "openFile"})))
        assert opened["result"]["content"] == "print('disk')\n"
        cancelled = HostApi(api.library, supervisor, lambda: None, "linux")
        empty = json.loads(cancelled.invoke(json.dumps({"method": "openFile"})))
        assert empty["result"]["cancelled"] is True
    finally:
        supervisor.shutdown()


def test_unknown_method_and_bad_pip_spec(tmp_path: Path):
    api, supervisor = _api(tmp_path)
    try:
        bad = json.loads(api.invoke(json.dumps({"method": "nope"})))
        assert bad["ok"] is False
        with pytest.raises(ValueError):
            validate_spec("git+https://example.com/pkg.git")
        with pytest.raises(ValueError):
            validate_spec("requests; rm -rf /")
        with pytest.raises(ValueError):
            validate_spec("../evil")
        assert validate_spec("requests==2.32.3") == "requests==2.32.3"
        assert validate_spec("package[extra]>=1") == "package[extra]>=1"
    finally:
        supervisor.shutdown()


def test_ui_has_no_remote_urls():
    ui = Path(__file__).resolve().parents[2] / "ui"
    for relative in ("index.html", "js/app.js", "js/live.js", "css/app.css"):
        text = (ui / relative).read_text(encoding="utf-8").lower()
        assert "http://" not in text
        assert "https://" not in text
        assert "xmlhttprequest" not in text
        import re
        assert re.search(r"(?<![a-z])fetch\s*\(", text) is None
