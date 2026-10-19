"""In-memory cleaned steps for the live graph page (SPEC §4 JSON shape)."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from agentfly.recorder.merge import step_merger
from agentfly.recorder.store import StepRecord

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


def _count(counts: dict[str, int], step: Step, sign: int = 1) -> None:
    counts["total"] += sign
    if step["kind"] in _KINDS:
        counts[step["kind"]] += sign
    if step["verdict"] in _ALARMS:
        counts[step["verdict"]] += sign


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

    def replace(self, old: Step, new: Step, marks: bool) -> bool:
        """Swap a step for its merged form (V2c). False when no such step was ever added here.

        The counts follow the change. A step already evicted from the window changes in the counts
        only: the cap is far above what two halves of one action are apart.
        """
        order: int = new["order"]
        retained: bool = False
        for steps in (self.steps, self.evicted_flagged):
            for index in range(len(steps) - 1, -1, -1):
                if steps[index]["order"] == order:
                    steps[index] = new
                    retained = retained or steps is self.steps
                    break
        if not retained and not (self.steps and order < self.steps[0]["order"]):
            return False
        _count(self.counts, old, -1)
        _count(self.counts, new)
        if self.marking is not None and self.marking["order"] == order:
            self.marking = new
        elif marks and self.marking is None:
            self.marking = new
        return True

    @property
    def marked_order(self) -> int | None:
        return None if self.marking is None else self.marking["order"]

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
            "marked_order": self.marked_order,
        }


def _step_dict(record: StepRecord) -> Step:
    step: Step = {
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
    # V8b: the Why card's text. Absent, not null, when no rule fired or the answer sent none.
    for key, value in (
        ("rule_text", record.rule_description),
        ("user_message", record.user_message),
        ("agent_message", record.agent_message),
    ):
        if value is not None:
            step[key] = value
    return step


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
        step_merger.clear()  # its steps are gone with the memory they point into

    def append_from_record(self, record: StepRecord, marks: bool = False) -> None:
        self.append_step(record.session_id, _step_dict(record), marks)

    def replace_from_record(self, old: StepRecord, new: StepRecord, marks: bool = False) -> None:
        """Show `new` in place of `old`, the same step merged with another hook of its action."""
        with self._lock:
            memory: _Session | None = self._sessions.get(new.session_id)
            if memory is not None and memory.replace(_step_dict(old), _step_dict(new), marks):
                self.current_session_id = new.session_id
                return
        self.append_from_record(new, marks)  # nothing to replace: show it as a step of its own

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
                if limit is not None:
                    return {**body, **_empty_view()}
                return {**body, "marked_order": None} if all_steps else body
            memory: _Session = self._sessions[sid]
            if limit is None:
                steps: list[Step] = list(memory.steps)
                if all_steps:  # V8b: the page no longer needs a second `?limit=1` request
                    return {"session": sid, "steps": steps, "marked_order": memory.marked_order}
                return {"session": sid, "steps": steps[-_LAST_N:]}
            return {"session": sid, **memory.window_view(limit)}


memory_steps: MemorySteps = MemorySteps()
