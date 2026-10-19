"""Unit tests for the capped in-memory step store and its `limit` view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentfly.recorder.memory import MAX_LIMIT, MemorySteps, parse_limit, pick_flagged
from agentfly.recorder.store import StepRecord

FIXTURE: Path = Path(__file__).parent / "fixtures" / "window_golden.json"
ZERO_HIDDEN: dict[str, int] = dict.fromkeys(
    ("total", "read", "shell", "edit", "tool", "blocked", "warned"), 0
)


def make_step(order: int, kind: str = "shell", verdict: str = "allowed") -> dict[str, Any]:
    return {
        "order": order,
        "kind": kind,
        "verdict": verdict,
        "tool": None,
        "file": None,
        "sensitive": False,
        "command": None,
        "host": None,
        "rule": None,
    }


def orders(steps: list[dict[str, Any]]) -> list[int]:
    return [s["order"] for s in steps]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("1", 1),
        ("20", 20),
        ("50", 50),
        ("51", 50),
        ("80", 50),
        ("10000", 50),
        ("007", 7),
        ("0" * 5000 + "7", 7),
        ("9" * 5000, MAX_LIMIT),
    ],
)
def test_parse_limit_accepts(raw: str | None, expected: int | None) -> None:
    assert parse_limit(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "0", "00", "0" * 5000, "-1", "abc", "+5", " 5", "5 ", "5_0", "1.5", "٣"],
)
def test_parse_limit_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match="bad limit"):
        parse_limit(raw)


def test_pick_flagged_takes_marking_then_the_newest_four() -> None:
    candidates = [make_step(o, verdict="blocked") for o in (20, 18, 16, 14, 12, 10)]
    got = pick_flagged(make_step(3), iter(candidates), floor=30)
    assert orders(got) == [3, 14, 16, 18, 20]


def test_pick_flagged_marking_inside_the_window_takes_no_slot() -> None:
    candidates = [make_step(o, verdict="blocked") for o in (20, 18, 16, 14, 12, 10)]
    got = pick_flagged(make_step(35), iter(candidates), floor=30)
    assert orders(got) == [12, 14, 16, 18, 20]


def test_pick_flagged_counts_a_marking_step_that_is_also_blocked_once() -> None:
    marking = make_step(3, verdict="blocked")
    got = pick_flagged(marking, iter([make_step(9, verdict="blocked"), marking]), floor=30)
    assert orders(got) == [3, 9]


def test_pick_flagged_skips_steps_at_or_above_the_floor_and_sorts_ascending() -> None:
    candidates = [make_step(o, verdict="warned") for o in (40, 30, 29, 5)]
    assert orders(pick_flagged(None, iter(candidates), floor=30)) == [5, 29]


def test_pick_flagged_with_nothing_is_empty() -> None:
    assert pick_flagged(None, iter([]), floor=10) == []


def test_cap_drops_the_oldest_but_counters_keep_counting() -> None:
    store = MemorySteps(cap=5)
    for order in range(1, 13):
        store.append_step("s", make_step(order))
    full = store.snapshot(all_steps=True)
    assert orders(full["steps"]) == [8, 9, 10, 11, 12]
    view = store.snapshot(limit=2)
    assert orders(view["steps"]) == [11, 12]
    assert view["hidden"]["total"] == 10
    assert view["hidden"]["shell"] == 10


def test_an_unknown_kind_counts_only_in_total() -> None:
    store = MemorySteps()
    store.append_step("s", make_step(1, kind="weird"))
    store.append_step("s", make_step(2))
    view = store.snapshot(limit=1)
    assert view["hidden"] == {**ZERO_HIDDEN, "total": 1}


def test_limit_above_the_retained_count_shows_everything_and_hides_nothing() -> None:
    store = MemorySteps()
    for order in range(1, 4):
        store.append_step("s", make_step(order, verdict="blocked"))
    view = store.snapshot(limit=50)
    assert orders(view["steps"]) == [1, 2, 3]
    assert view["hidden"] == ZERO_HIDDEN
    assert view["flagged"] == []
    assert view["marked_order"] is None


def test_only_the_first_marking_step_is_kept() -> None:
    store = MemorySteps()
    store.append_step("s", make_step(1), marks=True)
    store.append_step("s", make_step(2), marks=True)
    store.append_step("s", make_step(3))
    assert store.snapshot(limit=1)["marked_order"] == 1


def test_without_limit_the_snapshot_is_the_old_shape() -> None:
    store = MemorySteps()
    for order in range(1, 13):
        store.append_step("s", make_step(order))
    body = store.snapshot()
    assert set(body) == {"session", "steps"}
    assert orders(body["steps"]) == list(range(3, 13))
    assert orders(store.snapshot(all_steps=True)["steps"]) == list(range(1, 13))
    assert store.snapshot(limit=None, all_steps=True)["session"] == "s"


def test_empty_store() -> None:
    store = MemorySteps()
    assert store.snapshot() == {"session": None, "steps": []}
    assert store.snapshot(limit=20) == {
        "session": None,
        "steps": [],
        "hidden": ZERO_HIDDEN,
        "flagged": [],
        "marked_order": None,
    }


def test_clear_forgets_everything() -> None:
    store = MemorySteps()
    store.append_step("s", make_step(1), marks=True)
    store.clear()
    assert store.snapshot(limit=5)["session"] is None


def test_append_from_record_keeps_the_step_shape_and_takes_marks() -> None:
    record = StepRecord(
        session_id="s",
        started_at="t",
        order=4,
        time="t",
        kind="read",
        verdict="allowed",
        file_path=".env",
        file_sensitive=True,
    )
    store = MemorySteps()
    store.append_from_record(record, marks=True)
    view = store.snapshot(limit=1)
    expected_keys = {
        "order",
        "kind",
        "verdict",
        "tool",
        "file",
        "sensitive",
        "command",
        "host",
        "rule",
    }
    assert set(view["steps"][0]) == expected_keys
    assert view["marked_order"] == 4


def _scenarios() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["scenarios"]


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s["name"][:40])
def test_golden_scenarios(scenario: dict[str, Any]) -> None:
    store = MemorySteps(cap=scenario["cap"])
    for order, spec in enumerate(scenario["steps"], start=1):
        store.append_step(
            "g", make_step(order, spec["kind"], spec["verdict"]), marks=bool(spec.get("marks"))
        )
    for case in scenario["cases"]:
        got = store.snapshot(limit=case["limit"])
        want = case["expect"]
        assert orders(got["steps"]) == want["window"], case
        assert got["hidden"] == want["hidden"], case
        assert orders(got["flagged"]) == want["flagged"], case
        assert got["marked_order"] == want["marked_order"], case


# ---------------------------------------------------------------- replace (V2c: a merged step)


def rec(order: int, kind: str = "tool", verdict: str = "allowed", **fields: Any) -> StepRecord:
    return StepRecord(
        session_id="s", started_at="t", order=order, time="t", kind=kind, verdict=verdict, **fields
    )


def window(memory: MemorySteps, limit: int = 50) -> dict[str, Any]:
    return memory.snapshot(limit=limit)


def test_replace_swaps_the_step_and_moves_the_counts() -> None:
    memory = MemorySteps()
    memory.append_from_record(rec(1, tool="Shell"))
    memory.append_from_record(rec(2, "read"))
    memory.replace_from_record(rec(1, tool="Shell"), rec(1, "shell", "blocked", command="ls"))
    body = window(memory, 1)
    assert [s["order"] for s in body["steps"]] == [2]
    assert body["hidden"] == {**ZERO_HIDDEN, "total": 1, "shell": 1, "blocked": 1}
    assert [s["kind"] for s in memory.snapshot(all_steps=True)["steps"]] == ["shell", "read"]


def test_replace_follows_the_marking_step() -> None:
    memory = MemorySteps()
    memory.append_from_record(rec(1), marks=True)
    memory.replace_from_record(rec(1), rec(1, "read", file_path="a"))
    assert window(memory)["marked_order"] == 1
    memory.append_from_record(rec(2))
    memory.replace_from_record(rec(2), rec(2, "read"), marks=True)  # the chat was marked before
    assert window(memory)["marked_order"] == 1


def test_replace_marks_when_the_second_half_is_the_marking_one() -> None:
    memory = MemorySteps()
    memory.append_from_record(rec(1))
    memory.replace_from_record(rec(1), rec(1, "read"), marks=True)
    assert window(memory)["marked_order"] == 1


def test_replace_of_an_evicted_step_only_moves_the_counts() -> None:
    memory = MemorySteps(cap=2)
    for order in (1, 2, 3):
        memory.append_from_record(rec(order))
    memory.replace_from_record(rec(1), rec(1, "edit"))
    body = window(memory, 1)
    assert [s["order"] for s in body["steps"]] == [3]
    assert (body["hidden"]["total"], body["hidden"]["edit"], body["hidden"]["tool"]) == (
        2,
        1,
        1,
    )  # steps 1 (now edit) and 2 are out of the window
    assert [s["order"] for s in memory.snapshot(all_steps=True)["steps"]] == [2, 3]


def test_replace_of_an_unknown_step_is_added() -> None:
    memory = MemorySteps()
    memory.replace_from_record(rec(4), rec(4, "read"))
    assert [s["order"] for s in memory.snapshot(all_steps=True)["steps"]] == [4]


# ---------------------------------------------------------------- V8b: rule text, messages, marker


def test_a_step_a_rule_fired_on_carries_its_text_and_an_allowed_one_carries_nothing() -> None:
    memory = MemorySteps()
    memory.append_from_record(rec(1, "shell"))
    memory.append_from_record(
        rec(
            2,
            "shell",
            "blocked",
            rule_id="R1",
            rule_description="why",
            user_message="u",
            agent_message="a",
        )
    )
    memory.append_from_record(rec(3, "shell", "warned", rule_id="R1", rule_description="why"))
    plain, blocked, warned = memory.snapshot(all_steps=True)["steps"]
    keys = {"rule_text", "user_message", "agent_message"}
    assert keys.isdisjoint(plain)
    assert (blocked["rule_text"], blocked["user_message"], blocked["agent_message"]) == (
        "why",
        "u",
        "a",
    )
    assert warned["rule_text"] == "why"
    assert "user_message" not in warned and "agent_message" not in warned


def test_the_fields_travel_with_flagged_and_replaced_steps() -> None:
    memory = MemorySteps(cap=2)
    memory.append_from_record(
        rec(1, "shell", "blocked", rule_id="R1", rule_description="why", user_message="u")
    )
    for order in (2, 3):
        memory.append_from_record(rec(order, "shell"))  # step 1 leaves the window for `flagged`
    [flagged] = window(memory, 1)["flagged"]
    assert (flagged["rule_text"], flagged["user_message"]) == ("why", "u")
    memory.replace_from_record(
        rec(3, "shell"), rec(3, "shell", "blocked", rule_id="R0", rule_description="w3")
    )
    assert memory.snapshot(all_steps=True)["steps"][-1]["rule_text"] == "w3"


def test_all_steps_snapshot_names_the_marking_step() -> None:
    memory = MemorySteps()
    assert memory.snapshot(all_steps=True) == {"session": None, "steps": [], "marked_order": None}
    memory.append_step("s", make_step(1))
    assert memory.snapshot(all_steps=True)["marked_order"] is None
    memory.append_step("s", make_step(2), marks=True)
    memory.append_step("s", make_step(3))
    assert memory.snapshot(all_steps=True)["marked_order"] == 2
    assert (
        memory.snapshot(all_steps=True)["marked_order"] == memory.snapshot(limit=1)["marked_order"]
    )
    assert set(memory.snapshot()) == {"session", "steps"}
