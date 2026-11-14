"""Command-line proof that one subprocess can be killed while another keeps running."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pyrunner_host.supervisor import Supervisor


def run() -> int:
    with tempfile.TemporaryDirectory(prefix="pyrunner-probe-") as tmp:
        supervisor = Supervisor(Path(tmp), max_slots=2)
        try:
            result = supervisor.isolation_probe()
        finally:
            supervisor.shutdown()
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1
