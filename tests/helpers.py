"""Small helpers shared by several test files."""

from __future__ import annotations

import http.server
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

import pytest

NEO4J_ENV = "NEO4J_URI=neo4j+s://x.databases.neo4j.io\nNEO4J_USERNAME=u\nNEO4J_PASSWORD=pw\n"

# Tests that assert a time limit run on one xdist worker, so they do not compete with each other.
wallclock = pytest.mark.xdist_group(name="wallclock")

_PORT_TRIES = 10_000
# Above 8787 and every port a service of ours uses, below where the system picks port 0 (macOS
# 49152-65535, Linux 32768-60999): a `StubRecorder` bind or a connection cannot take a port that
# another worker was just handed and has not bound yet.
_PORTS = (20000, 32767)
_recent: deque[int] = deque(maxlen=64)  # ports this process was just handed: not handed again


def free_port() -> int:
    """A port nothing listens on that no other xdist worker of this run is handed.

    A random port of `_PORTS`, rounded up to the worker's own class: its remainder, by
    the worker count, is the worker's number. So workers never share a port, on any system (the
    system's own choice for port 0 can follow a pattern). A crashed worker's replacement is
    numbered past the count (gw8 of 8), hence the remainder of that too; it can share a class with
    a live worker until the run ends. Serial runs and the controller are one class of one. A
    process is not handed a port it got among its last 64 calls: a test that takes two gets two.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    count = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    own = int(worker[2:]) % count if worker.startswith("gw") else 0
    low, high = _PORTS
    for _ in range(_PORT_TRIES):
        port = random.randint(low, high)
        port += (own - port) % count
        if port > high or port in _recent:
            continue
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        except OSError:
            continue  # in use, or still closing
        _recent.append(port)
        return port
    raise RuntimeError(f"no free port of class {own} of {count} in {_PORT_TRIES} tries")


def make_legacy(home: Path, *, marked: bool = True) -> Path:
    """A hackathon `~/.config/flightrecorder` folder with a token, a Neo4j login and one session."""
    old: Path = home / ".config" / "flightrecorder"
    old.mkdir(parents=True)
    (old / "token").write_text("old-token", encoding="utf-8")
    (old / ".env").write_text(NEO4J_ENV, encoding="utf-8")
    sessions = [{"id": "s1", "marked": marked, "start_time": "t", "next_step": 4}]
    (old / "sessions.json").write_text(json.dumps(sessions), encoding="utf-8")
    return old


def package_files(package: Path) -> list[Path]:
    """Every file under a package folder, to prove a run wrote nothing there."""
    return sorted(p.relative_to(package) for p in package.rglob("*") if p.is_file())


# ---------------------------------------------------------------- hook client harness


REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tests" / "client_harness.py"


def copy_client(folder: Path) -> Path:
    """The client alone in an empty folder: it must not need anything else from the repo."""
    folder.mkdir(parents=True)
    shutil.copy(REPO / "agentfly" / "hook_client.py", folder / "hook_client.py")
    return folder


def client_env(home: Path) -> dict[str, str]:
    return {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def run_hook(
    folder: Path,
    home: Path,
    event: dict[str, Any] | bytes,
    *,
    port: int,
    budget: float | None = None,
    args: tuple[str, ...] = (),
    wrapper: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run the client copy once under `python -I -S`; `wrapper` is a shell prefix (`2>&-`, ...)."""
    data = event if isinstance(event, bytes) else json.dumps(event).encode()
    cmd = [
        sys.executable,
        "-I",
        "-S",
        str(HARNESS),
        str(folder),
        str(port),
        str(budget or ""),
        *args,
    ]
    if wrapper:
        cmd = ["/bin/sh", "-c", f'{wrapper} exec "$@"', "sh", *cmd]
    return subprocess.run(
        cmd, input=data, capture_output=True, env=client_env(home), check=False, timeout=60
    )


def answer_of(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    """The one JSON object on stdout; fails on anything else or a non-zero exit."""
    assert result.returncode == 0, result
    lines = result.stdout.decode("utf-8").splitlines()
    assert len(lines) == 1, result.stdout
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict) and parsed["permission"] in {"allow", "deny", "ask"}
    return parsed


def write_token(home: Path, token: str = "test-token") -> None:
    path = home / ".config" / "agentfly" / "token"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")


def hook_log_path(home: Path) -> Path:
    return home / ".local" / "share" / "agentfly" / "logs" / "events.jsonl"


def hook_log(home: Path) -> str:
    path = hook_log_path(home)
    return path.read_text(encoding="utf-8") if path.exists() else ""


class StubRecorder:
    """A stand-in for the recorder on a free port. It records what the client sends.

    mode: "answer" replies with `answer`; "status" replies with `status`; "silent" never replies.
    """

    def __init__(
        self,
        answer: dict[str, str] | None = None,
        *,
        mode: str = "answer",
        status: int = 200,
        raw: bytes | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        stub = self
        self._stop = threading.Event()
        reply = json.dumps(answer or {"permission": "allow"}).encode() if raw is None else raw

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                stub.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": body}
                )
                if mode == "silent":
                    stub._stop.wait(5)
                    return
                code = status if mode == "status" else 200
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args: Any) -> None:
                pass

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)  # the system picks it: no window to lose
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> StubRecorder:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r["body"]) for r in self.requests]


# What `agentfly serve ...` runs as; tests start the recorder from the repo, not from an install.
# It points the recorder at `<HOME>/test-rules.toml` first (a file that does not exist unless the
# test writes it, and that this user may own), so a child recorder never reads the real
# /Library/Application Support/AgentFly rules file (V5b). A launch snippet is the only way: no
# flag or variable moves the rules file.
RECORDER_CODE = (
    "import os, sys; from pathlib import Path; import agentfly.recorder.rulefile as rf; "
    "rf.ACTIVE_RULES = Path.home() / 'test-rules.toml'; rf.ACTIVE_OWNER_UID = os.getuid(); "
    "from agentfly.cli import main; sys.exit(main(sys.argv[1:]))"
)


def start_recorder(
    home: Path, port: int, env_extra: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """The real recorder (`agentfly serve`) under a temporary HOME."""
    env = {**client_env(home), **(env_extra or {})}
    return subprocess.Popen(
        [sys.executable, "-c", RECORDER_CODE, "serve", *(["--port", str(port)] if port else [])],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_health(port: int, process: subprocess.Popen[Any]) -> dict[str, Any]:
    deadline = time.time() + 30
    while time.time() < deadline:
        assert process.poll() is None, "recorder exited early"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                parsed: dict[str, Any] = json.loads(response.read())
                return parsed
        except OSError:
            time.sleep(0.2)
    raise AssertionError("recorder did not answer /health in 30 s")


def stop_recorder(process: subprocess.Popen[Any]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
