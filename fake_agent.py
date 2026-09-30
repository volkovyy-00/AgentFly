#!/usr/bin/env python3
"""Replay scripted Cursor hook events through hooks/hook.py (no model calls).

Usage:
  uv run python fake_agent.py
  uv run python fake_agent.py --scenario demo --session my-session-id
  uv run python fake_agent.py --scenario clean_sample

Requires the recorder on 127.0.0.1:8787 for blocked steps to succeed.
When the recorder is down, prints WARNING: recorder unreachable to stderr
and exits non-zero if any expect does not match.

Scenario file: demo/scenario.json
  {
    "<name>": {
      "description": "...",
      "events": [
        {
          "expect": "allowed" | "blocked" | "warned",
          "event": { ... Cursor hook payload fields ... }
        }
      ]
    }
  }

Verdict mapping from helper stdout:
  permission=deny  -> blocked
  otherwise        -> allowed
  (warned is reserved for WATCH_ONLY once the server exposes it)

SIMULATION (not a real agent) — first line of stdout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

_ROOT: Path = Path(__file__).resolve().parent
_SCENARIO_PATH: Path = _ROOT / "demo" / "scenario.json"
_HOOK_SCRIPT: Path = _ROOT / "hooks" / "hook.py"
_FAKE_SECRET: str = "FAKESECRET_drop_me_XYZ"


def load_scenarios() -> dict[str, Any]:
    raw: Any = json.loads(_SCENARIO_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit(f"invalid scenario file: {_SCENARIO_PATH}")
    return raw


def label_for(event: dict[str, Any]) -> str:
    name: str = str(event.get("hook_event_name", "?"))
    if "command" in event:
        cmd: str = str(event["command"])
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"{name} {cmd}"
    if "file_path" in event:
        return f"{name} {event['file_path']}"
    return name


def permission_to_verdict(payload: dict[str, Any]) -> str:
    if str(payload.get("permission", "")) == "deny":
        return "blocked"
    if str(payload.get("verdict", "")) == "warned":
        return "warned"
    return "allowed"


def run_hook(event: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Pipe event JSON to hooks/hook.py. Returns (parsed stdout, stdout, stderr)."""
    # Never send content to our own printers later; child still receives it so
    # the helper can prove it drops content.
    stdin_data: str = json.dumps(event)
    proc = subprocess.run(
        [sys.executable, str(_HOOK_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        check=False,
    )
    stdout: str = proc.stdout.strip()
    stderr: str = proc.stderr
    try:
        parsed: Any = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, stdout, stderr


def recorder_unreachable(stderr: str) -> bool:
    lower: str = stderr.lower()
    return (
        "unreachable" in lower
        or "connection refused" in lower
        or "no such file" in lower
        or "timed out" in lower
        or "timeout" in lower
        or "errno" in lower
    )


def assert_no_secret(*chunks: str) -> None:
    for chunk in chunks:
        if _FAKE_SECRET in chunk:
            raise SystemExit("fake secret leaked into output")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay demo/scenario.json through hooks/hook.py (simulation)."
    )
    parser.add_argument(
        "--scenario",
        default="demo",
        help="Scenario name in demo/scenario.json (default: demo)",
    )
    parser.add_argument(
        "--session",
        default="",
        help="conversation_id / session_id (default: new uuid)",
    )
    args = parser.parse_args()

    session_id: str = args.session.strip() or str(uuid.uuid4())
    scenarios: dict[str, Any] = load_scenarios()
    if args.scenario not in scenarios:
        names = ", ".join(sorted(scenarios))
        print(f"unknown scenario {args.scenario!r}; choose from: {names}", file=sys.stderr)
        return 2

    block: Any = scenarios[args.scenario]
    events: list[Any] = list(block.get("events", [])) if isinstance(block, dict) else []

    print("SIMULATION (not a real agent)")
    print(f"scenario={args.scenario} session={session_id}")

    all_ok: bool = True
    saw_unreachable: bool = False

    for index, item in enumerate(events, start=1):
        if not isinstance(item, dict):
            print(f"{index}. invalid event entry", file=sys.stderr)
            all_ok = False
            continue
        expect: str = str(item.get("expect", "allowed"))
        event_raw: Any = item.get("event", {})
        if not isinstance(event_raw, dict):
            print(f"{index}. invalid event payload", file=sys.stderr)
            all_ok = False
            continue

        event: dict[str, Any] = dict(event_raw)
        event["conversation_id"] = session_id
        event["session_id"] = session_id

        parsed, stdout, stderr = run_hook(event)
        if recorder_unreachable(stderr):
            saw_unreachable = True

        verdict: str = permission_to_verdict(parsed)
        ok: bool = verdict == expect
        if not ok:
            all_ok = False

        line: str = f"{index}. {label_for(event)}  verdict={verdict} expect={expect}" + (
            "" if ok else "  MISMATCH"
        )
        print(line)
        assert_no_secret(line, stdout, stderr)

    if saw_unreachable:
        print("WARNING: recorder unreachable", file=sys.stderr)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
