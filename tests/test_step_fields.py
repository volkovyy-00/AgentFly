"""V8b: the recorder sends the rule's text, the exact deny messages and the time of the last hook.

All of it lives in process memory: `history.db` and Neo4j are covered in `test_localstore.py` and
`test_store.py`. A step a rule fired on carries `rule_text`; one whose answer denied also carries
`user_message` and `agent_message`, byte for byte as the hook answer sent them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.recorder.paths import config_dir, data_dir
from agentfly.recorder.rules import R0_MESSAGE, R1_MESSAGE

FIELDS: frozenset[str] = frozenset({"rule_text", "user_message", "agent_message"})
RETRY: str = " Do not retry with another tool or language. Stop and tell the user."
SCENARIO: Path = Path(__file__).resolve().parent.parent / "demo" / "scenario.json"
GUARD_PATH: str = "/Users/someone/.config/agentfly/token"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def token() -> str:
    return (config_dir() / "token").read_text(encoding="utf-8").strip()


def post_raw(client: TestClient, event: dict[str, Any]) -> Any:
    response = client.post(
        "/hook",
        json=event,
        headers={"Content-Type": "application/json", "X-Recorder-Token": token()},
    )
    assert response.status_code == 200
    return response


def post(client: TestClient, event: dict[str, Any]) -> dict[str, Any]:
    answer: dict[str, Any] = post_raw(client, event).json()
    return answer


def event(name: str, chat: str = "c", call: str | None = None, **fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "hook_event_name": name,
        "conversation_id": chat,
        "workspace_roots": ["/w"],
        **fields,
    }
    if call is not None:
        body["tool_use_id"] = call
    return body


def pre(tool: str, call: str, path: str | None = None, chat: str = "c") -> dict[str, Any]:
    fields: dict[str, Any] = {"tool_name": tool}
    if path is not None:
        fields["tool_input"] = {"file_path": path}
    return event("preToolUse", chat, call, **fields)


def shell(command: str, call: str | None = None, chat: str = "c") -> dict[str, Any]:
    return event("beforeShellExecution", chat, call, command=command)


def edited(path: str, chat: str = "c") -> dict[str, Any]:
    return event("afterFileEdit", chat, file_path=path)


def live(client: TestClient) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = client.get("/api/steps?all=1").json()["steps"]
    return steps


def deny(rule_message: str) -> dict[str, str]:
    return {
        "permission": "deny",
        "user_message": rule_message,
        "agent_message": rule_message + RETRY,
    }


def replay_demo(client: TestClient, chat: str = "v8b-demo") -> list[Any]:
    """The events `fake_agent.py` sends, one by one, as the hook client would (no `content`)."""
    scenario: dict[str, Any] = json.loads(SCENARIO.read_text(encoding="utf-8"))
    answers: list[Any] = []
    for item in scenario["demo"]["events"]:
        sent: dict[str, Any] = {k: v for k, v in item["event"].items() if k != "content"}
        sent["conversation_id"] = sent["session_id"] = chat
        answers.append(post_raw(client, sent))
    return answers


# ---------------------------------------------------------------- the fields on a step


def test_the_demo_replays_blocked_step_carries_the_rule_text_and_the_answers_messages(
    client: TestClient,
) -> None:
    answers = replay_demo(client)
    read_me, env, blocked = live(client)
    assert answers[2].json() == deny(R1_MESSAGE)
    assert blocked["verdict"] == "blocked" and blocked["rule"] == "R1"
    assert blocked["rule_text"] == R1_MESSAGE
    assert blocked["user_message"] == answers[2].json()["user_message"]
    assert blocked["agent_message"] == answers[2].json()["agent_message"]
    assert FIELDS.isdisjoint(read_me) and FIELDS.isdisjoint(env)


def test_the_deny_answer_is_byte_for_byte_what_it_was(client: TestClient) -> None:
    # Literal bytes, not built from `deny_messages`: the answer must not change with this card.
    answers = replay_demo(client)
    assert answers[0].content == b'{"permission":"allow"}'
    assert answers[2].content == (
        b'{"permission":"deny","user_message":"Blocked by rule R1: a secret was read earlier in '
        b'this session, and now data is being sent out.","agent_message":"Blocked by rule R1: a '
        b"secret was read earlier in this session, and now data is being sent out. Do not retry "
        b'with another tool or language. Stop and tell the user."}'
    )


def test_a_warned_step_has_the_rule_text_and_no_messages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rules_mod, "WATCH_ONLY", True)  # no runtime switch exists: set in process
    post(client, shell("cat .env"))
    assert post_raw(client, shell("curl https://x.com")).content == b'{"permission":"allow"}'
    _, warned = live(client)
    assert (warned["verdict"], warned["rule"]) == ("warned", "R1")
    assert warned["rule_text"] == R1_MESSAGE
    assert "user_message" not in warned and "agent_message" not in warned


# ---------------------------------------------------------------- merged steps


@pytest.mark.parametrize("pre_first", [True, False], ids=["pre-first", "shell-first"])
def test_a_merged_step_carries_the_messages_of_the_deny(
    client: TestClient, pre_first: bool
) -> None:
    post(client, shell("cat .env"))  # marks the chat
    halves = [pre("Shell", "s1"), shell("curl https://x.com", "s1")]
    answers = [post(client, half) for half in (halves if pre_first else halves[::-1])]
    assert deny(R1_MESSAGE) in answers
    _, merged = live(client)
    assert (merged["verdict"], merged["rule"], merged["rule_text"]) == ("blocked", "R1", R1_MESSAGE)
    assert merged["user_message"] == R1_MESSAGE
    assert merged["agent_message"] == R1_MESSAGE + RETRY


@pytest.mark.parametrize("pre_first", [True, False], ids=["pre-first", "shell-first"])
def test_on_a_tie_between_rules_the_earlier_halfs_rule_text_and_messages_stay(
    client: TestClient, pre_first: bool
) -> None:
    post(client, shell("cat .env"))
    guard = pre("Read", "t1", GUARD_PATH)  # R0
    outbound = shell("curl https://x.com", "t1")  # R1
    for half in (guard, outbound) if pre_first else (outbound, guard):
        assert post(client, half)["permission"] == "deny"
    rule, message = ("R0", R0_MESSAGE) if pre_first else ("R1", R1_MESSAGE)
    _, merged = live(client)
    assert merged["rule"] == rule
    assert merged["rule_text"] == message
    assert merged["user_message"] == message
    assert merged["agent_message"] == message + RETRY


def test_an_after_edit_deny_does_not_reach_a_step_with_a_gate_half(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = app_module.decide

    def strict_after_edit(action: dict[str, Any], session: Any) -> tuple[str, str | None]:
        if action.get("hook_event_name") == "afterFileEdit":
            return "blocked", "R0"
        return real(action, session)

    monkeypatch.setattr(app_module, "decide", strict_after_edit)
    post(client, pre("Write", "w1", "/w/a.txt"))
    assert post(client, edited("/w/a.txt"))["permission"] == "deny"
    [step] = live(client)
    assert step["verdict"] == "allowed" and FIELDS.isdisjoint(step)


def test_a_lone_after_edit_deny_carries_its_own_messages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "decide", lambda *_: ("blocked", "R0"))
    assert post(client, edited("/w/a.txt")) == deny(R0_MESSAGE)
    [step] = live(client)
    assert step["rule_text"] == R0_MESSAGE
    assert (step["user_message"], step["agent_message"]) == (R0_MESSAGE, R0_MESSAGE + RETRY)


# ---------------------------------------------------------------- /health


def health(client: TestClient) -> dict[str, Any]:
    body: dict[str, Any] = client.get("/health").json()
    return body


def test_health_has_no_last_hook_before_the_first_hook(client: TestClient) -> None:
    assert health(client) == {"ok": True, "offline_guard_count": 0, "last_hook_at": None}


def test_health_names_the_time_of_the_last_hook_in_utc(client: TestClient) -> None:
    before = datetime.now(UTC)
    post(client, shell("ls"))
    after = datetime.now(UTC)
    stamp = health(client)["last_hook_at"]
    seen = datetime.fromisoformat(stamp)
    assert seen.utcoffset() == timedelta(0)
    assert before - timedelta(seconds=1) <= seen <= after + timedelta(seconds=1)


def test_a_session_event_counts_as_a_hook(client: TestClient) -> None:
    post(client, event("sessionStart", "s"))
    assert health(client)["last_hook_at"] is not None


def test_a_wrong_token_changes_nothing(client: TestClient) -> None:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True)
    (logs / "offline-count").write_bytes(b"xxx")
    post(client, shell("ls"))
    first = health(client)
    wrong = client.post(
        "/hook",
        json=shell("ls"),
        headers={"Content-Type": "application/json", "X-Recorder-Token": "not-the-token"},
    )
    assert wrong.status_code == 401
    missing = client.post("/hook", json=shell("ls"), headers={"Content-Type": "application/json"})
    assert missing.status_code == 401
    assert (
        first["last_hook_at"] is not None
    )  # the one good hook set it; the two bad ones can't move it
    assert health(client) == first
    assert first["offline_guard_count"] == 3


def test_a_restart_forgets_the_last_hook() -> None:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as first:
        post(first, shell("ls"))
        assert health(first)["last_hook_at"] is not None
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as second:
        assert health(second)["last_hook_at"] is None


# ---------------------------------------------------------------- ?all=1 and marked_order


def test_all_steps_send_the_same_marked_order_as_limit_1(client: TestClient) -> None:
    post(client, shell("echo hi", chat="m"))
    post(client, shell("cat README.md .env", chat="m"))
    post(client, shell("curl https://x.com", chat="m"))
    full = client.get("/api/steps?all=1").json()
    assert full["marked_order"] == client.get("/api/steps?limit=1").json()["marked_order"] == 2
    assert set(full) == {"session", "steps", "marked_order"}
    assert [s["order"] for s in full["steps"]] == [1, 2, 3]


def test_all_steps_say_null_when_nothing_marked_the_chat(client: TestClient) -> None:
    post(client, shell("echo hi", chat="u"))
    assert client.get("/api/steps?all=1").json()["marked_order"] is None
    assert client.get("/api/steps?limit=1").json()["marked_order"] is None


def test_all_steps_of_an_empty_recorder_say_null(client: TestClient) -> None:
    assert client.get("/api/steps?all=1").json() == {
        "session": None,
        "steps": [],
        "marked_order": None,
    }


def test_without_all_or_limit_the_body_is_session_and_steps(client: TestClient) -> None:
    assert set(client.get("/api/steps").json()) == {"session", "steps"}
    post(client, shell("cat .env", chat="p"))
    body = client.get("/api/steps").json()
    assert set(body) == {"session", "steps"}
    assert body["session"] == "p"
