"""V5b: an `after_then` trigger is kept per chat like R1's mark (D10, D21).

The rule here is not about secrets: "no `git push` once `pip install` ran in this chat". It must
survive a restart, reach subagents and parents, count before the check on the same command, and
leave R1's mark (and so the history flag) alone.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.sessions import FALLBACK_SECONDS
from tests.recorder_harness import Clock, Recorder
from tests.rules_helpers import default_with, ruleset_of

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


class Rec(Recorder):
    """The harness, with the answers shortened to the permission the tests compare."""

    def says(self, chat: str, command: str, **fields: Any) -> str:
        return self.run(chat, command, **fields)["permission"]

    def read_env(self, chat: str, **fields: Any) -> str:
        return self.read(chat, "/w/.env", **fields)["permission"]


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def rec(tmp_path: Path, clock: Clock) -> Iterator[Rec]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Rec(tmp_path / "data", clock)
    app_module._store = previous


@pytest.fixture()
def use() -> Callable[[str], None]:
    """Make a rules file's rules the active ones (the conftest puts the defaults back)."""

    def activate(text: str) -> None:
        rules_mod.activate(ruleset_of(text))

    return activate


def with_rules(*extra: str, drop_r1: bool = False) -> str:
    return default_with(LISTS, *extra, drop_r1=drop_r1)


@pytest.fixture()
def armed(use: Callable[[str], None]) -> None:
    use(with_rules(NO_PUSH))


# ---------------------------------------------------------------- the trigger itself


def test_the_follow_up_is_allowed_until_the_trigger_has_happened(rec: Rec, armed: None) -> None:
    assert rec.says("P", PUSH) == "allow"
    assert rec.says("P", INSTALL) == "allow"
    assert rec.says("P", PUSH) == "deny"


def test_the_denial_names_the_rule_and_says_its_text(rec: Rec, armed: None) -> None:
    rec.says("P", INSTALL)
    answer = rec.send("P", "beforeShellExecution", command=PUSH, cwd="")
    text = "No pushing after an install in this chat."
    assert answer["user_message"] == text
    assert answer["agent_message"].startswith(text)
    assert memory_steps.snapshot(all_steps=True)["steps"][-1]["rule"] == "no-push-after-install"


def test_another_chat_is_not_affected(rec: Rec, armed: None) -> None:
    rec.says("P", INSTALL)
    assert rec.says("OTHER", PUSH, workspace_roots=["/elsewhere"]) == "allow"


def test_the_trigger_counts_before_the_check_on_the_same_command(rec: Rec, armed: None) -> None:
    assert rec.says("P", f"{INSTALL} && {PUSH}") == "deny"


def test_the_trigger_is_found_through_wrappers_like_the_check_is(rec: Rec, armed: None) -> None:
    assert rec.says("P", f"sudo {INSTALL}") == "allow"
    assert rec.says("P", f"bash -c '{PUSH}'") == "deny"


def test_a_trigger_is_not_a_secret_read(rec: Rec, armed: None) -> None:
    assert rec.says("P", INSTALL) == "allow"
    stored = rec.store.get("P")
    assert stored is not None and stored.marked is False
    assert stored.triggers == {"no-push-after-install"}
    assert rec.says("P", "curl https://x.com") == "allow", "R1 is not armed by an install"


def test_one_rules_trigger_does_not_arm_another_rule(rec: Rec, use: Callable[[str], None]) -> None:
    use(with_rules(NO_PUSH, WARN_LINT.replace("pip install", "pip uninstall")))
    rec.says("P", "pip uninstall x")
    assert rec.says("P", PUSH) == "allow"


def test_the_secret_mark_does_not_arm_an_unrelated_rule(rec: Rec, armed: None) -> None:
    rec.read_env("P")
    assert rec.says("P", PUSH) == "deny", "git push is outbound once a secret was read: R1"
    answer = rec.send("P", "beforeShellExecution", command=PUSH, cwd="")
    assert answer["user_message"] == rules_mod.R1_MESSAGE


