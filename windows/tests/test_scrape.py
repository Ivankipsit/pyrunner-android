import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pyrunner_host.supervisor import Supervisor

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _page(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "pic.png").write_bytes(PNG)
    (folder / "index.html").write_text(
        """<!DOCTYPE html>
<html><body>
<a href="https://example.com/a">One</a>
<a href="files/b.html">Two</a>
<img src="pic.png" alt="dot">
</body></html>
""",
        encoding="utf-8",
    )


def test_save_links_and_images(tmp_path: Path):
    page = tmp_path / "page"
    _page(page)
    source = (Path(__file__).resolve().parents[2] / "examples" / "save_links.py").read_text(encoding="utf-8")
    supervisor = Supervisor(tmp_path / "data", max_slots=2)
    try:
        run = supervisor.start("save_links.py", source, origin_dir=str(page))
        status = _wait(supervisor, run["id"], {"finished", "failed"}, 15)
        log = supervisor.read_log(run["id"])["text"]
        assert status == "finished", log
        assert (page / "links.txt").read_text(encoding="utf-8").splitlines() == [
            "https://example.com/a",
            "files/b.html",
        ]
        assert (page / "images" / "pic.png").read_bytes() == PNG
    finally:
        supervisor.shutdown()


def test_fetch_links_from_local_page(tmp_path: Path):
    page = tmp_path / "site"
    _page(page)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(page), **kwargs)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    source = f"""
import requests
from bs4 import BeautifulSoup
from pathlib import Path
url = "http://127.0.0.1:{port}/index.html"
html = requests.get(url, timeout=10).text
soup = BeautifulSoup(html, "html.parser")
links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
Path("links.txt").write_text("\\n".join(links) + "\\n", encoding="utf-8")
img = requests.get("http://127.0.0.1:{port}/pic.png", timeout=10)
Path("pic.png").write_bytes(img.content)
print("fetched", len(links), flush=True)
"""
    supervisor = Supervisor(tmp_path / "data", max_slots=2)
    try:
        run = supervisor.start("fetch_page.py", source)
        status = _wait(supervisor, run["id"], {"finished", "failed"}, 20)
        log = supervisor.read_log(run["id"])["text"]
        assert status == "finished", log
        work = tmp_path / "data" / "runs" / run["id"] / "work"
        assert (work / "links.txt").read_text(encoding="utf-8").splitlines()[0] == "https://example.com/a"
        assert (work / "pic.png").read_bytes() == PNG
    finally:
        server.shutdown()
        supervisor.shutdown()


def _wait(supervisor: Supervisor, run_id: str, wanted: set[str], timeout: float) -> str:
    import time

    deadline = time.time() + timeout
    status = ""
    while time.time() < deadline:
        for run in supervisor.list_runs():
            if run["id"] == run_id:
                status = run["status"]
        if status in wanted:
            return status
        time.sleep(0.05)
    return status
