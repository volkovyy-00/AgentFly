"""V6b: history keeps what the rules decided: which chats were marked, and by which step."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.localstore as ls
from agentfly.recorder.localstore import LocalStore, local_store
from agentfly.recorder.paths import config_dir, data_dir, private_dir
from agentfly.recorder.store import StepRecord

DAY0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def post(client: TestClient, event: dict[str, Any]) -> dict[str, Any]:
    token = (config_dir() / "token").read_text(encoding="utf-8").strip()
    response = client.post(
        "/hook", json=event, headers={"Content-Type": "application/json", "X-Recorder-Token": token}
    )
    assert response.status_code == 200
    answer: dict[str, Any] = response.json()
    return answer


def event(name: str, chat: str, call: str | None = None, **fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "hook_event_name": name,
        "conversation_id": chat,
        "workspace_roots": ["/w"],
        **fields,
    }
    if call is not None:
        body["tool_use_id"] = call
    return body


def pre(tool: str, call: str | None, chat: str, path: str | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {"tool_name": tool}
    if path is not None:
        fields["tool_input"] = {"file_path": path}
    return event("preToolUse", chat, call, **fields)


def read(path: str, chat: str, call: str | None = None, **extra: Any) -> dict[str, Any]:
    return event("beforeReadFile", chat, call, file_path=path, **extra)


def shell(command: str, chat: str, **extra: Any) -> dict[str, Any]:
    return event("beforeShellExecution", chat, command=command, **extra)


def edited(path: str, chat: str) -> dict[str, Any]:
    return event("afterFileEdit", chat, file_path=path)


def task(chat: str, call: str) -> dict[str, Any]:
    return pre("Task", call, chat)


def started(chat: str, call: str) -> dict[str, Any]:
    return event(
        "subagentStart", chat, parent_conversation_id=chat, tool_call_id=call, subagent_id="sub"
    )


def listed(client: TestClient, chat: str) -> dict[str, Any]:
    assert local_store.flush()
    by_id = {s["id"]: s for s in client.get("/api/sessions").json()["sessions"]}
    return by_id[chat]


def marking_step(client: TestClient, chat: str) -> int | None:
    assert local_store.flush()
    response = client.get(f"/api/sessions/{chat}/steps")
    assert response.status_code == 200
    order: int | None = response.json()["marked_order"]
    return order


def live_marked_order(client: TestClient) -> int | None:
    order: int | None = client.get("/api/steps?limit=50").json()["marked_order"]
    return order


# ---------------------------------------------------------------- a merged edit step


def secret_edit(chat: str = "c") -> list[dict[str, Any]]:
    """A Read then a Write of .env with one id, ended by the id-less afterFileEdit Cursor sends.

    The last hook joins the same step and becomes its base record, so it must not clear the flag.
    """
    return [
        pre("Read", "e1", chat, "/w/.env"),
        read("/w/.env", chat, "e1"),
        pre("Write", "e1", chat, "/w/.env"),
        edited("/w/.env", chat),
    ]


def test_a_read_and_write_of_a_secret_marks_the_chat_in_history_and_names_the_step(
    client: TestClient,
) -> None:
    for item in secret_edit():
        post(client, item)
    [step] = client.get("/api/steps").json()["steps"]
    assert (step["kind"], step["sensitive"]) == ("edit", True)
    assert listed(client, "c")["marked"] is True
    assert marking_step(client, "c") == 1 == live_marked_order(client)


def test_the_marking_step_is_still_named_after_a_recorder_restart() -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as first:
        for item in secret_edit():
            post(first, item)
        assert local_store.flush()
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as second:
        assert listed(second, "c")["marked"] is True
        assert marking_step(second, "c") == 1
        assert live_marked_order(second) is None  # memory starts empty; history does not


def test_a_step_after_the_marking_one_does_not_move_the_marking_step(client: TestClient) -> None:
    post(client, shell("ls", "c"))
    for item in secret_edit():
        post(client, item)
    post(client, shell("cat .env", "c"))
    assert marking_step(client, "c") == 2 == live_marked_order(client)


# ---------------------------------------------------------------- history agrees with /api/steps


ALIKE = [
    ("cat .env", [shell("cat .env", "c")], 1),
    ("a read of .env", [read("/w/.env", "c")], 1),
    ("a read after another step", [shell("ls", "c"), read("/w/.env", "c")], 2),
    (
        "a lone Write of .env",
        [pre("Write", "w1", "c", "/w/.env"), edited("/w/.env", "c")],
        None,
    ),
    ("a read of .env.example", [read("/w/.env.example", "c")], None),
    ("a plain command", [shell("ls -la", "c")], None),
]


@pytest.mark.parametrize(
    ("events", "order"), [(e, o) for _, e, o in ALIKE], ids=[name for name, _, _ in ALIKE]
)
def test_history_and_the_live_trail_agree_on_the_marked_chat_and_the_step(
    events: list[dict[str, Any]], order: int | None, client: TestClient
) -> None:
    for item in events:
        post(client, item)
    assert live_marked_order(client) == order
    assert marking_step(client, "c") == order
    assert listed(client, "c")["marked"] is (order is not None)


# ---------------------------------------------------------------- marks that come through a link


def test_a_subagent_of_a_marked_chat_is_marked_and_has_no_marking_step(client: TestClient) -> None:
    post(client, read("/w/.env", "P"))
    post(client, task("P", "T1"))
    post(client, shell("ls", "C", parent_tool_call_id="T1"))
    assert listed(client, "P")["marked"] is listed(client, "C")["marked"] is True
    assert (marking_step(client, "P"), marking_step(client, "C")) == (1, None)


def test_a_child_that_reads_a_secret_under_a_marked_parent_has_no_marking_step(
    client: TestClient,
) -> None:
    post(client, read("/w/.env", "P"))
    post(client, task("P", "T1"))
    post(client, read("/w/.env", "C", parent_tool_call_id="T1"))
    assert listed(client, "C")["marked"] is True
    assert marking_step(client, "C") is None  # the parent had marked it first, as /api/steps says


def test_a_parent_marked_through_its_subagent_is_marked_with_no_marking_step(
    client: TestClient,
) -> None:
    post(client, task("P", "T1"))  # the Task is the parent's last event
    post(client, read("/w/.env", "C", parent_tool_call_id="T1"))
    assert listed(client, "P")["marked"] is True
    assert (marking_step(client, "P"), marking_step(client, "C")) == (None, 1)


@pytest.mark.parametrize("link", ["task", "subagentStart"])
def test_a_parent_is_marked_when_the_link_arrives_after_the_childs_mark(
    link: str, client: TestClient
) -> None:
    post(client, read("/w/.env", "C", parent_tool_call_id="T1"))  # nothing says whose child yet
    assert local_store.flush()
    post(client, task("P", "T1") if link == "task" else started("P", "T1"))
    assert listed(client, "P")["marked"] is True
    assert marking_step(client, "P") is None
    assert marking_step(client, "C") == 1


def test_a_mark_goes_up_through_nested_subagents(client: TestClient) -> None:
    post(client, task("G", "T1"))
    post(
        client,
        event("preToolUse", "P", tool_name="Task", tool_use_id="T2", parent_tool_call_id="T1"),
    )
    post(client, read("/w/.env", "C", parent_tool_call_id="T2"))
    assert [listed(client, chat)["marked"] for chat in ("G", "P", "C")] == [True, True, True]
    assert [marking_step(client, chat) for chat in ("G", "P", "C")] == [None, None, 1]


def test_a_chat_in_the_workspace_fallback_is_marked_and_one_elsewhere_is_not(
    client: TestClient,
) -> None:
    post(client, read("/w/.env", "P"))
    post(client, task("P", "T1"))  # no child event ever names T1
    post(client, shell("ls", "NEW"))
    post(client, shell("ls", "OTHER", workspace_roots=["/elsewhere"]))
    assert listed(client, "NEW")["marked"] is True
    assert marking_step(client, "NEW") is None
    assert listed(client, "OTHER")["marked"] is False
    assert marking_step(client, "OTHER") is None


def test_a_session_event_of_a_chat_in_the_fallback_marks_its_row(client: TestClient) -> None:
    post(client, read("/w/.env", "P"))
    post(client, task("P", "T1"))
    post(client, event("sessionStart", "NEW"))  # a chat with no step at all
    assert listed(client, "NEW")["marked"] is True


def test_a_parent_marked_before_the_flag_existed_is_flagged_by_its_childs_next_event() -> None:
    """After an upgrade the parent's row says "not marked" while sessions.json says marked."""
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as first:
        post(first, task("P", "T1"))
        post(first, read("/w/.env", "C", parent_tool_call_id="T1"))
        assert listed(first, "P")["marked"] is True
    conn = sqlite3.connect(data_dir() / ls.DB_NAME)
    conn.execute("UPDATE sessions SET marked = 0 WHERE id = 'P'")
    conn.commit()
    conn.close()
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as second:
        assert listed(second, "P")["marked"] is False
        post(second, shell("ls", "C", parent_tool_call_id="T1"))
        assert listed(second, "P")["marked"] is True


