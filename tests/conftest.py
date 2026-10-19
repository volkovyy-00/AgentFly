"""Every test runs under a temporary HOME: no test can reach the real ~/.config or ~/.local."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentfly.install import service
from tests.helpers import copy_client, free_port
from tests.service_helpers import Launchd


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


@pytest.fixture
def client(tmp_path: Path) -> Path:
    """A copy of the hook client alone in an empty folder."""
    return copy_client(tmp_path / "client")
