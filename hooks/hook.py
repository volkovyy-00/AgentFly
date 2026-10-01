#!/usr/bin/env python3
"""Cursor hook helper: sanitize, POST to local recorder, print allow/deny.

Stdlib only. Called via .cursor/hooks.json. Stdout must be ONLY the JSON
permission answer; diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT: Path = Path(__file__).resolve().parent.parent
_LOG_PATH: Path = _ROOT / "logs" / "events.jsonl"
_TOKEN_PATH: Path = Path.home() / ".config" / "flightrecorder" / "token"
_HOOK_URL: str = "http://127.0.0.1:8787/hook"
_TIMEOUT_S: float = 0.5

# Checkpoint A (SPEC §7): temporary hard-coded deny. Keep disabled after the decision.
_T0_ENABLED: bool = False
_T0_USER: str = "Blocked by test rule T0 (Checkpoint A)."
_T0_AGENT: str = (
    "Blocked by test rule T0 (Checkpoint A). "
    "Do not retry with another tool or language. Stop and tell the user."
)


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to send/log (no file contents or edit text)."""
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


def allow_fail_open(reason: str) -> dict[str, str]:
    print(f"agentfly: {reason}", file=sys.stderr)
    return {"permission": "allow"}


def post_hook(payload: dict[str, Any]) -> dict[str, Any]:
    """POST sanitized payload to the recorder. Raises on transport/HTTP errors."""
    token: str = _TOKEN_PATH.read_text(encoding="utf-8").strip()
    body: bytes = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _HOOK_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Recorder-Token": token,
        },
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        raw: bytes = response.read()
    parsed: Any = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("recorder response is not a JSON object")
    return parsed


def main() -> int:
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        decision = allow_fail_open(f"invalid hook JSON: {exc}")
        print(json.dumps(decision))
        return 0

    if not isinstance(payload, dict):
        decision = allow_fail_open("hook payload is not an object")
        print(json.dumps(decision))
        return 0

    # Local T0 remains available for Checkpoint A replay; disabled by default.
    if (
        _T0_ENABLED
        and str(payload.get("hook_event_name", "")) == "beforeShellExecution"
        and "curl" in str(payload.get("command", ""))
    ):
        decision = {
            "permission": "deny",
            "user_message": _T0_USER,
            "agent_message": _T0_AGENT,
        }
        print(json.dumps(decision))
        return 0

    sanitized: dict[str, Any] = sanitize(payload)
    try:
        decision_any: dict[str, Any] = post_hook(sanitized)
        decision: dict[str, str] = {
            "permission": str(decision_any.get("permission", "allow")),
        }
        if "user_message" in decision_any:
            decision["user_message"] = str(decision_any["user_message"])
        if "agent_message" in decision_any:
            decision["agent_message"] = str(decision_any["agent_message"])
    except Exception as exc:  # noqa: BLE001 — fail-open for any transport/IO error
        decision = allow_fail_open(f"recorder unreachable or error: {exc}")

    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "event": sanitized,
        "decision": decision.get("permission", "allow"),
    }
    try:
        append_log(record)
    except OSError as exc:
        print(f"agentfly: failed to write log: {exc}", file=sys.stderr)

    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
