"""Background Neo4j step store (MERGE only; DELETE only via --clear)."""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neo4j import Driver, GraphDatabase

from recorder.clean import command_for_storage, website_name
from recorder.config_env import CREDENTIALS_PATH, neo4j_settings
from recorder.names import is_sensitive, words
from recorder.rules import RULES, Session

logger = logging.getLogger("flightrecorder")

_LABELS: tuple[str, ...] = ("Session", "Step", "File", "Command", "Host", "Rule")
_QUEUE_MAX: int = 256
_SENTINEL: object = object()


@dataclass(frozen=True)
class StepRecord:
    session_id: str
    started_at: str
    order: int
    time: str
    kind: str
    verdict: str
    tool: str | None = None
    file_path: str | None = None
    file_sensitive: bool = False
    command: str | None = None
    hosts: tuple[str, ...] = ()
    rule_id: str | None = None
    rule_description: str | None = None
    prev_step_id: str | None = None

    @property
    def step_id(self) -> str:
        return f"{self.session_id}:{self.order}"


@dataclass
class GraphStore:
    """Bounded-queue Neo4j writer. Safe to enqueue when disabled (no-op)."""

    enabled: bool = False
    _driver: Driver | None = field(default=None, repr=False)
    _queue: queue.Queue[StepRecord | object] = field(
        default_factory=lambda: queue.Queue(maxsize=_QUEUE_MAX),
        repr=False,
    )
    _thread: threading.Thread | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start(self, credentials_path: Path | None = None) -> None:
        path: Path = credentials_path if credentials_path is not None else CREDENTIALS_PATH
        settings = neo4j_settings(path)
        if settings is None:
            logger.warning("Neo4j credentials missing; store disabled")
            self.enabled = False
            return
        uri, user, password = settings
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            self._ensure_constraints()
            self.enabled = True
            self._thread = threading.Thread(target=self._worker, name="neo4j-store", daemon=True)
            self._thread.start()
            logger.info("Neo4j store started")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j store disabled: %s", type(exc).__name__)
            self.enabled = False
            if self._driver is not None:
                self._driver.close()
                self._driver = None

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            try:
                self._queue.put(_SENTINEL, timeout=1.0)
            except queue.Full:
                pass
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._driver is not None:
            close = getattr(self._driver, "close", None)
            if callable(close):
                close()
            self._driver = None
        self.enabled = False

    def enqueue(self, record: StepRecord) -> None:
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            logger.warning("Neo4j queue full; dropping step %s", record.step_id)

    def write_record_sync(self, record: StepRecord) -> None:
        """Write one record on the calling thread (tests / flush)."""
        if self._driver is None:
            raise RuntimeError("Neo4j driver not available")
        self._write(record)

    def _worker(self) -> None:
        while True:
            item: StepRecord | object = self._queue.get()
            if item is _SENTINEL:
                break
            assert isinstance(item, StepRecord)
            try:
                self._write(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Neo4j write failed: %s", type(exc).__name__)

    def _ensure_constraints(self) -> None:
        assert self._driver is not None
        with self._driver.session() as session:
            for label in _LABELS:
                session.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                )

    def _write(self, record: StepRecord) -> None:
        assert self._driver is not None
        with self._driver.session() as session:
            session.execute_write(_merge_step, record)

    def counts(self) -> dict[str, int]:
        if self._driver is None:
            raise RuntimeError("Neo4j driver not available")
        result: dict[str, int] = {}
        with self._driver.session() as session:
            for label in _LABELS:
                row = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
                result[label] = int(row["c"]) if row else 0
            for rel in ("HAS_STEP", "NEXT", "TOUCHED", "BLOCKED_BY"):
                row = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()
                result[rel] = int(row["c"]) if row else 0
        return result

    def clear_all(self) -> None:
        """DELETE all nodes — only code path that uses DELETE."""
        if self._driver is None:
            raise RuntimeError("Neo4j driver not available")
        with self._driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")


def _merge_step(tx: Any, record: StepRecord) -> None:
    tx.run(
        "MERGE (s:Session {id: $id}) ON CREATE SET s.started_at = $started_at",
        id=record.session_id,
        started_at=record.started_at,
    )
    tx.run(
        """
        MERGE (st:Step {id: $id})
        SET st.order = $order, st.time = $time, st.kind = $kind,
            st.verdict = $verdict, st.tool = $tool
        WITH st
        MATCH (s:Session {id: $session_id})
        MERGE (s)-[:HAS_STEP]->(st)
        """,
        id=record.step_id,
        order=record.order,
        time=record.time,
        kind=record.kind,
        verdict=record.verdict,
        tool=record.tool,
        session_id=record.session_id,
    )
    if record.prev_step_id:
        tx.run(
            """
            MATCH (prev:Step {id: $prev_id}), (st:Step {id: $id})
            MERGE (prev)-[:NEXT]->(st)
            """,
            prev_id=record.prev_step_id,
            id=record.step_id,
        )
    if record.file_path:
        tx.run(
            """
            MERGE (f:File {id: $fid})
            SET f.sensitive = $sensitive
            WITH f
            MATCH (st:Step {id: $sid})
            MERGE (st)-[:TOUCHED]->(f)
            """,
            fid=record.file_path,
            sensitive=record.file_sensitive,
            sid=record.step_id,
        )
    if record.command:
        tx.run(
            """
            MERGE (c:Command {id: $cid})
            WITH c
            MATCH (st:Step {id: $sid})
            MERGE (st)-[:TOUCHED]->(c)
            """,
            cid=record.command,
            sid=record.step_id,
        )
    for host in record.hosts:
        tx.run(
            """
            MERGE (h:Host {id: $hid})
            WITH h
            MATCH (st:Step {id: $sid})
            MERGE (st)-[:TOUCHED]->(h)
            """,
            hid=host,
            sid=record.step_id,
        )
    if record.rule_id:
        tx.run(
            """
            MERGE (r:Rule {id: $rid})
            SET r.description = $description
            WITH r
            MATCH (st:Step {id: $sid})
            MERGE (st)-[:BLOCKED_BY]->(r)
            """,
            rid=record.rule_id,
            description=record.rule_description or "",
            sid=record.step_id,
        )


