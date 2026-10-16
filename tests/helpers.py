"""Small helpers shared by several test files."""

from __future__ import annotations

import json
import socket
from pathlib import Path

NEO4J_ENV = "NEO4J_URI=neo4j+s://x.databases.neo4j.io\nNEO4J_USERNAME=u\nNEO4J_PASSWORD=pw\n"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    assert port != 8787
    return port


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

import http.server  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
from typing import Any  # noqa: E402

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


def hook_log(home: Path) -> str:
    path = home / ".local" / "share" / "agentfly" / "logs" / "events.jsonl"
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
        self.port = free_port()
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

        self._server = Server(("127.0.0.1", self.port), Handler)
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


def start_recorder(
    home: Path, port: int, env_extra: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """The real recorder (`agentfly serve`) under a temporary HOME."""
    env = {**client_env(home), **(env_extra or {})}
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from agentfly.cli import main; sys.exit(main(sys.argv[1:]))",
            "serve",
            *(["--port", str(port)] if port else []),
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process


def wait_for_health(port: int, process: subprocess.Popen[bytes]) -> dict[str, Any]:
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


def stop_recorder(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
