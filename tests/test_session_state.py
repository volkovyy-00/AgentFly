"""F11: session notes reach the disk when they must, and stay off the hook path otherwise.

A change that makes a chat stricter (mark, trigger, inherited window, parent link, a parent changed
by propagation) and every links.json change is written before the answer; the step counter, the
activity time and a plain new chat wait for the writer. D29 drops notes idle for 29 days, and CR1
makes a pending Task hand on what its chat holds when the new chat arrives.

"Killed" below means `Recorder.restart()` with no flush: a new store reads whatever the first one
had put on disk, which is what a SIGKILL leaves (`tests/test_session_kill.py` does the real kill).
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import statistics
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.localstore as ls
import agentfly.recorder.rules as rules_mod
import agentfly.recorder.sessions as sessions_module
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.paths import config_dir, data_dir
from agentfly.recorder.rules import Session
from agentfly.recorder.sessions import FALLBACK_SECONDS, IDLE_DROP_SECONDS, SessionStore
from tests.helpers import wallclock
from tests.recorder_harness import Clock, Recorder
from tests.rules_helpers import default_with, ruleset_of

CURL = "curl https://x.com"
INSTALL = "pip install requests"
PUSH = "git push origin main"
DAY = 86400.0
HANG_GUARD_S = 10.0  # a test gives up on a thread it waits for after this: a hang guard
LISTS = 'install_cmds = ["pip install"]\npush_cmds = ["git push"]\n'
NO_PUSH = """
[[rule]]
id = "no-push-after-install"
kind = "after_then"
severity = "block"
message = "No pushing after an install in this chat."
after = { event = ["shell"], command = "install_cmds" }
then = { event = ["shell"], command = "push_cmds" }
  [[rule.test]]
  steps = ["shell: pip install x", "shell: git push"]
  expect = "block"
  [[rule.test]]
  steps = ["shell: git push"]
  expect = "allow"
"""


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def rec(tmp_path: Path, clock: Clock) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data", clock)
    app_module._store = previous


@pytest.fixture()
def armed() -> None:
    """A rule that sets a trigger which is not R1's mark: no push once a chat ran an install."""
    rules_mod.activate(ruleset_of(default_with(LISTS, NO_PUSH)))


def says(rec: Recorder, chat: str, command: str, **fields: Any) -> str:
    return rec.run(chat, command, **fields)["permission"]


def event(chat: str, **fields: Any) -> dict[str, Any]:
    return {"hook_event_name": "beforeShellExecution", "conversation_id": chat, **fields}


# ---------------------------------------------------------------- on disk before the answer


def mark(rec: Recorder) -> Callable[[], str]:
    rec.read("A", "/w/.env")
    return lambda: says(rec, "A", CURL)


def trigger(rec: Recorder) -> Callable[[], str]:
    says(rec, "A", INSTALL)
    return lambda: says(rec, "A", PUSH)


def task_of_a_marked_chat(rec: Recorder) -> Callable[[], str]:
    rec.read("A", "/w/.env")
    rec.task("A", "T1")  # no child names it: a new chat in the workspace inherits
    return lambda: says(rec, "NEW", CURL)


def subagent_link(rec: Recorder) -> Callable[[], str]:
    rec.read("A", "/w/.env")
    rec.task("A", "T1")
    says(rec, "C", "ls", parent_tool_call_id="T1")
    return lambda: says(rec, "C", CURL, parent_tool_call_id="T1")


def chat_in_an_inherited_window(rec: Recorder) -> Callable[[], str]:
    rec.read("A", "/w/.env")
    rec.task("A", "T1")
    says(rec, "NEW", "ls")  # opens inside the 30-minute window
    rec.store.links_path.unlink()  # only its own note can carry the window now
    return lambda: says(rec, "NEW", CURL)


def parent_changed_by_propagation(rec: Recorder) -> Callable[[], str]:
    rec.task("P", "T1")
    rec.read("C", "/w/.env", parent_tool_call_id="T1")
    return lambda: says(rec, "P", CURL)


def trigger_in_a_fallback_chat(rec: Recorder) -> Callable[[], str]:
    says(rec, "A", INSTALL)
    rec.task("A", "T1")
    says(rec, "NEW", "ls")
    rec.store.links_path.unlink()
    return lambda: says(rec, "NEW", PUSH)


