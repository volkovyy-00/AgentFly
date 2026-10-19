"""A stand-in for /bin/launchctl that keeps its jobs in a JSON file (see tests/service_helpers.py).

Run as `python launchctl_stub.py <state file> <launchctl arguments>`. It knows the verbs the service
code uses and prints what the real tool printed on macOS 15.7 (`print` of a missing job exits 113,
`bootout` of a missing job exits 3, a loaded KeepAlive job shows `properties = keepalive | ...`).
`bootout_lag` makes a booted-out job linger for that many `print` calls, as launchd's teardown does,
and `bootout_code` is the exit code of the first `bootout` (Homebrew sees 36 while it is going).
`bootstrap_code`, when not 0, makes every `bootstrap` fail with that code.
"""

from __future__ import annotations

import json
import plistlib
import sys
from pathlib import Path
from typing import Any


def label_of(target: str) -> str:
    return target.rsplit("/", 1)[-1]


def render(label: str, job: dict[str, Any]) -> str:
    lines = [
        f"gui/501/{label} = {{",
        "\tactive count = 1",
        f"\tpath = {job['plist']}",
        "\ttype = LaunchAgent",
        f"\tstate = {'running' if job['pid'] else 'not running'}",
        "",
        "\targuments = {",
        *[f"\t\t{argument}" for argument in job["args"]],
        "\t}",
        "",
        "\truns = 1",
    ]
    if job["pid"]:
        lines.append(f"\tpid = {job['pid']}")
    properties = ["keepalive"] if job["keepalive"] else []
    lines += [f"\tproperties = {' | '.join([*properties, 'runatload'])}", "}"]
    return "\n".join(lines) + "\n"


def run(state: dict[str, Any], args: list[str]) -> tuple[int, str, str]:
    jobs: dict[str, dict[str, Any]] = state["jobs"]
    verb, rest = (args[0] if args else ""), args[1:]
    if verb == "enable":
        return 0, "", ""
    if verb == "bootstrap":
        plist = rest[-1]
        data = plistlib.loads(Path(plist).read_bytes())
        label = data["Label"]
        if label in jobs or state["bootstrap_code"]:
            code = state["bootstrap_code"] or 5
            return code, "", f"Bootstrap failed: {code}: Input/output error\n"
        state["next_pid"] += 1
        jobs[label] = {
            "plist": plist,
            "keepalive": bool(data.get("KeepAlive")),
            "args": data["ProgramArguments"],
            "pid": state["next_pid"] if state["start_ok"] else None,
            "dying": 0,
        }
        return 0, "", ""
    if verb == "bootout":
        label = label_of(rest[0])
        job = jobs.get(label)
        if job is None:
            return 3, "", "Boot-out failed: 3: No such process\n"
        if job["dying"]:
            return 36, "", "Boot-out failed: 36: Operation now in progress\n"
        if state["bootout_lag"]:
            job["dying"] = state["bootout_lag"]
            return state["bootout_code"], "", ""
        del jobs[label]
        return 0, "", ""
    if verb == "print":
        label = label_of(rest[0])
        job = jobs.get(label)
        if job is None:
            return (
                113,
                "",
                f'Bad request.\nCould not find service "{label}" in domain for user gui: 501\n',
            )
        text = render(label, job)
        if job["dying"]:
            job["dying"] -= 1
            if not job["dying"]:
                del jobs[label]
        return 0, text, ""
    if verb == "kickstart":
        label = label_of(rest[-1])
        job = jobs.get(label)
        if job is None:
            return 113, "", f'Could not find service "{label}" in domain for user gui: 501\n'
        state["next_pid"] += 1
        job["pid"] = state["next_pid"]
        return 0, "", ""
    if verb == "list":
        rows = ["PID\tStatus\tLabel"]
        rows += [f"{job['pid'] or '-'}\t0\t{label}" for label, job in jobs.items()]
        return 0, "\n".join(rows) + "\n", ""
    return 64, "", f"stub launchctl: unsupported arguments {args}\n"


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
