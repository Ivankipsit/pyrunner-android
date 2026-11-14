"""Print which curated packages this device can import.

Playwright and Selenium are expected to be missing on Android.
"""

import importlib

MODULES = [
    "requests",
    "httpx",
    "bs4",
    "lxml",
    "pandas",
    "numpy",
    "aiohttp",
    "dotenv",
    "tenacity",
    "tqdm",
    "playwright",
    "selenium",
]

for name in MODULES:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        print(f"missing {name}: {exc.__class__.__name__}")
        continue
    version = getattr(module, "__version__", "")
    print(f"ok {name} {version}".rstrip())
