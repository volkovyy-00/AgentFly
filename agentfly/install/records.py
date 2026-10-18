"""The hash record `init -g` leaves in the system folder, read by `init -g` and V3b's `doctor`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentfly.install.layout import Layout

SCHEMA: int = 1


def read(layout: Layout) -> dict[str, Any] | None:
    """The record, or None when it is missing, unreadable or of another schema."""
    try:
        data = json.loads(layout.record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def build(
    *,
    agentfly_version: str,
    cursor_version: str,
    archive_name: str,
    archive_sha256: str,
    interpreter_sha256: str,
    tree_sha256: str,
    client_sha256: str,
    entries: list[dict[str, Any]],
    created_hooks_file: bool,
    layout: Layout,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "agentfly_version": agentfly_version,
        "cursor_version": cursor_version,
        "python": {
            "archive": archive_name,
            "archive_sha256": archive_sha256,
            "interpreter": _relative(layout.interpreter, layout),
            "interpreter_sha256": interpreter_sha256,
            "tree_sha256": tree_sha256,
        },
        "client": {"path": _relative(layout.client, layout), "sha256": client_sha256},
        "hooks_file": {
            "path": str(layout.hooks_file),
            "entries": entries,
            "created": created_hooks_file,
        },
    }


def _relative(path: Path, layout: Layout) -> str:
    return path.relative_to(layout.system_root).as_posix()


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"