SCENARIOS = [
    mark,
    trigger,
    task_of_a_marked_chat,
    subagent_link,
    chat_in_an_inherited_window,
    parent_changed_by_propagation,
    trigger_in_a_fallback_chat,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.__name__)
def test_what_makes_a_chat_stricter_is_on_disk_when_the_answer_is_given(
    rec: Recorder, armed: None, scenario: Callable[[Recorder], Callable[[], str]]
) -> None:
    probe = scenario(rec)
    rec.restart()  # killed right after the answer: no flush
    assert probe() == "deny"


# ---------------------------------------------------------------- what may wait


def test_a_plain_action_writes_nothing_until_the_writer_or_a_flush(
    rec: Recorder, clock: Clock
) -> None:
    says(rec, "A", "ls")
    says(rec, "A", "ls")
    assert not rec.path.exists() and not rec.store.links_path.exists()
    rec.store.flush()
    [row] = json.loads(rec.path.read_text(encoding="utf-8"))
    assert row["id"] == "A" and row["next_step"] == 3 and row["last_active"] == clock.now
    stamp = rec.path.stat().st_mtime_ns
    rec.store.flush()  # nothing changed: nothing is written
    assert rec.path.stat().st_mtime_ns == stamp


def test_a_strict_write_carries_the_lazy_fields_too(rec: Recorder) -> None:
    says(rec, "A", "ls")
    rec.read("B", "/w/.env")  # strict: the whole file is written
    rows = {row["id"]: row for row in json.loads(rec.path.read_text(encoding="utf-8"))}
    assert rows["A"]["next_step"] == 2 and rows["B"]["marked"] is True


def test_the_session_file_is_a_json_list_without_indent(rec: Recorder) -> None:
    rec.read("A", "/w/.env")
    text = rec.path.read_text(encoding="utf-8")
    assert isinstance(json.loads(text), list) and "\n  " not in text


# ---------------------------------------------------------------- the file cannot be written


def block_the_file(path: Path) -> None:
    """A directory where sessions.json goes: the write fails, whatever the folder's mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()


def test_an_action_that_changes_nothing_is_answered_with_the_file_unwritable(rec: Recorder) -> None:
    block_the_file(rec.path)
    assert says(rec, "A", "ls") == "allow"
    assert says(rec, "A", "ls") == "allow"


def test_a_failed_save_of_a_mark_is_an_error_and_the_mark_still_holds_in_memory(
    rec: Recorder,
) -> None:
    block_the_file(rec.path)
    with pytest.raises(OSError):
        rec.read("A", "/w/.env")
    assert says(rec, "A", CURL) == "deny"  # answered from memory, no second error
    rec.path.rmdir()
    rec.store.flush()  # the writer's retry
    rec.restart()
    assert says(rec, "A", CURL) == "deny"


def test_a_failed_save_of_a_link_is_an_error(rec: Recorder) -> None:
    block_the_file(rec.store.links_path)
    with pytest.raises(OSError):
        rec.task("A", "T1")


@pytest.fixture()
def served() -> Iterator[TestClient]:
    """The recorder's own start and stop (lifespan), with Neo4j off."""
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        app_module.graph_store.enabled = False
        yield client


@pytest.fixture()
def lenient_client() -> Iterator[TestClient]:
    with TestClient(
        app_module.app, base_url="http://127.0.0.1:8787", raise_server_exceptions=False
    ) as client:
        app_module.graph_store.enabled = False
        yield client


def post(client: TestClient, body: dict[str, Any]) -> Any:
    token = (config_dir() / "token").read_text(encoding="utf-8").strip()
    return client.post(
        "/hook", json=body, headers={"Content-Type": "application/json", "X-Recorder-Token": token}
    )


def test_through_the_server_a_failed_save_is_a_500_and_the_next_action_is_answered(
    lenient_client: TestClient,
) -> None:
    block_the_file(data_dir() / "sessions.json")
    marking = {**event("A"), "hook_event_name": "beforeReadFile", "file_path": "/w/.env"}
    assert post(lenient_client, marking).status_code == 500  # the client then applies its guard
    answer = post(lenient_client, event("A", command="ls", cwd=""))
    assert answer.status_code == 200 and answer.json() == {"permission": "allow"}
    denied = post(lenient_client, event("A", command=CURL, cwd=""))
    assert denied.status_code == 200 and denied.json()["permission"] == "deny"


