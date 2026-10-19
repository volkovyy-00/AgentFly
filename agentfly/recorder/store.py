"""Background Neo4j step store (MERGE only; DELETE only via --clear)."""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
import tomllib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neo4j import Driver, GraphDatabase

from agentfly.recorder import clean as clean_settings
from agentfly.recorder.clean import clean_command, website_name
from agentfly.recorder.config_env import neo4j_settings
from agentfly.recorder.names import is_sensitive, words
from agentfly.recorder.paths import config_dir
from agentfly.recorder.rules import RULES, Session, mark

logger = logging.getLogger("agentfly")

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
    workspace_root: str | None = None
    # V6b: this is the step on whose event the rules first counted the chat as marked.
    marks: bool = False
    # The command as typed, only when CLEAN_COMMANDS is off. Neo4j's Command node reads it;
    # `command` (history, live trail) is always the cleaned text.
    raw_command: str | None = field(default=None, repr=False, compare=False)
    # V8b: the deny answer's messages, for the live page's Why card. Memory only: no store writes
    # these (the rule's own text is `rule_description`).
    user_message: str | None = field(default=None, repr=False, compare=False)
    agent_message: str | None = field(default=None, repr=False, compare=False)

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
        settings = neo4j_settings(credentials_path)
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
            cid=record.raw_command or record.command,
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


def neo4j_opt_in(config_path: Path | None = None) -> bool:
    """True only when config.toml says `neo4j = true` (owner, 2026-10-18; D14).

    A present neo4j.env alone does not turn Neo4j on. A missing or broken file means off.
    """
    path: Path = config_path if config_path is not None else config_dir() / "config.toml"
    try:
        with path.open("rb") as handle:
            settings: dict[str, Any] = tomllib.load(handle)
    except FileNotFoundError:
        return False
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        logger.warning("config.toml not read (%s); Neo4j stays off", type(exc).__name__)
        return False
    return settings.get("neo4j") is True


def first_workspace_root(payload: dict[str, Any]) -> str | None:
    """The workspace root Cursor reports, or None. Never the recorder's own folder."""
    roots: Any = payload.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0]:
        return roots[0]
    return None


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
    marks: bool = False,
) -> StepRecord:
    """Build a cleaned StepRecord. Uses session.next_step only via `order` arg.

    `marks` is what `SessionStore.apply_mark` said about this event: it made the chat marked.
    """
    event: str = str(payload.get("hook_event_name", ""))
    kind: str = kind_from_event(event)
    now: str = datetime.now(UTC).isoformat()
    root: Path = project_root_from_payload(payload)

    file_path: str | None = None
    file_sensitive: bool = False
    command: str | None = None
    hosts: tuple[str, ...] = ()
    tool: str | None = None
    raw_command: str | None = None

    if kind == "read" or kind == "edit":
        raw_path: str = str(payload.get("file_path", "") or "")
        if raw_path:
            file_path = relative_file_path(raw_path, root)
            file_sensitive = is_sensitive(raw_path)
    elif kind == "shell":
        raw_cmd: str = str(payload.get("command", "") or "")
        command = clean_command(raw_cmd, root)
        if not clean_settings.CLEAN_COMMANDS:
            raw_command = raw_cmd
        hosts = hosts_from_cleaned(command)
        # Paths that survived cleaning (e.g. .env) as File touch; a sensitive one wins.
        for token in words(command):
            if token in {"<arg>", "<unparsed>"} or token.startswith("-") or "=" in token:
                continue
            if is_sensitive(token):
                file_path = relative_file_path(token, root)
                file_sensitive = True
                break
            if file_path is None and (root / token).exists():
                file_path = relative_file_path(token, root)
    elif kind == "tool":
        tool = str(payload.get("tool_name", "") or payload.get("name", "") or "tool")
        tool_input: Any = payload.get("tool_input")
        written: Any = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        if tool.casefold() == "write" and isinstance(written, str) and written:
            # V2c: a Write that no specific hook follows still says which file it wrote.
            file_path = relative_file_path(written, root)
            file_sensitive = is_sensitive(written)

    if kind == "shell" and not file_sensitive:
        # The rule engine's own test, whatever this chat's mark is: the history and R1 agree.
        # (A read step already used it above: `mark()` tests the same file name.)
        if mark(payload, replace(session, marked=False)).marked:
            file_sensitive = True
            file_path = None  # the cleaner hid the name; do not show another file as touched

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
        workspace_root=first_workspace_root(payload),
        marks=marks,
        raw_command=raw_command,
    )


# Module-level store used by the FastAPI app.
graph_store: GraphStore = GraphStore()


def _open_cli_store() -> GraphStore:
    store = GraphStore()
    settings = neo4j_settings()
    if settings is None:
        raise SystemExit("Neo4j credentials missing")
    uri, user, password = settings
    store._driver = GraphDatabase.driver(uri, auth=(user, password))
    store._ensure_constraints()
    store.enabled = True
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentFly Neo4j store utilities")
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
