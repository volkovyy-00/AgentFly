"""Unit tests for the capped in-memory step store and its `limit` view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recorder.memory import MAX_LIMIT, MemorySteps, parse_limit, pick_flagged
from recorder.store import StepRecord

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
