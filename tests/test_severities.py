"""V5b, D11: block, warn and highlight. Who wins, what Cursor is told, what the page shows.

The rules come from a rules file (the recorder reads `rulefile.ACTIVE_RULES` once at start), so
these tests write one next to the packaged default's R1 and start the app on it.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
import agentfly.recorder.store as store_module
from agentfly.recorder.rules import R0_MESSAGE, R1_MESSAGE, Session, decide, mark
from tests.helpers import REPO
from tests.rules_helpers import default_with, ruleset_of
from tests.test_step_fields import FIELDS, RETRY, post_raw
from tests.test_step_merge import event, live, pre, read, saved, shell

SKIP_TAIL = " If the user skips this, do not retry with another tool or language."

LISTS = (
    'ls_cmds = ["ls"]\npush_cmds = ["git push"]\npy_files = ["*.py"]\nenv_local = [".env.local"]\n'
)


def rule(rid: str, severity: str, message: str, *, command: str = "push_cmds") -> str:
    return f"""
[[rule]]
id = "{rid}"
kind = "match"
severity = "{severity}"
message = "{message}"
event = ["shell"]
command = "{command}"
  [[rule.test]]
  steps = ["shell: git push"]
  expect = "{severity}"
  [[rule.test]]
  steps = ["shell: echo hi"]
  expect = "allow"
