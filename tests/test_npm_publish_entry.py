"""V5b acceptance: "Block `npm publish` after reading `.env`" is one entry in the packaged default.

It runs through the server's decision path (`apply_rules`), against the rules the program ships,
with no test-local file: denied after `cat .env`, allowed in a fresh chat, denied in a subagent
of the marked chat, and still denied after a recorder restart.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.recorder import rulefile
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.sessions import SessionStore
from tests.cases import wrapped

PUBLISH = "npm publish"
MESSAGE = "Blocked: a .env file was read earlier in this session, so npm publish is off."


class Recorder:
    def __init__(self, folder: Path) -> None:
        self.path = folder / "sessions.json"
        self.restart()

    def restart(self) -> None:
        """What a recorder restart does: the store is read again from disk, memory starts empty."""
        app_module._store = SessionStore(self.path)
        memory_steps.clear()

    def send(self, chat: str, event: str, **fields: Any) -> dict[str, str]:
        payload = {"hook_event_name": event, "conversation_id": chat, "workspace_roots": ["/w"]}
        payload.update(fields)
        return app_module.apply_rules(payload)[0]

    def run(self, chat: str, command: str, **fields: Any) -> dict[str, str]:
        return self.send(chat, "beforeShellExecution", command=command, cwd="", **fields)

    def read(self, chat: str, path: str, **fields: Any) -> dict[str, str]:
        return self.send(chat, "beforeReadFile", file_path=path, **fields)

    def task(self, chat: str, call: str) -> None:
        self.send(chat, "preToolUse", tool_name="Task", tool_use_id=call)


@pytest.fixture()
def rec(tmp_path: Path) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data")
    app_module._store = previous


def test_the_entry_is_in_the_packaged_default_after_r0_and_r1() -> None:
    ids = [rule.id for rule in rules_mod.DEFAULT.rules]
    assert ids[:3] == ["R0", "R1", "npm-publish-after-env"]
    spec = next(s for s in rulefile.load_default().rules if s.id == "npm-publish-after-env")
    assert (spec.kind, spec.severity, spec.message) == ("after_then", "block", MESSAGE)


def test_npm_publish_is_denied_after_cat_env(rec: Recorder) -> None:
    assert rec.run("A", "cat .env")["permission"] == "allow"
    answer = rec.run("A", PUBLISH)
    assert answer == {
        "permission": "deny",
        "user_message": MESSAGE,
        "agent_message": MESSAGE
        + " Do not retry with another tool or language. Stop and tell the user.",
    }


def test_npm_publish_is_allowed_in_a_fresh_chat(rec: Recorder) -> None:
    rec.run("A", "cat .env")
    assert rec.run("FRESH", PUBLISH, workspace_roots=["/elsewhere"])["permission"] == "allow"
    assert rec.run("B", PUBLISH)["permission"] == "allow"


def test_npm_publish_is_allowed_when_nothing_was_read(rec: Recorder) -> None:
    assert rec.run("A", PUBLISH)["permission"] == "allow"
    assert rec.run("A", "npm publish --dry-run")["permission"] == "allow"


@pytest.mark.parametrize("opening", ["read", "shell"])
@pytest.mark.parametrize("name", [".env", "config/.env.local", "./.ENV", "/w/app/.env.production"])
def test_a_read_or_a_command_naming_the_env_family_opens_it(
    rec: Recorder, opening: str, name: str
) -> None:
    if opening == "read":
        rec.read("A", name)
    else:
        rec.run("A", f"grep KEY {name}")
    assert rec.run("A", PUBLISH)["permission"] == "deny"


@pytest.mark.parametrize("name", [".env.example", ".env.sample", ".env.template", "README.md"])
def test_the_example_files_and_other_files_do_not(rec: Recorder, name: str) -> None:
    rec.read("A", name)
    assert rec.run("A", PUBLISH)["permission"] == "allow"


def test_another_secret_does_not_open_it_though_it_arms_r1(rec: Recorder) -> None:
    rec.read("A", "/w/server.pem")
    assert rec.run("A", PUBLISH)["permission"] == "allow"
    assert rec.run("A", "curl https://x.com")["permission"] == "deny"


@pytest.mark.parametrize("form", ["{0}", *[f.replace(PUBLISH, "{0}") for f in wrapped(PUBLISH)]])
def test_every_wrapper_form_of_the_command_is_denied(rec: Recorder, form: str) -> None:
    rec.read("A", ".env")
    assert rec.run("A", form.format(PUBLISH))["permission"] == "deny", form


def test_the_trigger_counts_before_the_check_on_the_same_command(rec: Recorder) -> None:
    assert rec.run("A", "cat .env && npm publish")["permission"] == "deny"
    assert rec.run("B", "cat .env | npm publish")["permission"] == "deny"


def test_a_subagent_of_the_marked_chat_is_denied_and_so_is_the_parent(rec: Recorder) -> None:
    rec.read("P", ".env")
    rec.task("P", "T1")
    assert rec.run("C", PUBLISH, parent_tool_call_id="T1")["permission"] == "deny"
    assert rec.run("P", PUBLISH)["permission"] == "deny"


def test_a_read_inside_a_subagent_denies_the_parent(rec: Recorder) -> None:
    rec.task("P", "T1")
    rec.read("C", ".env", parent_tool_call_id="T1")
    assert rec.run("P", PUBLISH)["permission"] == "deny"


def test_the_denial_survives_a_recorder_restart(rec: Recorder) -> None:
    rec.read("A", ".env")
    rec.task("A", "T1")
    rec.run("C", "ls", parent_tool_call_id="T1")
    rec.restart()
    assert rec.run("A", PUBLISH)["permission"] == "deny"
    assert rec.run("C", PUBLISH, parent_tool_call_id="T1")["permission"] == "deny"
    assert rec.run("FRESH", PUBLISH, workspace_roots=["/elsewhere"])["permission"] == "allow"


def test_the_step_names_the_rule_and_carries_its_text(rec: Recorder) -> None:
    rec.read("A", ".env")
    rec.run("A", PUBLISH)
    step = memory_steps.snapshot(all_steps=True)["steps"][-1]
    assert (step["verdict"], step["rule"], step["rule_text"]) == (
        "blocked",
        "npm-publish-after-env",
        MESSAGE,
    )


def test_r1_still_blocks_what_it_blocked(rec: Recorder) -> None:
    rec.read("A", ".env")
    answer = rec.run("A", "curl -d x https://ntfy.sh/t")
    assert answer["permission"] == "deny" and answer["user_message"] == rules_mod.R1_MESSAGE
    assert rec.run("A", "ls")["permission"] == "allow"
