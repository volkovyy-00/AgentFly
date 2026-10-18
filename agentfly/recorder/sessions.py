"""In-memory session notes with atomic JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from agentfly.recorder.paths import private_dir
from agentfly.recorder.rules import Session, mark

# D21 A fallback: a marked chat starts a Task and no child event names it, so a new chat in the
# same workspace inherits the mark for this long (counted from the Task).
FALLBACK_SECONDS: float = 30 * 60
_MAX_CALLS: int = 2000  # remembered Task calls; the oldest are forgotten first
_MAX_DEPTH: int = 32  # parent links followed when asking whether a chat is marked
_UNKNOWN: str = "unknown"  # `apply_rules` maps a missing conversation id to this shared name


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _roots(payload: dict[str, Any]) -> list[str]:
    """Workspace roots of an event, folded so '/P/' and '/p' are the same place."""
    roots: Any = payload.get("workspace_roots")
    if not isinstance(roots, list):
        return []
    return sorted({r.rstrip("/").casefold() for r in roots if isinstance(r, str) and r.strip("/")})


class SessionStore:
    """session id -> Session; persists to sessions.json on change."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path: Path = path
        self.links_path: Path = path.with_name("links.json")
        self.clock: Callable[[], float] = clock
        self._sessions: dict[str, Session] = {}
        # Task call id -> the chat that started it (D21 A), and calls no child event has named yet.
        self.calls: dict[str, str] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        self._sessions = {}
        if not self.path.is_file():
            return
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            sid: str = str(item.get("id", ""))
            if not sid:
                continue
            self._sessions[sid] = Session(
                id=sid,
                marked=bool(item.get("marked", False)),
                start_time=str(item.get("start_time", "")),
                next_step=int(item.get("next_step", 1)),
                parent_call=_text(item.get("parent_call")),
                parent_id=_text(item.get("parent_id")),
                inherited_until=float(item.get("inherited_until", 0.0) or 0.0),
            )
        self.load_links()

    def load_links(self) -> None:
        self.calls, self.pending = {}, {}
        try:
            raw: Any = json.loads(self.links_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        calls: Any = raw.get("calls")
        if isinstance(calls, dict):
            self.calls = {str(k): str(v) for k, v in calls.items() if isinstance(v, str)}
        pending: Any = raw.get("pending")
        if isinstance(pending, dict):
            for call, item in pending.items():
                if isinstance(item, dict) and isinstance(item.get("roots"), list):
                    self.pending[str(call)] = {
                        "parent": _text(item.get("parent")),
                        "roots": [str(r) for r in item["roots"]],
                        "t0": float(item.get("t0", 0.0) or 0.0),
                    }

    def save(self) -> None:
        private_dir(self.path.parent)
        payload: list[dict[str, Any]] = [
            {
                "id": s.id,
                "marked": s.marked,
                "start_time": s.start_time,
                "next_step": s.next_step,
                "parent_call": s.parent_call,
                "parent_id": s.parent_id,
                "inherited_until": s.inherited_until,
            }
            for s in self._sessions.values()
        ]
        data: str = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd: int
        tmp_name: str
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".sessions-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def save_links(self) -> None:
        """Write links.json (calls and pending Tasks). Rare: only when a Task or link changes."""
        private_dir(self.links_path.parent)
        data: str = json.dumps({"calls": self.calls, "pending": self.pending}, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.links_path.parent), prefix=".links-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data + "\n")
            os.replace(tmp_name, self.links_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def get_or_create(self, session_id: str) -> Session:
        existing: Session | None = self._sessions.get(session_id)
        if existing is not None:
            return existing
        created = Session(
            id=session_id,
            marked=False,
            start_time=datetime.now(UTC).isoformat(),
            next_step=1,
        )
        self._sessions[session_id] = created
        self.save()
        return created

    def put(self, session: Session) -> None:
        """Replace session and persist (call when marked/next_step change)."""
        self._sessions[session.id] = session
        self.save()

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    # ------------------------------------------------------------ subagents (D21 A)

    def observe(self, payload: dict[str, Any]) -> Session:
        """The session of this event, after recording what it says about Tasks and parent links.

        A `Task` call (`preToolUse`) and `subagentStart` say which chat started a call id; a child
        event carries `parent_tool_call_id`. The two may arrive in either order, so the chat tree
        is resolved lazily (`parent_of`) and marks are propagated whenever a link appears.
        """
        sid: str = _text(payload.get("conversation_id")) or _UNKNOWN
        linkable: bool = sid != _UNKNOWN
        call: str = _text(payload.get("parent_tool_call_id")) if linkable else ""
        session: Session | None = self._sessions.get(sid)
        changed: bool = False
        links_changed: bool = False
        if session is None:
            session = Session(
                id=sid,
                marked=False,
                start_time=datetime.now(UTC).isoformat(),
                next_step=1,
                parent_call=call,
                inherited_until=self.fallback_until(payload) if linkable and not call else 0.0,
            )
            self._sessions[sid] = session
            changed = True
        elif call and session.parent_call != call:
            session = replace(session, parent_call=call, inherited_until=0.0)
            self._sessions[sid] = session
            changed = True
        if call and self.pending.pop(call, None) is not None:
            links_changed = True  # a child event linked this Task: no fallback needed
        if linkable:
            links_changed |= self.register_task(payload, sid)
        if call in self.calls and not session.parent_id:
            self._sessions[sid] = session = replace(session, parent_id=self.calls[call])
            changed = True
        if changed or links_changed:
            self.propagate()
            if links_changed:
                self.save_links()
            self.save()
        return self._sessions[sid]

    def register_task(self, payload: dict[str, Any], sid: str) -> bool:
        """Remember which chat started a Task call. True if links.json needs writing."""
        event: str = _text(payload.get("hook_event_name"))
        call: str
        parent: str
        if event == "preToolUse" and _text(payload.get("tool_name")).casefold() == "task":
            call, parent = _text(payload.get("tool_use_id")), sid
        elif event == "subagentStart":
            call = _text(payload.get("tool_call_id"))
            parent = _text(payload.get("parent_conversation_id")) or sid
        else:
            return False
        if not call or parent == _UNKNOWN:
            return False
        changed: bool = self.calls.get(call) != parent
        if changed:
            self.calls[call] = parent
            while len(self.calls) > _MAX_CALLS:
                del self.calls[next(iter(self.calls))]
        started: Session | None = self._sessions.get(parent)
        linked: bool = any(s.parent_call == call for s in self._sessions.values())
        if call not in self.pending and not linked and started and self.effective_marked(started):
            self.pending[call] = {
                "parent": parent,
                "roots": _roots(payload),
                "t0": self.clock(),
            }
            changed = True
        return self.prune_pending() or changed

    def prune_pending(self) -> bool:
        now: float = self.clock()
        stale: list[str] = [c for c, p in self.pending.items() if now - p["t0"] > FALLBACK_SECONDS]
        for call in stale:
            del self.pending[call]
        return bool(stale)

    def fallback_until(self, payload: dict[str, Any]) -> float:
        """For a new chat with no parent link: when an inherited workspace mark ends (0: none)."""
        roots: set[str] = set(_roots(payload))
        now: float = self.clock()
        until: float = 0.0
        for entry in self.pending.values():
            if now - entry["t0"] <= FALLBACK_SECONDS and roots & set(entry["roots"]):
                until = max(until, entry["t0"] + FALLBACK_SECONDS)
        return until

    def parent_of(self, session: Session) -> Session | None:
        parent_id: str = session.parent_id or self.calls.get(session.parent_call, "")
        return self._sessions.get(parent_id) if parent_id else None

    def chain(self, session: Session) -> Iterator[Session]:
        """The chat, then its parent, grandparent and so on (a cycle or a long chain ends)."""
        seen: set[str] = set()
        current: Session | None = session
        while current is not None and current.id not in seen and len(seen) < _MAX_DEPTH:
            yield current
            seen.add(current.id)
            current = self.parent_of(current)

    def effective_marked(self, session: Session) -> bool:
        """Marked itself, inside an inherited window, or a descendant of a marked chat."""
        now: float = self.clock()
        return any(s.marked or s.inherited_until > now for s in self.chain(session))

    def effective(self, session: Session) -> Session:
        """The session as the rules should see it: marked if a parent chat is."""
        if not session.marked and self.effective_marked(session):
            return replace(session, marked=True)
        return session

    def propagate(self) -> bool:
        """A mark set inside a subagent marks its parents. True if any session changed."""
        changed: bool = False
        for session in list(self._sessions.values()):
            if not session.marked:
                continue
            for ancestor in islice(self.chain(session), 1, None):
                if not ancestor.marked:
                    self._sessions[ancestor.id] = replace(ancestor, marked=True)
                    changed = True
        return changed

    def apply_mark(self, payload: dict[str, Any], stored: Session) -> tuple[Session, Session, bool]:
        """Run the marking rule for one event: (session to save, session the rules see, marks).

        A secret read in this chat marks it and its parents for good, even if a parent already
        marked it. The caller saves the returned session with `put`, which writes the parents too.
        `marks` is true when the chat became marked on this event, itself or through a parent.
        """
        was_marked: bool = self.effective_marked(stored)
        if mark(payload, stored).marked and not stored.marked:
            self._sessions[stored.id] = stored = replace(stored, marked=True)
            self.propagate()
        session: Session = self.effective(stored)
        return stored, session, session.marked and not was_marked