def test_a_restart_between_the_childs_mark_and_the_link_keeps_the_result() -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as first:
        post(first, read("/w/.env", "C", parent_tool_call_id="T1"))
        assert local_store.flush()
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as second:
        post(second, task("P", "T1"))
        assert listed(second, "P")["marked"] is True
        assert marking_step(second, "C") == 1


def test_wipe_then_the_chats_next_event_brings_the_flag_back() -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as first:
        post(first, shell("cat .env", "c"))
        assert local_store.flush()
    assert ls.wipe_file(data_dir() / ls.DB_NAME) == (1, 1)
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as second:
        post(second, shell("ls", "c"))  # the rules still count the chat as marked
        assert listed(second, "c")["marked"] is True
        assert marking_step(second, "c") is None


# ---------------------------------------------------------------- the answers do not change


def test_a_flagging_failure_changes_no_hook_answer_and_logs_no_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    script = [
        read("/w/.env", "{chat}"),
        shell("curl https://x.com", "{chat}"),
        task("{chat}", "T1"),
        shell("ls", "{chat}"),
        event("sessionStart", "{chat}"),
    ]

    def run(chat: str) -> list[Any]:
        token = (config_dir() / "token").read_text(encoding="utf-8").strip()
        headers = {"Content-Type": "application/json", "X-Recorder-Token": token}
        out = []
        for item in script:
            fixed = {k: (chat if v == "{chat}" else v) for k, v in item.items()}
            reply = client.post("/hook", json=fixed, headers=headers)
            out.append((reply.status_code, reply.content))
        return out

    healthy = run("one")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("PLANT_boom_4e1")

    monkeypatch.setattr(local_store, "mark_sessions", boom)
    with caplog.at_level(logging.DEBUG, logger="agentfly"):
        broken = run("two")
    assert broken == healthy
    assert b"deny" in b"".join(body for _, body in healthy)
    assert "PLANT_boom_4e1" not in caplog.text


