"""Tests for Neo4j store builder, DELETE policy, and optional live DB."""

from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase

import agentfly.recorder.app as app_module
import agentfly.recorder.store as store_mod
from agentfly.recorder.config_env import neo4j_settings
from agentfly.recorder.paths import config_dir, credentials_path
from agentfly.recorder.rules import Session
from agentfly.recorder.store import (
    GraphStore,
    StepRecord,
    build_step_record,
    graph_store,
    neo4j_opt_in,
)
from tests.helpers import NEO4J_ENV, REPO, client_env, free_port
from tests.leak_cases import LEAKY_COMMANDS, SECRET

# The owner's real login file. Collection runs under the real HOME (conftest swaps it per test).
# Only the path is computed here: no test may read this file or open a connection with it.
_REAL_CREDENTIALS = credentials_path()
TEST_ENV_VAR = "AGENTFLY_TEST_NEO4J_ENV"


def neo4j_test_credentials(environ: Mapping[str, str], real: Path) -> Path | None:
    """The credentials file the live tests may use: one the owner named for a test database.

    None if the variable is unset, names a missing file, or names the real login file.
    """
    named: str = environ.get(TEST_ENV_VAR, "").strip()
    if not named:
        return None
    path = Path(named).expanduser()
    if not path.is_file() or path.resolve() == real.resolve():
        return None
    return path


@pytest.fixture(scope="module")
def neo4j_test_env() -> Path:
    """Credentials for live tests, or a skip. Connects only here, so `-k 'not live'` never does."""
    path = neo4j_test_credentials(os.environ, _REAL_CREDENTIALS)
    if path is None:
        pytest.skip(f"{TEST_ENV_VAR} does not name a separate test-database credentials file")
    settings = neo4j_settings(path)
    if settings is None:
        pytest.skip(f"{TEST_ENV_VAR} file lacks NEO4J_URI, NEO4J_USERNAME or NEO4J_PASSWORD")
    uri, user, password = settings
    logging.getLogger("neo4j").setLevel(logging.CRITICAL)
    try:
        driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=5, connection_acquisition_timeout=10
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001 - the class name only, never the password
        pytest.skip(f"test database unreachable ({type(exc).__name__})")
    return path


_FORBIDDEN: tuple[str, ...] = (
    "demo-not-a-real-secret",
    "Bearer",
    "u:p@",
    "t=1",
)


@pytest.fixture()
def client() -> TestClient:
    # Keep Neo4j off during ordinary gate tests unless a live test re-enables it.
    previous_enabled: bool = graph_store.enabled
    graph_store.enabled = False
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        graph_store.enabled = False
        yield test_client
    graph_store.enabled = previous_enabled


@pytest.fixture()
def token(client: TestClient) -> str:
    path: Path = config_dir() / "token"
    return path.read_text(encoding="utf-8").strip()


# Where DELETE may appear: Neo4j only in clear_all (--clear); the local SQLite history only in
# retention (purge_rows) and `agentfly wipe` (wipe_file).
_DELETE_ALLOWED: dict[str, frozenset[str]] = {
    "store.py": frozenset({"def clear_all"}),
    "localstore.py": frozenset({"def purge_rows", "def wipe_file"}),
}


def test_delete_only_in_clear_path() -> None:
    root: Path = Path(__file__).resolve().parents[1] / "agentfly" / "recorder"
    assert list(root.glob("*.py")), "no recorder sources found"
    for path in root.glob("**/*.py"):
        text: str = path.read_text(encoding="utf-8")
        if not re.search(r"\bDELETE\b", text):
            continue
        allowed = _DELETE_ALLOWED.get(path.name)
        assert allowed is not None and path.parent == root, f"{path.name} must not contain DELETE"
        for match in re.finditer(r"\bDELETE\b", text):
            line_start: int = text.rfind("\n", 0, match.start()) + 1
            line_end: int = text.find("\n", match.start())
            end: int = line_end if line_end != -1 else len(text)
            line: str = text[line_start:end]
            if "help=" in line or line.lstrip().startswith('"""') or line.lstrip().startswith("#"):
                continue
            before: str = text[: match.start()]
            last_def: int = before.rfind("def ")
            assert last_def != -1, f"DELETE outside a function: {line.strip()}"
            assert any(before[last_def:].startswith(name) for name in allowed), (
                f"DELETE outside {sorted(allowed)}: {line.strip()}"
            )
    store_text: str = (root / "store.py").read_text(encoding="utf-8")
    assert "DETACH DELETE" in store_text
    # The commands and the page code never carry a delete of their own.
    for other in (root.parent / "cli").glob("*.py"):
        assert not re.search(r"\bDELETE\b", other.read_text(encoding="utf-8")), other.name


