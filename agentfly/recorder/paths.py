"""v1 file locations (SPEC section 3, D7) and the one-time move from the hackathon folder."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("agentfly")

_MARKER_NAME: str = ".migrated-from-flightrecorder"


def config_dir() -> Path:
    """Token, settings and the optional neo4j.env. Computed on each call so HOME can change."""
    return Path.home() / ".config" / "agentfly"


def data_dir() -> Path:
    """Session notes and logs."""
    return Path.home() / ".local" / "share" / "agentfly"


def credentials_path() -> Path:
    return config_dir() / "neo4j.env"


def legacy_dir() -> Path:
    return Path.home() / ".config" / "flightrecorder"


def private_dir(path: Path) -> Path:
    """Create a folder only the user can open. `mkdir(mode=)` covers only the leaf, so chmod."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _move(source: Path, target: Path, mode: int) -> None:
    if not source.is_file():
        return
    if target.exists():
        logger.warning("not overwriting %s; old copy left at %s", target, source)
        return
    private_dir(target.parent)
    os.replace(source, target)
    target.chmod(mode)


def migrate_legacy() -> None:
    """Move ~/.config/flightrecorder into the v1 folders, once.

    The marker is checked before the old folder is looked at, so a second start never
    reads it. It is written only after every step worked, so a failed run is retried.
    """
    marker: Path = config_dir() / _MARKER_NAME
    if marker.exists():
        return
    try:
        old: Path = legacy_dir()
        if old.is_dir():
            _move(old / "sessions.json", data_dir() / "sessions.json", 0o600)
            _move(old / ".env", credentials_path(), 0o600)
            token: Path = old / "token"
            if token.is_file():
                token.unlink()  # the token is rewritten on every start
            try:
                old.rmdir()
            except OSError:
                pass  # other files left in it are not ours to move
        private_dir(config_dir())
        marker.write_text("", encoding="utf-8")
    except OSError as exc:
        logger.warning("migration from the hackathon folder failed: %s", type(exc).__name__)
