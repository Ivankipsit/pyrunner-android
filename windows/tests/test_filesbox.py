from pathlib import Path

import pytest

from pyrunner_host.filesbox import copy_into, export_to, inbox_dir, safe_filename, store_file
from pyrunner_host.supervisor import Supervisor


def test_html_name_is_kept_and_copied_into_the_run(tmp_path: Path):
    assert safe_filename("index.html") == "index.html"
    assert safe_filename("docs/notes.txt") == "notes.txt"
    assert safe_filename("../secret.html") == "secret.html"
    with pytest.raises(ValueError):
        safe_filename("..")
    inbox = inbox_dir(tmp_path, None)
    store_file(inbox, "index.html", b"<b>ok</b>")
    folder = tmp_path / "out"
    written = export_to(folder, "index.html", b"<b>saved</b>", [])
    assert written == ["index.html"]
    assert (folder / "index.html").read_text(encoding="utf-8") == "<b>saved</b>"

    supervisor = Supervisor(tmp_path / "runs", max_slots=2)
    try:
        store_file(inbox_dir(supervisor.root, None), "index.html", b"<b>ok</b>")
        source = "from pathlib import Path\nprint(Path('index.html').read_text(encoding='utf-8'), flush=True)\n"
        run = supervisor.start("read_html.py", source)
        deadline_status = ""
        log = ""
        import time
        deadline = time.time() + 8
        while time.time() < deadline:
            deadline_status = next(item["status"] for item in supervisor.list_runs() if item["id"] == run["id"])
            log = supervisor.read_log(run["id"])["text"]
            if deadline_status in {"finished", "failed"}:
                break
            time.sleep(0.05)
        assert deadline_status == "finished", log
        assert "<b>ok</b>" in log
    finally:
        supervisor.shutdown()


def test_copy_into_skips_the_runner_script(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "main.py").write_text("print(1)\n", encoding="utf-8")
    (inbox / "page.html").write_text("hi", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / "main.py").write_text("print(2)\n", encoding="utf-8")
    copy_into(work, inbox)
    assert (work / "main.py").read_text(encoding="utf-8") == "print(2)\n"
    assert (work / "page.html").read_text(encoding="utf-8") == "hi"