# ---------------------------------------------------------------- one writer, in order


def with_save_gate(
    store: SessionStore, failures: int, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Event, threading.Event]:
    """Make `save` take its snapshot, say so, wait for the gate, then fail `failures` times."""
    inside, gate = threading.Event(), threading.Event()
    real_save = store.save
    left = {"failures": failures}

    def save() -> None:
        real_save()  # the snapshot, before the wait
        inside.set()
        gate.wait(10)
        if left["failures"]:
            left["failures"] -= 1
            raise OSError("disk full")

    monkeypatch.setattr(store, "save", save)
    return inside, gate


def run_in_thread(work: Callable[[], None], errors: list[BaseException]) -> threading.Thread:
    def target() -> None:
        try:
            work()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    return thread


@pytest.mark.parametrize(
    "failures", [0, 1, 99], ids=["write-works", "write-fails-once", "write-keeps-failing"]
)
def test_a_commit_waits_for_the_write_carrying_its_change_and_does_not_trust_one_that_failed(
    tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch, failures: int
) -> None:
    store = SessionStore(tmp_path / "s.json", clock=clock)
    session = store.observe(event("P"))
    inside, gate = with_save_gate(store, failures, monkeypatch)
    store._remember(replace(session, marked=True))  # the request thread's change; no commit yet
    writer_errors: list[BaseException] = []
    commit_errors: list[BaseException] = []
    writer = run_in_thread(store.flush, writer_errors)  # the background writer picks it up first
    assert inside.wait(10)
    committer = run_in_thread(store.commit, commit_errors)
    committer.join(0.3)
    assert committer.is_alive()  # it must not answer while the write is only half done
    gate.set()
    writer.join(10)
    committer.join(10)
    assert len(writer_errors) == (1 if failures else 0)  # the writer's failure was real
    if failures > 1:
        assert len(commit_errors) == 1 and isinstance(commit_errors[0], OSError)
    else:
        assert not commit_errors  # the write worked, or the commit wrote it itself
        assert json.loads((tmp_path / "s.json").read_text())[0]["marked"] is True


def test_a_strict_change_is_on_disk_whenever_commit_returns_while_another_thread_flushes(
    tmp_path: Path, clock: Clock
) -> None:
    path = tmp_path / "s.json"
    store = SessionStore(path, clock=clock)
    stop = threading.Event()

    def hammer() -> None:
        while not stop.is_set():
            store.flush()

    thread = threading.Thread(target=hammer)
    thread.start()
    try:
        for number in range(40):
            chat = f"c{number}"
            store.put(replace(store.observe(event(chat)), marked=True))
            on_disk = {r["id"] for r in json.loads(path.read_text()) if r["marked"]}
            assert chat in on_disk
    finally:
        stop.set()
        thread.join(10)


# ---------------------------------------------------------------- 5000 chats cost nothing extra


def note(chat: str, **fields: Any) -> dict[str, Any]:
    """A session note as an older recorder wrote it (no activity time)."""
    return {"id": chat, "marked": False, "start_time": "t", "next_step": 1, **fields}


def write_notes(path: Path, *rows: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(rows)), encoding="utf-8")


def store_with(folder: Path, chats: int, clock: Clock) -> SessionStore:
    write_notes(
        folder / "sessions.json",
        *(note(f"chat-{n:05d}", marked=n % 50 == 0, next_step=40) for n in range(chats)),
        note("hot"),
    )
    return SessionStore(folder / "sessions.json", clock=clock)


def hook_ms(store: SessionStore, payload: dict[str, Any]) -> float:
    app_module._store = store
    started = time.perf_counter()
    app_module.apply_rules(dict(payload))
    return (time.perf_counter() - started) * 1000