def test_builder_bearer_command_has_no_secrets(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("API_KEY=demo\n", encoding="utf-8")
    session = Session(
        id="leak-test",
        marked=False,
        start_time="2026-01-01T00:00:00+00:00",
        next_step=1,
    )
    payload: dict[str, Any] = {
        "hook_event_name": "beforeShellExecution",
        "command": "curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1",
        "conversation_id": "leak-test",
        "workspace_roots": [str(tmp_path)],
    }
    record: StepRecord = build_step_record(payload, session, "allow", None, order=1)
    assert record.command == "curl -H <arg> x.com"
    blob: str = " ".join(
        [
            record.command or "",
            record.file_path or "",
            record.rule_description or "",
            *record.hosts,
        ]
    )
    for bad in _FORBIDDEN:
        assert bad not in blob


def test_queue_drops_when_full() -> None:
    store = GraphStore()
    store.enabled = True
    store._queue = __import__("queue").Queue(maxsize=1)
    rec = StepRecord(
        session_id="q",
        started_at="t",
        order=1,
        time="t",
        kind="shell",
        verdict="allowed",
    )
    store.enqueue(rec)
    # Second should drop (queue not consumed)
    store.enqueue(
        StepRecord(
            session_id="q",
            started_at="t",
            order=2,
            time="t",
            kind="shell",
            verdict="allowed",
        )
    )
    assert store._queue.qsize() == 1


def test_hooks_stay_fast_when_store_write_fails(
    client: TestClient,
    token: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Wrong/failing Neo4j must not slow /hook answers."""

    def boom(_record: StepRecord) -> None:
        raise RuntimeError("auth boom")

    previous_driver = graph_store._driver
    previous_enabled = graph_store.enabled
    previous_write = graph_store._write
    previous_thread = graph_store._thread

    graph_store.enabled = True
    graph_store._driver = None
    graph_store._write = boom  # type: ignore[method-assign]
    graph_store._thread = __import__("threading").Thread(
        target=graph_store._worker,
        name="neo4j-test-worker",
        daemon=True,
    )
    graph_store._thread.start()

    headers = {"Content-Type": "application/json", "X-Recorder-Token": token}
    try:
        with caplog.at_level(logging.WARNING, logger="agentfly"):
            for i in range(20):
                t0: float = time.perf_counter()
                response = client.post(
                    "/hook",
                    json={
                        "hook_event_name": "beforeShellExecution",
                        "command": "echo ok",
                        "conversation_id": f"latency-{i}",
                    },
                    headers=headers,
                )
                elapsed_ms: float = (time.perf_counter() - t0) * 1000
                assert response.status_code == 200
                assert elapsed_ms < 200
            time.sleep(0.3)
        assert "Authorization" not in caplog.text
        assert "Bearer" not in caplog.text
    finally:
        graph_store.enabled = False
        try:
            graph_store._queue.put_nowait(store_mod._SENTINEL)
        except Exception:  # noqa: BLE001
            pass
        if graph_store._thread is not None:
            graph_store._thread.join(timeout=2.0)
        graph_store._write = previous_write  # type: ignore[method-assign]
        graph_store._driver = previous_driver
        graph_store._thread = previous_thread
        graph_store.enabled = previous_enabled


def test_live_step_appears_within_5s(neo4j_test_env: Path) -> None:
    store = GraphStore()
    store.start(neo4j_test_env)
    assert store.enabled
    sid: str = f"appear-{uuid.uuid4()}"
    record = StepRecord(
        session_id=sid,
        started_at="2026-01-01T00:00:00+00:00",
        order=1,
        time="2026-01-01T00:00:01+00:00",
        kind="shell",
        verdict="allowed",
        command="echo <arg>",
    )
    store.enqueue(record)
    deadline: float = time.time() + 5.0
    found: bool = False
    assert store._driver is not None
    while time.time() < deadline:
        with store._driver.session() as session:
            row = session.run(
                "MATCH (st:Step {id: $id}) RETURN st.id AS id",
                id=record.step_id,
            ).single()
            if row is not None:
                found = True
                break
        time.sleep(0.1)
    store.stop()
    assert found


def test_live_merge_idempotent(neo4j_test_env: Path) -> None:
    store = GraphStore()
    store.start(neo4j_test_env)
    assert store.enabled
    sid: str = f"idem-{uuid.uuid4()}"
    record = StepRecord(
        session_id=sid,
        started_at="2026-01-01T00:00:00+00:00",
        order=1,
        time="2026-01-01T00:00:01+00:00",
        kind="read",
        verdict="allowed",
        file_path="README.md",
        file_sensitive=False,
    )
    store.write_record_sync(record)
    assert store._driver is not None

    def session_touch_count() -> int:
        assert store._driver is not None
        with store._driver.session() as neo:
            row = neo.run(
                """
                MATCH (s:Session {id: $sid})-[:HAS_STEP]->(st:Step)
                OPTIONAL MATCH (st)-[t:TOUCHED]->()
                RETURN count(DISTINCT st) AS steps, count(t) AS touches
                """,
                sid=sid,
            ).single()
        assert row is not None
        return int(row["steps"]) + int(row["touches"])

    before = session_touch_count()
    store.write_record_sync(record)
    after = session_touch_count()
    store.stop()
    assert before == after
    assert before >= 1


def test_live_two_halves_of_one_action_are_one_step_node(neo4j_test_env: Path) -> None:
    store = GraphStore()
    store.start(neo4j_test_env)
    assert store.enabled
    sid: str = f"merged-{uuid.uuid4()}"
    common: dict[str, Any] = {
        "session_id": sid,
        "started_at": "2026-01-01T00:00:00+00:00",
        "order": 1,
        "time": "2026-01-01T00:00:01+00:00",
    }
    store.write_record_sync(
        StepRecord(
            **common, kind="tool", verdict="warned", tool="Read", rule_id="R9", rule_description="d"
        )
    )
    store.write_record_sync(
        StepRecord(**common, kind="read", verdict="warned", file_path="README.md", rule_id="R9")
    )
    assert store._driver is not None
    with store._driver.session() as neo:
        row = neo.run(
            """
            MATCH (:Session {id: $sid})-[:HAS_STEP]->(st:Step)
            OPTIONAL MATCH (st)-[:TOUCHED]->(f:File)
            OPTIONAL MATCH (st)-[:BLOCKED_BY]->(r:Rule)
            RETURN count(DISTINCT st) AS steps, st.kind AS kind, st.tool AS tool,
                   count(DISTINCT f) AS files, count(DISTINCT r) AS rules
            """,
            sid=sid,
        ).single()
    store.stop()
    assert row is not None
    assert (row["steps"], row["kind"], row["tool"], row["files"], row["rules"]) == (
        1,
        "read",
        None,
        1,
        1,
    )


def test_live_two_sessions_share_file_and_rule_nodes(neo4j_test_env: Path) -> None:
    store = GraphStore()
    store.start(neo4j_test_env)
    assert store.enabled
    for _ in (1, 2):
        sid: str = f"share-{uuid.uuid4()}"
        readme = StepRecord(
            session_id=sid,
            started_at="2026-01-01T00:00:00+00:00",
            order=1,
            time="2026-01-01T00:00:01+00:00",
            kind="read",
            verdict="allowed",
            file_path="README.md",
            file_sensitive=False,
        )
        env = StepRecord(
            session_id=sid,
            started_at="2026-01-01T00:00:00+00:00",
            order=2,
            time="2026-01-01T00:00:02+00:00",
            kind="read",
            verdict="allowed",
            file_path=".env",
            file_sensitive=True,
            prev_step_id=f"{sid}:1",
        )
        blocked = StepRecord(
            session_id=sid,
            started_at="2026-01-01T00:00:00+00:00",
            order=3,
            time="2026-01-01T00:00:03+00:00",
            kind="shell",
            verdict="blocked",
            command="curl <arg> ntfy.sh",
            hosts=("ntfy.sh",),
            rule_id="R1",
            rule_description="Blocked by rule R1",
            prev_step_id=f"{sid}:2",
        )
        store.write_record_sync(readme)
        store.write_record_sync(env)
        store.write_record_sync(blocked)

    assert store._driver is not None
    with store._driver.session() as session:
        readme_n = session.run("MATCH (f:File {id: 'README.md'}) RETURN count(f) AS c").single()
        env_n = session.run("MATCH (f:File {id: '.env'}) RETURN count(f) AS c").single()
        r1_n = session.run("MATCH (r:Rule {id: 'R1'}) RETURN count(r) AS c").single()
    store.stop()
    assert readme_n is not None and int(readme_n["c"]) == 1
    assert env_n is not None and int(env_n["c"]) == 1
    assert r1_n is not None and int(r1_n["c"]) == 1


def test_live_no_secret_properties_after_bearer_step(neo4j_test_env: Path) -> None:
    store = GraphStore()
    store.start(neo4j_test_env)
    assert store.enabled
    session = Session(
        id=f"clean-{uuid.uuid4()}",
        marked=False,
        start_time="2026-01-01T00:00:00+00:00",
        next_step=1,
    )
    payload = {
        "hook_event_name": "beforeShellExecution",
        "command": "curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1",
        "conversation_id": session.id,
        "workspace_roots": [str(Path.cwd())],
    }
    record = build_step_record(payload, session, "allow", None, order=1)
    store.write_record_sync(record)
    assert store._driver is not None
    with store._driver.session() as neo:
        rows = neo.run(
            """
            MATCH (n)
            WHERE n.id CONTAINS $a OR n.id CONTAINS $b OR n.id CONTAINS $c OR n.id CONTAINS $d
               OR coalesce(n.description, '') CONTAINS $a
               OR coalesce(n.description, '') CONTAINS $b
            RETURN n.id AS id LIMIT 5
            """,
            a="demo-not-a-real-secret",
            b="Bearer",
            c="u:p@",
            d="t=1",
        ).data()
    store.stop()
    assert rows == []


@pytest.mark.parametrize("raw", LEAKY_COMMANDS)
def test_builder_keeps_no_secret_in_any_stored_field(tmp_path: Path, raw: str) -> None:
    (tmp_path / ".env").write_text("API_KEY=demo\n", encoding="utf-8")
    session = Session(id="leaks", marked=False, start_time="2026-01-01T00:00:00+00:00", next_step=1)
    payload: dict[str, Any] = {
        "hook_event_name": "beforeShellExecution",
        "command": raw,
        "conversation_id": "leaks",
        "workspace_roots": [str(tmp_path)],
    }
    record: StepRecord = build_step_record(payload, session, "allow", None, order=1)
    assert SECRET not in repr(record)


# ---------------------------------------------------------------- Neo4j is opt-in (D14)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("neo4j = true\n", True),
        ("# comment\nneo4j = true  # yes\n", True),
        ("neo4j = false\n", False),
        ('neo4j = "true"\n', False),
        ("neo4j = 1\n", False),
        ("other = true\n", False),
        ("neo4j = \n", False),  # broken TOML
        ("[neo4j]\nenabled = true\n", False),
        ("", False),
    ],
)
def test_only_neo4j_true_in_config_toml_turns_it_on(text: str, expected: bool) -> None:
    path = config_dir() / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    assert neo4j_opt_in() is expected


def test_a_missing_config_toml_means_off() -> None:
    assert neo4j_opt_in() is False
    assert neo4j_opt_in(config_dir() / "nowhere.toml") is False


class _Calls:
    """Stands in for GraphDatabase.driver: counts calls and fails them, so nothing connects."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        self.count += 1
        raise RuntimeError("no network in tests")


class _RecordingTx:
    """A Neo4j transaction stand-in: keeps each query and its parameters, connects to nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, query: str, **params: Any) -> None:
        self.calls.append((query, params))


def test_the_deny_messages_never_reach_neo4j() -> None:
    """V8b: `user_message` and `agent_message` are memory-only. The rule's own text still goes to
    `Rule.description`, so the markers are distinct from it."""
    tx = _RecordingTx()
    store_mod._merge_step(
        tx,
        StepRecord(
            session_id="s",
            started_at="2026-01-01T00:00:00+00:00",
            order=2,
            time="2026-01-01T00:00:02+00:00",
            kind="shell",
            verdict="blocked",
            command="curl <arg> ntfy.sh",
            hosts=("ntfy.sh",),
            file_path=".env",
            rule_id="R1",
            rule_description="RULE_TEXT_MARK",
            prev_step_id="s:1",
            user_message="UM_MARK_71c2",
            agent_message="AM_MARK_71c2",
        ),
    )
    everything = repr(tx.calls)
    assert "UM_MARK_71c2" not in everything and "AM_MARK_71c2" not in everything
    assert "RULE_TEXT_MARK" in everything  # the positive control: the rule node still gets its text
    assert {name for _, params in tx.calls for name in params} == {
        "id",
        "started_at",
        "order",
        "time",
        "kind",
        "verdict",
        "tool",
        "session_id",
        "prev_id",
        "fid",
        "sensitive",
        "sid",
        "cid",
        "hid",
        "rid",
        "description",
    }


def start_recorder_with(
    monkeypatch: pytest.MonkeyPatch, *, env_file: bool, config: str | None
) -> int:
    calls = _Calls()
    monkeypatch.setattr(store_mod.GraphDatabase, "driver", calls)
    if env_file:
        credentials_path().parent.mkdir(parents=True, exist_ok=True)
        credentials_path().write_text(NEO4J_ENV, encoding="utf-8")
    if config is not None:
        (config_dir() / "config.toml").write_text(config, encoding="utf-8")
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as started:
        assert started.get("/health").status_code == 200
    return calls.count


def test_neo4j_env_alone_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    assert start_recorder_with(monkeypatch, env_file=True, config=None) == 0


@pytest.mark.parametrize("config", ["neo4j = false\n", 'neo4j = "true"\n', "neo4j = \n"])
def test_a_config_that_does_not_say_true_opens_no_connection(
    config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir().mkdir(parents=True)
    assert start_recorder_with(monkeypatch, env_file=True, config=config) == 0


def test_neo4j_true_with_credentials_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir().mkdir(parents=True)
    assert start_recorder_with(monkeypatch, env_file=True, config="neo4j = true\n") == 1


def test_neo4j_true_without_credentials_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir().mkdir(parents=True)
    assert start_recorder_with(monkeypatch, env_file=False, config="neo4j = true\n") == 0


# ---------------------------------------------------------------- live tests and the real login


def test_only_a_separate_named_file_counts_as_test_credentials(tmp_path: Path) -> None:
    real = tmp_path / "home" / ".config" / "agentfly" / "neo4j.env"
    real.parent.mkdir(parents=True)
    real.write_text("NEO4J_URI=bolt://real\n", encoding="utf-8")
    separate = tmp_path / "test-db.env"
    separate.write_text("NEO4J_URI=bolt://test\n", encoding="utf-8")
    link = tmp_path / "link.env"
    link.symlink_to(real)

    def pick(value: str | None) -> Path | None:
        env = {} if value is None else {TEST_ENV_VAR: value}
        return neo4j_test_credentials(env, real)

    assert pick(None) is None and pick("") is None and pick("  ") is None
    assert pick(str(tmp_path / "missing.env")) is None
    assert pick(str(real)) is None  # the real login file is refused
    assert pick(str(link)) is None  # also through a symlink
    assert pick(str(separate)) == separate


@pytest.mark.parametrize(
    "named_test_file", [False, True], ids=["unset", "separate file, dead port"]
)
def test_database_tests_skip_and_never_touch_the_real_login(
    tmp_path: Path, named_test_file: bool
) -> None:
    """A child pytest runs only the live tests under a HOME whose neo4j.env names a listener.

    The listener stands in for the owner's database: it must see no connection, and every live
    test must skip. (A variable naming the real login file is covered by the helper test above.)
    """
    home = tmp_path / "home"
    real = home / ".config" / "agentfly" / "neo4j.env"
    real.parent.mkdir(parents=True)
    env = client_env(home)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        listener.settimeout(0.2)
        real.write_text(
            f"NEO4J_URI=bolt://127.0.0.1:{listener.getsockname()[1]}\n"
            "NEO4J_USERNAME=u\nNEO4J_PASSWORD=pw-real\n",
            encoding="utf-8",
        )
        if named_test_file:
            separate = tmp_path / "test-db.env"
            separate.write_text(
                f"NEO4J_URI=bolt://127.0.0.1:{free_port()}\n"
                "NEO4J_USERNAME=u\nNEO4J_PASSWORD=pw-test\n",
                encoding="utf-8",
            )
            env[TEST_ENV_VAR] = str(separate)
        child = [sys.executable, "-m", "pytest", "tests/test_store.py", "-k", "live", "-q", "-rs"]
        result = subprocess.run(
            [*child, "-p", "no:cacheprovider"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        with pytest.raises(OSError):  # the accept times out: nobody connected
            listener.accept()
    assert result.returncode == 0, result.stdout + result.stderr
    assert " skipped" in result.stdout and "passed" not in result.stdout
    assert "pw-real" not in result.stdout + result.stderr
    assert ("unreachable" if named_test_file else TEST_ENV_VAR) in result.stdout
