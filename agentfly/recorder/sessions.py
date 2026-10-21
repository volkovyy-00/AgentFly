"""In-memory session notes with atomic JSON persistence (F11).

What makes a chat stricter (a mark, a trigger, an inherited window, a parent link) and every
`links.json` change is on disk before the hook answers (`commit`). The rest (step counter, last
activity, a plain new chat) is saved later by one background writer. Both go through
`_write_locked`, which takes its snapshot under the lock, so an older snapshot never overwrites a
newer one. Notes idle for 29 days are dropped by `sweep` unless they matter (D29).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from itertools import islice
from operator import attrgetter
from pathlib import Path
from typing import Any

from agentfly.recorder.paths import private_dir
from agentfly.recorder.rules import Session, mark

logger = logging.getLogger("agentfly")

# D21 A fallback: a marked chat starts a Task and no child event names it, so a new chat in the
# same workspace inherits the mark for this long (counted from the Task).
FALLBACK_SECONDS: float = 30 * 60
# Remembered Task calls; the oldest are forgotten first, except calls a chat points to or that no
# child has named yet (forgetting those would free a subagent from its parent's mark).
_MAX_CALLS: int = 2000
_MAX_DEPTH: int = 32  # parent links followed when asking whether a chat is marked
_UNKNOWN: str = "unknown"  # `apply_rules` maps a missing conversation id to this shared name
# F11: how long a change that may wait is held back, so a burst of hooks is one write.
SAVE_DELAY_S: float = 10.0
# D29: a note idle this long is dropped (one day past history's 28), unless it still matters.
IDLE_DROP_SECONDS: float = 29 * 24 * 3600
SWEEP_EVERY_SECONDS: float = 3600.0


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _ids(value: Any) -> frozenset[str]:
    """Trigger ids from a saved row; anything that is not a list of strings is left out."""
    return (
        frozenset(v for v in value if isinstance(v, str))
        if isinstance(value, list)
        else frozenset()
    )


def _number(value: Any) -> float | None:
    """A saved number; a bool or anything else is None."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _windows(value: Any) -> dict[str, float]:
    """Trigger id -> end time from a saved row; damaged entries are left out."""
    if not isinstance(value, dict):
        return {}
    found: dict[str, float] = {}
    for key, until in value.items():
        number: float | None = _number(until)
        if isinstance(key, str) and number is not None:
            found[key] = number
    return found


def _longer(first: Mapping[str, float], second: Mapping[str, float]) -> dict[str, float]:
    return {k: max(first.get(k, 0.0), second.get(k, 0.0)) for k in first.keys() | second.keys()}


def _roots(payload: dict[str, Any]) -> list[str]:
    """Workspace roots of an event, folded so '/P/' and '/p' are the same place."""
    roots: Any = payload.get("workspace_roots")
    if not isinstance(roots, list):
        return []
    return sorted({r.rstrip("/").casefold() for r in roots if isinstance(r, str) and r.strip("/")})


# What makes a chat stricter. A change in it must be on disk before the hook answers. A chat that
# is not there yet holds nothing, which is what a blank row says.
_HOLD = attrgetter(
    "marked", "triggers", "inherited_until", "inherited_triggers", "parent_call", "parent_id"
)
_BLANK = Session(id="", marked=False, start_time="", next_step=1)


def _active_time(value: Any) -> float:
    """A saved last-activity time; anything that is not a positive number is 0 (unknown)."""
    number: float | None = _number(value)
    return number if number is not None and number > 0 else 0.0


