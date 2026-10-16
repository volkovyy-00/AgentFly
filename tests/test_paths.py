"""v1 folders and the one-time move from ~/.config/flightrecorder (SPEC section 3, D7)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
from agentfly.recorder import paths
from agentfly.recorder.config_env import neo4j_settings
from agentfly.recorder.store import graph_store

NEO4J_ENV = "NEO4J_URI=neo4j+s://x.databases.neo4j.io\nNEO4J_USERNAME=u\nNEO4J_PASSWORD=pw\n"


def make_legacy(home: Path, *, marked: bool = True) -> Path:
    old: Path = home / ".config" / "flightrecorder"
    old.mkdir(parents=True)
    (old / "token").write_text("old-token", encoding="utf-8")
    (old / ".env").write_text(NEO4J_ENV, encoding="utf-8")
    sessions = [{"id": "s1", "marked": marked, "start_time": "t", "next_step": 4}]
    (old / "sessions.json").write_text(json.dumps(sessions), encoding="utf-8")
    return old


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_folders_follow_home(isolated_home: Path) -> None:
    assert paths.config_dir() == isolated_home / ".config" / "agentfly"
    assert paths.data_dir() == isolated_home / ".local" / "share" / "agentfly"
    assert paths.credentials_path() == paths.config_dir() / "neo4j.env"


def test_migration_moves_marks_and_login(isolated_home: Path) -> None:
    old = make_legacy(isolated_home)
    paths.migrate_legacy()
    sessions = json.loads((paths.data_dir() / "sessions.json").read_text(encoding="utf-8"))
    assert sessions[0]["marked"] is True and sessions[0]["next_step"] == 4
    assert neo4j_settings() == ("neo4j+s://x.databases.neo4j.io", "u", "pw")
    assert mode(paths.credentials_path()) == 0o600
    assert mode(paths.config_dir()) == 0o700
    assert not old.exists()  # emptied, so removed


def test_migration_runs_once(isolated_home: Path) -> None:
    make_legacy(isolated_home)
    paths.migrate_legacy()
    decoy = make_legacy(isolated_home, marked=False)
    before = {p.name: p.read_bytes() for p in decoy.iterdir()}
    paths.migrate_legacy()
    assert {p.name: p.read_bytes() for p in decoy.iterdir()} == before
    sessions = json.loads((paths.data_dir() / "sessions.json").read_text(encoding="utf-8"))
    assert sessions[0]["marked"] is True


def test_nothing_to_move_still_sets_the_marker(isolated_home: Path) -> None:
    paths.migrate_legacy()
    make_legacy(isolated_home)
    paths.migrate_legacy()
    assert (isolated_home / ".config" / "flightrecorder" / ".env").exists()
    assert not paths.credentials_path().exists()


def test_existing_target_is_never_overwritten(isolated_home: Path) -> None:
    old = make_legacy(isolated_home)
    paths.config_dir().mkdir(parents=True)
    paths.credentials_path().write_text("NEO4J_URI=mine\n", encoding="utf-8")
    paths.migrate_legacy()
    assert paths.credentials_path().read_text(encoding="utf-8") == "NEO4J_URI=mine\n"
    assert (old / ".env").read_text(encoding="utf-8") == NEO4J_ENV  # old copy is left


def test_unknown_files_stay_and_keep_the_folder(isolated_home: Path) -> None:
    old = make_legacy(isolated_home)
    (old / "notes.txt").write_text("keep", encoding="utf-8")
    paths.migrate_legacy()
    assert (old / "notes.txt").read_text(encoding="utf-8") == "keep"


def test_a_failed_move_does_not_stop_start_or_set_the_marker(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_legacy(isolated_home)

    def broken(*_args: object) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(paths.os, "replace", broken)
    paths.migrate_legacy()  # must not raise
    assert not (paths.config_dir() / ".migrated-from-flightrecorder").exists()


def test_first_start_migrates_and_second_start_ignores_the_old_folder(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(graph_store, "start", lambda *_a, **_k: None)  # no network
    make_legacy(isolated_home)
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787"):
        assert app_module.get_store().get("s1").marked is True  # type: ignore[union-attr]
        assert paths.credentials_path().is_file()
        token = (paths.config_dir() / "token").read_text(encoding="utf-8")
        assert token != "old-token" and mode(paths.config_dir() / "token") == 0o600
    decoy = make_legacy(isolated_home, marked=False)
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787"):
        assert app_module.get_store().get("s1").marked is True  # type: ignore[union-attr]
    assert json.loads((decoy / "sessions.json").read_text(encoding="utf-8"))[0]["marked"] is False
    assert (decoy / ".env").exists() and (decoy / "token").read_text() == "old-token"
