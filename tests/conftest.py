"""Every test runs under a temporary HOME: no test can reach the real ~/.config or ~/.local."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import copy_client


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home: Path = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def client(tmp_path: Path) -> Path:
    """A copy of the hook client alone in an empty folder."""
    return copy_client(tmp_path / "client")
