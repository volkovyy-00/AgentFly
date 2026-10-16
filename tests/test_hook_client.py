"""The hook client, run as the repo shim (what ./install.sh wires) with no recorder."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import agentfly.hook_client as client_module

REPO = Path(__file__).resolve().parents[1]
MARKER = "FILE-CONTENT-MARKER-77"
EVENT: dict[str, Any] = {
    "hook_event_name": "beforeReadFile",
    "file_path": "/proj/README.md",
    "content": f"# secret body {MARKER}",
    "attachments": [],
    "conversation_id": "c1",
}


def run_client(
    command: list[str], home: Path, event: dict[str, Any]
) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        command, input=json.dumps(event), capture_output=True, text=True, env=env, check=False
    )


def check_allow_and_log(result: subprocess.CompletedProcess, home: Path) -> None:
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"permission": "allow"}
    log = home / ".local" / "share" / "agentfly" / "logs" / "events.jsonl"
    text = log.read_text(encoding="utf-8")
    assert "beforeReadFile" in text and MARKER not in text
    assert MARKER not in result.stdout + result.stderr
    assert (log.stat().st_mode & 0o777) == 0o600
    assert (log.parent.stat().st_mode & 0o777) == 0o700


def test_shim_with_no_recorder_prints_allow_and_logs_in_the_data_folder(
    isolated_home: Path,
) -> None:
    # No token exists under this HOME, so the client stops before any network call.
    repo_logs = REPO / "logs" / "events.jsonl"
    before = repo_logs.stat().st_size if repo_logs.exists() else None
    result = run_client([sys.executable, str(REPO / "hooks" / "hook.py")], isolated_home, EVENT)
    check_allow_and_log(result, isolated_home)
    assert (repo_logs.stat().st_size if repo_logs.exists() else None) == before


def test_client_file_runs_directly_too(isolated_home: Path) -> None:
    script = str(REPO / "agentfly" / "hook_client.py")
    check_allow_and_log(run_client([sys.executable, script], isolated_home, EVENT), isolated_home)


def test_nothing_is_written_next_to_the_client(isolated_home: Path) -> None:
    package = REPO / "agentfly"
    before = sorted(p.relative_to(package) for p in package.rglob("*") if p.is_file())
    run_client([sys.executable, str(REPO / "hooks" / "hook.py")], isolated_home, EVENT)
    after = sorted(p.relative_to(package) for p in package.rglob("*") if p.is_file())
    assert after == before


def test_recorder_down_with_a_token_still_allows(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = isolated_home / ".config" / "agentfly" / "token"
    token.parent.mkdir(parents=True)
    token.write_text("t", encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 8787
    monkeypatch.setattr(client_module, "_TOKEN_PATH", token)
    monkeypatch.setattr(client_module, "_HOOK_URL", f"http://127.0.0.1:{port}/hook")
    monkeypatch.setattr(client_module, "_LOG_PATH", isolated_home / "log" / "events.jsonl")
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(EVENT)))
    assert client_module.main() == 0
    assert json.loads(capsys.readouterr().out) == {"permission": "allow"}
