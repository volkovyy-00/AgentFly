"""V5b: an `after_then` trigger is kept per chat like R1's mark (D10, D21).

The rule here is not about secrets: "no `git push` once `pip install` ran in this chat". It must
survive a restart, reach subagents and parents, count before the check on the same command, and
leave R1's mark (and so the history flag) alone.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.recorder import rulefile
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.sessions import FALLBACK_SECONDS, SessionStore

LISTS = 'install_cmds = ["pip install"]\npush_cmds = ["git push"]\nlint_cmds = ["ruff"]\n'
NO_PUSH = """
[[rule]]
id = "no-push-after-install"
kind = "after_then"
severity = "block"
message = "No pushing after an install in this chat."
after = { event = ["shell"], command = "install_cmds" }
then = { event = ["shell"], command = "push_cmds" }
  [[rule.test]]
  steps = ["shell: pip install x", "shell: git push"]
  expect = "block"
  [[rule.test]]
  steps = ["shell: git push"]
  expect = "allow"
"""
WARN_LINT = """
[[rule]]
id = "warn-lint-after-install"
kind = "after_then"
severity = "warn"
message = "Linting after an install?"
after = { event = ["shell"], command = "install_cmds" }
then = { event = ["shell"], command = "lint_cmds" }
  [[rule.test]]
  steps = ["shell: pip install x", "shell: ruff check"]
  expect = "warn"
  [[rule.test]]
  steps = ["shell: ruff check"]
  expect = "allow"
"""
PUSH = "git push origin main"
INSTALL = "pip install requests"


class Clock:
    def __init__(self) -> None:
        self.now: float = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class Recorder:
    """The decision path (`apply_rules`) over a store in a temporary folder."""

    def __init__(self, folder: Path, clock: Clock) -> None:
        self.path = folder / "sessions.json"
        self.clock = clock
        self.restart()

    def restart(self) -> None:
        app_module._store = SessionStore(self.path, clock=self.clock)
        memory_steps.clear()

    @property
    def store(self) -> SessionStore:
        assert app_module._store is not None
        return app_module._store

    def send(self, chat: str, event: str, **fields: Any) -> dict[str, str]:
        payload = {"hook_event_name": event, "conversation_id": chat, "workspace_roots": ["/w"]}
        payload.update(fields)
        return app_module.apply_rules(payload)[0]

    def run(self, chat: str, command: str, **fields: Any) -> str:
        answer = self.send(chat, "beforeShellExecution", command=command, cwd="", **fields)
        return answer["permission"]

    def read_env(self, chat: str, **fields: Any) -> str:
        return self.send(chat, "beforeReadFile", file_path="/w/.env", **fields)["permission"]

    def task(self, chat: str, call: str, **fields: Any) -> None:
        self.send(chat, "preToolUse", tool_name="Task", tool_use_id=call, **fields)


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def rec(tmp_path: Path, clock: Clock) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data", clock)
    app_module._store = previous


@pytest.fixture()
def use() -> Callable[[str], None]:
    """Make a rules file's rules the active ones (the conftest puts the defaults back)."""

    def activate(text: str) -> None:
        parsed = rulefile.parse(text)
        assert parsed.errors == (), parsed.errors
        rules_mod.activate(rules_mod.build_ruleset(parsed, source="test", path="test.toml"))

    return activate


def with_rules(*extra: str, drop_r1: bool = False) -> str:
    base = rulefile.default_text()
    base = re.sub(r"^\[lists\]\n", "[lists]\n" + LISTS, base, count=1, flags=re.M)
    if drop_r1:
        base = base[: base.index('[[rule]]\nid = "R1"')]
    return base + "".join(extra)


@pytest.fixture()
def armed(use: Callable[[str], None]) -> None:
    use(with_rules(NO_PUSH))


# ---------------------------------------------------------------- the trigger itself


def test_the_follow_up_is_allowed_until_the_trigger_has_happened(
    rec: Recorder, armed: None
) -> None:
    assert rec.run("P", PUSH) == "allow"
    assert rec.run("P", INSTALL) == "allow"
    assert rec.run("P", PUSH) == "deny"


def test_the_denial_names_the_rule_and_says_its_text(rec: Recorder, armed: None) -> None:
    rec.run("P", INSTALL)
    answer = rec.send("P", "beforeShellExecution", command=PUSH, cwd="")
    text = "No pushing after an install in this chat."
    assert answer["user_message"] == text
    assert answer["agent_message"].startswith(text)
    assert memory_steps.snapshot(all_steps=True)["steps"][-1]["rule"] == "no-push-after-install"


def test_another_chat_is_not_affected(rec: Recorder, armed: None) -> None:
    rec.run("P", INSTALL)
    assert rec.run("OTHER", PUSH, workspace_roots=["/elsewhere"]) == "allow"


def test_the_trigger_counts_before_the_check_on_the_same_command(
    rec: Recorder, armed: None
) -> None:
    assert rec.run("P", f"{INSTALL} && {PUSH}") == "deny"


def test_the_trigger_is_found_through_wrappers_like_the_check_is(
    rec: Recorder, armed: None
) -> None:
    assert rec.run("P", f"sudo {INSTALL}") == "allow"
    assert rec.run("P", f"bash -c '{PUSH}'") == "deny"