# ---------------------------------------------------------------- subagents, parents, restart


def test_a_subagent_of_a_triggered_chat_is_denied_the_follow_up(rec: Rec, armed: None) -> None:
    rec.says("P", INSTALL)
    rec.task("P", "T1")
    assert rec.says("C", PUSH, parent_tool_call_id="T1") == "deny"
    assert rec.says("P", PUSH) == "deny"


def test_a_trigger_inside_a_subagent_reaches_the_parent(rec: Rec, armed: None) -> None:
    rec.task("P", "T1")
    assert rec.says("C", INSTALL, parent_tool_call_id="T1") == "allow"
    assert rec.says("P", PUSH) == "deny"


def test_a_trigger_goes_up_through_nested_subagents(rec: Rec, armed: None) -> None:
    rec.task("P", "T1")
    rec.send("C", "preToolUse", tool_name="Task", tool_use_id="T2", parent_tool_call_id="T1")
    rec.says("G", INSTALL, parent_tool_call_id="T2")
    assert rec.says("C", PUSH) == "deny"
    assert rec.says("P", PUSH) == "deny"


def test_the_trigger_and_the_link_survive_a_restart(rec: Rec, armed: None) -> None:
    rec.says("P", INSTALL)
    rec.task("P", "T1")
    rec.says("C", "ls", parent_tool_call_id="T1")
    rec.restart()
    assert rec.says("P", PUSH) == "deny"
    assert rec.says("C", PUSH, parent_tool_call_id="T1") == "deny"
    assert rec.says("FRESH", PUSH, workspace_roots=["/elsewhere"]) == "allow"


def test_a_child_trigger_survives_a_restart_and_reaches_the_parent(rec: Rec, armed: None) -> None:
    rec.task("P", "T1")
    rec.says("C", INSTALL, parent_tool_call_id="T1")
    rec.restart()
    assert rec.says("P", PUSH) == "deny"


# ---------------------------------------------------------------- the workspace fallback


def test_a_new_chat_in_the_workspace_inherits_the_trigger_for_30_minutes(
    rec: Rec, clock: Clock, armed: None
) -> None:
    rec.says("P", INSTALL)
    rec.task("P", "T1")  # no child event ever names T1
    assert rec.says("NEW", PUSH) == "deny"
    clock.now += FALLBACK_SECONDS + 1
    assert rec.says("NEW", PUSH) == "allow"


def test_a_chat_in_another_workspace_does_not_inherit_it(rec: Rec, armed: None) -> None:
    rec.says("P", INSTALL)
    rec.task("P", "T1")
    assert rec.says("ELSE", PUSH, workspace_roots=["/elsewhere"]) == "allow"


def test_the_inherited_trigger_does_not_inherit_the_secret_mark(rec: Rec, armed: None) -> None:
    rec.says("P", INSTALL)
    rec.task("P", "T1")
    assert rec.says("NEW", "curl https://x.com") == "allow"


# ---------------------------------------------------------------- R1 and the file


def test_a_file_without_r1_is_refused_and_the_default_keeps_blocking(
    rec: Rec, active_rules: Path
) -> None:
    """D27: R1 cannot be taken out. The recorder runs the packaged default and says why."""
    active_rules.write_text(with_rules(NO_PUSH, drop_r1=True), encoding="utf-8")
    loaded = rules_mod.load_active()
    assert loaded.source == "default" and "rule R1: missing" in (loaded.problem or "")
    rules_mod.activate(loaded)
    rec.read_env("P")
    assert rec.says("P", "curl https://x.com") == "deny"


def test_a_warn_after_then_asks_on_a_shell_command(rec: Rec, use: Callable[[str], None]) -> None:
    use(with_rules(WARN_LINT))
    assert rec.says("P", "ruff check") == "allow"
    rec.says("P", INSTALL)
    answer = rec.send("P", "beforeShellExecution", command="ruff check", cwd="")
    assert answer["permission"] == "ask"
    assert answer["user_message"] == "Linting after an install?"
