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