def project_root_from_payload(payload: dict[str, Any]) -> Path:
    roots: Any = payload.get("workspace_roots")
    if isinstance(roots, list) and roots:
        return Path(str(roots[0]))
    cwd: str = str(payload.get("cwd", "") or "")
    if cwd:
        return Path(cwd)
    return Path.cwd()


def relative_file_path(file_path: str, project_root: Path) -> str:
    raw: Path = Path(file_path)
    root: Path = project_root.resolve()
    try:
        if raw.is_absolute():
            return raw.resolve().relative_to(root).as_posix()
    except ValueError:
        pass
    # Fall back to basename so shared files still MERGE (README.md, .env).
    return raw.name


def hosts_from_cleaned(cleaned: str) -> tuple[str, ...]:
    found: list[str] = []
    for token in words(cleaned):
        if token in {"<arg>", "<unparsed>", "<removed>"}:
            continue
        if token.startswith("-"):
            continue
        site: str | None = website_name(token)
        if site is None and "." in token and "/" not in token and "=" not in token:
            if website_name(f"https://{token}") is not None:
                site = token
            elif token.count(".") >= 1 and not token.startswith("<"):
                site = token
        if site is not None and site not in found:
            found.append(site)
    return tuple(found)


def kind_from_event(event: str) -> str:
    mapping: dict[str, str] = {
        "beforeReadFile": "read",
        "beforeShellExecution": "shell",
        "afterFileEdit": "edit",
        "beforeMCPExecution": "tool",
        "preToolUse": "tool",
    }
    return mapping.get(event, "tool")


def build_step_record(
    payload: dict[str, Any],
    session: Session,
    verdict: str,
    rule_id: str | None,
    *,
    order: int,
) -> StepRecord:
    """Build a cleaned StepRecord. Uses session.next_step only via `order` arg."""
    event: str = str(payload.get("hook_event_name", ""))
    kind: str = kind_from_event(event)
    now: str = datetime.now(UTC).isoformat()
    root: Path = project_root_from_payload(payload)

    file_path: str | None = None
    file_sensitive: bool = False
    command: str | None = None
    hosts: tuple[str, ...] = ()
    tool: str | None = None

    if kind == "read" or kind == "edit":
        raw_path: str = str(payload.get("file_path", "") or "")
        if raw_path:
            file_path = relative_file_path(raw_path, root)
            file_sensitive = is_sensitive(raw_path)
    elif kind == "shell":
        raw_cmd: str = str(payload.get("command", "") or "")
        command = command_for_storage(raw_cmd, root)
        hosts = hosts_from_cleaned(command)
        # Paths that survived cleaning (e.g. .env) as File touch
        for token in words(command):
            if token in {"<arg>", "<unparsed>"} or token.startswith("-") or "=" in token:
                continue
            if is_sensitive(token) or (root / token).exists():
                if file_path is None:
                    file_path = relative_file_path(token, root)
                    file_sensitive = is_sensitive(token)
    elif kind == "tool":
        tool = str(payload.get("tool_name", "") or payload.get("name", "") or "tool")

    rule_description: str | None = None
    if rule_id is not None:
        for rule in RULES:
            if rule.id == rule_id:
                rule_description = rule.message
                break

    prev_step_id: str | None = None
    if order > 1:
        prev_step_id = f"{session.id}:{order - 1}"

    # Map decide() "allow" to stored verdict "allowed"
    stored_verdict: str = "allowed" if verdict == "allow" else verdict

    return StepRecord(
        session_id=session.id,
        started_at=session.start_time,
        order=order,
        time=now,
        kind=kind,
        verdict=stored_verdict,
        tool=tool,
        file_path=file_path,
        file_sensitive=file_sensitive,
        command=command,
        hosts=hosts,
        rule_id=rule_id,
        rule_description=rule_description,
        prev_step_id=prev_step_id,
    )


# Module-level store used by the FastAPI app.
graph_store: GraphStore = GraphStore()


def _open_cli_store() -> GraphStore:
    store = GraphStore()
    settings = neo4j_settings(CREDENTIALS_PATH)
    if settings is None:
        raise SystemExit("Neo4j credentials missing")
    uri, user, password = settings
    store._driver = GraphDatabase.driver(uri, auth=(user, password))
    store._ensure_constraints()
    store.enabled = True
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flight Recorder Neo4j store utilities")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--counts", action="store_true", help="Print node and link counts")
    group.add_argument("--clear", action="store_true", help="DELETE all nodes (dangerous)")
    args = parser.parse_args(argv)

    store = _open_cli_store()
    try:
        if args.counts:
            for key, value in store.counts().items():
                print(f"{key}\t{value}")
            return 0
        if args.clear:
            store.clear_all()
            print("cleared")
            return 0
    finally:
        if store._driver is not None:
            store._driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
