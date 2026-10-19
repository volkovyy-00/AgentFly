"""A stand-in for /bin/launchctl that keeps its jobs in a JSON file (see tests/service_helpers.py).

Run as `python launchctl_stub.py <state file> <launchctl arguments>`. It knows the verbs the service
code uses and prints what the real tool printed on macOS 15.7 (`print` of a missing job exits 113,
`bootout` of a missing job exits 3, a loaded KeepAlive job shows `properties = keepalive | ...`).
`bootout_lag` makes a booted-out job linger for that many `print` calls, as launchd's teardown does,
and `bootout_code` is the exit code of the first `bootout` (Homebrew sees 36 while it is going).
`bootstrap_code`, when not 0, makes every `bootstrap` fail with that code. `disabled` lists labels
that `print-disabled` reports as switched off until `enable` is run for them.
"""

from __future__ import annotations

import sys

from stub_state import serve


def label_of(target: str) -> str:
    return target.rsplit("/", 1)[-1]


def render(label: str, job: dict) -> str:
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


def run(state: dict, args: list[str]) -> tuple[int, str, str]:
    jobs: dict[str, dict] = state["jobs"]
    verb, rest = (args[0] if args else ""), args[1:]
    if verb == "enable":
        label = label_of(rest[0])
        state["disabled"] = [name for name in state["disabled"] if name != label]
        return 0, "", ""
    if verb == "print-disabled":
        rows = ['\t\t"com.example.other" => enabled']
        rows += [f'\t\t"{name}" => disabled' for name in state["disabled"]]
        return 0, "\tdisabled services = {\n" + "\n".join(rows) + "\n\t}\n", ""
    if verb == "bootstrap":
        import plistlib

        plist = rest[-1]
        with open(plist, "rb") as handle:
            data = plistlib.load(handle)
        label = data["Label"]
        if label in jobs or state["bootstrap_code"]:
            code = state["bootstrap_code"] or 5
            return code, "", f"Bootstrap failed: {code}: Input/output error\n"
        state["next_pid"] += 1
        jobs[label] = {
            "plist": plist,
            "keepalive": bool(data.get("KeepAlive")),
            "args": data["ProgramArguments"],
            "pid": state["next_pid"],
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
    return 64, "", f"stub launchctl: unsupported arguments {args}\n"


if __name__ == "__main__":
    sys.exit(serve(run, sys.argv[1:]))
