"""Every test runs under a temporary HOME: no test can reach the real ~/.config or ~/.local."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import agentfly.recorder.app as app_module


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home: Path = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    yield home
    app_module.set_port(app_module.DEFAULT_PORT)  # a test that changed the port must not leak it
