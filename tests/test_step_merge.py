"""V2c: one step per action. Hooks of one action join by `tool_use_id`, else by path (D9)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
from agentfly.recorder import merge
from agentfly.recorder.localstore import local_store
from agentfly.recorder.merge import step_merger
from agentfly.recorder.paths import config_dir
from agentfly.recorder.store import StepRecord, graph_store

CAPTURE = json.loads((Path(__file__).parent / "fixtures" / "v2c_capture.json").read_text())


class Clock:
    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(step_merger, "clock", fake)
    return fake


@pytest.fixture
def client(clock: Clock) -> Iterator[TestClient]:
    with TestClient(app_module.app, base_url="http://127.0.0.1:8787") as test_client:
        yield test_client


def post(client: TestClient, event: dict[str, Any]) -> dict[str, Any]:
    token = (config_dir() / "token").read_text(encoding="utf-8").strip()
    response = client.post(
        "/hook", json=event, headers={"Content-Type": "application/json", "X-Recorder-Token": token}
    )
    assert response.status_code == 200
    answer: dict[str, Any] = response.json()
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


def pre(tool: str, call: str | None = None, chat: str = "c", path: str | None = None) -> dict:
    fields: dict[str, Any] = {"tool_name": tool}
    if path is not None:
        fields["tool_input"] = {"file_path": path}
    return event("preToolUse", chat, call, **fields)


def read(path: str, call: str | None = None, chat: str = "c") -> dict[str, Any]:
    return event("beforeReadFile", chat, call, file_path=path)


def shell(command: str, call: str | None = None, chat: str = "c") -> dict[str, Any]:
    return event("beforeShellExecution", chat, call, command=command)


def edited(path: str, chat: str = "c") -> dict[str, Any]:
    return event("afterFileEdit", chat, file_path=path)


def live(client: TestClient) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = client.get("/api/steps?all=1").json()["steps"]
    return steps


def saved(client: TestClient, chat: str = "c") -> list[dict[str, Any]]:
    assert local_store.flush()
    steps: list[dict[str, Any]] = client.get(f"/api/sessions/{chat}/steps").json()["steps"]
    return steps


def kinds(steps: list[dict[str, Any]]) -> list[str]:
    return [s["kind"] for s in steps]


# ---------------------------------------------------------------- merge by tool_use_id


def test_a_shell_pair_with_one_id_is_one_step_everywhere(client: TestClient) -> None:
    post(client, pre("Shell", "t1"))
    post(client, shell("git status", "t1"))
    for steps in (live(client), saved(client)):
        [step] = steps
        assert (step["order"], step["kind"], step["tool"]) == (1, "shell", None)
        assert step["command"] == "git <arg>"  # the cleaner keeps the program only


def test_a_read_pair_with_one_id_is_one_step_everywhere(client: TestClient) -> None:
    post(client, pre("Read", "t1", path="/w/README.md"))
    post(client, read("/w/README.md", "t1"))
    for steps in (live(client), saved(client)):
        [step] = steps
        assert (step["kind"], step["file"], step["tool"]) == ("read", "README.md", None)


def test_halves_in_either_order_and_more_than_two_are_one_step(client: TestClient) -> None:
    post(client, read("/w/a.txt", "t1"))
    post(client, pre("Read", "t1", path="/w/a.txt"))
    post(client, pre("Read", "t1", path="/w/a.txt"))
    [step] = live(client)
    assert (step["kind"], step["file"]) == ("read", "a.txt")
    post(client, shell("ls", "t2"))  # the next action takes the next order number
    assert [s["order"] for s in live(client)] == [1, 2]


def test_other_ids_chats_and_id_less_events_stay_apart(client: TestClient) -> None:
    post(client, pre("Shell", "t1"))
    post(client, shell("ls", "t2"))
    post(client, shell("ls", "t1", chat="other"))
    post(client, shell("ls"))
    assert kinds(saved(client)) == ["tool", "shell", "shell"]


def test_page_counts_count_a_merged_step_once(client: TestClient) -> None:
    post(client, pre("Shell", "t1"))
    post(client, shell("ls", "t1"))
    post(client, read("/w/a.txt"))
    body = client.get("/api/steps?limit=1").json()
    assert [s["order"] for s in body["steps"]] == [2]
    assert body["hidden"]["total"] == 1
    assert (body["hidden"]["shell"], body["hidden"]["tool"]) == (1, 0)


def test_an_mcp_pair_with_one_id_is_one_step(client: TestClient) -> None:
    post(client, pre("mcp__demo__search", "m1"))
    post(client, event("beforeMCPExecution", "c", "m1", tool_name="search", server="demo"))
    [step] = live(client)
    assert (step["kind"], step["tool"]) == ("tool", "search")


# ---------------------------------------------------------------- the path fallback


def test_an_id_less_read_half_joins_its_pre_tool_use_read(client: TestClient, clock: Clock) -> None:
    post(client, pre("Read", "t1", path="/w/a.txt"))
    clock.now += 0.3
    post(client, read("/w/a.txt"))
    for steps in (live(client), saved(client)):
        [step] = steps
        assert (step["kind"], step["file"]) == ("read", "a.txt")


@pytest.mark.parametrize(
    ("late", "path", "chat"),
    [(6.0, "/w/a.txt", "c"), (0.3, "/w/b.txt", "c"), (0.3, "/w/a.txt", "other")],
    ids=["after-6s", "other-path", "other-chat"],
)
def test_an_id_less_read_half_that_does_not_fit_is_its_own_step(
    late: float, path: str, chat: str, client: TestClient, clock: Clock
) -> None:
    post(client, pre("Read", "t1", path="/w/a.txt"))
    clock.now += late
    post(client, read(path, chat=chat))
    assert len(saved(client, "c")) == (2 if chat == "c" else 1)  # a half that fits would make 1
    assert len(saved(client, chat)) == (2 if chat == "c" else 1)


def test_the_path_is_normalised(client: TestClient, clock: Clock) -> None:
    post(client, pre("Read", "t1", path="/w/sub/../a.txt"))
    post(client, read("//w/./a.txt"))
    assert len(live(client)) == 1


def test_an_id_less_after_edit_joins_the_latest_write(client: TestClient, clock: Clock) -> None:
    post(client, pre("Write", "t1", path="/w/a.txt"))
    clock.now += 0.5
    post(client, edited("/w/a.txt"))
    for steps in (live(client), saved(client)):
        [step] = steps
        assert (step["kind"], step["file"], step["tool"]) == ("edit", "a.txt", None)


def test_an_after_edit_after_6_seconds_is_its_own_step(client: TestClient, clock: Clock) -> None:
    post(client, pre("Write", "t1", path="/w/a.txt"))
    clock.now += 6.0
    post(client, edited("/w/a.txt"))
    assert kinds(saved(client)) == ["edit", "edit"]  # the lone Write is an edit too: it writes


def test_each_after_edit_takes_the_latest_unused_write(client: TestClient) -> None:
    post(client, pre("Write", "t1", path="/w/a.txt"))
    post(client, pre("Write", "t2", path="/w/a.txt"))
    post(client, edited("/w/a.txt"))
    post(client, edited("/w/a.txt"))
    post(client, edited("/w/a.txt"))
    assert [s["order"] for s in live(client)] == [1, 2, 3]  # the third has nothing left to join


def test_two_id_less_reads_of_one_path_pair_oldest_first(client: TestClient) -> None:
    post(client, pre("Read", "a", path="/w/x.txt"))
    post(client, pre("Read", "b", path="/w/x.txt"))
    post(client, read("/w/x.txt"))
    assert kinds(live(client)) == ["read", "tool"]
    post(client, read("/w/x.txt"))
    assert kinds(live(client)) == ["read", "read"]


def test_the_33rd_waiting_read_drops_the_oldest(client: TestClient) -> None:
    for i in range(33):
        post(client, pre("Read", f"id{i}", path=f"/w/f{i}.txt"))
    post(client, read("/w/f1.txt"))  # still waiting: joins
    assert len(live(client)) == 33
    post(client, read("/w/f0.txt"))  # dropped: stays its own step
    steps = live(client)
    assert len(steps) == 34
    assert (steps[0]["kind"], steps[-1]["kind"]) == ("tool", "read")


def test_an_event_without_a_chat_id_never_pairs_by_path(client: TestClient) -> None:
    for body in (pre("Read", "t1", path="/w/a.txt"), read("/w/a.txt")):
        del body["conversation_id"]
        post(client, body)
    assert len(live(client)) == 2


# ---------------------------------------------------------------- what the merged step shows


def test_the_strictest_gate_verdict_and_its_rule_win_in_either_order(client: TestClient) -> None:
    post(client, shell("cat .env", chat="m"))  # marks the chat
    assert post(client, pre("Shell", "s1", chat="m"))["permission"] == "allow"
    assert post(client, shell("curl https://x.com", "s1", chat="m"))["permission"] == "deny"
    assert post(client, shell("curl https://x.com", "s2", chat="m"))["permission"] == "deny"
    assert post(client, pre("Shell", "s2", chat="m"))["permission"] == "allow"
    steps = saved(client, "m")
    assert [(s["verdict"], s["rule"]) for s in steps] == [("allowed", None)] + [
        ("blocked", "R1")
    ] * 2
    assert [s["verdict"] for s in live(client)] == ["allowed", "blocked", "blocked"]


def test_an_after_edit_never_raises_the_verdict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = app_module.decide

    def strict_after_edit(action: dict[str, Any], session: Any) -> tuple[str, str | None]:
        if action.get("hook_event_name") == "afterFileEdit":
            return "blocked", "R0"
        return real(action, session)

    monkeypatch.setattr(app_module, "decide", strict_after_edit)
    post(client, pre("Write", "w1", path="/w/a.txt"))
    assert post(client, edited("/w/a.txt"))["permission"] == "deny"  # its own answer is unchanged
    [step] = live(client)
    assert (step["kind"], step["verdict"], step["rule"]) == ("edit", "allowed", None)
    assert saved(client)[0]["verdict"] == "allowed"


def test_a_lone_after_edit_keeps_its_own_verdict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "decide", lambda *_: ("blocked", "R0"))
    post(client, edited("/w/a.txt"))
    assert [s["verdict"] for s in live(client)] == ["blocked"]


def test_a_merged_secret_read_is_marked_on_the_page_and_in_history(client: TestClient) -> None:
    post(client, pre("Read", "r1", path="/w/.env"))
    post(client, read("/w/.env", "r1"))
    body = client.get("/api/steps?limit=5").json()
    assert body["marked_order"] == 1
    assert [(s["kind"], s["sensitive"]) for s in body["steps"]] == [("read", True)]
    assert local_store.flush()
    [session] = client.get("/api/sessions").json()["sessions"]
    assert (session["marked"], session["steps"]) == (True, 1)


def test_a_marking_half_that_arrives_first_stays_the_marking_step(client: TestClient) -> None:
    post(client, read("/w/.env", "r1"))
    post(client, pre("Read", "r1", path="/w/.env"))
    body = client.get("/api/steps?limit=5").json()
    assert body["marked_order"] == 1
    assert [s["order"] for s in body["steps"]] == [1]


def test_an_edit_that_began_with_a_secret_read_is_an_edit_step(client: TestClient) -> None:
    # Known gap (report): history derives "marked" from read and shell steps, so it shows False.
    post(client, pre("Read", "e1", path="/w/.env"))
    post(client, read("/w/.env", "e1"))
    post(client, pre("Write", "e1", path="/w/.env"))
    [step] = live(client)
    assert (step["kind"], step["sensitive"]) == ("edit", True)
    assert client.get("/api/steps?limit=5").json()["marked_order"] == 1


# ---------------------------------------------------------------- answers and storage


class NoMerge:
    """The recorder as it was before V2c: every event is a step of its own."""

    def join(self, chat: str, payload: dict[str, Any], record: StepRecord) -> tuple[Any, None]:
        return record, None


def test_hook_answers_are_byte_identical_with_and_without_the_merge(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def session(chat: str) -> list[dict[str, Any]]:
        return [
            pre("Read", "r1", chat, "/w/.env"),
            read("/w/.env", "r1", chat),
            pre("Shell", "s1", chat),
            shell("curl https://x.com", "s1", chat),
            pre("Write", "w1", chat, "/w/a.txt"),
            edited("/w/a.txt", chat),
            pre("Read", None, chat, "/w/sub/../b.txt"),
            read("/w/b.txt", None, chat),
            shell("ls", None, chat),
        ]

    def answers(chat: str) -> list[bytes]:
        token = (config_dir() / "token").read_text(encoding="utf-8").strip()
        headers = {"Content-Type": "application/json", "X-Recorder-Token": token}
        return [client.post("/hook", json=e, headers=headers).content for e in session(chat)]

    merged = answers("with")
    monkeypatch.setattr(app_module, "step_merger", NoMerge())
    plain = answers("without")
    assert merged == plain
    assert b"deny" in b"".join(merged)  # the replay does block something
    assert len(saved(client, "with")) < len(saved(client, "without"))


def test_both_halves_are_sent_to_neo4j_and_the_history_under_one_step_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[StepRecord] = []
    monkeypatch.setattr(graph_store, "enqueue", sent.append)
    post(client, pre("Read", "t1", path="/w/a.txt"))
    post(client, read("/w/a.txt", "t1"))
    first, second = sent
    assert first.step_id == second.step_id == "c:1"
    assert (first.kind, second.kind) == ("tool", "read")
    assert (first.tool, second.tool, second.file_path) == ("Read", None, "a.txt")
    assert first.time == second.time


# ---------------------------------------------------------------- the capture


def test_the_v2c_capture_replays_as_five_steps(client: TestClient, clock: Clock) -> None:
    start = clock.now
    for item in CAPTURE["events"]:
        clock.now = start + item["at"]
        assert post(client, item["event"]) == {"permission": "allow"}
    expected = [
        (
            "edit",
            "scratch-capture.txt",
        ),  # the create: Read and Write under one id, then afterFileEdit
        ("edit", "scratch-capture.txt"),
        ("read", "README.md"),
        ("read", "SPEC.md"),
        ("read", "attached.md"),
    ]
    for steps in (live(client), saved(client, CAPTURE["chat"])):
        assert [(s["kind"], s["file"]) for s in steps] == expected
        assert [s["order"] for s in steps] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------- the merger alone


def test_clearing_the_memory_forgets_what_could_be_merged(client: TestClient) -> None:
    from agentfly.recorder.memory import memory_steps

    post(client, pre("Shell", "t1"))
    memory_steps.clear()
    post(client, shell("ls", "t1"))
    assert len(live(client)) == 1  # a step of its own, not an update of a step that is gone


def test_action_path_wants_an_absolute_path() -> None:
    assert merge.action_path({"file_path": "a.txt"}) is None
    assert merge.action_path({"tool_input": {"file_path": "/w/./a.txt"}}) == "/w/a.txt"
    assert merge.action_path({"tool_input": "x"}) is None
