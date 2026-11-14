"""Save links and local images from an HTML page in the working directory.

Looks for index.html next to the current directory. Image files are copied
into images/. This does not call the network.
"""

from pathlib import Path
import shutil

from bs4 import BeautifulSoup

page = Path("index.html")
html = page.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
Path("links.txt").write_text("\n".join(links) + "\n", encoding="utf-8")
out = Path("images")
out.mkdir(exist_ok=True)
saved = 0
for img in soup.find_all("img"):
    src = img.get("src") or ""
    if not src or "://" in src or src.startswith("//"):
        continue
    source = Path(src)
    if source.is_file():
        shutil.copyfile(source, out / source.name)
        saved += 1
for item in links:
    print(item, flush=True)
print(f"images {saved}", flush=True)
