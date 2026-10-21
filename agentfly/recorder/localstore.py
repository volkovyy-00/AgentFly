"""Local SQLite history: a cleaned copy of every step, written in the background (D14).

Saving never touches a hook answer: `enqueue` is a non-blocking put and one thread does the
writing. Reads use short-lived read-only connections, named queries and a time limit.
Deleting rows happens in two functions only: `purge_rows` (28-day retention) and `wipe_file`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentfly.recorder.paths import private_dir
from agentfly.recorder.store import StepRecord, first_workspace_root

logger = logging.getLogger("agentfly")

DB_NAME: str = "history.db"
RETENTION: timedelta = timedelta(days=28)
PURGE_EVERY: timedelta = timedelta(hours=1)
SESSION_EVENTS: frozenset[str] = frozenset({"sessionStart", "sessionEnd", "subagentStart"})
VERDICTS: tuple[str, ...] = ("allowed", "blocked", "warned", "highlighted")

QUEUE_MAX: int = 1024
TICK_S: float = 60.0  # how often an idle writer wakes up to check the purge schedule
REOPEN_AFTER_S: float = 5.0
WRITE_TIMEOUT_S: float = 5.0
WIPE_BUDGET_S: float = 10.0  # `agentfly wipe` gives up after this long, however busy the file is
READ_TIMEOUT_S: float = 2.0
PROGRESS_OPS: int = 1000  # SQLite VM steps between two looks at the read deadline
SESSIONS_CAP: int = 500
STEPS_CAP: int = 10_000
ROOT_MAX: int = 4096

_SCHEMA: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        workspace_root TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        marked INTEGER NOT NULL DEFAULT 0
    )""",
    f"""CREATE TABLE IF NOT EXISTS steps (
        session_id TEXT NOT NULL,
        ord INTEGER NOT NULL,
        time TEXT NOT NULL,
        kind TEXT NOT NULL,
        tool TEXT,
        verdict TEXT NOT NULL CHECK (verdict IN ({", ".join(repr(v) for v in VERDICTS)})),
        file_path TEXT,
        file_sensitive INTEGER NOT NULL DEFAULT 0,
        command TEXT,
        hosts TEXT NOT NULL DEFAULT '[]',
        rule_id TEXT,
        marks INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (session_id, ord)
    )""",
    "CREATE INDEX IF NOT EXISTS steps_time ON steps (time)",
    "CREATE INDEX IF NOT EXISTS sessions_started ON sessions (started_at)",
)

_UPSERT_SESSION: str = """
INSERT INTO sessions (id, workspace_root, started_at) VALUES (?, ?, ?)
ON CONFLICT (id) DO UPDATE SET
    workspace_root = COALESCE(sessions.workspace_root, excluded.workspace_root),
    started_at = MIN(sessions.started_at, excluded.started_at)
"""
_UPSERT_STEP: str = """
INSERT OR REPLACE INTO steps (session_id, ord, time, kind, tool, verdict, file_path,
                              file_sensitive, command, hosts, rule_id, marks)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_END_SESSION: str = "UPDATE sessions SET ended_at = ? WHERE id = ?"
# V6b: the flag only goes up. A chat with no row (purged, wiped) gets none: its next step makes one.
_MARK_SESSION: str = "UPDATE sessions SET marked = 1 WHERE id = ? AND marked = 0"

# Before V6b "marked" was a guess: a read or shell step touched a sensitive file. It stays the
# value of a chat saved by that recorder (see `_upgrade`).
_GUESSED_MARK: str = "t.file_sensitive = 1 AND t.kind IN ('read', 'shell')"
_LISTING: str = """
SELECT s.id, s.workspace_root, s.started_at,
       COALESCE(s.ended_at, MAX(t.time)) AS ended_at,
       COUNT(t.ord) AS steps,
       COALESCE(SUM(t.verdict = 'blocked'), 0) AS blocked,
       COALESCE(SUM(t.verdict = 'warned'), 0) AS warned,
       {marked} AS marked
FROM (SELECT id, workspace_root, started_at, ended_at{column} FROM sessions
      ORDER BY started_at DESC, id LIMIT ?) s
