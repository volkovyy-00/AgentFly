"""In-memory cleaned steps for the live graph page (SPEC §4 JSON shape)."""

from __future__ import annotations

import threading
from typing import Any

from recorder.store import StepRecord

_LAST_N: int = 10


class MemorySteps:
    """Thread-safe per-session step lists for GET /api/steps."""

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self.current_session_id: str | None = None
        self._steps_by_session: dict[str, list[dict[str, Any]]] = {}

    def clear(self) -> None:
        with self._lock:
            self.current_session_id = None
            self._steps_by_session.clear()

    def append_from_record(self, record: StepRecord) -> None:
        step: dict[str, Any] = {
            "order": record.order,
            "kind": record.kind,
            "verdict": record.verdict,
            "tool": record.tool,
            "file": record.file_path,
            "sensitive": record.file_sensitive,
            "command": record.command,
            "host": record.hosts[0] if record.hosts else None,
            "rule": record.rule_id,
        }
        with self._lock:
            bucket: list[dict[str, Any]] = self._steps_by_session.setdefault(
                record.session_id,
                [],
            )
            bucket.append(step)
            self.current_session_id = record.session_id

    def snapshot(self, *, all_steps: bool = False) -> dict[str, Any]:
        with self._lock:
            sid: str | None = self.current_session_id
            if sid is None:
                return {"session": None, "steps": []}
            steps: list[dict[str, Any]] = list(self._steps_by_session.get(sid, []))
            if not all_steps:
                steps = steps[-_LAST_N:]
            return {"session": sid, "steps": steps}


memory_steps: MemorySteps = MemorySteps()
