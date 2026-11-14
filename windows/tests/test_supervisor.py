import sys
import time
from pathlib import Path

from pyrunner_host.supervisor import Supervisor


def _wait_status(supervisor: Supervisor, run_id: str, wanted: set[str], timeout: float = 8) -> str:
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


def test_stop_interrupts_sleep(tmp_path: Path):
    supervisor = Supervisor(tmp_path, max_slots=2)
    try:
        run = supervisor.start("sleep.py", "import time\nprint('START', flush=True)\ntime.sleep(30)\nprint('END', flush=True)\n")
        assert _wait_log(supervisor, run["id"], "START", 8)
        supervisor.stop(run["id"])
        status = _wait_status(supervisor, run["id"], {"stopped", "finished", "failed"})
        assert status == "stopped"
        assert "END" not in supervisor.read_log(run["id"])["text"]
    finally:
        supervisor.shutdown()


def test_stop_does_not_force_a_catch_loop(tmp_path: Path):
    supervisor = Supervisor(tmp_path, max_slots=2)
    source = (
        "import time\n"
        "print('UP', flush=True)\n"
        "while True:\n"
        "    try:\n"
        "        time.sleep(0.2)\n"
        "    except KeyboardInterrupt:\n"
        "        print('IGNORED', flush=True)\n"
    )
    try:
        run = supervisor.start("catch.py", source)
        assert _wait_log(supervisor, run["id"], "UP", 8)
        supervisor.stop(run["id"])
        assert _wait_log(supervisor, run["id"], "IGNORED", 8)
        time.sleep(1.6)
        status = next(item["status"] for item in supervisor.list_runs() if item["id"] == run["id"])
        assert status == "running"
        supervisor.kill(run["id"])
        assert _wait_status(supervisor, run["id"], {"killed"}) == "killed"
    finally:
        supervisor.shutdown()


def test_kill_one_of_two(tmp_path: Path):
    supervisor = Supervisor(tmp_path, max_slots=2)
    try:
        result = supervisor.isolation_probe()
        assert result["ok"], result
    finally:
        supervisor.shutdown()


def test_queue_respects_slot_limit(tmp_path: Path):
    supervisor = Supervisor(tmp_path, max_slots=1)
    try:
        first = supervisor.start("a.py", "import time\nprint('A', flush=True)\ntime.sleep(0.8)\nprint('ADONE', flush=True)\n")
        second = supervisor.start("b.py", "print('B', flush=True)\n")
        queued = next(item for item in supervisor.list_runs() if item["id"] == second["id"])
        assert queued["status"] == "queued"
        assert _wait_status(supervisor, first["id"], {"finished"}) == "finished"
        assert _wait_status(supervisor, second["id"], {"finished"}) == "finished"
        assert "B" in supervisor.read_log(second["id"])["text"]
    finally:
        supervisor.shutdown()


def test_multiprocessing_spawn(tmp_path: Path):
    source = Path(__file__).resolve().parents[2] / "examples" / "desktop" / "multiprocess_check.py"
    supervisor = Supervisor(tmp_path, python=sys.executable, max_slots=2)
    try:
        run = supervisor.start("multiprocess_check.py", source.read_text(encoding="utf-8"))
        status = _wait_status(supervisor, run["id"], {"finished", "failed"}, timeout=30)
        log = supervisor.read_log(run["id"])["text"]
        assert status == "finished", log
        assert "[4, 9, 16, 25]" in log
    finally:
        supervisor.shutdown()


def _wait_log(supervisor: Supervisor, run_id: str, token: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if token in supervisor.read_log(run_id)["text"]:
            return True
        time.sleep(0.05)
    return False
