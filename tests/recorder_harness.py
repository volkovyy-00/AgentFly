"""The server's decision path (`apply_rules`) over a session store in a temporary folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import agentfly.recorder.app as app_module
from agentfly.recorder.memory import memory_steps
from agentfly.recorder.sessions import SessionStore


class Clock:
    """A clock a test moves by hand."""

    def __init__(self) -> None:
        self.now: float = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class Recorder:
    def __init__(self, folder: Path, clock: Clock | None = None) -> None:
        self.path: Path = folder / "sessions.json"
        self.clock: Clock = clock or Clock()
        self.restart()

    def restart(self) -> None:
        """What a recorder restart does: the store is read again from disk, memory starts empty."""
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

    def run(self, chat: str, command: str, **fields: Any) -> dict[str, str]:
        return self.send(chat, "beforeShellExecution", command=command, cwd="", **fields)

    def read(self, chat: str, path: str, **fields: Any) -> dict[str, str]:
        return self.send(chat, "beforeReadFile", file_path=path, **fields)

    def task(self, chat: str, call: str, **fields: Any) -> dict[str, str]:
        return self.send(chat, "preToolUse", tool_name="Task", tool_use_id=call, **fields)
