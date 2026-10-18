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
from collections.abc import Callable, Iterator
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
        ended_at TEXT
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
                              file_sensitive, command, hosts, rule_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_END_SESSION: str = "UPDATE sessions SET ended_at = ? WHERE id = ?"

# "Marked by R1" is derived: a read or shell step touched a sensitive file (what mark() reacts to).
SESSIONS_QUERY: str = """
SELECT s.id, s.workspace_root, s.started_at,
       COALESCE(s.ended_at, MAX(t.time)) AS ended_at,
       COUNT(t.ord) AS steps,
       COALESCE(SUM(t.verdict = 'blocked'), 0) AS blocked,
       COALESCE(SUM(t.verdict = 'warned'), 0) AS warned,
       COALESCE(MAX(t.file_sensitive = 1 AND t.kind IN ('read', 'shell')), 0) AS marked
FROM (SELECT id, workspace_root, started_at, ended_at FROM sessions
      ORDER BY started_at DESC, id LIMIT ?) s
LEFT JOIN steps t ON t.session_id = s.id
GROUP BY s.id
ORDER BY s.started_at DESC, s.id
"""
SESSION_EXISTS_QUERY: str = "SELECT 1 FROM sessions WHERE id = ?"
STEPS_QUERY: str = """
SELECT ord, time, kind, verdict, tool, file_path, file_sensitive, command, hosts, rule_id
FROM steps WHERE session_id = ? ORDER BY ord LIMIT ?
"""


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


_STOP: object = object()
_Item = object  # a StepRecord, a SessionEvent, a flush Event or _STOP


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
            raise WipeIncomplete(_IN_USE) from exc
    finally:
        conn.close()
    return sessions, steps


def step_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """One STEPS_QUERY row in the same keys as GET /api/steps, plus the time."""
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
                    ),
                )
        elif isinstance(item, SessionEvent):
            with _transaction(conn):
                conn.execute(_UPSERT_SESSION, (item.session_id, item.workspace_root, item.time))
                if item.ended:
                    conn.execute(_END_SESSION, (item.time, item.session_id))

    # ---- reads (request threads)

    def _read(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        path = self.path
        if path is None or not path.exists():
            return None
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

    def list_sessions(self) -> list[dict[str, Any]]:
        """Past sessions, newest first. Empty when nothing was ever saved."""

        def work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(SESSIONS_QUERY, (SESSIONS_CAP,)).fetchall()
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

    def session_steps(self, session_id: str) -> tuple[list[dict[str, Any]], bool] | None:
        """(steps in order, truncated) or None for an unknown session."""

        def work(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], bool] | None:
            if conn.execute(SESSION_EXISTS_QUERY, (session_id,)).fetchone() is None:
                return None
            rows = conn.execute(STEPS_QUERY, (session_id, STEPS_CAP + 1)).fetchall()
            return [step_row_to_dict(r) for r in rows[:STEPS_CAP]], len(rows) > STEPS_CAP

        result: tuple[list[dict[str, Any]], bool] | None = self._read(work)
        return result


local_store: LocalStore = LocalStore()