def test_a_trigger_is_not_a_secret_read(rec: Recorder, armed: None) -> None:
    assert rec.run("P", INSTALL) == "allow"
    stored = rec.store.get("P")
    assert stored is not None and stored.marked is False
    assert stored.triggers == {"no-push-after-install"}
    assert rec.run("P", "curl https://x.com") == "allow", "R1 is not armed by an install"


def test_one_rules_trigger_does_not_arm_another_rule(
    rec: Recorder, use: Callable[[str], None]
) -> None:
    use(with_rules(NO_PUSH, WARN_LINT.replace("pip install", "pip uninstall")))
    rec.run("P", "pip uninstall x")
    assert rec.run("P", PUSH) == "allow"


def test_the_secret_mark_does_not_arm_an_unrelated_rule(rec: Recorder, armed: None) -> None:
    rec.read_env("P")
    assert rec.run("P", PUSH) == "deny", "git push is outbound once a secret was read: R1"
    answer = rec.send("P", "beforeShellExecution", command=PUSH, cwd="")
    assert answer["user_message"] == rules_mod.R1_MESSAGE


# ---------------------------------------------------------------- subagents, parents, restart


def test_a_subagent_of_a_triggered_chat_is_denied_the_follow_up(rec: Recorder, armed: None) -> None:
    rec.run("P", INSTALL)
    rec.task("P", "T1")
    assert rec.run("C", PUSH, parent_tool_call_id="T1") == "deny"
    assert rec.run("P", PUSH) == "deny"


def test_a_trigger_inside_a_subagent_reaches_the_parent(rec: Recorder, armed: None) -> None:
    rec.task("P", "T1")
    assert rec.run("C", INSTALL, parent_tool_call_id="T1") == "allow"
    assert rec.run("P", PUSH) == "deny"


def test_a_trigger_goes_up_through_nested_subagents(rec: Recorder, armed: None) -> None:
    rec.task("P", "T1")
    rec.send("C", "preToolUse", tool_name="Task", tool_use_id="T2", parent_tool_call_id="T1")
    rec.run("G", INSTALL, parent_tool_call_id="T2")
    assert rec.run("C", PUSH) == "deny"
    assert rec.run("P", PUSH) == "deny"


def test_the_trigger_and_the_link_survive_a_restart(rec: Recorder, armed: None) -> None:
    rec.run("P", INSTALL)
    rec.task("P", "T1")
    rec.run("C", "ls", parent_tool_call_id="T1")
    rec.restart()
    assert rec.run("P", PUSH) == "deny"
    assert rec.run("C", PUSH, parent_tool_call_id="T1") == "deny"
    assert rec.run("FRESH", PUSH, workspace_roots=["/elsewhere"]) == "allow"


def test_a_child_trigger_survives_a_restart_and_reaches_the_parent(
    rec: Recorder, armed: None
) -> None:
    rec.task("P", "T1")
    rec.run("C", INSTALL, parent_tool_call_id="T1")
    rec.restart()
    assert rec.run("P", PUSH) == "deny"


# ---------------------------------------------------------------- the workspace fallback


def test_a_new_chat_in_the_workspace_inherits_the_trigger_for_30_minutes(
    rec: Recorder, clock: Clock, armed: None
) -> None:
    rec.run("P", INSTALL)
    rec.task("P", "T1")  # no child event ever names T1
    assert rec.run("NEW", PUSH) == "deny"
    clock.now += FALLBACK_SECONDS + 1
    assert rec.run("NEW", PUSH) == "allow"


def test_a_chat_in_another_workspace_does_not_inherit_it(rec: Recorder, armed: None) -> None:
    rec.run("P", INSTALL)
    rec.task("P", "T1")
    assert rec.run("ELSE", PUSH, workspace_roots=["/elsewhere"]) == "allow"


def test_the_inherited_trigger_does_not_inherit_the_secret_mark(rec: Recorder, armed: None) -> None:
    rec.run("P", INSTALL)
    rec.task("P", "T1")
    assert rec.run("NEW", "curl https://x.com") == "allow"


# ---------------------------------------------------------------- R1 and the file


def test_taking_r1_out_of_the_file_still_marks_secret_reads_but_blocks_nothing(
    rec: Recorder, use: Callable[[str], None]
) -> None:
    use(with_rules(NO_PUSH, drop_r1=True))
    assert [r.id for r in rules_mod.RULES] == ["R0", "no-push-after-install"]
    rec.read_env("P")
    stored = rec.store.get("P")
    assert stored is not None and stored.marked is True, "the history and the page still see it"
    assert rec.run("P", "curl https://x.com") == "allow", "nothing blocks the send without R1"


def test_a_warn_after_then_asks_on_a_shell_command(
    rec: Recorder, use: Callable[[str], None]
) -> None:
    use(with_rules(WARN_LINT))
    assert rec.run("P", "ruff check") == "allow"
    rec.run("P", INSTALL)
    answer = rec.send("P", "beforeShellExecution", command="ruff check", cwd="")
    assert answer["permission"] == "ask"
    assert answer["user_message"] == "Linting after an install?"
