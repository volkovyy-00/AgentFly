"""F11: a killed recorder comes back judging every chat as before, and never reuses an order number.

These start the real recorder (`agentfly serve`) in a child process and end it with SIGKILL (no
shutdown code runs) or SIGTERM (the lifespan stops cleanly). `tests/test_session_state.py` covers
the same rules in-process, class by class.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import free_port, start_recorder, stop_recorder, wait_for_health, wallclock
from tests.rules_helpers import default_with
from tests.test_session_state import CURL, INSTALL, LISTS, NO_PUSH, PUSH, wait_for
from tests.test_sessions_api import call

pytestmark = pytest.mark.slow  # both tests start the real recorder in a child process


def shell(chat: str, command: str, root: str, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "beforeShellExecution",
        "conversation_id": chat,
        "command": command,
        "cwd": "",
        "workspace_roots": [root],
        **extra,
    }


def read_env(chat: str, root: str, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "beforeReadFile",
        "conversation_id": chat,
        "file_path": f"{root}/.env",
        "workspace_roots": [root],
        **extra,
    }


def task(chat: str, call_id: str, root: str) -> dict[str, Any]:
    return {
        "hook_event_name": "preToolUse",
        "conversation_id": chat,
        "tool_name": "Task",
        "tool_use_id": call_id,
        "workspace_roots": [root],
    }


class Running:
    """One child recorder: post hooks to it, list a chat's saved steps."""

    def __init__(self, home: Path) -> None:
        self.port = free_port()
        self.process: subprocess.Popen[bytes] = start_recorder(home, self.port)
        wait_for_health(self.port, self.process)
        self.token = (home / ".config" / "agentfly" / "token").read_text().strip()

    def post(self, event: dict[str, Any]) -> str:
        status, answer = call(self.port, "POST", "/hook", self.token, event)
        assert status == 200
        return str(answer["permission"])

    def steps(self, chat: str) -> list[dict[str, Any]]:
        status, body = call(self.port, "GET", f"/api/sessions/{chat}/steps")
        steps: list[dict[str, Any]] = body["steps"] if status == 200 else []  # 404: not saved yet
        return steps

    def wait_for_steps(self, chat: str, count: int) -> list[dict[str, Any]]:
        """History is written in the background: wait until it holds `count` steps of the chat."""
        assert wait_for(lambda: len(self.steps(chat)) >= count, 15), f"{count} steps of {chat}"
        return self.steps(chat)

    def kill(self) -> None:
        self.process.kill()  # SIGKILL: no shutdown code runs
        self.process.wait(timeout=10)

    def stop(self) -> None:
        stop_recorder(self.process)  # SIGTERM: the lifespan stops cleanly


@contextmanager
def recorder(home: Path) -> Iterator[Running]:
    running = Running(home)
    try:
        yield running
    finally:
        if running.process.poll() is None:
            running.kill()


def note_of(home: Path, chat: str) -> dict[str, Any]:
    saved = home / ".local" / "share" / "agentfly" / "sessions.json"
    [row] = [r for r in json.loads(saved.read_text("utf-8")) if r["id"] == chat]
    return row


@wallclock
def test_a_killed_recorder_comes_back_as_it_was(isolated_home: Path) -> None:
    (isolated_home / "test-rules.toml").write_text(default_with(LISTS, NO_PUSH), encoding="utf-8")
    with recorder(isolated_home) as first:
        for _ in range(5):  # plain steps: their counter is only ever in memory
            first.post(shell("cn", "ls", "/w"))
        assert [s["order"] for s in first.wait_for_steps("cn", 5)] == [1, 2, 3, 4, 5]
        first.post(read_env("mk", "/w-mk"))  # a mark
        first.post(shell("tr", INSTALL, "/w-tr"))  # a trigger that is not R1's mark
        first.post(read_env("tkP", "/w-tk"))
        first.post(task("tkP", "TK1", "/w-tk"))  # a Task of a marked chat; no child names it
        first.post(read_env("lkP", "/w-lk"))
        first.post(task("lkP", "LK1", "/w-lk"))
        first.post(shell("lkC", "ls", "/w-lk", parent_tool_call_id="LK1"))  # a subagent links
        first.post(read_env("winP", "/w-win"))
        first.post(task("winP", "WN1", "/w-win"))
        first.post(shell("winNEW", "ls", "/w-win"))  # a chat opens inside the inherited window
        first.post(task("prP", "PR1", "/w-pr"))
        first.post(read_env("prC", "/w-pr", parent_tool_call_id="PR1"))  # the mark climbs up
        first.kill()  # right after the last answer

    probes: list[tuple[str, dict[str, Any]]] = [
        ("marked chat", shell("mk", CURL, "/w-mk")),
        ("trigger", shell("tr", PUSH, "/w-tr")),
        ("new chat after a Task", shell("tkNEW", CURL, "/w-tk")),
        ("subagent", shell("lkC", CURL, "/w-lk", parent_tool_call_id="LK1")),
        ("its parent", shell("lkP", CURL, "/w-lk")),
        ("chat in the window", shell("winNEW", CURL, "/w-win")),
        ("parent of a marked subagent", shell("prP", CURL, "/w-pr")),
        ("marked subagent", shell("prC", CURL, "/w-pr", parent_tool_call_id="PR1")),
    ]
    with recorder(isolated_home) as second:
        answers = {name: second.post(event) for name, event in probes}
        assert answers == {name: "deny" for name, _ in probes}
        assert second.post(shell("clean", CURL, "/w-clean")) == "allow"  # nothing leaks to others
        second.post(shell("cn", "ls", "/w"))  # the counter died with the process; history has it
        assert [s["order"] for s in second.wait_for_steps("cn", 6)] == [1, 2, 3, 4, 5, 6]
        second.stop()
    assert note_of(isolated_home, "cn")["next_step"] == 7  # and a clean stop leaves it in the file


def test_after_a_clean_stop_nothing_is_lost(isolated_home: Path) -> None:
    with recorder(isolated_home) as first:
        for _ in range(3):
            first.post(shell("cl", "ls", "/w"))
        first.stop()
    row = note_of(isolated_home, "cl")
    assert row["next_step"] == 4 and row["last_active"] > 0
