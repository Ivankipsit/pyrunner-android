import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from pyrunner_host.artifacts import list_new, read, snapshot
from pyrunner_host.supervisor import Supervisor

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_extract_links_from_the_shared_ui():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = Path(__file__).resolve().parents[2] / "ui" / "js" / "live.js"
    program = r"""
const fs = require("fs");
eval(fs.readFileSync(process.argv[1], "utf8"));
const links = globalThis.PyRunnerLive.extractLinks(
  "fetch https://example.com/a) then https://example.com/a and http://127.0.0.1:9/x.png\n"
);
const expected = ["https://example.com/a", "http://127.0.0.1:9/x.png"];
if (JSON.stringify(links) !== JSON.stringify(expected)) {
  console.error(JSON.stringify(links));
  process.exit(1);
}
"""
    result = subprocess.run([node, "-e", program, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_new_images_are_listed_and_old_ones_are_not(tmp_path: Path):
    work = tmp_path / "work"
    origin = tmp_path / "page"
    work.mkdir()
    origin.mkdir()
    (origin / "old.png").write_bytes(PNG)
    baseline = snapshot(work, str(origin))
    assert list_new(work, str(origin), baseline) == []
    (work / "images").mkdir()
    (work / "images" / "pic.png").write_bytes(PNG)
    (origin / "new.png").write_bytes(PNG)
    names = [item["name"] for item in list_new(work, str(origin), baseline)]
    assert names == ["images/pic.png", "origin/new.png"]
    loaded = read(work, str(origin), "images/pic.png")
    assert loaded["mime"] == "image/png"
    assert loaded["base64"]
    with pytest.raises(ValueError):
        read(work, str(origin), "../page/new.png")
    with pytest.raises(ValueError):
        read(work, str(origin), "main.py")


def test_links_and_images_are_visible_while_the_script_is_running(tmp_path: Path):
    source = """
import time
from pathlib import Path
print("fetch https://example.com/a", flush=True)
Path("images").mkdir()
Path("images/pic.png").write_bytes(bytes.fromhex("%s"))
print("wrote image", flush=True)
time.sleep(3)
""" % PNG.hex()
    supervisor = Supervisor(tmp_path / "data", max_slots=2)
    try:
        run = supervisor.start("live.py", source)
        deadline = time.time() + 8
        status = ""
        log = ""
        names: list[str] = []
        while time.time() < deadline:
            status = next(item["status"] for item in supervisor.list_runs() if item["id"] == run["id"])
            log = supervisor.read_log(run["id"])["text"]
            names = [item["name"] for item in supervisor.list_artifacts(run["id"])]
            if "https://example.com/a" in log and "images/pic.png" in names and status == "running":
                break
            time.sleep(0.05)
        assert status == "running", log
        assert "https://example.com/a" in log
        assert "images/pic.png" in names
        loaded = supervisor.read_artifact(run["id"], "images/pic.png")
        assert loaded["mime"] == "image/png"
    finally:
        supervisor.shutdown()
