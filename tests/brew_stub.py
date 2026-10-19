"""A stand-in for `brew services` for AgentFly's formula (see tests/service_helpers.py).

Run as `python brew_stub.py <state file> services <start|stop|info> agentfly [--json]`.
`info --json` prints the field names Homebrew 7.0.9 prints (`running`, `loaded`, `pid`, `file`,
`loaded_file`, `registered`, `service_name`). `start` writes the service file the way Homebrew
does, into `~/Library/LaunchAgents`; `stop` removes it again.
"""

from __future__ import annotations

import json
import plistlib
import sys
from pathlib import Path
from typing import Any

FORMULA = "agentfly"
LABEL = "sh.brew.agentfly"


def info(state: dict[str, Any]) -> list[dict[str, Any]]:
    started = state["started"]
    return [
        {
            "name": FORMULA,
            "service_name": LABEL,
            "running": started,
            "loaded": started,
            "schedulable": False,
            "pid": 4242 if started else None,
            "exit_code": None,
            "user": "me" if started else None,
            "status": "started" if started else "none",
            "file": f"/usr/local/opt/{FORMULA}/{LABEL}.plist",
            "registered": started,
            "loaded_file": state["plist"] if started else None,
        }
    ]


def run(state: dict[str, Any], args: list[str]) -> tuple[int, str, str]:
    if args[:1] != ["services"] or len(args) < 3 or args[2] != FORMULA:
        return 64, "", f"stub brew: unsupported arguments {args}\n"
    verb = args[1]
    plist = Path(state["plist"])
    if verb == "start":
        plist.parent.mkdir(parents=True, exist_ok=True)
        data = {"Label": LABEL, "KeepAlive": state["keepalive"], "ProgramArguments": [FORMULA]}
        plist.write_bytes(plistlib.dumps(data))
        state["started"] = True
        return 0, f"==> Successfully started `{FORMULA}` (label: {LABEL})\n", ""
    if verb == "stop":
        plist.unlink(missing_ok=True)
        state["started"] = False
        return 0, f"Successfully stopped `{FORMULA}` (label: {LABEL})\n", ""
    if verb == "info":
        return 0, json.dumps(info(state), indent=2) + "\n", ""
    return 64, "", f"stub brew: unsupported arguments {args}\n"


def main(argv: list[str]) -> int:
    state_path = Path(argv[0])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["calls"].append(argv[1:])
    code, out, err = run(state, argv[1:])
    state_path.write_text(json.dumps(state), encoding="utf-8")
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
