"""`after_then` triggers are kept per chat like R1's mark (V5b, D21).

Hand-built: the tests put trigger ids on sessions and watch them travel through the store, a
restart, the parent links and the 30-minute workspace fallback. No rule is involved here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import agentfly.recorder.sessions as sessions_mod
from agentfly.recorder.rules import Session
from agentfly.recorder.sessions import FALLBACK_SECONDS, SessionStore
from tests.recorder_harness import Clock

X = frozenset({"X"})
Y = frozenset({"Y"})


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def path(tmp_path: Path) -> Path:
    return tmp_path / "sessions.json"


@pytest.fixture()
def store(path: Path, clock: Clock) -> SessionStore:
    return SessionStore(path, clock=clock)


def event(chat: str, name: str = "beforeShellExecution", **fields: Any) -> dict[str, Any]:
    return {
        "hook_event_name": name,
        "conversation_id": chat,
        "workspace_roots": ["/w"],
        "command": "ls",
        **fields,
    }


def task(chat: str, call: str, **fields: Any) -> dict[str, Any]:
    return event(chat, "preToolUse", tool_name="Task", tool_use_id=call, **fields)


def arm(store: SessionStore, chat: str, triggers: frozenset[str]) -> None:
    """Give a chat triggers, as `apply_mark` does when an `after` clause fires."""
    session = store.observe(event(chat))
    store.put(replace(session, triggers=triggers))


def effective(store: SessionStore, chat: str) -> frozenset[str]:
    session = store.get(chat)
    assert session is not None
    return store.effective(session).triggers


# ---------------------------------------------------------------- parents and children


def test_a_session_has_no_triggers_until_one_fires(store: SessionStore) -> None:
    assert store.observe(event("P")).triggers == frozenset()
    assert store.observe(event("P")).inherited_triggers == {}


def test_a_trigger_reaches_a_subagent_but_not_an_unrelated_chat(store: SessionStore) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    store.observe(event("C", parent_tool_call_id="T1"))
    store.observe(event("OTHER", workspace_roots=["/elsewhere"]))
    assert effective(store, "C") == X
    assert effective(store, "P") == X
    assert effective(store, "OTHER") == frozenset()


def test_the_child_keeps_the_parents_trigger_out_of_its_own_stored_row(store: SessionStore) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    store.observe(event("C", parent_tool_call_id="T1"))
    child = store.get("C")
    assert child is not None and child.triggers == frozenset()
    assert store.effective(child).triggers == X


def test_a_trigger_inside_a_subagent_reaches_its_parent_and_grandparent(
    store: SessionStore,
) -> None:
    store.observe(task("P", "T1"))
    store.observe(task("C", "T2", parent_tool_call_id="T1"))
    store.observe(event("G", parent_tool_call_id="T2"))
    arm(store, "G", Y)
    store.propagate()
    for chat in ("P", "C", "G"):
        stored = store.get(chat)
        assert stored is not None and stored.triggers == Y, chat


def test_different_triggers_add_up_along_the_chain(store: SessionStore) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    store.observe(event("C", parent_tool_call_id="T1"))
    arm(store, "C", Y)
    assert effective(store, "C") == X | Y


def test_a_cycle_of_links_ends_with_triggers_too(store: SessionStore) -> None:
    store.calls = {"a": "X1", "b": "Y1"}
    store.put(Session(id="X1", marked=False, start_time="t", next_step=1, parent_call="b"))
    store.put(
        Session(id="Y1", marked=False, start_time="t", next_step=1, parent_call="a", triggers=X)
    )
    assert effective(store, "X1") == X
    store.propagate()


# ---------------------------------------------------------------- a stale copy never clears one


def test_a_stale_copy_never_clears_a_trigger(store: SessionStore) -> None:
    arm(store, "P", X)
    store.put(Session(id="P", marked=False, start_time="t", next_step=9))
    kept = store.get("P")
    assert kept is not None and kept.triggers == X


def test_a_put_adds_triggers_to_the_ones_already_there(store: SessionStore) -> None:
    arm(store, "P", X)
    session = store.get("P")
    assert session is not None
    store.put(replace(session, triggers=Y))
    kept = store.get("P")
    assert kept is not None and kept.triggers == X | Y


def test_a_put_keeps_the_longer_inherited_window_of_each_trigger(store: SessionStore) -> None:
    session = store.observe(event("P"))
    store.put(replace(session, inherited_triggers={"X": 50.0, "Y": 10.0}))
    store.put(replace(session, inherited_triggers={"X": 20.0, "Z": 5.0}))
    kept = store.get("P")
    assert kept is not None and kept.inherited_triggers == {"X": 50.0, "Y": 10.0, "Z": 5.0}


# ---------------------------------------------------------------- restart and old files


def test_triggers_survive_a_restart(store: SessionStore, path: Path, clock: Clock) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    store.observe(event("C", parent_tool_call_id="T1"))
    again = SessionStore(path, clock=clock)
    assert effective(again, "C") == X
    parent = again.get("P")
    assert parent is not None and parent.triggers == X
    saved = {item["id"]: item for item in json.loads(path.read_text(encoding="utf-8"))}
    assert saved["P"]["triggers"] == ["X"]


def test_a_sessions_file_from_before_triggers_loads_with_none(path: Path, clock: Clock) -> None:
    old = [{"id": "O", "marked": True, "start_time": "t", "next_step": 3}]
    path.write_text(json.dumps(old), encoding="utf-8")
    loaded = SessionStore(path, clock=clock).get("O")
    assert loaded is not None and loaded.marked
    assert loaded.triggers == frozenset() and loaded.inherited_triggers == {}


@pytest.mark.parametrize("junk", ["X", 5, {"X": "soon"}, [1, None, "Y"], {"X": True}])
def test_a_damaged_triggers_entry_is_ignored_not_fatal(path: Path, clock: Clock, junk: Any) -> None:
    row = {"id": "O", "marked": False, "start_time": "t", "next_step": 1, "triggers": junk}
    row["inherited_triggers"] = junk
    path.write_text(json.dumps([row]), encoding="utf-8")
    loaded = SessionStore(path, clock=clock).get("O")
    assert loaded is not None
    assert loaded.triggers <= {"Y"} and set(loaded.inherited_triggers) <= {"Y"}


# ---------------------------------------------------------------- the workspace fallback


def test_a_trigger_is_inherited_for_30_minutes_when_no_child_links_the_task(
    store: SessionStore, clock: Clock
) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))  # no child event ever names T1
    store.observe(event("NEW"))
    assert effective(store, "NEW") == X
    clock.now += FALLBACK_SECONDS + 1
    assert effective(store, "NEW") == frozenset()


def test_an_inherited_trigger_does_not_mark_the_chat_as_having_read_a_secret(
    store: SessionStore,
) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    new = store.observe(event("NEW"))
    assert store.effective_marked(new) is False
    assert new.inherited_until == 0.0


def test_a_chat_in_another_workspace_inherits_nothing(store: SessionStore) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    store.observe(event("ELSE", workspace_roots=["/elsewhere"]))
    assert effective(store, "ELSE") == frozenset()


def test_a_marked_chat_without_triggers_still_gives_the_r1_fallback_and_no_triggers(
    store: SessionStore,
) -> None:
    session = store.observe(event("P"))
    store.put(replace(session, marked=True))
    store.observe(task("P", "T1"))
    new = store.observe(event("NEW"))
    assert store.effective_marked(new) is True
    assert new.inherited_triggers == {}


def test_a_chat_with_triggers_but_no_mark_gives_a_trigger_fallback_and_no_mark(
    store: SessionStore, path: Path
) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    links = json.loads(path.with_name("links.json").read_text(encoding="utf-8"))
    entry = links["pending"]["T1"]
    assert entry["marked"] is False and entry["triggers"] == ["X"]


def test_a_child_that_names_the_task_ends_the_trigger_fallback(store: SessionStore) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    store.observe(event("C", parent_tool_call_id="T1"))  # the link exists: no fallback needed
    store.observe(event("NEW"))
    assert effective(store, "NEW") == frozenset()


def test_a_task_started_by_a_chat_with_nothing_to_hand_on_leaves_no_pending_entry(
    store: SessionStore,
) -> None:
    store.observe(event("P"))
    store.observe(task("P", "T1"))
    assert store.pending == {}


def test_the_pending_triggers_survive_a_restart(
    store: SessionStore, path: Path, clock: Clock
) -> None:
    arm(store, "P", X)
    store.observe(task("P", "T1"))
    again = SessionStore(path, clock=clock)
    again.observe(event("NEW"))
    assert effective(again, "NEW") == X


def test_a_links_file_from_before_triggers_keeps_giving_the_r1_fallback(
    path: Path, clock: Clock
) -> None:
    path.write_text(json.dumps([{"id": "P", "marked": True, "start_time": "t", "next_step": 1}]))
    links = {
        "calls": {"T1": "P"},
        "pending": {"T1": {"parent": "P", "roots": ["/w"], "t0": clock.now}},
    }
    path.with_name("links.json").write_text(json.dumps(links), encoding="utf-8")
    again = SessionStore(path, clock=clock)
    new = again.observe(event("NEW"))
    assert again.effective_marked(new) is True


# ---------------------------------------------------------------- apply_mark


def adds_trigger(name: str) -> Callable[[dict[str, Any], Session], Session]:
    """A stand-in for `rules.mark` that sets one trigger off on the command `fire`."""

    def mark(action: dict[str, Any], session: Session) -> Session:
        if action.get("command") == "fire":
            return replace(session, triggers=session.triggers | {name})
        return session

    return mark


def test_apply_mark_stores_a_new_trigger_and_hands_it_to_the_decision(
    store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions_mod, "mark", adds_trigger("X"))
    payload = event("P", command="fire")
    stored, session, marks = store.apply_mark(payload, store.observe(payload))
    assert stored.triggers == X and session.triggers == X
    assert marks is False, "a trigger is not a secret read: the history flag stays as it was"
    again = store.get("P")
    assert again is not None and again.triggers == X


def test_apply_mark_pushes_a_childs_new_trigger_up_to_the_parent(
    store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions_mod, "mark", adds_trigger("X"))
    store.observe(task("P", "T1"))
    payload = event("C", command="fire", parent_tool_call_id="T1")
    store.apply_mark(payload, store.observe(payload))
    parent = store.get("P")
    assert parent is not None and parent.triggers == X


def test_apply_mark_leaves_a_session_alone_when_nothing_new_fires(
    store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions_mod, "mark", adds_trigger("X"))
    arm(store, "P", X)
    payload = event("P", command="fire")
    stored, session, _ = store.apply_mark(payload, store.observe(payload))
    assert stored.triggers == X and session.triggers == X


def test_effective_returns_the_same_object_when_there_is_nothing_to_add(
    store: SessionStore,
) -> None:
    session = store.observe(event("P"))
    assert store.effective(session) is session