@wallclock
def test_with_5000_chats_a_hook_that_changes_nothing_costs_no_more_than_with_10(
    tmp_path: Path, clock: Clock
) -> None:
    previous = app_module._store
    app_module.graph_store.enabled = False
    small = store_with(tmp_path / "small", 10, clock)
    big = store_with(tmp_path / "big", 5000, clock)
    stamp = big.path.stat().st_mtime_ns
    payload = event("hot", command="ls", cwd="", workspace_roots=["/w"])
    try:
        for _ in range(5):  # warm both
            hook_ms(small, payload)
            hook_ms(big, payload)
        few: list[float] = []
        many: list[float] = []
        for _ in range(80):  # interleaved: a loaded machine slows both alike
            few.append(hook_ms(small, payload))
            many.append(hook_ms(big, payload))
    finally:
        app_module._store = previous
    assert statistics.median(many) - statistics.median(few) < 5.0
    assert big.path.stat().st_mtime_ns == stamp  # and nothing was written on the way


# ---------------------------------------------------------------- the step counter


def next_step_of(store: SessionStore, chat: str) -> int:
    session = store.get(chat)
    assert session is not None
    return session.next_step


def test_the_counter_is_raised_to_what_history_holds(tmp_path: Path, clock: Clock) -> None:
    write_notes(tmp_path / "s.json", note("P", next_step=3))
    store = SessionStore(tmp_path / "s.json", clock=clock)
    store.raise_counters({"P": 9, "Q": 4, "R": 2})
    assert next_step_of(store, "P") == 9
    assert store.observe(event("Q")).next_step == 4  # a chat with no note yet
    store.raise_counters({"P": 2})  # a lower number never lowers it
    assert next_step_of(store, "P") == 9
    store.put(Session(id="P", marked=False, start_time="t", next_step=1))  # a stale copy
    assert next_step_of(store, "P") == 9


