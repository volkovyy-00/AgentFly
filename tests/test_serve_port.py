"""`agentfly serve` reads AGENTFLY_PORT (`--port` wins); nothing else does (D25)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agentfly.cli import serve
from tests.helpers import (
    REPO,
    client_env,
    free_port,
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
    code = "import sys; from agentfly.cli import main; sys.exit(main(['serve']))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env={**client_env(isolated_home), "AGENTFLY_PORT": "nope"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 2 and "AGENTFLY_PORT" in result.stderr
