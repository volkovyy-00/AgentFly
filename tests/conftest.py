"""Every test runs under a temporary HOME: no test can reach the real ~/.config or ~/.local."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agentfly.install import packages, service
from agentfly.recorder import rulefile, rules
from tests.helpers import copy_client, free_port
from tests.install_helpers import make_tool_env
from tests.service_helpers import Launchd

# Taken at import: a test that patches `rules.DEFAULT` must not change what is put back.
PACKAGED_DEFAULT = rules.DEFAULT


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home: Path = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture(autouse=True)
def launchd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Launchd:
    """No test reaches the real launchd or the real recorder on 8787 (V3b).

    `service.LAUNCHCTL` is a stub that answers "no such job" until a test loads one, and the health
    check asks a port nothing listens on. Tests that want an answer patch `service.health`.
    """
    stub = Launchd(tmp_path / "stubs")
    monkeypatch.setattr(service, "LAUNCHCTL", str(stub.path))
    monkeypatch.setattr(service, "HEALTH_PORT", free_port())
    monkeypatch.setattr(service, "POLL_INTERVAL", 0.001)
    monkeypatch.setattr(service, "START_TIMEOUT", 0.05)
    return stub


@pytest.fixture(autouse=True)
def tool_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> packages.Environment:
    """No test hashes the real tool environment (V3c): this process "runs from" a small clean one.

    A test that wants a different environment patches `packages.tool_environment` again.
    """
    env = make_tool_env(tmp_path / "toolenv")
    monkeypatch.setattr(packages, "tool_environment", lambda: env)
    return env


@pytest.fixture(autouse=True)
def active_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """No test reads the real /Library/Application Support/AgentFly/rules.toml (V5b).

    The recorder reads `rulefile.ACTIVE_RULES` once at start; here it is a file that does not
    exist, so the packaged default is in force. A test that wants other rules writes this path.
    A recorder started as a child process gets the same by its launch snippet (`RECORDER_CODE`).
    """
    path = tmp_path / "no-active-rules.toml"
    monkeypatch.setattr(rulefile, "ACTIVE_RULES", path)
    yield path
    rules.activate(PACKAGED_DEFAULT)  # no test leaves other rules in force


@pytest.fixture
def client(tmp_path: Path) -> Path:
    """A copy of the hook client alone in an empty folder."""
    return copy_client(tmp_path / "client")
