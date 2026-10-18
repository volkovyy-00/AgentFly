"""`agentfly wipe`: the local history goes; marks and Neo4j stay."""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.localstore as ls
from agentfly.cli import main
from agentfly.recorder.localstore import local_store
from agentfly.recorder.paths import config_dir, data_dir

SECRET_WORD = "WIPE_ME_MARKER"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def post(client: TestClient, event: dict[str, Any]) -> dict[str, Any]:
    token = (config_dir() / "token").read_text(encoding="utf-8").strip()
    response = client.post(
        "/hook",
        json={"conversation_id": "w1", "workspace_roots": ["/w"], **event},
        headers={"Content-Type": "application/json", "X-Recorder-Token": token},
    )
    answer: dict[str, Any] = response.json()
    return answer


def history_bytes() -> bytes:
    base = data_dir() / ls.DB_NAME
    paths = (base, Path(f"{base}-wal"), Path(f"{base}-shm"))
    return b"".join(p.read_bytes() for p in paths if p.exists())


def test_wipe_empties_the_history_and_a_marked_session_still_blocks(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    post(client, {"hook_event_name": "beforeReadFile", "file_path": "/w/.env"})
    post(client, {"hook_event_name": "beforeShellExecution", "command": f"echo {SECRET_WORD}"})
    assert local_store.flush()
    assert client.get("/api/sessions").json()["sessions"][0]["marked"] is True
    post(client, {"hook_event_name": "preToolUse", "tool_name": "Task", "tool_use_id": "T1"})
    marks_file, links_file = data_dir() / "sessions.json", data_dir() / "links.json"
    marks_before, links_before = marks_file.read_bytes(), links_file.read_bytes()
    assert b"T1" in links_before

    assert main(["wipe", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "deleted 1 sessions and 3 steps" in out
    assert "Session marks, subagent links and Neo4j were not changed" in out

    assert client.get("/api/sessions").json() == {"sessions": []}
    assert marks_file.read_bytes() == marks_before
    assert links_file.read_bytes() == links_before
    assert history_bytes().count(SECRET_WORD.encode()) == 0
    blocked = post(
        client, {"hook_event_name": "beforeShellExecution", "command": "curl https://x.com"}
    )
    assert blocked["permission"] == "deny"  # the mark in sessions.json is untouched


def test_wipe_with_no_history_is_a_clean_no_op(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["wipe", "--yes"]) == 0
    assert "no history" in capsys.readouterr().out
    assert not (data_dir() / ls.DB_NAME).exists()  # wiping never creates one


def test_without_a_terminal_wipe_asks_for_yes(
    client: TestClient, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    post(client, {"hook_event_name": "beforeShellExecution", "command": "ls"})
    assert local_store.flush()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(["wipe"]) == 2
    assert "--yes" in capsys.readouterr().err
    assert len(client.get("/api/sessions").json()["sessions"]) == 1


@pytest.mark.parametrize(("answer", "code", "left"), [("n", 1, 1), ("", 1, 1), ("y", 0, 0)])
def test_wipe_asks_first_on_a_terminal(
    answer: str,
    code: int,
    left: int,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post(client, {"hook_event_name": "beforeShellExecution", "command": "ls"})
    assert local_store.flush()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)
    assert main(["wipe"]) == code
    assert len(client.get("/api/sessions").json()["sessions"]) == left


def test_wipe_gives_up_within_its_budget_when_a_reader_holds_the_file(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post(client, {"hook_event_name": "beforeShellExecution", "command": f"echo {SECRET_WORD}"})
    assert local_store.flush()
    assert ls.WIPE_BUDGET_S <= 10.0  # the promise in the card
    monkeypatch.setattr(ls, "WIPE_BUDGET_S", 1.0)  # same code path, a shorter wait for the test
    reader = sqlite3.connect(data_dir() / ls.DB_NAME, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM steps").fetchall()  # a snapshot the log cannot pass
    try:
        started = time.monotonic()
        assert main(["wipe", "--yes"]) == 1
        elapsed = time.monotonic() - started
    finally:
        reader.execute("ROLLBACK")
        reader.close()
    err = capsys.readouterr().err
    assert elapsed < 3.0
    assert "in use" in err and "run it again" in err
    assert "nothing else was changed" not in err  # the rows are gone; do not claim otherwise

    assert main(["wipe", "--yes"]) == 0  # the reader is gone: the second run finishes the job
    assert history_bytes().count(SECRET_WORD.encode()) == 0


def test_wipe_does_not_hold_the_write_lock_while_it_waits_for_a_reader(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    post(client, {"hook_event_name": "beforeShellExecution", "command": "ls"})
    assert local_store.flush()
    monkeypatch.setattr(ls, "WIPE_BUDGET_S", 2.0)
    path = data_dir() / ls.DB_NAME
    reader = sqlite3.connect(path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM steps").fetchall()
    outcome: list[object] = []
    wiper = threading.Thread(target=lambda: outcome.append(_wipe_result(path)), daemon=True)
    try:
        wiper.start()
        time.sleep(0.8)  # the wipe is now waiting for the reader
        writer = sqlite3.connect(path, timeout=0, isolation_level=None)
        try:
            writer.execute("BEGIN IMMEDIATE")  # the recorder's own writer must still get in
            writer.execute("ROLLBACK")
        finally:
            writer.close()
    finally:
        wiper.join(5.0)
        reader.execute("ROLLBACK")
        reader.close()
    assert outcome == ["incomplete"]


def _wipe_result(path: Path) -> str:
    try:
        ls.wipe_file(path)
    except ls.WipeIncomplete:
        return "incomplete"
    return "done"


def test_wipe_of_an_empty_file_with_no_tables_is_a_clean_no_op(
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir().mkdir(parents=True)
    (data_dir() / ls.DB_NAME).write_bytes(b"")  # the recorder was stopped before it made the tables
    assert main(["wipe", "--yes"]) == 0
    assert "deleted 0 sessions and 0 steps" in capsys.readouterr().out


def test_wipe_leaves_the_file_private(client: TestClient) -> None:
    post(client, {"hook_event_name": "beforeShellExecution", "command": "ls"})
    assert local_store.flush()
    assert main(["wipe", "--yes"]) == 0
    assert (data_dir() / ls.DB_NAME).stat().st_mode & 0o077 == 0
