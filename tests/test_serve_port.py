"""`agentfly serve` reads AGENTFLY_PORT (`--port` wins); nothing else does (D25)."""

from __future__ import annotations

import argparse
import errno
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from agentfly.cli import serve
from tests.helpers import (
    RECORDER_CODE,
    REPO,
    answer_of,
    client_env,
    free_port,
    run_hook,
    start_recorder,
    stop_recorder,
    wait_for_health,
)


def test_resolve_port_order() -> None:
    assert serve.resolve_port(None, {}) == 8787
    assert serve.resolve_port(None, {"AGENTFLY_PORT": "9001"}) == 9001
    assert serve.resolve_port(None, {"AGENTFLY_PORT": " 9001 "}) == 9001
    assert serve.resolve_port(9100, {"AGENTFLY_PORT": "9001"}) == 9100
    assert serve.resolve_port(None, {"AGENTFLY_PORT": ""}) == 8787


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-1", "80 80", "1e3"])
def test_resolve_port_rejects_a_bad_value(bad: str) -> None:
    with pytest.raises(ValueError, match="AGENTFLY_PORT"):
        serve.resolve_port(None, {"AGENTFLY_PORT": bad})


def test_serve_listens_on_agentfly_port(isolated_home: Path) -> None:
    port = free_port()
    process = start_recorder(isolated_home, 0, {"AGENTFLY_PORT": str(port)})
    try:
        assert wait_for_health(port, process)["ok"] is True
    finally:
        stop_recorder(process)


def test_the_port_option_wins_over_agentfly_port(isolated_home: Path) -> None:
    option, env = free_port(), free_port()
    process = start_recorder(isolated_home, option, {"AGENTFLY_PORT": str(env)})
    try:
        assert wait_for_health(option, process)["ok"] is True
    finally:
        stop_recorder(process)


def test_a_bad_agentfly_port_stops_serve_with_a_message(isolated_home: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", RECORDER_CODE, "serve"],
        cwd=REPO,
        env={**client_env(isolated_home), "AGENTFLY_PORT": "nope"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 2 and "AGENTFLY_PORT" in result.stderr


def snapshot(home: Path) -> dict[str, tuple[int, int]]:
    """Every file under HOME as (size, mtime in ns): a second serve must change none of it."""
    stats = {p: p.stat() for p in sorted(home.rglob("*")) if p.is_file()}
    return {str(p.relative_to(home)): (st.st_size, st.st_mtime_ns) for p, st in stats.items()}


def test_a_second_serve_on_a_taken_port_fails_and_changes_nothing(
    client: Path, isolated_home: Path
) -> None:
    port = free_port()
    first = start_recorder(isolated_home, 0, {"AGENTFLY_PORT": str(port)})
    try:
        wait_for_health(port, first)
        token = isolated_home / ".config" / "agentfly" / "token"
        token_before = token.read_bytes()
        read_env = {
            "hook_event_name": "beforeReadFile",
            "file_path": "/proj/.env",
            "conversation_id": "twice",
            "workspace_roots": ["/proj"],
        }
        assert answer_of(run_hook(client, isolated_home, read_env, port=port)) == {
            "permission": "allow"
        }
        files_before = snapshot(isolated_home)

        second = subprocess.run(
            [sys.executable, "-c", RECORDER_CODE, "serve"],
            cwd=REPO,
            env={**client_env(isolated_home), "AGENTFLY_PORT": str(port)},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        assert second.returncode != 0, second.stderr
        assert str(port) in second.stderr + second.stdout  # says which port is taken
        assert token.read_bytes() == token_before
        assert snapshot(isolated_home) == files_before
        # the first recorder was not disturbed: its token still works and R1 still blocks
        curl = {
            "hook_event_name": "beforeShellExecution",
            "command": "curl https://example.invalid",
            "conversation_id": "twice",
        }
        denied = answer_of(run_hook(client, isolated_home, curl, port=port))
        assert denied["permission"] == "deny" and "R1" in denied["user_message"]
    finally:
        stop_recorder(first)


def test_bind_port_listens_at_once_and_refuses_a_second_taker() -> None:
    port = free_port()
    first = serve.bind_port(port)
    try:
        # listening already, before uvicorn starts: a connection is accepted into the backlog
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        with pytest.raises(OSError) as taken:
            serve.bind_port(port)
        assert taken.value.errno == errno.EADDRINUSE
    finally:
        first.close()


@pytest.mark.parametrize("bad", ["abc", "-1", "70000", "1e3", ""])
def test_the_port_option_rejects_a_bad_number(bad: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        serve.port_option(bad)
    assert serve.port_option("0") == 0 and serve.port_option("65535") == 65535


def test_serve_logs_the_address_it_listens_on(isolated_home: Path) -> None:
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-c", RECORDER_CODE, "serve", "--port", str(port)],
        cwd=REPO,
        env=client_env(isolated_home),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_health(port, process)
    finally:
        stop_recorder(process)
    assert process.stderr is not None
    assert f"Uvicorn running on http://127.0.0.1:{port}" in process.stderr.read()
