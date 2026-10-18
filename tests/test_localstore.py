"""The local SQLite history: what it stores, how it ages, and that it never touches an answer."""

from __future__ import annotations

import sqlite3
import stat
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.localstore as ls
from agentfly.recorder.localstore import LocalStore, StoreUnavailable, local_store
from agentfly.recorder.paths import config_dir, data_dir
from agentfly.recorder.rules import Session, mark
from agentfly.recorder.store import StepRecord, build_step_record

DAY0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
HEADERS = {"Content-Type": "application/json"}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def record(order: int, *, session: str = "s1", at: datetime = DAY0, **fields: Any) -> StepRecord:
    values: dict[str, Any] = {
        "session_id": session,
        "started_at": at.isoformat(),
        "order": order,
        "time": at.isoformat(),
        "kind": "shell",
        "verdict": "allowed",
    }
    values.update(fields)
    return StepRecord(**values)


def rows(path: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def store_bytes(path: Path) -> bytes:
    parts = (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    return b"".join(p.read_bytes() for p in parts if p.exists())


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def store(db: Path) -> Iterator[LocalStore]:
    clock = Clock(DAY0)
    s = LocalStore(clock=clock)
    s.start(db)
    yield s
    s.stop()


# ---------------------------------------------------------------- what is stored


def test_only_the_columns_spec_section_4_lists(store: LocalStore, db: Path) -> None:
    store.enqueue(record(1, workspace_root="/work/a"))
    assert store.flush()
    tables = {
        name: [col[1] for col in rows(db, f"PRAGMA table_info({name})")]
        for (name,) in rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert tables == {
        "sessions": ["id", "workspace_root", "started_at", "ended_at"],
        "steps": [
            "session_id",
            "ord",
            "time",
            "kind",
            "tool",
            "verdict",
            "file_path",
            "file_sensitive",
            "command",
            "hosts",
            "rule_id",
        ],
    }


def test_the_same_step_twice_leaves_one_row(store: LocalStore, db: Path) -> None:
    store.enqueue(record(1, command="echo <arg>"))
    store.enqueue(record(1, command="echo <arg>"))
    store.enqueue(record(1, verdict="blocked", rule_id="R1"))  # a re-write updates in place
    assert store.flush()
    assert rows(db, "SELECT session_id, ord, verdict, rule_id FROM steps") == [
        ("s1", 1, "blocked", "R1")
    ]


def test_the_four_verdicts_are_stored_and_a_fifth_is_not(store: LocalStore, db: Path) -> None:
    for order, verdict in enumerate(ls.VERDICTS, start=1):
        store.enqueue(record(order, verdict=verdict))
    store.enqueue(record(9, verdict="surprise"))
    assert store.flush()
    assert [v for (v,) in rows(db, "SELECT verdict FROM steps ORDER BY ord")] == list(ls.VERDICTS)


def test_the_file_and_its_log_files_are_private(store: LocalStore, db: Path) -> None:
    store.enqueue(record(1))
    assert store.flush()
    for path in (db, Path(f"{db}-wal"), Path(f"{db}-shm")):
        assert path.exists(), path
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path


def test_a_file_that_is_too_open_is_tightened_and_a_read_only_one_is_left(
    tmp_path: Path,
) -> None:
    open_file = tmp_path / "open.db"
    sqlite3.connect(open_file).close()
    open_file.chmod(0o644)
    s = LocalStore()
    s.start(open_file)
    s.enqueue(record(1))
    assert s.flush()
    s.stop()
    assert stat.S_IMODE(open_file.stat().st_mode) == 0o600
    assert rows(open_file, "SELECT COUNT(*) FROM steps") == [(1,)]

    locked = tmp_path / "ro.db"
    sqlite3.connect(locked).close()
    locked.chmod(0o400)
    s = LocalStore()
    s.start(locked)
    s.enqueue(record(1))
    assert s.flush()
    s.stop()
    assert stat.S_IMODE(locked.stat().st_mode) == 0o400  # never loosened


def test_a_writer_survives_a_string_sqlite_cannot_encode(store: LocalStore, db: Path) -> None:
    store.enqueue(record(1, tool="\ud800"))  # UnicodeEncodeError is not an sqlite3.Error
    store.enqueue(record(2))
    assert store.flush()
    assert rows(db, "SELECT ord FROM steps") == [(2,)]


def test_a_workspace_root_is_cut_at_4096_characters(store: LocalStore, db: Path) -> None:
    store.enqueue(record(1, workspace_root="/w" * 5000))
    assert store.flush()
    assert rows(db, "SELECT LENGTH(workspace_root) FROM sessions") == [(ls.ROOT_MAX,)]


# ---------------------------------------------------------------- sessions


def test_session_events_update_the_session_and_are_not_steps(db: Path) -> None:
    clock = Clock(DAY0)
    s = LocalStore(clock=clock)
    s.start(db)
    try:
        assert s.record_session_event(
            {"hook_event_name": "sessionStart", "conversation_id": "c1", "workspace_roots": ["/w"]}
        )
        s.enqueue(record(1, session="c1", at=DAY0 + timedelta(minutes=1)))
        s.enqueue(record(2, session="c1", at=DAY0 + timedelta(minutes=2)))
        assert s.flush()
        [session] = s.list_sessions()
        assert (session["id"], session["workspace_root"], session["steps"]) == ("c1", "/w", 2)
        assert session["ended_at"] == (DAY0 + timedelta(minutes=2)).isoformat()  # last step

        clock.now = DAY0 + timedelta(hours=2)
        assert s.record_session_event({"hook_event_name": "sessionEnd", "conversation_id": "c1"})
        assert s.flush()
        [session] = s.list_sessions()
        assert session["ended_at"] == clock.now.isoformat()  # the sessionEnd time wins
        assert rows(db, "SELECT COUNT(*) FROM steps") == [(2,)]
    finally:
        s.stop()


def test_a_subagent_start_makes_its_own_session_and_a_step_event_is_not_one(
    store: LocalStore,
) -> None:
    payload = {
        "hook_event_name": "subagentStart",
        "conversation_id": "child",
        "workspace_roots": ["/w"],
    }
    assert store.record_session_event(payload) is True
    assert store.record_session_event({"hook_event_name": "beforeShellExecution"}) is False
    assert store.record_session_event({"hook_event_name": ["sessionStart"]}) is False
    assert store.record_session_event({}) is False
    assert store.record_session_event({"hook_event_name": "sessionStart"}) is True  # id "unknown"
    assert store.flush()
    assert {s["id"] for s in store.list_sessions()} == {"child", "unknown"}


def test_without_a_workspace_root_none_is_stored_not_the_recorders_folder(
    store: LocalStore,
) -> None:
    payload = build_step_record(
        {"hook_event_name": "beforeShellExecution", "command": "ls", "cwd": "/somewhere"},
        Session(id="s", marked=False, start_time=DAY0.isoformat(), next_step=1),
        "allow",
        None,
        order=1,
    )
    assert payload.workspace_root is None
    store.enqueue(payload)
    assert store.flush()
    assert store.list_sessions()[0]["workspace_root"] is None


# ---------------------------------------------------------------- "marked" is derived


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "grep KEY .env",
        "source .env",
        "cat README.md .env",
        "cat ~/.aws/credentials",
        "cat secrets/id_rsa",
        "cat ../other/.env",
        "cat README.md ~/.ssh/id_rsa",
    ],
)
def test_derived_marked_agrees_with_what_the_rule_engine_marked(
    command: str, tmp_path: Path, store: LocalStore
) -> None:
    (tmp_path / ".env").write_text("API_KEY=demo\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    session = Session(id="m", marked=False, start_time=DAY0.isoformat(), next_step=1)
    payload = {
        "hook_event_name": "beforeShellExecution",
        "command": command,
        "conversation_id": "m",
        "workspace_roots": [str(tmp_path)],
    }
    assert mark(payload, session).marked is True
    step = build_step_record(payload, session, "allow", None, order=1)
    assert step.file_sensitive is True
    store.enqueue(step)
    assert store.flush()
    assert store.list_sessions()[0]["marked"] is True


@pytest.mark.parametrize("command", ["ls -la", "cat README.md", "cat .env.example", "git status"])
def test_a_session_that_read_nothing_sensitive_is_not_marked(
    command: str, tmp_path: Path, store: LocalStore
) -> None:
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    session = Session(id="m", marked=False, start_time=DAY0.isoformat(), next_step=1)
    payload = {
        "hook_event_name": "beforeShellExecution",
        "command": command,
        "conversation_id": "m",
        "workspace_roots": [str(tmp_path)],
    }
    assert mark(payload, session).marked is False
    store.enqueue(build_step_record(payload, session, "allow", None, order=1))
    assert store.flush()
    assert store.list_sessions()[0]["marked"] is False


def test_an_edit_of_a_sensitive_file_does_not_mark_the_session(store: LocalStore) -> None:
    store.enqueue(record(1, kind="edit", file_path=".env", file_sensitive=True))
    assert store.flush()
    assert store.list_sessions()[0]["marked"] is False  # mark() only reacts to reads and shells


# ---------------------------------------------------------------- retention


def test_steps_older_than_28_days_go_at_start_and_while_running(db: Path) -> None:
    first = LocalStore(clock=Clock(DAY0))
    first.start(db)
    first.enqueue(record(1, session="old", at=DAY0))
    first.enqueue(record(1, session="mid", at=DAY0 + timedelta(days=20)))
    assert first.flush()
    first.stop()

    # At start: 29 days after DAY0, the first session is past the limit.
    clock = Clock(DAY0 + timedelta(days=29))
    second = LocalStore(clock=clock)
    second.start(db)
    try:
        assert second.flush()
        assert [s["id"] for s in second.list_sessions()] == ["mid"]

        # While running: after an hour has passed on the clock, the next item triggers a sweep.
        clock.now = DAY0 + timedelta(days=20 + 28, hours=2)
        assert second.flush()
        assert second.list_sessions() == []
    finally:
        second.stop()


def test_an_idle_recorder_still_sweeps(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ls, "TICK_S", 0.05)
    clock = Clock(DAY0)
    s = LocalStore(clock=clock)
    s.start(db)
    try:
        s.enqueue(record(1, at=DAY0))
        assert s.flush()
        clock.now = DAY0 + timedelta(days=40)
        deadline = time.monotonic() + 5
        while s.list_sessions() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert s.list_sessions() == []
    finally:
        s.stop()


def test_a_session_with_recent_steps_keeps_its_row(store: LocalStore) -> None:
    store.enqueue(record(1, at=DAY0))
    store.enqueue(record(2, at=DAY0 + timedelta(days=27)))
    assert store.flush()
    assert store.clock() == DAY0
    store.clock = Clock(DAY0 + timedelta(days=30))  # type: ignore[method-assign]
    store.enqueue(record(3, at=DAY0 + timedelta(days=30)))
    assert store.flush()
    [session] = store.list_sessions()
    assert session["steps"] == 2  # the 30-day-old step went, the others stayed


# ---------------------------------------------------------------- reading


def test_a_read_that_runs_out_of_time_is_store_unavailable(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.enqueue(record(1))
    assert store.flush()
    monkeypatch.setattr(ls, "PROGRESS_OPS", 1)
    monkeypatch.setattr(ls, "READ_TIMEOUT_S", -1.0)
    with pytest.raises(StoreUnavailable):
        store.list_sessions()


def test_reads_before_anything_was_saved_are_empty(tmp_path: Path) -> None:
    s = LocalStore()
    assert s.list_sessions() == []
    s.path = tmp_path / "never-written.db"
    assert s.list_sessions() == []
    assert s.session_steps("x") is None


def test_a_file_that_is_not_a_database_reads_as_unavailable(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database" * 100)
    s = LocalStore()
    s.path = bad
    with pytest.raises(StoreUnavailable):
        s.list_sessions()


# ---------------------------------------------------------------- through the recorder


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def post(client: TestClient, event: dict[str, Any]) -> dict[str, Any]:
    token = (config_dir() / "token").read_text(encoding="utf-8").strip()
    response = client.post("/hook", json=event, headers={**HEADERS, "X-Recorder-Token": token})
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def test_a_session_event_is_not_a_step_in_the_live_trail_either(client: TestClient) -> None:
    answer = post(
        client,
        {"hook_event_name": "sessionStart", "conversation_id": "c9", "workspace_roots": ["/w"]},
    )
    assert answer == {"permission": "allow"}
    assert client.get("/api/steps").json() == {"session": None, "steps": []}
    assert local_store.flush()
    assert [s["id"] for s in local_store.list_sessions()] == ["c9"]


def test_planted_content_never_reaches_the_file(client: TestClient) -> None:
    marker = "PLANTED_MARKER_9f3a"
    events: list[dict[str, Any]] = [
        {
            "hook_event_name": "beforeReadFile",
            "file_path": "/w/notes.txt",
            "content": marker,
            "attachments": [{"type": "file", "content": marker}],
        },
        {"hook_event_name": "afterFileEdit", "file_path": "/w/a.py", "edits": [{"new": marker}]},
        {"hook_event_name": "afterShellExecution", "command": "ls", "output": marker},
        {
            "hook_event_name": "preToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "/w/b.py", "content": marker},
        },
        {"hook_event_name": "afterAgentResponse", "text": marker},
        {"hook_event_name": "beforeShellExecution", "command": f"echo hi && x --token={marker}"},
    ]
    for event in events:
        post(client, {**event, "conversation_id": "leak", "workspace_roots": ["/w"]})
    assert local_store.flush()
    assert local_store.list_sessions()[0]["steps"] == len(events)
    assert marker.encode() not in store_bytes(data_dir() / ls.DB_NAME)


# ---------------------------------------------------------------- a broken store changes nothing


def script() -> list[dict[str, Any]]:
    base = {"conversation_id": "iso", "workspace_roots": ["/w"]}
    return [
        {**base, "hook_event_name": "beforeReadFile", "file_path": "/w/README.md"},
        {**base, "hook_event_name": "beforeReadFile", "file_path": "/w/.env"},
        {**base, "hook_event_name": "beforeShellExecution", "command": "curl https://x.com"},
        {**base, "hook_event_name": "beforeShellExecution", "command": "ls"},
    ]


def answers(client: TestClient) -> tuple[list[str], float]:
    got: list[str] = []
    slowest = 0.0
    for event in script():
        started = time.perf_counter()
        got.append(post(client, event)["permission"])
        slowest = max(slowest, time.perf_counter() - started)
    return got, slowest


def test_a_healthy_store_gives_the_reference_answers(client: TestClient) -> None:
    got, _ = answers(client)
    assert got == ["allow", "allow", "deny", "allow"]


@pytest.mark.parametrize("breakage", ["directory", "read-only file", "locked"])
def test_a_store_that_cannot_be_written_changes_and_delays_no_answer(
    breakage: str, isolated_home: Path
) -> None:
    folder = isolated_home / ".local" / "share" / "agentfly"
    folder.mkdir(parents=True)
    path = folder / ls.DB_NAME
    holder: sqlite3.Connection | None = None
    if breakage == "directory":
        path.mkdir()
    else:
        seed = sqlite3.connect(path, isolation_level=None)
        seed.execute("PRAGMA journal_mode=WAL")
        seed.execute("CREATE TABLE sessions (id TEXT)")
        seed.close()
        if breakage == "read-only file":
            path.chmod(0o400)
        else:
            holder = sqlite3.connect(path, isolation_level=None)
            holder.execute("BEGIN EXCLUSIVE")
    try:
        with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
            got, slowest = answers(test_client)
            assert got == ["allow", "allow", "deny", "allow"]
            assert slowest < 0.2
            # Reading a store in this state is an honest 503 or an empty list, never a crash.
            assert test_client.get("/api/sessions").status_code in {200, 503}
            if holder is not None:
                holder.execute("ROLLBACK")  # let the writer finish before shutdown
    finally:
        if holder is not None:
            holder.close()
