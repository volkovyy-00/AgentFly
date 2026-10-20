"""The suite runs in parallel under pytest-xdist (F7): ports, worker groups, strict markers."""

from __future__ import annotations

import ast
import re
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests import helpers, test_package
from tests.helpers import REPO, client_env, free_port

TESTS = Path(__file__).parent
TIMED = re.compile(r"\b(?:perf_counter|monotonic)\b")


# ---------------------------------------------------------------- worker groups


def test_the_package_tests_share_one_worker() -> None:
    groups = {m.kwargs["name"] for m in test_package.pytestmark if m.name == "xdist_group"}
    assert groups == {"package"}


def read_tests() -> list[tuple[Path, str, ast.FunctionDef]]:
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path != Path(__file__):
            source = path.read_text(encoding="utf-8")
            found += [
                (path, source, node)
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            ]
    return found


def test_a_test_that_reads_the_clock_is_on_the_wallclock_worker() -> None:
    # Tests that assert a time limit (or lean on a sleep) carry @wallclock by hand, so they share
    # one worker and do not compete with each other. This scan sees only `perf_counter` and
    # `monotonic`: in a test's own body (the test needs the mark), and anywhere in a module (the
    # module must use the mark somewhere). `time.time`, `sleep` and helpers are not scanned.
    timers = [t for t in read_tests() if TIMED.search(ast.get_source_segment(t[1], t[2]) or "")]
    assert timers, "the scan found no test that reads the clock"
    bare = [
        f"{path.name}::{node.name}"
        for path, _, node in timers
        if not any(isinstance(d, ast.Name) and d.id == "wallclock" for d in node.decorator_list)
    ]
    assert bare == [], f"these tests read the clock without @wallclock: {bare}"
    modules = {p for p in TESTS.glob("test_*.py") if TIMED.search(p.read_text(encoding="utf-8"))}
    unmarked = sorted(
        p.name for p in modules - {Path(__file__)} if "@wallclock" not in p.read_text()
    )
    assert unmarked == [], f"these modules time a test but never use @wallclock: {unmarked}"
    # helpers.py is imported before pytest registers markers, so a typo in the mark's name would
    # pass strict_markers and silently group nothing.
    assert (helpers.wallclock.name, helpers.wallclock.kwargs) == (
        "xdist_group",
        {"name": "wallclock"},
    )


# ---------------------------------------------------------------- ports


def set_worker(monkeypatch: pytest.MonkeyPatch, worker: str, count: int) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", str(count))


def test_a_worker_is_only_handed_ports_of_its_own_class(monkeypatch: pytest.MonkeyPatch) -> None:
    for worker in ("gw0", "gw3", "gw7"):
        set_worker(monkeypatch, worker, 8)
        ports = [free_port() for _ in range(30)]
        assert {port % 8 for port in ports} == {int(worker[2:])}
        assert all(20000 <= port <= 32767 for port in ports)  # below where bind(0) picks
        for port in ports[:5]:  # nothing listens there
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))


def test_a_replacement_worker_still_gets_a_port(monkeypatch: pytest.MonkeyPatch) -> None:
    # xdist starts a crashed worker's replacement as gw8 while the count stays 8.
    set_worker(monkeypatch, "gw9", 8)
    assert {free_port() % 8 for _ in range(30)} == {1}


def test_a_serial_run_and_the_controller_get_any_port(monkeypatch: pytest.MonkeyPatch) -> None:
    set_worker(monkeypatch, "master", 1)
    assert 0 < free_port() < 65536


def test_an_impossible_class_is_an_error_not_a_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    set_worker(monkeypatch, "gw0", 10**9)  # no real port is a multiple of a billion
    monkeypatch.setattr(helpers, "_PORT_TRIES", 50)
    with pytest.raises(RuntimeError, match="free port"):
        free_port()


# ---------------------------------------------------------------- markers and config


def test_the_config_holds_no_parallel_flags() -> None:
    # The live-Neo4j test starts its own `pytest` and reads this file too: -n and --dist stay on the
    # command line. (strict_markers is covered by the run below.)
    ini = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = ini["tool"]["pytest"]["ini_options"].get("addopts", "")
    words = " ".join(addopts) if isinstance(addopts, list) else str(addopts)
    assert "-n" not in words.split() and "--dist" not in words and "xdist" not in words


@pytest.mark.parametrize(
    "extra", [[], ["-n", "2", "--dist", "loadgroup"]], ids=["serial", "parallel"]
)
def test_an_unknown_marker_fails_the_run(
    tmp_path: Path, isolated_home: Path, extra: list[str]
) -> None:
    (tmp_path / "test_unknown.py").write_text(
        "import pytest\n\n\n@pytest.mark.nope\ndef test_it() -> None:\n    pass\n", encoding="utf-8"
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(REPO / "pyproject.toml"),
        "--rootdir",
        str(tmp_path),
        "-p",
        "no:cacheprovider",
        *extra,
        str(tmp_path / "test_unknown.py"),
    ]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=client_env(isolated_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode != 0, result.stdout
    assert "'nope' not found in `markers` configuration option" in result.stdout + result.stderr