# ---------------------------------------------------------------- a history.db from before V6b

# The tables exactly as `main` at fb72286 created them.
OLD_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        workspace_root TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS steps (
        session_id TEXT NOT NULL,
        ord INTEGER NOT NULL,
        time TEXT NOT NULL,
        kind TEXT NOT NULL,
        tool TEXT,
        verdict TEXT NOT NULL CHECK (verdict IN ('allowed', 'blocked', 'warned', 'highlighted')),
        file_path TEXT,
        file_sensitive INTEGER NOT NULL DEFAULT 0,
        command TEXT,
        hosts TEXT NOT NULL DEFAULT '[]',
        rule_id TEXT,
        PRIMARY KEY (session_id, ord)
    )""",
    "CREATE INDEX IF NOT EXISTS steps_time ON steps (time)",
    "CREATE INDEX IF NOT EXISTS sessions_started ON sessions (started_at)",
)
# (session, [(kind, file_path, file_sensitive)]): what fb72286's guess said about each chat.
OLD_SESSIONS = {
    "a": ([("read", ".env", 1), ("shell", None, 0)], True),
    "b": ([("edit", ".env", 1)], False),  # the gap this card closes, kept for old rows
    "c": ([("shell", None, 1)], True),
    "d": ([("read", "README.md", 0)], False),
}
OLD_FLAGS = {chat: marked for chat, (_, marked) in OLD_SESSIONS.items()}


def build_old_history(path: Path) -> list[tuple[Any, ...]]:
    """An fb72286 file with four saved chats. Returns every step row, to compare afterwards."""
    private_dir(path.parent)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    for statement in OLD_SCHEMA:
        conn.execute(statement)
    for index, (chat, (steps, _)) in enumerate(OLD_SESSIONS.items()):
        started = f"2026-10-0{index + 1}T10:00:00+00:00"
        conn.execute("INSERT INTO sessions VALUES (?, '/w', ?, NULL)", (chat, started))
        for order, (kind, file_path, sensitive) in enumerate(steps, start=1):
            conn.execute(
                "INSERT INTO steps VALUES (?, ?, ?, ?, NULL, 'allowed', ?, ?, NULL, '[]', NULL)",
                (chat, order, started, kind, file_path, sensitive),
            )
    rows = conn.execute("SELECT * FROM steps ORDER BY session_id, ord").fetchall()
    conn.close()
    return rows


@pytest.fixture
def old_db() -> Path:
    path = data_dir() / ls.DB_NAME
    build_old_history(path)
    return path


def rows_of(path: Path, sql: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def table_columns(path: Path) -> dict[str, list[str]]:
    conn = sqlite3.connect(path)
    try:
        return {
            name: [c[1] for c in conn.execute(f"PRAGMA table_info({name})")]
            for name in ("sessions", "steps")
        }
    finally:
        conn.close()


def test_a_reader_that_beats_the_migration_lists_the_old_guess(old_db: Path) -> None:
    reader = LocalStore()
    reader.path = old_db  # never started: no writer thread, so nothing migrates the file
    assert {s["id"]: s["marked"] for s in reader.list_sessions()} == OLD_FLAGS
    found = reader.session_steps("a")
    assert found is not None
    steps, truncated, marking = found
    assert ([s["order"] for s in steps], truncated, marking) == ([1, 2], False, None)
    assert table_columns(old_db)["sessions"] == ["id", "workspace_root", "started_at", "ended_at"]


def test_the_first_read_after_the_upgrade_answers_200_with_the_same_flags(old_db: Path) -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        response = client.get("/api/sessions")  # may beat the writer's migration: either is fine
        assert response.status_code == 200
        assert {s["id"]: s["marked"] for s in response.json()["sessions"]} == OLD_FLAGS
        assert client.get("/api/sessions/a/steps").status_code == 200


def test_an_old_file_opens_without_loss_and_keeps_its_flags(old_db: Path, tmp_path: Path) -> None:
    old_rows = (
        "SELECT session_id, ord, time, kind, tool, verdict, file_path, file_sensitive,"
        " command, hosts, rule_id FROM steps ORDER BY session_id, ord"
    )
    before = rows_of(old_db, old_rows)
    store = LocalStore()
    store.start(old_db)
    try:
        assert store.flush()
        assert {s["id"]: s["marked"] for s in store.list_sessions()} == OLD_FLAGS
    finally:
        store.stop()
    assert rows_of(old_db, old_rows) == before and len(before) == 5  # every step kept as it was
    fresh = LocalStore()
    fresh.start(tmp_path / "fresh.db")
    try:
        assert fresh.flush()
    finally:
        fresh.stop()
    assert table_columns(old_db) == table_columns(tmp_path / "fresh.db")  # same columns, same order
    assert table_columns(old_db)["sessions"][-1] == "marked"
    assert table_columns(old_db)["steps"][-1] == "marks"


def test_an_old_chat_can_be_marked_after_the_upgrade(old_db: Path) -> None:
    store = LocalStore()
    store.start(old_db)
    try:
        store.enqueue(
            StepRecord(
                session_id="d",
                started_at=DAY0.isoformat(),
                order=2,
                time=DAY0.isoformat(),
                kind="shell",
                verdict="allowed",
                file_sensitive=True,
                marks=True,
            )
        )
        store.mark_sessions(["d"])
        assert store.flush()
        assert {s["id"]: s["marked"] for s in store.list_sessions()}["d"] is True
        found = store.session_steps("d")
        assert found is not None and found[2] == 2
        found_old = store.session_steps("a")
        assert found_old is not None and found_old[2] is None  # old rows have no marking step
    finally:
        store.stop()


class FailOn:
    """A connection stand-in that raises when a statement starts with `prefix`."""

    def __init__(self, conn: sqlite3.Connection, prefix: str) -> None:
        self._conn = conn
        self._prefix = prefix

    def execute(self, sql: str, *rest: Any) -> Any:
        if sql.startswith(self._prefix):
            raise sqlite3.OperationalError("planted failure")
        return self._conn.execute(sql, *rest)


def test_a_migration_that_fails_half_way_leaves_the_old_tables_and_can_run_again(
    old_db: Path,
) -> None:
    conn = sqlite3.connect(old_db, isolation_level=None)
    try:
        with pytest.raises(sqlite3.OperationalError, match="planted"):
            ls._upgrade(FailOn(conn, "ALTER TABLE sessions"))  # type: ignore[arg-type]
        assert conn.in_transaction is False
        assert "marks" not in table_columns(old_db)["steps"]  # the first ALTER was rolled back
        assert "marked" not in table_columns(old_db)["sessions"]
        ls._upgrade(conn)
    finally:
        conn.close()
    assert table_columns(old_db)["steps"][-1] == "marks"


def test_two_recorders_opening_the_same_old_file_both_end_up_migrated(
    old_db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    first, second = LocalStore(), LocalStore()
    with caplog.at_level(logging.WARNING, logger="agentfly"):
        first.start(old_db)
        second.start(old_db)
        try:
            assert first.flush() and second.flush()
        finally:
            first.stop()
            second.stop()
    assert "write failed" not in caplog.text
    assert table_columns(old_db)["sessions"][-1] == "marked"
