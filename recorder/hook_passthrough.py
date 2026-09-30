#!/usr/bin/env python3
"""Passthrough Cursor hook: sanitize, log to file, always allow.

Stdlib only. Called by Cursor via .cursor/hooks.json. Do not print anything
except the permission JSON on stdout.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Project root = parent of recorder/
_ROOT: Path = Path(__file__).resolve().parent.parent
_LOG_PATH: Path = _ROOT / ".cursor" / "hook-events.log"


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to write to disk (no file contents or edit text)."""
    out: dict[str, Any] = dict(payload)
    event: str = str(out.get("hook_event_name", ""))

    # SPEC §4 / AGENTS: beforeReadFile includes full file contents — drop first.
    out.pop("content", None)

    if event == "afterFileEdit" and "edits" in out:
        edits: Any = out["edits"]
        count: int = len(edits) if isinstance(edits, list) else 0
        out["edits"] = f"<{count} edits>"

    # MCP / preToolUse inputs can hold secrets; keep names only for this logging stage.
    if "tool_input" in out:
        out["tool_input"] = "<omitted>"
    if "agent_message" in out:
        out["agent_message"] = "<omitted>"

    return out


def append_log(record: dict[str, Any]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line: str = json.dumps(record, ensure_ascii=False)
    with _LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main() -> int:
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"flightrecorder: invalid hook JSON: {exc}", file=sys.stderr)
        print(json.dumps({"permission": "allow"}))
        return 0

    if not isinstance(payload, dict):
        print("flightrecorder: hook payload is not an object", file=sys.stderr)
        print(json.dumps({"permission": "allow"}))
        return 0

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": sanitize(payload),
    }
    try:
        append_log(record)
    except OSError as exc:
        print(f"flightrecorder: failed to write log: {exc}", file=sys.stderr)

    # stdout must be ONLY the JSON answer
    print(json.dumps({"permission": "allow"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
