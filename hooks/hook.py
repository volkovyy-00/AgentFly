#!/usr/bin/env python3
"""Cursor hook helper: sanitize, log, decide allow/deny.

Stdlib only. Called via .cursor/hooks.json. Stdout must be ONLY the JSON
permission answer; diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT: Path = Path(__file__).resolve().parent.parent
_LOG_PATH: Path = _ROOT / "logs" / "events.jsonl"

# Checkpoint A (SPEC §7): temporary hard-coded deny. Keep disabled after the decision.
_T0_ENABLED: bool = False
_T0_USER: str = "Blocked by test rule T0 (Checkpoint A)."
_T0_AGENT: str = (
    "Blocked by test rule T0 (Checkpoint A). "
    "Do not retry with another tool or language. Stop and tell the user."
)


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to write to disk (no file contents or edit text)."""
    out: dict[str, Any] = dict(payload)
    event: str = str(out.get("hook_event_name", ""))

    # SPEC §4: beforeReadFile includes full file contents — drop first.
    out.pop("content", None)

    if event == "afterFileEdit" and "edits" in out:
        edits: Any = out["edits"]
        count: int = len(edits) if isinstance(edits, list) else 0
        out["edits"] = f"<{count} edits>"

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


def decide(payload: dict[str, Any]) -> dict[str, str]:
    """Return the permission object for Cursor."""
    event: str = str(payload.get("hook_event_name", ""))
    command: str = str(payload.get("command", ""))

    if _T0_ENABLED and event == "beforeShellExecution" and "curl" in command:
        return {
            "permission": "deny",
            "user_message": _T0_USER,
            "agent_message": _T0_AGENT,
        }

    return {"permission": "allow"}


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

    decision: dict[str, str] = decide(payload)
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "event": sanitize(payload),
        "decision": decision.get("permission", "allow"),
    }
    try:
        append_log(record)
    except OSError as exc:
        print(f"flightrecorder: failed to write log: {exc}", file=sys.stderr)

    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