"""


WARN_READ = """
[[rule]]
id = "warn-env"
kind = "match"
severity = "warn"
message = "An env file is being read."
event = ["read"]
path = "env_local"
"""

HIGHLIGHT_WRITE = """
[[rule]]
id = "hl-py"
kind = "match"
severity = "highlight"
message = "A Python file is written."
event = ["write"]
path = "py_files"
"""


def rules_text(*extra: str) -> str:
    """The packaged default (R0's neighbour R1) with more lists and rules after it."""
    return default_with(LISTS, *extra)


def ruleset(*extra: str) -> rules_mod.RuleSet:
    return ruleset_of(rules_text(*extra))


def session(*, marked: bool = False) -> Session:
    return Session(id="s", marked=marked, start_time="t", next_step=1)


def verdict(rs: rules_mod.RuleSet, action: dict[str, Any], *, marked: bool = False) -> Any:
    sess = mark(action, session(marked=marked), rs)
    return decide(action, sess, rs)


def push() -> dict[str, Any]:
    return shell("git push origin main")


# ---------------------------------------------------------------- who wins


def test_a_warn_rule_gives_warned_and_a_highlight_rule_gives_highlighted() -> None:
    rs = ruleset(rule("w", "warn", "careful"), rule("h", "highlight", "noted", command="ls_cmds"))
    assert verdict(rs, push()) == ("warned", "w")
    assert verdict(rs, shell("ls -la")) == ("highlighted", "h")
    assert verdict(rs, shell("echo hi")) == ("allow", None)


@pytest.mark.parametrize("order", list(itertools.permutations(["block", "warn", "highlight"])))
def test_the_strictest_rule_wins_whatever_the_file_order(order: tuple[str, ...]) -> None:
    rs = ruleset(*(rule(f"r-{sev}", sev, f"{sev} text") for sev in order))
    assert verdict(rs, push()) == ("blocked", "r-block")


def test_a_warn_beats_a_highlight_and_a_tie_goes_to_the_first_in_the_file() -> None:
    rs = ruleset(rule("h1", "highlight", "a"), rule("w1", "warn", "b"), rule("w2", "warn", "c"))
    assert verdict(rs, push()) == ("warned", "w1")
    rs = ruleset(rule("h1", "highlight", "a"), rule("h2", "highlight", "b"))
    assert verdict(rs, push()) == ("highlighted", "h1")


def test_a_block_and_a_warn_that_both_match_answer_block() -> None:
    rs = ruleset(rule("w", "warn", "careful"))
    assert verdict(rs, push()) == ("warned", "w")
    assert verdict(rs, push(), marked=True) == ("blocked", "R1"), (
        "git push is outbound after a secret"
    )


def test_r0_stays_first_and_cannot_be_outvoted() -> None:
    rs = ruleset(rule("h", "highlight", "x", command="ls_cmds"))
    assert rs.rules[0].id == "R0" and rs.rules[0].severity == "block"
    assert verdict(rs, shell("agentfly stop")) == ("blocked", "R0")


# ---------------------------------------------------------------- through the app


@pytest.fixture
def served(active_rules: Path) -> Iterator[Callable[..., TestClient]]:
    clients: list[Any] = []

    def start(*extra: str) -> TestClient:
        active_rules.write_text(rules_text(*extra), encoding="utf-8")
        context = TestClient(app_module.app, base_url="http://127.0.0.1:8787")
        clients.append(context)
        return context.__enter__()

    yield start
    for context in clients:
        context.__exit__(None, None, None)


def test_a_warn_on_a_shell_command_answers_ask_with_the_text_in_both_messages(
    served: Callable[..., TestClient],
) -> None:
    client = served(rule("warn-push", "warn", "A push needs a look."))
    answer = post_raw(client, push())
    assert answer.content == (
        b'{"permission":"ask","user_message":"A push needs a look.",'
        b'"agent_message":"A push needs a look. If the user skips this, do not retry with '
        b'another tool or language."}'
    )
    [step] = live(client)
    assert (step["verdict"], step["rule"], step["rule_text"]) == (
        "warned",
        "warn-push",
        "A push needs a look.",
    )
    assert step["user_message"] == "A push needs a look."
    assert step["agent_message"] == "A push needs a look." + SKIP_TAIL


def test_a_warn_on_any_other_event_allows_and_marks_the_step_without_messages(
    served: Callable[..., TestClient],
) -> None:
    client = served(WARN_READ)
    assert post_raw(client, read("/w/.env.local")).content == b'{"permission":"allow"}'
    [step] = live(client)
    assert (step["verdict"], step["rule"]) == ("warned", "warn-env")
    assert step["rule_text"] == "An env file is being read."
    assert "user_message" not in step and "agent_message" not in step


def test_a_highlight_allows_and_the_step_carries_the_rule_text_only(
    served: Callable[..., TestClient],
) -> None:
    client = served(HIGHLIGHT_WRITE, rule("hl-ls", "highlight", "Listing.", command="ls_cmds"))
    assert post_raw(client, shell("ls")).content == b'{"permission":"allow"}'
    assert post_raw(client, pre("Write", "w1", path="/w/a.py")).content == b'{"permission":"allow"}'
    listing, written = live(client)
    for step, rid, text in (
        (listing, "hl-ls", "Listing."),
        (written, "hl-py", "A Python file is written."),
    ):
        assert (step["verdict"], step["rule"], step["rule_text"]) == ("highlighted", rid, text)
        assert "user_message" not in step and "agent_message" not in step


def test_a_block_and_a_warn_that_both_match_the_command_deny(
    served: Callable[..., TestClient],
) -> None:
    client = served(rule("warn-push", "warn", "A push needs a look."))
    post_raw(client, shell("cat .env"))  # marks the chat: R1 now blocks outbound commands
    answer = post_raw(client, push())
    assert answer.json() == {
        "permission": "deny",
        "user_message": R1_MESSAGE,
        "agent_message": R1_MESSAGE + RETRY,
    }
    assert live(client)[-1]["rule"] == "R1"


def test_the_page_and_the_history_show_a_warned_and_a_highlighted_step(
    served: Callable[..., TestClient],
) -> None:
    client = served(rule("warn-push", "warn", "A push needs a look."), HIGHLIGHT_WRITE)
    post_raw(client, push())
    post_raw(client, pre("Write", "w1", path="/w/a.py"))
    page = live(client)
    assert [(s["verdict"], s["rule_text"]) for s in page] == [
        ("warned", "A push needs a look."),
        ("highlighted", "A Python file is written."),
    ]
    history = saved(client)
    assert [(s["verdict"], s["rule"]) for s in history] == [
        ("warned", "warn-push"),
        ("highlighted", "hl-py"),
    ]
    assert all(FIELDS.isdisjoint(s) for s in history), "the messages never reach history"
    counts = client.get("/api/sessions").json()["sessions"][0]
    assert counts["warned"] == 1


def test_a_merged_shell_pair_shows_the_warn_and_its_messages(
    served: Callable[..., TestClient],
) -> None:
    client = served(rule("warn-push", "warn", "A push needs a look."))
    for half in (pre("Shell", "s1"), event("beforeShellExecution", "c", "s1", command="git push")):
        post_raw(client, half)
    [step] = live(client)
    assert (step["verdict"], step["rule"]) == ("warned", "warn-push")
    assert step["user_message"] == "A push needs a look."


def test_the_rule_is_looked_up_once_per_hook_and_the_store_does_not_look_it_up_again(
    served: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = served(rule("warn-push", "warn", "A push needs a look."))
    calls: list[str] = []
    real = rules_mod.find_rule

    def counting(rule_id: str | None) -> Any:
        calls.append(str(rule_id))
        return real(rule_id)

    monkeypatch.setattr(app_module, "find_rule", counting)
    post_raw(client, push())
    assert calls == ["warn-push"]
    assert not hasattr(store_module, "find_rule"), "the step record is handed the text"
    assert live(client)[-1]["rule_text"] == "A push needs a look."


def test_the_answers_for_the_demo_do_not_change_with_the_file_format(
    served: Callable[..., TestClient],
) -> None:
    client = served()
    scenario = json.loads((REPO / "examples/scenario.json").read_text(encoding="utf-8"))["demo"][
        "events"
    ]
    answers = []
    for item in scenario:
        body = {k: v for k, v in item["event"].items() if k != "content"}
        body["conversation_id"] = body["session_id"] = "demo"
        body["workspace_roots"] = ["/w"]
        answers.append(post_raw(client, body).content)
    assert answers[0] == answers[1] == b'{"permission":"allow"}'
    assert answers[2] == (
        b'{"permission":"deny","user_message":"Blocked by rule R1: a secret was read earlier in '
        b'this session, and now data is being sent out.","agent_message":"Blocked by rule R1: a '
        b"secret was read earlier in this session, and now data is being sent out. Do not retry "
        b'with another tool or language. Stop and tell the user."}'
    )


def test_r0_keeps_denying_when_the_file_makes_every_other_rule_gentle(
    served: Callable[..., TestClient],
) -> None:
    client = served(rule("hl", "highlight", "x", command="ls_cmds"))
    answer = post_raw(client, shell("agentfly stop")).json()
    assert answer["permission"] == "deny" and answer["user_message"] == R0_MESSAGE


def test_the_replay_script_reads_ask_as_warned_and_deny_as_blocked() -> None:
    spec = importlib.util.spec_from_file_location("fake_agent", REPO / "examples/fake_agent.py")
    assert spec is not None and spec.loader is not None
    fake_agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake_agent)

    assert fake_agent.permission_to_verdict({"permission": "ask"}) == "warned"
    assert fake_agent.permission_to_verdict({"permission": "deny"}) == "blocked"
    assert fake_agent.permission_to_verdict({"permission": "allow"}) == "allowed"
    assert fake_agent.permission_to_verdict({"verdict": "warned"}) == "allowed"
