"""Tests for Neo4j store builder, DELETE policy, and optional live DB."""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import recorder.app as app_module
import recorder.store as store_mod
from recorder.config_env import CREDENTIALS_PATH
from recorder.rules import Session
from recorder.store import (
    GraphStore,
    StepRecord,
    build_step_record,
    graph_store,
)

_HAS_CREDS: bool = CREDENTIALS_PATH.is_file()


def _neo4j_reachable() -> bool:
    if not _HAS_CREDS:
        return False
    try:
        from recorder.check_db import main as check_main

        return check_main() == 0
    except Exception:  # noqa: BLE001
        return False


_live = pytest.mark.skipif(
    not _neo4j_reachable(),
    reason="Neo4j credentials missing or database unreachable",
)

_FORBIDDEN: tuple[str, ...] = (
    "demo-not-a-real-secret",
    "Bearer",
    "u:p@",
    "t=1",
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app_module.config_dir = tmp_path / "flightrecorder"
    # Keep Neo4j off during ordinary gate tests unless a live test re-enables it.
    previous_enabled: bool = graph_store.enabled
    graph_store.enabled = False
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        graph_store.enabled = False
        yield test_client
    graph_store.enabled = previous_enabled


@pytest.fixture()
def token(client: TestClient) -> str:
    path: Path = app_module.config_dir / "token"
    return path.read_text(encoding="utf-8").strip()


def test_delete_only_in_clear_path() -> None:
    root: Path = Path(__file__).resolve().parents[1] / "recorder"
    for path in root.glob("*.py"):
        text: str = path.read_text(encoding="utf-8")
        if not re.search(r"\bDELETE\b", text):
            continue
        assert path.name == "store.py", f"{path.name} must not contain DELETE"
        for match in re.finditer(r"\bDELETE\b", text):
            line_start: int = text.rfind("\n", 0, match.start()) + 1
            line_end: int = text.find("\n", match.start())
            end: int = line_end if line_end != -1 else len(text)
            line: str = text[line_start:end]
            if "help=" in line or line.lstrip().startswith('"""') or line.lstrip().startswith("#"):
                continue
            before: str = text[: match.start()]
            assert "def clear_all" in before, f"DELETE outside clear_all: {line.strip()}"
            last_def: int = before.rfind("def ")
            assert last_def != -1
            assert before[last_def:].startswith("def clear_all")
    store_text: str = (root / "store.py").read_text(encoding="utf-8")
    assert "DETACH DELETE" in store_text


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
        with caplog.at_level(logging.WARNING, logger="flightrecorder"):
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


@_live
def test_live_step_appears_within_5s() -> None:
    store = GraphStore()
    store.start(CREDENTIALS_PATH)
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


@_live
def test_live_merge_idempotent() -> None:
    store = GraphStore()
    store.start(CREDENTIALS_PATH)
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


@_live
def test_live_two_sessions_share_file_and_rule_nodes() -> None:
    store = GraphStore()
    store.start(CREDENTIALS_PATH)
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


@_live
def test_live_no_secret_properties_after_bearer_step() -> None:
    store = GraphStore()
    store.start(CREDENTIALS_PATH)
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
