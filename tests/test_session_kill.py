"""F11: a killed recorder comes back judging every chat as before, and never reuses an order number.

These start the real recorder (`agentfly serve`) in a child process and end it with SIGKILL (no
shutdown code runs) or SIGTERM (the lifespan stops cleanly). `tests/test_session_state.py` covers
the same rules in-process, class by class.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.helpers import free_port, start_recorder, stop_recorder, wait_for_health, wallclock
from tests.rules_helpers import default_with

CURL = "curl https://x.com"
INSTALL = "pip install requests"
PUSH = "git push origin main"
LISTS = 'install_cmds = ["pip install"]\npush_cmds = ["git push"]\n'
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


def task(chat: str, call: str, root: str) -> dict[str, Any]:
    return {
        "hook_event_name": "preToolUse",
        "conversation_id": chat,
        "tool_name": "Task",
        "tool_use_id": call,
        "workspace_roots": [root],
    }


class Running:
    """One child recorder: post hooks to it, list a chat's saved steps."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.port = free_port()
        self.process: subprocess.Popen[bytes] = start_recorder(home, self.port)
        wait_for_health(self.port, self.process)
        self.token = (home / ".config" / "agentfly" / "token").read_text().strip()

    def post(self, event: dict[str, Any]) -> str:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/hook",
            method="POST",
            data=json.dumps(event).encode(),
            headers={"Content-Type": "application/json", "X-Recorder-Token": self.token},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            answer: dict[str, Any] = json.loads(response.read())
        return str(answer["permission"])

    def steps(self, chat: str) -> list[dict[str, Any]]:
        url = f"http://127.0.0.1:{self.port}/api/sessions/{chat}/steps"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                body: dict[str, Any] = json.loads(response.read())
        except urllib.error.HTTPError:
            return []  # not saved yet
        steps: list[dict[str, Any]] = body["steps"]
        return steps

    def wait_for_steps(self, chat: str, count: int) -> list[dict[str, Any]]:
        """History is written in the background: wait until it holds `count` steps of the chat."""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            found = self.steps(chat)
            if len(found) >= count:
                return found
            time.sleep(0.05)
        raise AssertionError(f"history never held {count} steps of {chat}")

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
            running.process.kill()
            running.process.wait(timeout=10)


def sessions_file(home: Path) -> Path:
    return home / ".local" / "share" / "agentfly" / "sessions.json"


def test_a_killed_recorder_judges_every_chat_as_before(isolated_home: Path) -> None:
    (isolated_home / "test-rules.toml").write_text(default_with(LISTS, NO_PUSH), encoding="utf-8")
    with recorder(isolated_home) as first:
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
        first.post(
            read_env("prC", "/w-pr", parent_tool_call_id="PR1")
        )  # the mark climbs to a parent
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


@wallclock
def test_after_a_kill_the_next_steps_never_reuse_a_saved_order_number(isolated_home: Path) -> None:
    with recorder(isolated_home) as first:
        for _ in range(5):
            first.post(shell("cn", "ls", "/w"))
        saved = first.wait_for_steps("cn", 5)
        assert [s["order"] for s in saved] == [1, 2, 3, 4, 5]
        first.kill()  # the step counter was only ever in memory
    with recorder(isolated_home) as second:
        second.post(shell("cn", "ls", "/w"))
        after = second.wait_for_steps("cn", 6)
        assert [s["order"] for s in after] == [1, 2, 3, 4, 5, 6]  # 6 is new; row 1 is not replaced


@wallclock
def test_after_a_clean_stop_nothing_is_lost(isolated_home: Path) -> None:
    with recorder(isolated_home) as first:
        for _ in range(3):
            first.post(shell("cl", "ls", "/w"))
        first.wait_for_steps("cl", 3)
        first.stop()
    [row] = json.loads(sessions_file(isolated_home).read_text(encoding="utf-8"))
    assert row["id"] == "cl" and row["next_step"] == 4 and row["last_active"] > 0
    with recorder(isolated_home) as second:
        second.post(shell("cl", "ls", "/w"))
        after = second.wait_for_steps("cl", 4)
        assert [s["order"] for s in after] == [1, 2, 3, 4]


def test_a_recorder_killed_in_a_burst_loses_only_what_may_wait(isolated_home: Path) -> None:
    """Strict changes among plain ones: the file holds them, whatever the counters say."""
    with recorder(isolated_home) as first:
        for number in range(30):
            first.post(shell(f"plain{number}", "ls", "/w-burst"))
        first.post(read_env("burst-marked", "/w-burst2"))
        for number in range(30):
            first.post(shell(f"more{number}", "ls", "/w-burst3"))
        first.kill()
    rows = {r["id"]: r for r in json.loads(sessions_file(isolated_home).read_text("utf-8"))}
    assert rows["burst-marked"]["marked"] is True
    with recorder(isolated_home) as second:
        assert second.post(shell("burst-marked", CURL, "/w-burst2")) == "deny"