LEFT JOIN steps t ON t.session_id = s.id
GROUP BY s.id
ORDER BY s.started_at DESC, s.id
"""
SESSIONS_QUERY: str = _LISTING.format(marked="s.marked", column=", marked")
# The same listing for a file the writer has not upgraded yet (a read can beat it at start-up).
SESSIONS_QUERY_V1: str = _LISTING.format(marked=f"COALESCE(MAX({_GUESSED_MARK}), 0)", column="")
SESSION_EXISTS_QUERY: str = "SELECT 1 FROM sessions WHERE id = ?"
STEPS_QUERY: str = """
SELECT ord, time, kind, verdict, tool, file_path, file_sensitive, command, hosts, rule_id
FROM steps WHERE session_id = ? ORDER BY ord LIMIT ?
"""
# F11: the first order number each chat's saved steps have not used (`INSERT OR REPLACE` on
# (session_id, ord) means a counter that goes back overwrites history).
NEXT_ORDERS_QUERY: str = "SELECT session_id, MAX(ord) + 1 FROM steps GROUP BY session_id"
# Not limited by STEPS_CAP: the marking step is named even when the list is cut.
MARKING_STEP_QUERY: str = "SELECT MIN(ord) FROM steps WHERE session_id = ? AND marks = 1"

_UPGRADED: str = "SELECT 1 FROM pragma_table_info('sessions') WHERE name = 'marked'"
# What a file written before V6b needs, in one transaction: it has both new columns or neither.
_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE steps ADD COLUMN marks INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE sessions ADD COLUMN marked INTEGER NOT NULL DEFAULT 0",
    # Old chats keep the value the old listing gave them; old steps keep marks = 0.
    "UPDATE sessions SET marked = EXISTS (SELECT 1 FROM steps t"
    f" WHERE t.session_id = sessions.id AND {_GUESSED_MARK})",
)


class StoreUnavailable(Exception):
    """The history cannot be read right now (cannot open, or the time limit ran out)."""


_IN_USE: str = "the history file is in use; old pages may remain"


class WipeIncomplete(Exception):
    """Rows are deleted but the file still holds old pages (a reader kept the log busy)."""


class _Unavailable(Exception):
    """Writer-side: the store could not be opened a moment ago; the item is dropped quietly."""


@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    time: str
    workspace_root: str | None
    ended: bool


@dataclass(frozen=True)
class MarkedSessions:
    """Chats the rules count as marked (V6b). Queued after their steps, so their rows exist."""

    session_ids: tuple[str, ...]


_STOP: object = object()
_Item = object  # a StepRecord, a SessionEvent, a MarkedSessions, a flush Event or _STOP


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clip(text: str | None) -> str | None:
    return None if text is None else text[:ROOT_MAX]


@contextlib.contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _upgraded(conn: sqlite3.Connection) -> bool:
    """False for a file an older recorder wrote (before V6b): it has no `marked` column yet."""
    return conn.execute(_UPGRADED).fetchone() is not None


def _upgrade(conn: sqlite3.Connection) -> None:
    """Bring a file written by an older recorder up to the current tables, losing nothing.

    All in one transaction (DDL rolls back too), so a crash leaves the old tables. It checks again
    inside it: a second recorder may have upgraded the file a moment ago.
    """
    if _upgraded(conn):
        return
    with _transaction(conn):
        if not _upgraded(conn):
            for statement in _UPGRADE:
                conn.execute(statement)


def _truncate_wal(conn: sqlite3.Connection) -> bool:
    """Cut the log down to nothing so no old page image stays in it. False when a reader is busy.

    It never waits: the writer thread must stay free, and the caller tries again later.
    """
    conn.execute("PRAGMA busy_timeout=0")
    try:
        busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    finally:
        conn.execute(f"PRAGMA busy_timeout={int(WRITE_TIMEOUT_S * 1000)}")
    return not busy


def purge_rows(conn: sqlite3.Connection, cutoff: str) -> bool:
    """Retention: steps older than the cutoff, then sessions that have no step left.

    Returns False when the log could not be cut yet (a reader holds it); try `_truncate_wal` again.
    """
    with _transaction(conn):
        conn.execute("DELETE FROM steps WHERE time < ?", (cutoff,))
        conn.execute(
            "DELETE FROM sessions WHERE started_at < ?"
            " AND NOT EXISTS (SELECT 1 FROM steps WHERE steps.session_id = sessions.id)",
            (cutoff,),
        )
    return _truncate_wal(conn)


def _checkpoint(conn: sqlite3.Connection, deadline: float) -> None:
    """Fold the log into the file and cut it. A busy answer is not an error, so look at it.

    Quick tries with a pause between them: a checkpoint that waits for a reader would hold the
    write lock the whole time and starve the recorder's own writer.
    """
    while not _truncate_wal(conn):
        if time.monotonic() >= deadline:
            raise WipeIncomplete(_IN_USE)
        time.sleep(0.2)


def _wipe_reason(exc: sqlite3.Error) -> str:
    """Why the file could not be rewritten: busy gets the "in use" text, anything else its class."""
    busy = isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()
    return _IN_USE if busy else f"the history file could not be rewritten ({type(exc).__name__})"


def wipe_file(path: Path) -> tuple[int, int]:
    """Delete every session and step, then rewrite the file so nothing old stays in it.

    Returns (sessions, steps) deleted. Session marks and Neo4j are not touched here. Gives up after
    WIPE_BUDGET_S in total: with nothing deleted yet it raises the sqlite error, with rows already
    deleted it raises WipeIncomplete.
    """
    deadline = time.monotonic() + WIPE_BUDGET_S
    conn = sqlite3.connect(path, timeout=WIPE_BUDGET_S, isolation_level=None)
    try:
        conn.execute("PRAGMA secure_delete=ON")
        try:
            with _transaction(conn):
                steps = conn.execute("DELETE FROM steps").rowcount
                sessions = conn.execute("DELETE FROM sessions").rowcount
        except sqlite3.OperationalError as exc:
            if not str(exc).startswith("no such table"):
                raise
            return 0, 0  # the recorder made the file but was stopped before the tables
        try:
            _checkpoint(conn, deadline)
            left = max(0, int((deadline - time.monotonic()) * 1000))
            conn.execute(f"PRAGMA busy_timeout={left}")  # VACUUM may wait, but only this long
            conn.execute("VACUUM")
            _checkpoint(conn, deadline)
        except sqlite3.Error as exc:
            raise WipeIncomplete(_wipe_reason(exc)) from exc
    finally:
        conn.close()
    return sessions, steps


def read_only(path: Path, work: Callable[[sqlite3.Connection], Any]) -> Any:
    """Run `work` on a short-lived read-only connection with a time limit.

    None when the file has no tables yet (the writer has made it but not filled it). Any other
    sqlite problem, or the time limit, is `StoreUnavailable`.
    """
    deadline = time.monotonic() + READ_TIMEOUT_S
    try:
        conn = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, timeout=READ_TIMEOUT_S, isolation_level=None
        )
    except sqlite3.Error as exc:
        raise StoreUnavailable(type(exc).__name__) from None
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), PROGRESS_OPS)
        return work(conn)
    except sqlite3.Error as exc:
        if str(exc).startswith("no such table"):
            return None  # the writer has made the file but not the tables yet: nothing saved
        raise StoreUnavailable(type(exc).__name__) from None
    finally:
        conn.close()


def next_orders(path: Path) -> dict[str, int]:
    """Chat id -> first order number its saved steps have not used (F11); {} if nothing can be read.

    Read once at start-up, before the writer opens the file, so a recorder that was killed can
    not number new steps over old rows. It works on a log a killed writer left behind. A file that
    cannot be read gives {} and one warning: the numbers then come from sessions.json alone.
    """
    if not path.exists():
        return {}
    try:
        found: dict[str, int] | None = read_only(
            path,
            lambda conn: {str(sid): int(first) for sid, first in conn.execute(NEXT_ORDERS_QUERY)},
        )
    except StoreUnavailable as exc:
        logger.warning("local store: step numbers not read (%s)", exc)
        return {}
    return found or {}


def step_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """One STEPS_QUERY row in the keys of GET /api/steps, plus the time.

    Not `rule_text`, `user_message` or `agent_message`: history stores none of the three (SPEC §4).
    """
    hosts: list[str] = json.loads(row[8])
    return {
        "order": row[0],
        "time": row[1],
        "kind": row[2],
        "verdict": row[3],
        "tool": row[4],
        "file": row[5],
        "sensitive": bool(row[6]),
        "command": row[7],
        "host": hosts[0] if hosts else None,
        "rule": row[9],
    }


class LocalStore:
    """Background SQLite writer plus named read queries. Safe to call before `start`."""

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self.clock: Callable[[], datetime] = clock
        self.path: Path | None = None
        self._queue: queue.Queue[_Item] = queue.Queue(maxsize=QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._conn: sqlite3.Connection | None = None
        self._last_purge: datetime | None = None
        self._retry_at: float = 0.0
        self._failing: bool = False
        self._dropping: bool = False
        self._wal_dirty: bool = False  # a purge could not cut the log yet

    # ---- lifecycle

    def start(self, path: Path) -> None:
        """Begin writing to `path`. Never raises; the file is opened by the writer thread."""
        self.stop()
        self.path = path
        self._queue = queue.Queue(maxsize=QUEUE_MAX)
        self._last_purge = None
        self._retry_at = 0.0
        self._failing = self._dropping = False
        self._wal_dirty = False
        # The thread keeps its own queue: a writer that outlives a failed stop() must not
        # start taking items meant for the next start().
        self._thread = threading.Thread(
            target=self._run, args=(self._queue,), name="local-store", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        with contextlib.suppress(queue.Full):
            self._queue.put(_STOP, timeout=1.0)
        thread.join(timeout=10.0)
        self._thread = None

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued so far has been handled (tests, shutdown)."""
        if self._thread is None:
            return True
        done = threading.Event()
        try:
            self._queue.put(done, timeout=timeout)
        except queue.Full:
            return False
        return done.wait(timeout)

    # ---- called from the request path: must never raise or wait

    def record_session_event(self, payload: dict[str, Any]) -> bool:
        """True when the payload is a session event: it updates the session and is not a step."""
        event: Any = payload.get("hook_event_name")
        if not isinstance(event, str) or event not in SESSION_EVENTS:
            return False
        self.enqueue(
            SessionEvent(
                session_id=str(payload.get("conversation_id", "") or "unknown"),
                time=self.clock().isoformat(),
                workspace_root=_clip(first_workspace_root(payload)),
                ended=event == "sessionEnd",
            )
        )
        return True

    def enqueue(self, item: StepRecord | SessionEvent) -> None:
        if self._thread is None:
            return
        try:
            self._queue.put_nowait(item)
            self._dropping = False
        except queue.Full:
            if not self._dropping:
                self._dropping = True
                logger.warning("local store queue full; dropping steps until it drains")
        except Exception as exc:  # noqa: BLE001
            logger.warning("local store: not queued (%s)", type(exc).__name__)

    def mark_sessions(self, session_ids: Iterable[str]) -> None:
        """The rules count these chats as marked now (V6b); the flag only goes up.

        Called after the chat's step or session event was queued, so the row is there when this
        runs. Never waits: a full queue drops it, and every later event of a marked chat sends it
        again. The steps' own drop warning covers the full queue, so this one stays quiet.
        """
        ids: tuple[str, ...] = tuple(session_ids)
        if self._thread is not None and ids:
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(MarkedSessions(ids))

    # ---- writer thread

    def _run(self, items: queue.Queue[_Item]) -> None:
        try:
            self._tick()
            while True:
                try:
                    item: _Item | None = items.get(timeout=TICK_S)
                except queue.Empty:
                    item = None
                try:
                    if item is _STOP:
                        break
                    self._tick()
                    if isinstance(item, threading.Event):
                        item.set()
                    elif item is not None:
                        self._write(item)
                        self._failing = False
                except Exception as exc:  # noqa: BLE001 - one bad item must not end saving
                    self._failed(exc)
                finally:
                    if item is not None:
                        items.task_done()
        finally:
            self._close()

    def _tick(self) -> None:
        """Run the retention sweep at start and once per PURGE_EVERY. Between sweeps, finish a
        cut of the log that a reader blocked."""
        now = self.clock()
        due = self._last_purge is None or now - self._last_purge >= PURGE_EVERY
        try:
            if due:
                self._last_purge = now
                self._wal_dirty = not purge_rows(self._connection(), (now - RETENTION).isoformat())
            elif self._wal_dirty:
                self._wal_dirty = not _truncate_wal(self._connection())
        except Exception as exc:  # noqa: BLE001
            self._failed(exc)

    def _failed(self, exc: Exception) -> None:
        if isinstance(exc, sqlite3.Error | OSError | _Unavailable):
            self._close()
        if isinstance(exc, _Unavailable) or self._failing:
            return
        self._failing = True
        logger.warning("local store write failed: %s", type(exc).__name__)

    def _close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    def _connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self.path is None or time.monotonic() < self._retry_at:
            raise _Unavailable
        try:
            self._conn = self._open(self.path)
        except Exception:
            self._retry_at = time.monotonic() + REOPEN_AFTER_S
            raise
        return self._conn

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        private_dir(path.parent)
        os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
        if path.stat().st_mode & 0o077:
            path.chmod(0o600)  # tighten a file that is too open; never loosen one
        conn = sqlite3.connect(path, timeout=WRITE_TIMEOUT_S, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # also keeps readers off the writer's back
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA secure_delete=ON")  # deleted rows must not linger in the file
            for statement in _SCHEMA:
                conn.execute(statement)
            _upgrade(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _write(self, item: _Item) -> None:
        conn = self._connection()
        if isinstance(item, StepRecord):
            with _transaction(conn):
                conn.execute(
                    _UPSERT_SESSION,
                    (item.session_id, _clip(item.workspace_root), item.started_at),
                )
                conn.execute(
                    _UPSERT_STEP,
                    (
                        item.session_id,
                        item.order,
                        item.time,
                        item.kind,
                        item.tool,
                        item.verdict,
                        item.file_path,
                        int(item.file_sensitive),
                        item.command,
                        json.dumps(list(item.hosts)),
                        item.rule_id,
                        int(item.marks),
                    ),
                )
                if item.marks:  # the marking step and its chat's flag are never apart
                    conn.execute(_MARK_SESSION, (item.session_id,))
        elif isinstance(item, SessionEvent):
            with _transaction(conn):
                conn.execute(_UPSERT_SESSION, (item.session_id, item.workspace_root, item.time))
                if item.ended:
                    conn.execute(_END_SESSION, (item.time, item.session_id))
        elif isinstance(item, MarkedSessions):
            with _transaction(conn):
                conn.executemany(_MARK_SESSION, [(sid,) for sid in item.session_ids])

    # ---- reads (request threads)

    def _read(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        path = self.path
        if path is None or not path.exists():
            return None
        return read_only(path, work)

    def list_sessions(self) -> list[dict[str, Any]]:
        """Past sessions, newest first. Empty when nothing was ever saved."""

        def work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            query: str = SESSIONS_QUERY if _upgraded(conn) else SESSIONS_QUERY_V1
            rows = conn.execute(query, (SESSIONS_CAP,)).fetchall()
            return [
                {
                    "id": r[0],
                    "workspace_root": r[1],
                    "started_at": r[2],
                    "ended_at": r[3],
                    "steps": r[4],
                    "blocked": r[5],
                    "warned": r[6],
                    "marked": bool(r[7]),
                }
                for r in rows
            ]

        found: list[dict[str, Any]] | None = self._read(work)
        return [] if found is None else found

    def session_steps(
        self, session_id: str
    ) -> tuple[list[dict[str, Any]], bool, int | None] | None:
        """(steps in order, truncated, order of the step that marked the chat) or None if unknown.

        The marking step is None for a chat that was never marked, whose marking step aged out,
        that an older recorder saved (those steps have no flag), or that is marked through a link
        (subagent, parent, workspace fallback): the step that marked it is in another chat.
        """

        def work(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], bool, int | None] | None:
            if conn.execute(SESSION_EXISTS_QUERY, (session_id,)).fetchone() is None:
                return None
            rows = conn.execute(STEPS_QUERY, (session_id, STEPS_CAP + 1)).fetchall()
            marking: int | None = None
            if _upgraded(conn):
                marking = conn.execute(MARKING_STEP_QUERY, (session_id,)).fetchone()[0]
            return [step_row_to_dict(r) for r in rows[:STEPS_CAP]], len(rows) > STEPS_CAP, marking

        result: tuple[list[dict[str, Any]], bool, int | None] | None = self._read(work)
        return result


local_store: LocalStore = LocalStore()
