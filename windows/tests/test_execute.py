import threading
from pathlib import Path

from pyrunner_rt.execute import execute_source


def test_streams_stdout_and_stderr(tmp_path: Path):
    out: list[str] = []
    err: list[str] = []
    result = execute_source(
        "import sys\nprint('hi', flush=True)\nsys.stderr.write('nope\\n')\n",
        filename="t.py",
        workdir=str(tmp_path),
        on_stdout=out.append,
        on_stderr=err.append,
        chdir=True,
    )
    assert result["exitCode"] == 0
    assert "".join(out) == "hi\n"
    assert "".join(err) == "nope\n"


def test_syntax_error_is_failure(tmp_path: Path):
    err: list[str] = []
    result = execute_source(
        "def (\n",
        filename="bad.py",
        workdir=str(tmp_path),
        on_stdout=lambda _text: None,
        on_stderr=err.append,
    )
    assert result["exitCode"] == 1
    assert "SyntaxError" in "".join(err)


def test_cancel_during_sleep(tmp_path: Path):
    cancel = threading.Event()
    seen: list[str] = []

    def on_out(text: str) -> None:
        seen.append(text)
        if "START" in "".join(seen):
            cancel.set()

    result = execute_source(
        "import time\nprint('START', flush=True)\ntime.sleep(30)\nprint('END', flush=True)\n",
        filename="sleep.py",
        workdir=str(tmp_path),
        on_stdout=on_out,
        on_stderr=lambda _text: None,
        cancel=cancel,
    )
    assert result["exitCode"] == 130
    assert "END" not in "".join(seen)


def test_cancel_busy_loop(tmp_path: Path):
    cancel = threading.Event()
    holder: dict = {}

    def target() -> None:
        def on_out(text: str) -> None:
            if "START" in text:
                cancel.set()

        holder["result"] = execute_source(
            "print('START', flush=True)\nwhile True:\n    x = 1\n",
            filename="loop.py",
            workdir=str(tmp_path),
            on_stdout=on_out,
            on_stderr=lambda _text: None,
            cancel=cancel,
        )

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert holder["result"]["exitCode"] == 130


def test_parallel_stdout_does_not_mix(tmp_path: Path):
    out = {"a": [], "b": []}

    def run(key: str, token: str) -> None:
        execute_source(
            f"import time\nprint('{token}', flush=True)\ntime.sleep(0.2)\nprint('{token}2', flush=True)\n",
            filename=f"{key}.py",
            workdir=str(tmp_path),
            on_stdout=out[key].append,
            on_stderr=lambda _text: None,
        )

    threads = [
        threading.Thread(target=run, args=("a", "AAA")),
        threading.Thread(target=run, args=("b", "BBB")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads)
    assert "BBB" not in "".join(out["a"])
    assert "AAA" not in "".join(out["b"])
    assert "AAA2" in "".join(out["a"])
    assert "BBB2" in "".join(out["b"])
