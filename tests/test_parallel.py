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
SOURCES = {
    path: path.read_text(encoding="utf-8")
    for path in sorted(TESTS.glob("test_*.py"))
    if path != Path(__file__)
}


# ---------------------------------------------------------------- worker groups


def test_the_package_tests_share_one_worker() -> None:
    groups = {m.kwargs["name"] for m in test_package.pytestmark if m.name == "xdist_group"}
    assert groups == {"package"}


def timed_tests(
    sources: dict[Path, str] = SOURCES,
) -> list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """The test functions whose own body names `perf_counter` or `monotonic`."""
    found = []
    for path, source in sources.items():
        if not TIMED.search(source):
            continue  # most files: no need to parse them
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                "test_"
            ):
                if TIMED.search(ast.get_source_segment(source, node) or ""):
                    found.append((path, node))
    return found


def test_a_test_that_reads_the_clock_is_on_the_wallclock_worker() -> None:
    # Tests that assert a time limit (or lean on a sleep) carry @wallclock by hand, so they share
    # one worker and do not compete with each other. This scan sees only `perf_counter` and
    # `monotonic`: in a test's own body (the test needs the mark), and anywhere in a module (the
    # module must use the mark somewhere). `time.time`, `sleep` and helpers are not scanned.
    timers = timed_tests()
    assert timers, "the scan found no test that reads the clock"
    bare = [
        f"{path.name}::{node.name}"
        for path, node in timers
        if not any(isinstance(d, ast.Name) and d.id == "wallclock" for d in node.decorator_list)
    ]
    assert bare == [], f"these tests read the clock without @wallclock: {bare}"
    unmarked = [
        path.name
        for path, source in SOURCES.items()
        if TIMED.search(source) and "@wallclock" not in source
    ]
    assert unmarked == [], f"these modules time a test but never use @wallclock: {unmarked}"


def test_the_wallclock_mark_names_its_group() -> None:
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


# gw9 of 8: xdist starts a crashed worker's replacement under a new number, the count stays 8.
@pytest.mark.parametrize(("worker", "own"), [("gw0", 0), ("gw3", 3), ("gw7", 7), ("gw9", 1)])
def test_a_worker_is_only_handed_ports_of_its_own_class(
    monkeypatch: pytest.MonkeyPatch, worker: str, own: int
) -> None:
    set_worker(monkeypatch, worker, 8)
    ports = [free_port() for _ in range(30)]
    assert {port % 8 for port in ports} == {own}
    assert all(20000 <= port <= 32767 for port in ports)  # below where bind(0) picks
    for port in ports[:5]:  # nothing listens there
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))


def test_a_worker_does_not_hand_out_a_port_twice_in_a_row(monkeypatch: pytest.MonkeyPatch) -> None:
    # `test_the_port_option_wins_over_agentfly_port` takes two ports in one test: they must differ.
    set_worker(monkeypatch, "gw0", 8)
    ports = [free_port() for _ in range(400)]
    assert all(len(set(ports[i : i + 64])) == 64 for i in range(len(ports) - 63))


def test_the_clock_scan_reads_the_lines_python_counts() -> None:
    # A form feed ends a line for `str.splitlines` but not for the parser: the scan must not shift.
    source = "import time\n\n\ndef test_x():\n    pass\x0c\n    t = time.perf_counter()\n"
    assert [node.name for _, node in timed_tests({Path("test_x.py"): source})] == ["test_x"]


def test_the_clock_scan_sees_an_async_test() -> None:
    source = "import time\n\n\nasync def test_y():\n    t = time.monotonic()\n"
    assert [node.name for _, node in timed_tests({Path("test_y.py"): source})] == ["test_y"]


def test_a_serial_run_gets_any_port_of_the_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    assert 20000 <= free_port() <= 32767


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
