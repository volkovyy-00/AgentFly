"""In-memory session notes with atomic JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from recorder.rules import Session


class SessionStore:
    """session id -> Session; persists to sessions.json on change."""

    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self._sessions: dict[str, Session] = {}
        self.load()

    def load(self) -> None:
        self._sessions = {}
        if not self.path.is_file():
            return
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            sid: str = str(item.get("id", ""))
            if not sid:
                continue
            self._sessions[sid] = Session(
                id=sid,
                marked=bool(item.get("marked", False)),
                start_time=str(item.get("start_time", "")),
                next_step=int(item.get("next_step", 1)),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: list[dict[str, Any]] = [
            {
                "id": s.id,
                "marked": s.marked,
                "start_time": s.start_time,
                "next_step": s.next_step,
            }
            for s in self._sessions.values()
        ]
        data: str = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd: int
        tmp_name: str
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".sessions-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def get_or_create(self, session_id: str) -> Session:
        existing: Session | None = self._sessions.get(session_id)
        if existing is not None:
            return existing
        created = Session(
            id=session_id,
            marked=False,
            start_time=datetime.now(UTC).isoformat(),
            next_step=1,
        )
        self._sessions[session_id] = created
        self.save()
        return created

    def put(self, session: Session) -> None:
        """Replace session and persist (call when marked/next_step change)."""
        self._sessions[session.id] = session
        self.save()

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)
