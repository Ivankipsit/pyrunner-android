(function (root) {
  const PIP = {
    requests: "requests",
    bs4: "beautifulsoup4",
    httpx: "httpx",
    lxml: "lxml",
    pandas: "pandas",
    numpy: "numpy",
    aiohttp: "aiohttp",
    dotenv: "python-dotenv",
    selenium: "selenium",
    playwright: "playwright",
    tqdm: "tqdm",
    tenacity: "tenacity",
  };

  const SCRAPE = [
    "import requests",
    "from bs4 import BeautifulSoup",
    "from pathlib import Path",
    "",
    'url = "https://example.com"',
    'print("fetch " + url, flush=True)',
    "html = requests.get(url, timeout=30).text",
    'soup = BeautifulSoup(html, "html.parser")',
    'links = [a.get("href") for a in soup.find_all("a") if a.get("href")]',
    'Path("links.txt").write_text("\\n".join(links) + "\\n", encoding="utf-8")',
    "for item in links:",
    "    print(item, flush=True)",
    'print("links", len(links), flush=True)',
    "",
  ].join("\n");

  const MODELS = [
    {
      id: "builtin",
      label: "Built-in helper",
      size: "none",
      detail: "On this device. No download. Explains scraping and how to ask for help.",
    },
    {
      id: "qwen2.5-coder:3b",
      label: "Qwen2.5-Coder 3B",
      size: "1.9 GB",
      detail: "Best small coding model. Fits a modest PC.",
    },
    {
      id: "qwen2.5-coder:7b",
      label: "Qwen2.5-Coder 7B",
      size: "4.7 GB",
      detail: "Better code than 3B when the PC has about 8 GB free.",
    },
    {
      id: "qwen2.5-coder:14b",
      label: "Qwen2.5-Coder 14B",
      size: "9 GB",
      detail: "Stronger again, for a PC with about 16 GB free.",
    },
  ];

  function scriptPackages(source) {
    const found = [];
    const seen = Object.create(null);
    const pattern = /^\s*(?:import|from)\s+([A-Za-z0-9_]+)/gm;
    let match;
    while ((match = pattern.exec(source || ""))) {
      const pip = PIP[match[1]];
      if (!pip || seen[pip]) continue;
      seen[pip] = true;
      found.push(pip);
    }
    return found;
  }

  function builtinReply(prompt) {
    const text = (prompt || "").toLowerCase();
    const scrape = /scrap|image|link|beautifulsoup|requests|page|website|html/.test(text);
    const usage = /how|agent|model|help|use|download|delete/.test(text) || !text;
    const parts = [];
    let code = "";
    if (usage) {
      parts.push("Ask a question in this box. The built-in helper answers on this device and does not download anything.");
      parts.push("On Windows, install Ollama, then Download a model here. Switch models in the list. Delete removes that model from this PC. The download talks only to 127.0.0.1.");
      parts.push("On the phone, keep this helper. The larger models are for the Windows app.");
    }
    if (scrape) {
      parts.push("To scrape a page: put the URL in a script, press Run, and watch Output. Printed links and saved images show up while it runs.");
      parts.push("requests and beautifulsoup4 are already included. If Library marks a package missing, Install it on Windows.");
      code = SCRAPE;
    }
    if (!parts.length) {
      parts.push("Ask how to scrape a page, or how to use a model. Insert scraper puts a starter script in the editor.");
    }
    return { text: parts.join("\n\n"), code: code };
  }

  root.PyRunnerGuide = {
    PIP: PIP,
    SCRAPE: SCRAPE,
    MODELS: MODELS,
    scriptPackages: scriptPackages,
    builtinReply: builtinReply,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