def make_history(path: Path, steps: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    for statement in ls._SCHEMA:
        conn.execute(statement)
    for chat, count in steps.items():
        for order in range(1, count + 1):
            conn.execute(
                "INSERT INTO steps (session_id, ord, time, kind, verdict)"
                " VALUES (?, ?, 't', 'shell', 'allowed')",
                (chat, order),
            )
    conn.commit()
    conn.close()


def test_next_orders_is_the_first_unused_order_of_each_chat(tmp_path: Path) -> None:
    make_history(tmp_path / "h.db", {"a": 2, "b": 7})
    assert ls.next_orders(tmp_path / "h.db") == {"a": 3, "b": 8}


def test_next_orders_is_empty_when_nothing_can_be_read(tmp_path: Path) -> None:
    assert ls.next_orders(tmp_path / "missing.db") == {}
    (tmp_path / "empty.db").write_bytes(b"")
    assert ls.next_orders(tmp_path / "empty.db") == {}
    (tmp_path / "junk.db").write_bytes(b"not a database" * 40)
    assert ls.next_orders(tmp_path / "junk.db") == {}


def test_at_start_the_counter_comes_from_history() -> None:
    make_history(data_dir() / ls.DB_NAME, {"c1": 5})
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        app_module.graph_store.enabled = False
        post(client, event("c1", command="ls", cwd=""))
        saved = app_module.get_store().get("c1")
        assert saved is not None and saved.next_step == 7  # this step was number 6


def test_a_swept_chat_still_numbers_its_next_step_after_what_history_holds() -> None:
    """The sweep runs first at start, so the floor of a dropped note is not lost with it."""
    write_notes(data_dir() / "sessions.json", note("old", last_active=time.time() - 40 * DAY))
    make_history(data_dir() / ls.DB_NAME, {"old": 5})
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        app_module.graph_store.enabled = False
        assert app_module.get_store().get("old") is None
        post(client, event("old", command="ls", cwd=""))
        assert next_step_of(app_module.get_store(), "old") == 7  # this step was number 6


# ---------------------------------------------------------------- old notes (D29)


def idle(rec: Recorder, chat: str, **fields: Any) -> None:
    """A note last active IDLE_DROP_SECONDS ago (stored as given: `put` keeps a set time)."""
    rec.store.put(
        Session(
            id=chat,
            marked=False,
            start_time="t",
            next_step=1,
            last_active=rec.clock.now - IDLE_DROP_SECONDS,
            **fields,
        )
    )


def test_a_note_idle_29_days_goes_and_one_idle_28_days_stays(rec: Recorder, clock: Clock) -> None:
    says(rec, "OLD", "ls")
    clock.now += DAY
    says(rec, "NEWER", "ls")
    clock.now += 28 * DAY  # OLD: 29 days, NEWER: 28
    assert rec.store.sweep() == 1
    assert rec.store.get("OLD") is None and rec.store.get("NEWER") is not None


def test_a_chat_that_returns_after_a_sweep_never_reuses_an_order_number(
    rec: Recorder, clock: Clock
) -> None:
    for _ in range(5):
        says(rec, "A", "ls")
    clock.now += IDLE_DROP_SECONDS + 1  # a second past the 29 days
    assert rec.store.sweep() == 1 and rec.store.get("A") is None
    says(rec, "A", "ls")  # it returns; the recorder was not restarted
    orders = [step["order"] for step in memory_steps.snapshot(all_steps=True)["steps"]]
    assert orders == [1, 2, 3, 4, 5, 6]  # the sixth step is number 6, not 1 again


def test_a_subagent_marked_only_through_its_parent_survives_the_sweep(
    rec: Recorder, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec.read("P", "/w/.env")
    rec.task("P", "T1")
    says(rec, "C", "ls", parent_tool_call_id="T1")
    child = rec.store.get("C")
    assert child is not None and not child.marked  # it holds the mark only through its parent
    clock.now += 30 * DAY
    assert rec.store.sweep() == 0 and rec.store.get("C") is not None
    # 2,500 Task calls from other chats push old calls out of the bounded memory of calls; the one
    # C points to must stay (writes are skipped as in the F5 flood tests: only memory matters)
    monkeypatch.setattr(rec.store, "save", lambda: None)
    monkeypatch.setattr(rec.store, "save_links", lambda: None)
    for number in range(2500):
        rec.task("OTHER", f"flood-{number}", workspace_roots=["/elsewhere"])
    monkeypatch.undo()
    rec.store.save()
    rec.store.save_links()
    assert len(rec.store.calls) <= 2000 and rec.store.calls["T1"] == "P"
    rec.restart()
    assert says(rec, "C", CURL, parent_tool_call_id="T1") == "deny"


def test_the_sweep_keeps_what_d29_keeps(rec: Recorder, clock: Clock, armed: None) -> None:
    says(rec, "idle", "ls")
    rec.read("marked", "/w/.env")
    says(rec, "trigger", INSTALL)
    says(rec, "PARENT", "ls")
    says(rec, "Y", "ls")
    clock.now += 40 * DAY
    soon = clock.now + 600
    idle(rec, "window", inherited_until=soon)
    idle(rec, "trigger-window", inherited_triggers={"no-push-after-install": soon})
    idle(rec, "C", parent_call="T1", parent_id="PARENT", inherited_until=soon)
    idle(rec, "X", parent_call="T2", parent_id="Y")
    rec.store.calls.update({"T1": "PARENT", "T2": "Y"})
    expired = clock.now - 1
    idle(rec, "expired", inherited_until=expired, inherited_triggers={"x": expired})

    gone = {"idle", "X", "Y", "expired"}
    stays = {"marked", "trigger", "PARENT", "C", "window", "trigger-window"}
    assert rec.store.sweep() == len(gone)
    assert {c for c in gone | stays if rec.store.get(c) is not None} == stays
    assert rec.store.calls == {"T1": "PARENT"}  # the call of two dropped chats goes with them
    assert rec.store.sweep() == 0

    rec.store.flush()
    rec.restart()
    assert says(rec, "marked", CURL) == "deny"
    assert says(rec, "trigger", PUSH) == "deny"
    assert says(rec, "window", CURL) == "deny"
    assert says(rec, "C", CURL, parent_tool_call_id="T1") == "deny"


def test_a_pending_task_and_the_call_a_kept_chat_points_to_survive_the_sweep(
    rec: Recorder, clock: Clock
) -> None:
    rec.read("P", "/w/.env")
    rec.task("P", "T1")
    clock.now += FALLBACK_SECONDS / 2
    assert rec.store.sweep() == 0
    assert "T1" in rec.store.pending and rec.store.calls == {"T1": "P"}
    clock.now += 40 * DAY  # P is marked and T1 is old by now, but a kept chat's call stays
    assert rec.store.sweep() == 0 and rec.store.calls == {"T1": "P"}
    assert rec.store.pending == {}  # the stale pending record went, as it does at the next Task


def test_a_hackathon_file_loads_with_every_mark_and_the_first_sweep_drops_nothing(
    rec: Recorder, clock: Clock
) -> None:
    write_notes(rec.path, note("s1", marked=True, next_step=4), note("s2", next_step=9))
    rec.restart()
    loaded = rec.store.get("s2")
    assert loaded is not None and loaded.last_active == clock.now  # counted from this start
    assert rec.store.sweep() == 0
    assert says(rec, "s1", CURL) == "deny"
    clock.now += IDLE_DROP_SECONDS  # from then on they age like any other note
    assert rec.store.sweep() == 1  # s2; s1 is marked
    assert rec.store.get("s1") is not None


@pytest.mark.parametrize("junk", ["soon", -5, True, None, [], 0])
def test_a_damaged_activity_time_counts_from_this_start(
    rec: Recorder, clock: Clock, junk: Any
) -> None:
    write_notes(rec.path, note("s", last_active=junk))
    rec.restart()
    loaded = rec.store.get("s")
    assert loaded is not None and loaded.last_active == clock.now


def test_the_activity_time_round_trips(rec: Recorder, clock: Clock) -> None:
    says(rec, "A", "ls")
    clock.now += 100
    rec.store.flush()
    rec.restart()
    kept = rec.store.get("A")
    assert kept is not None and kept.last_active == clock.now - 100


# ---------------------------------------------------------------- CR1


def test_a_chat_with_only_a_trigger_that_is_marked_later_hands_the_mark_to_a_fallback_subagent(
    rec: Recorder, armed: None
) -> None:
    says(rec, "P", INSTALL)  # a trigger, no R1 mark
    rec.task("P", "T1")
    assert rec.store.pending["T1"]["marked"] is False
    rec.read("P", "/w/.env")  # marked afterwards
    assert says(rec, "NEW", CURL) == "deny"  # R1, not the trigger's rule
    rec.restart()
    assert says(rec, "NEW", CURL) == "deny"


def test_the_mark_reaches_the_fallback_subagent_after_a_restart_too(
    rec: Recorder, armed: None
) -> None:
    says(rec, "P", INSTALL)
    rec.task("P", "T1")
    rec.read("P", "/w/.env")
    rec.restart()  # the subagent only appears afterwards
    assert says(rec, "NEW", CURL) == "deny"


def test_a_chat_that_arrived_before_the_mark_is_not_marked_by_it(
    rec: Recorder, clock: Clock, armed: None
) -> None:
    says(rec, "P", INSTALL)
    rec.task("P", "T1")
    assert says(rec, "EARLY", CURL) == "allow"  # it arrived while the parent held a trigger only
    rec.read("P", "/w/.env")
    assert says(rec, "EARLY", CURL) == "allow"  # it keeps what the parent held when it arrived
    assert says(rec, "LATE", CURL) == "deny"
    clock.now += FALLBACK_SECONDS + 1  # the window is still counted from the Task
    assert says(rec, "TOO-LATE", CURL) == "allow"


def test_the_stored_snapshot_is_still_a_floor(rec: Recorder) -> None:
    rec.read("P", "/w/.env")
    rec.task("P", "T1")
    rec.store.flush()
    kept = [row for row in json.loads(rec.path.read_text("utf-8")) if row["id"] != "P"]
    write_notes(rec.path, *kept)  # the parent's note is gone (a sweep, a damaged file)
    rec.restart()
    assert says(rec, "NEW", CURL) == "deny"  # the record made at the Task still hands on its mark


# ---------------------------------------------------------------- start, background writer, stop


@pytest.fixture()
def quick_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions_module, "SAVE_DELAY_S", 0.05)


@pytest.fixture()
def slow_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions_module, "SAVE_DELAY_S", 3600.0)