def _write_atomic(path: Path, text: str, prefix: str, sync: bool) -> None:
    """Replace `path` with `text` in one step: a reader sees the old file or the new, never half."""
    private_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
            if sync:
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class SessionStore:
    """session id -> Session; persists to sessions.json (see the module docstring)."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path: Path = path
        self.links_path: Path = path.with_name("links.json")
        self.clock: Callable[[], float] = clock
        self._sessions: dict[str, Session] = {}
        # Task call id -> the chat that started it (D21 A), and calls no child event has named yet.
        self.calls: dict[str, str] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        # F11 saving state. The request thread bumps `_strict_seq` / sets the flags AFTER it changes
        # memory; `_write_locked` reads them under `_lock` BEFORE it takes its snapshot.
        self._lock: threading.Lock = threading.Lock()
        self._strict_seq: int = 0  # last change that makes a chat stricter, or changes the links
        self._saved_seq: int = 0  # the `_strict_seq` the last successful write covered
        self._asked_seq: int = 0  # the `_strict_seq` a `commit` has already waited for
        self._lazy_dirty: bool = False  # something that may wait is not on disk
        self._links_seq: int = 0  # last change to calls / pending
        self._links_saved: int = 0  # the `_links_seq` the last links.json write covered
        self._floors: dict[str, int] = {}  # chat id -> first order number history has not used
        self._wake: threading.Event = threading.Event()
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
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
        now: float = self.clock()
        for item in raw:
            if not isinstance(item, dict):
                continue
            sid: str = str(item.get("id", ""))
            if not sid:
                continue
            active: float = _active_time(item.get("last_active"))
            if not active:  # a note from before F11 counts as active from this start (D29)
                active = now
                self._lazy_dirty = True
            self._sessions[sid] = Session(
                id=sid,
                marked=bool(item.get("marked", False)),
                start_time=str(item.get("start_time", "")),
                next_step=int(item.get("next_step", 1)),
                parent_call=_text(item.get("parent_call")),
                parent_id=_text(item.get("parent_id")),
                inherited_until=float(item.get("inherited_until", 0.0) or 0.0),
                triggers=_ids(item.get("triggers")),
                inherited_triggers=_windows(item.get("inherited_triggers")),
                last_active=active,
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
                        # V5b: what the chat that started the Task hands on. Before V5b only the
                        # R1 mark was kept here, so a missing `marked` means it was set.
                        "marked": bool(item.get("marked", True)),
                        "triggers": sorted(_ids(item.get("triggers"))),
                    }

    def save(self) -> None:
        """Write sessions.json now: the whole file, from a copy of the table."""
        # One C call, so the request thread cannot change the table under it (CPython, GIL).
        # Sessions are replaced, never changed in place, so each row of the copy is whole.
        rows: list[Session] = list(self._sessions.values())
        payload: list[dict[str, Any]] = [
            {
                "id": s.id,
                "marked": s.marked,
                "start_time": s.start_time,
                "next_step": s.next_step,
                "parent_call": s.parent_call,
                "parent_id": s.parent_id,
                "inherited_until": s.inherited_until,
                "last_active": s.last_active,
                # V5b: only when there is something, so the file does not grow for chats without
                **({"triggers": sorted(s.triggers)} if s.triggers else {}),
                **(
                    {"inherited_triggers": dict(sorted(s.inherited_triggers.items()))}
                    if s.inherited_triggers
                    else {}
                ),
            }
            for s in rows
        ]
        # No `indent`: the C encoder runs only without it (3x faster at 5000 chats).
        data: str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        _write_atomic(self.path, data, ".sessions-", sync=True)

    def save_links(self) -> None:
        """Write links.json (calls and pending Tasks). Rare: only when a Task or link changes."""
        calls: dict[str, str] = dict(self.calls)  # copies: the request thread may be changing them
        pending: dict[str, dict[str, Any]] = dict(self.pending)  # entries are replaced, not edited
        data: str = json.dumps({"calls": calls, "pending": pending}, sort_keys=True)
        _write_atomic(self.links_path, data, ".links-", sync=False)

    # ------------------------------------------------------------ when things reach the disk (F11)

    def _remember(self, session: Session) -> Session:
        """Keep this row. A change that makes the chat stricter is owed to disk before the answer.

        Returns the row as stored (a row with no activity time gets now).
        """
        if session.last_active <= 0:
            session = replace(session, last_active=self.clock())
        old: Session | None = self._sessions.get(session.id)
        self._sessions[session.id] = session
        if _HOLD(old or _BLANK) != _HOLD(session):
            self._strict_seq += 1
        self._lazy_dirty = True
        return session

    def _links_touched(self) -> None:
        """calls / pending changed on a hook: links.json is owed before the answer."""
        self._links_seq += 1
        self._strict_seq += 1

    def _wake_writer(self) -> None:
        if not self._wake.is_set():  # it stays set for the whole delay: one hook, one call at most
            self._wake.set()

    def commit(self) -> None:
        """End of a hook's changes. Wait for the disk only if this hook made a chat stricter.

        A write already in flight (the background writer's) is waited for, not trusted: if it
        fails, this call writes again and raises. A failed write raises here once; the next hook
        that changes nothing is answered from memory, and the writer keeps trying.
        """
        seq: int = self._strict_seq
        if seq > self._asked_seq:
            self._asked_seq = seq
            with self._lock:
                if self._saved_seq < seq:
                    self._write_locked()
        elif self._lazy_dirty:
            self._wake_writer()

    def flush(self) -> None:
        """Write whatever is not on disk yet, now (tests, shutdown, the writer thread)."""
        with self._lock:
            self._write_locked()

    def _write_locked(self) -> None:
        """The only code that writes. Needs `_lock`. Writes nothing when nothing is owed."""
        links_seq: int = self._links_seq
        seq: int = self._strict_seq
        links: bool = links_seq > self._links_saved
        if not (links or self._lazy_dirty or seq > self._saved_seq):
            return
        self._lazy_dirty = False  # before the copy: a later change sets it again
        try:
            if links:
                self.save_links()
            self.save()
        except BaseException:
            self._lazy_dirty = True
            self._wake.set()  # the writer thread, if there is one, tries again
            raise
        self._links_saved, self._saved_seq = links_seq, seq

    def start(self) -> None:
        """Save the changes that may wait in the background. The recorder starts it; tests flush."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._write_later, name="session-notes", daemon=True)
        self._thread.start()
        # what loading and the start-up sweep changed is owed to the disk too
        if self._lazy_dirty or self._links_seq > self._links_saved:
            self._wake.set()

    def close(self) -> None:
        """Stop the writer and save everything (clean stop). Never raises."""
        thread, self._thread = self._thread, None
        if thread is not None:
            self._stop.set()
            self._wake.set()
            thread.join(timeout=10.0)
        try:
            self.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("session notes: last save failed (%s)", type(exc).__name__)

    def _write_later(self) -> None:
        failing: bool = False
        while True:
            self._wake.wait()
            if self._stop.wait(SAVE_DELAY_S):  # a burst of hooks becomes one write
                return
            self._wake.clear()
            try:
                self.flush()
                failing = False
            except Exception as exc:  # noqa: BLE001 - `_write_locked` has woken us for a retry
                if not failing:
                    logger.warning(
                        "session notes: not saved (%s); trying again", type(exc).__name__
                    )
                failing = True

    def raise_counters(self, floors: Mapping[str, int]) -> None:
        """Never hand out an order number history already holds (a crash can lose the counter).

        `floors` maps a chat id to the first order number its saved steps have not used.
        """
        for sid, first_free in floors.items():
            session: Session | None = self._sessions.get(sid)
            if session is None:
                self._floors[sid] = first_free  # a chat with no note yet: used when it appears
            elif first_free > session.next_step:
                self._remember(replace(session, next_step=first_free))

    def get_or_create(self, session_id: str) -> Session:
        existing: Session | None = self._sessions.get(session_id)
        if existing is not None:
            return existing
        created = self._new_session(session_id, last_active=self.clock())
        self.commit()
        return created

    def _new_session(self, sid: str, **fields: Any) -> Session:
        """A chat seen for the first time: its counter starts after what history already holds."""
        return self._remember(
            Session(
                id=sid,
                marked=False,
                start_time=datetime.now(UTC).isoformat(),
                next_step=self._floors.pop(sid, 1),
                **fields,
            )
        )

    def put(self, session: Session) -> None:
        """Replace session and persist (call when marked/next_step change).

        Marks only get stricter: a stale copy never clears a mark or a trigger, shortens a fallback,
        replaces a parent link that is already set, or moves the step counter or activity time back.
        """
        old: Session | None = self._sessions.get(session.id)
        if old is not None:
            session = replace(
                session,
                marked=session.marked or old.marked,
                next_step=max(session.next_step, old.next_step),
                inherited_until=max(session.inherited_until, old.inherited_until),
                parent_call=old.parent_call or session.parent_call,
                parent_id=old.parent_id or session.parent_id,
                triggers=session.triggers | old.triggers,
                inherited_triggers=_longer(session.inherited_triggers, old.inherited_triggers),
                last_active=max(session.last_active, old.last_active),
            )
        self._remember(session)
        self.commit()

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
        now: float = self.clock()
        session: Session | None = self._sessions.get(sid)
        changed: bool = False  # a link appeared: marks may have to travel (`propagate`)
        links_changed: bool = False
        if session is None:
            inherit: bool = linkable and not call  # a chat with no parent link may inherit
            session = self._new_session(
                sid,
                parent_call=call,
                inherited_until=self.fallback_until(payload) if inherit else 0.0,
                inherited_triggers=self.fallback_triggers(payload) if inherit else {},
                last_active=now,
            )
            changed = True
        else:
            # Activity time only (it may wait); not `changed`, or propagate() runs on every hook.
            session = self._remember(replace(session, last_active=now))
            if call and not session.parent_call:
                # The first link sticks and a fallback mark is never cut short: no later event,
                # whatever call id it names, may move the link or release the chat.
                session = self._remember(replace(session, parent_call=call))
                changed = True
        link: str = session.parent_call
        if call and call == link and self.pending.pop(call, None) is not None:
            links_changed = True  # a child event linked this Task: no fallback needed
        if linkable:
            links_changed |= self.register_task(payload, sid)
        if link in self.calls and not session.parent_id:
            session = self._remember(replace(session, parent_id=self.calls[link]))
            changed = True
        if links_changed:
            self._links_touched()
        if changed or links_changed:
            self.propagate()
        self.commit()
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
        changed: bool = call not in self.calls  # the first parent named stays (never moved)
        if changed:
            self.calls[call] = parent
            self.forget_old_calls(keep=call)
        started: Session | None = self._sessions.get(parent)
        linked: bool = any(s.parent_call == call for s in self._sessions.values())
        if call not in self.pending and not linked and started:
            handed_on: Session = self.effective(started)  # what its subagents would inherit
            if handed_on.marked or handed_on.triggers:
                self.pending[call] = {
                    "parent": parent,
                    "roots": _roots(payload),
                    "t0": self.clock(),
                    "marked": handed_on.marked,
                    "triggers": sorted(handed_on.triggers),
                }
                changed = True
        return self.prune_pending() or changed

    def forget_old_calls(self, keep: str) -> None:
        """Drop the oldest calls over `_MAX_CALLS`, never `keep`, a linked or a pending one."""
        excess: int = len(self.calls) - _MAX_CALLS
        if excess <= 0:
            return
        held: set[str] = {s.parent_call for s in self._sessions.values()}
        held |= {keep, *self.pending}
        victims: list[str] = []
        for call in self.calls:  # oldest first; usually the first one goes
            if len(victims) == excess:
                break
            if call not in held:
                victims.append(call)
        for call in victims:
            del self.calls[call]

    def prune_pending(self) -> bool:
        now: float = self.clock()
        stale: list[str] = [c for c, p in self.pending.items() if now - p["t0"] > FALLBACK_SECONDS]
        for call in stale:
            del self.pending[call]
        return bool(stale)

    def _inheritable(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Pending Tasks inside the fallback window that share a workspace with this event."""
        roots: set[str] = set(_roots(payload))
        now: float = self.clock()
        return [
            entry
            for entry in self.pending.values()
            if now - entry["t0"] <= FALLBACK_SECONDS and roots & set(entry["roots"])
        ]

    def _handed_on(self, entry: dict[str, Any]) -> tuple[bool, frozenset[str]]:
        """What the chat that started a pending Task holds NOW (CR1), not only when it started it.

        The record made at the Task is kept as a floor: an old links.json, or a parent whose note
        is gone, still hands on what the record says.
        """
        marked: bool = bool(entry["marked"])
        triggers: frozenset[str] = frozenset(entry["triggers"])
        parent: Session | None = self._sessions.get(entry["parent"])
        if parent is not None:
            held: Session = self.effective(parent)
            marked = marked or held.marked
            triggers = triggers | held.triggers
        return marked, triggers

    def fallback_until(self, payload: dict[str, Any]) -> float:
        """For a new chat with no parent link: when an inherited workspace mark ends (0: none)."""
        ends = (
            e["t0"] + FALLBACK_SECONDS for e in self._inheritable(payload) if self._handed_on(e)[0]
        )
        return max(ends, default=0.0)

    def fallback_triggers(self, payload: dict[str, Any]) -> dict[str, float]:
        """For a new chat with no parent link: each trigger it inherits and when that ends."""
        until: dict[str, float] = {}
        for entry in self._inheritable(payload):
            for trigger in self._handed_on(entry)[1]:
                until[trigger] = max(until.get(trigger, 0.0), entry["t0"] + FALLBACK_SECONDS)
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

    def effective_triggers(self, session: Session) -> frozenset[str]:
        """Triggers of the chat, of its parents, and those inherited through the fallback."""
        now: float = self.clock()
        found: set[str] = set()
        for s in self.chain(session):
            found |= s.triggers
            found |= {t for t, until in s.inherited_triggers.items() if until > now}
        return frozenset(found)

    def effective(self, session: Session) -> Session:
        """The session as the rules should see it: marked and triggered as its parents are."""
        marked: bool = session.marked or self.effective_marked(session)
        triggers: frozenset[str] = self.effective_triggers(session)
        if marked == session.marked and triggers == session.triggers:
            return session
        return replace(session, marked=marked, triggers=triggers)

    def propagate(self) -> bool:
        """A mark or trigger set inside a subagent reaches its parents. True if any changed."""
        changed: bool = False
        for session in list(self._sessions.values()):
            if not (session.marked or session.triggers):
                continue
            for ancestor in islice(self.chain(session), 1, None):
                if (
                    ancestor.marked or not session.marked
                ) and session.triggers <= ancestor.triggers:
                    continue  # nothing to hand up
                self._remember(
                    replace(
                        ancestor,
                        marked=ancestor.marked or session.marked,
                        triggers=ancestor.triggers | session.triggers,
                    )
                )
                changed = True
        return changed

    # ------------------------------------------------------------ old notes (D29)

    def _holds_on(self, session: Session, now: float) -> bool:
        """A mark, a trigger or an open inherited window: the note matters whatever its age."""
        return bool(
            session.marked
            or session.triggers
            or session.inherited_until > now
            or any(until > now for until in session.inherited_triggers.values())
        )

    def sweep(self) -> int:
        """Drop notes idle for 29 days unless they matter (D29). Returns how many went.

        Kept: a chat with activity in the last 29 days, a marked one, one with a trigger, one with
        an open inherited window, and every parent of a chat that stays. A call stays while a kept
        chat points to it, it is pending, or its parent stays. The writer saves the result.
        """
        now: float = self.clock()
        links: bool = self.prune_pending()
        cutoff: float = now - IDLE_DROP_SECONDS
        keep: set[str] = {
            sid
            for sid, s in self._sessions.items()
            if s.last_active > cutoff or self._holds_on(s, now)
        }
        for sid in list(keep):  # the parents, found while every link is still there
            child: Session = self._sessions[sid]
            if child.parent_id or child.parent_call:  # most chats have none
                keep.update(a.id for a in islice(self.chain(child), 1, None))
        dropped: set[str] = set(self._sessions) - keep
        if dropped:
            held: set[str] = {self._sessions[sid].parent_call for sid in keep}
            for sid in dropped:
                del self._sessions[sid]
            for call, parent in list(self.calls.items()):
                if parent in dropped and call not in held and call not in self.pending:
                    del self.calls[call]
                    links = True
        if dropped or links:
            self._lazy_dirty = True
            self._links_seq += links  # not strict: no hook waits for a sweep
            self._wake_writer()
        return len(dropped)

    def apply_mark(self, payload: dict[str, Any], stored: Session) -> tuple[Session, Session, bool]:
        """Run the marking rule for one event: (session to save, session the rules see, marks).

        A secret read in this chat marks it and its parents for good, even if a parent already
        marked it; a trigger that fires is kept the same way. The caller saves the returned session
        with `put`, which writes the parents too. `marks` is true when the chat became marked on
        this event, itself or through a parent (a trigger is not a secret read).
        """
        was_marked: bool = self.effective_marked(stored)
        fired: Session = mark(payload, stored)  # a superset of `stored`: marks only get stricter
        if fired != stored:
            stored = self._remember(fired)
            self.propagate()
        session: Session = self.effective(stored)
        return stored, session, session.marked and not was_marked
