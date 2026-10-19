"""One step per agent action: join the hooks of one action (V2c, D9 "Merge rule").

Cursor can fire a general `preToolUse` and a specific hook (`beforeShellExecution`,
`beforeReadFile`, `afterFileEdit`) for one action. Events of one chat with the same
`tool_use_id` become one step. Two id-less cases have a path fallback: a `beforeReadFile`
joins the oldest unpaired `preToolUse` Read, an `afterFileEdit` the latest `preToolUse` Write
(same chat, same absolute path, within `WAIT_S`). Nothing here changes what a hook answers:
the rules still decide every event; this only decides which step it is saved into.

State lives in memory only. It is called from the event loop thread, like `SessionStore`.
"""

from __future__ import annotations

import posixpath
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from agentfly.recorder.store import StepRecord

WAIT_S: float = 5.0
WAIT_CAP: int = 32  # waiting preToolUse Read/Write entries per chat; the oldest is dropped
IDS_CAP: int = 2000  # remembered (chat, tool_use_id) pairs; the oldest is forgotten
UNKNOWN_CHAT: str = "unknown"  # shared name for events with no conversation id: no path fallback

_PATHED: frozenset[str] = frozenset({"preToolUse", "beforeReadFile", "afterFileEdit"})
_SPECIFIC: frozenset[str] = frozenset(
    {"beforeShellExecution", "beforeReadFile", "afterFileEdit", "beforeMCPExecution"}
)
_RANK: dict[str, int] = {"allowed": 0, "highlighted": 1, "warned": 2, "blocked": 3}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def action_path(payload: dict[str, Any]) -> str | None:
    """The normalised absolute path a file event names, else None (no fallback without one)."""
    raw: str = _text(payload.get("file_path"))
    if not raw:
        tool_input: Any = payload.get("tool_input")
        raw = _text(tool_input.get("file_path")) if isinstance(tool_input, dict) else ""
    if not raw.startswith("/"):
        return None
    return posixpath.normpath("/" + raw.lstrip("/"))  # normpath keeps a leading `//`


@dataclass
class Joined:
    """One step and the halves it was built from."""

    first: StepRecord  # the earliest half: order, time and link to the previous step
    specific: StepRecord | None = None  # the latest half from a specific hook
    best: StepRecord | None = None  # the strictest half from a gate hook (not afterFileEdit)
    wrote: bool = False
    events: set[str] = field(default_factory=set)  # the hook events folded in so far

    def add(self, event: str, record: StepRecord, writes: bool) -> StepRecord:
        """Fold one more half in; return the merged record to save."""
        if event in _SPECIFIC:
            self.specific = record
        if event != "afterFileEdit" and (
            self.best is None or _RANK[record.verdict] > _RANK[self.best.verdict]
        ):
            self.best = record
        self.wrote = self.wrote or writes
        self.events.add(event)
        return self.merged()

    def merged(self) -> StepRecord:
        base: StepRecord = self.specific or self.first
        verdict: StepRecord = self.best or base
        merged: StepRecord = replace(
            base,
            order=self.first.order,
            time=self.first.time,
            prev_step_id=self.first.prev_step_id,
            verdict=verdict.verdict,
            rule_id=verdict.rule_id,
            rule_description=verdict.rule_description,
        )
        if self.wrote:
            merged = replace(merged, kind="edit", tool=None)
        return merged


@dataclass(frozen=True)
class _Waiting:
    at: float
    kind: str  # "read" or "write"
    path: str
    step: Joined


class StepMerger:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock: Callable[[], float] = clock
        self._ids: OrderedDict[tuple[str, str], Joined] = OrderedDict()
        self._waiting: dict[str, deque[_Waiting]] = {}

    def clear(self) -> None:
        self._ids.clear()
        self._waiting.clear()

    def join(
        self, chat: str, payload: dict[str, Any], record: StepRecord
    ) -> tuple[StepRecord, StepRecord | None]:
        """(record to save, the record saved for this step before, or None for a new step)."""
        event: str = _text(payload.get("hook_event_name"))
        call: str = _text(payload.get("tool_use_id"))
        tool: str = _text(payload.get("tool_name")).casefold()
        writes: bool = event == "afterFileEdit" or (event == "preToolUse" and tool == "write")
        now: float = self.clock()
        self._expire(now)

        step: Joined | None = self._ids.get((chat, call)) if call else None
        path: str | None = None
        if event in _PATHED and chat != UNKNOWN_CHAT:
            path = action_path(payload)
        if step is None and not call and path is not None:
            step = self._pair(chat, event, path)
        previous: StepRecord | None = step.merged() if step is not None else None
        if step is None:
            step = Joined(first=record)
            if call:
                self._remember(chat, call, step)
        merged: StepRecord = step.add(event, record, writes)
        if event == "preToolUse" and path is not None and tool in {"read", "write"}:
            self._wait(chat, _Waiting(now, tool, path, step))
        return merged, previous

    def _remember(self, chat: str, call: str, step: Joined) -> None:
        self._ids[(chat, call)] = step
        while len(self._ids) > IDS_CAP:
            self._ids.popitem(last=False)

    def _wait(self, chat: str, entry: _Waiting) -> None:
        self._waiting.setdefault(chat, deque(maxlen=WAIT_CAP)).append(entry)

    def _expire(self, now: float) -> None:
        for chat in list(self._waiting):
            entries: deque[_Waiting] = self._waiting[chat]
            while entries and now - entries[0].at > WAIT_S:
                entries.popleft()
            if not entries:
                del self._waiting[chat]

    def _pair(self, chat: str, event: str, path: str) -> Joined | None:
        """The waiting preToolUse an id-less beforeReadFile / afterFileEdit belongs to."""
        entries: deque[_Waiting] | None = self._waiting.get(chat)
        if not entries or event not in {"beforeReadFile", "afterFileEdit"}:
            return None
        read: bool = event == "beforeReadFile"  # the oldest unpaired Read, else the latest Write
        for entry in entries if read else reversed(entries):
            if entry.kind == ("read" if read else "write") and entry.path == path:
                if event not in entry.step.events:
                    entries.remove(entry)
                    return entry.step
        return None


step_merger: StepMerger = StepMerger()