@pytest.fixture()
def quick_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions_module, "SWEEP_EVERY_SECONDS", 0.05)


def wait_for(check: Callable[[], bool], seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


def saved_ids() -> set[str] | None:
    """The chats in sessions.json now, or None while there is no file."""
    path = data_dir() / "sessions.json"
    if not path.exists():
        return None
    return {row["id"] for row in json.loads(path.read_text(encoding="utf-8"))}


@wallclock
def test_the_background_writer_saves_what_may_wait(quick_writer: None, served: TestClient) -> None:
    post(served, event("A", command="ls", cwd=""))
    path = data_dir() / "sessions.json"
    assert wait_for(path.exists)
    assert json.loads(path.read_text(encoding="utf-8"))[0]["next_step"] == 2


def test_a_clean_stop_saves_everything(slow_writer: None) -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        app_module.graph_store.enabled = False
        post(client, event("A", command="ls", cwd=""))
        post(client, event("A", command="ls", cwd=""))
        assert saved_ids() is None  # still waiting
    [row] = json.loads((data_dir() / "sessions.json").read_text(encoding="utf-8"))
    assert row["id"] == "A" and row["next_step"] == 3


def test_a_clean_stop_does_not_raise_when_the_file_cannot_be_written(
    slow_writer: None, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        app_module.graph_store.enabled = False
        post(client, event("A", command="ls", cwd=""))
        block_the_file(data_dir() / "sessions.json")
    assert "last save failed" in caplog.text


@wallclock
def test_notes_idle_29_days_are_swept_at_start_and_the_file_follows(quick_writer: None) -> None:
    long_ago = time.time() - 40 * DAY
    write_notes(
        data_dir() / "sessions.json",
        note("old", last_active=long_ago),
        note("old-marked", marked=True, last_active=1.0),
    )
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787"):
        store = app_module.get_store()
        assert store.get("old") is None and store.get("old-marked") is not None
        assert wait_for(lambda: saved_ids() == {"old-marked"})  # with no hook to wake the writer


@wallclock
def test_the_sweep_runs_again_while_the_recorder_is_up(
    quick_sweep: None, quick_writer: None, served: TestClient
) -> None:
    post(served, event("A", command="ls", cwd=""))
    store = app_module.get_store()
    assert store.get("A") is not None
    assert wait_for(lambda: saved_ids() == {"A"})
    store.clock = lambda: time.time() + 40 * DAY
    assert wait_for(lambda: store.get("A") is None)
    assert wait_for(lambda: saved_ids() == set())  # and the file follows


@wallclock
def test_one_failing_sweep_does_not_end_the_hourly_job(
    quick_sweep: None, served: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def flaky() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(app_module.get_store(), "sweep", flaky)
    assert wait_for(lambda: len(calls) >= 3)


def test_housekeeping_that_fails_at_start_does_not_stop_the_recorder(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*_args: Any) -> Any:
        raise RuntimeError("odd data")

    monkeypatch.setattr(SessionStore, "sweep", broken)
    monkeypatch.setattr(app_module, "next_orders", broken)
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as client:
        app_module.graph_store.enabled = False
        assert post(client, event("A", command="ls", cwd="")).json() == {"permission": "allow"}
    assert "sweep skipped" in caplog.text and "step counters skipped" in caplog.text


@wallclock
def test_a_clean_stop_does_not_wait_for_ever_for_a_stuck_write(
    tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    wait = 0.25
    monkeypatch.setattr(sessions_module, "STOP_WAIT_S", wait)

    def closing_time(name: str, stuck: bool) -> float:
        """How long `close()` takes on a store that has a change to save; with `stuck`, a writer
        sits in a write that never ends (the lock is held). It runs on a thread the test can
        give up on, so a stop that waits for ever fails the test instead of hanging it."""
        store = SessionStore(tmp_path / f"{name}.json", clock=clock)
        store.observe(event("A"))
        took: list[float] = []

        def close() -> None:
            started = time.monotonic()
            store.close()
            took.append(time.monotonic() - started)

        closer = threading.Thread(target=close, daemon=True)
        with store._lock if stuck else contextlib.nullcontext():
            closer.start()
            closer.join(HANG_GUARD_S)
        assert took, "close() was still waiting when the test gave up on it"
        return took[0]

    baseline = min(closing_time(f"free-{n}", stuck=False) for n in range(3))
    stuck = closing_time("stuck", stuck=True)
    assert stuck >= 0.9 * wait, "close() did not wait for the write at all"
    assert stuck < 4 * wait + 5 * baseline, "close() waited longer than its limit"
    assert "write is stuck" in caplog.text
