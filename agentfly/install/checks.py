"""The checks behind `agentfly doctor` (SPEC section 7, D1, D4, D5, D23, D24).

Each check looks at one thing and gives one line: `ok`, `warn` or `fail`. A check that needs
something another check is already failing on (the hash record, the service file) answers
`warn "not checked: ..."`, so one fault turns one line to fail and not a column of them. Nothing
here changes anything.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agentfly.install import InstallError, cursor, hooks_file, hookslog, installer, records, service
from agentfly.install.hooks_file import HookEntry
from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild, file_sha256, tree_digest

Level = Literal["ok", "warn", "fail"]

# D24: events that can allow or deny an action. A hook on one of them in a file the agent can write
# runs next to ours. Claude Code's own names for them differ only in case (`PreToolUse`).
GATE_EVENTS: frozenset[str] = frozenset(
    {"pretooluse", "beforeshellexecution", "beforereadfile", "beforemcpexecution"}
)


@dataclass(frozen=True)
class Check:
    id: str
    level: Level
    text: str


@dataclass(frozen=True)
class Context:
    layout: Layout
    build: PythonBuild
    source: Path  # the hook client this AgentFly ships
    home: Path
    search_path: list[str]
    own_script: Path | None  # the `agentfly` command of this install
    own_python: Path
    cursor_version: str | None
    valid_events: frozenset[str] | None  # what that Cursor version accepts; None when unknown
    state: service.State | None
    state_error: str


def default_own_script() -> Path | None:
    script = Path(sys.executable).parent / "agentfly"
    return script if script.exists() else None


def build_context(
    layout: Layout,
    build: PythonBuild,
    source: Path,
    *,
    home: Path | None = None,
    search_path: list[str] | None = None,
    own_script: Path | None = None,
) -> Context:
    try:
        version: str | None = cursor.installed_version(layout.cursor_app)
    except InstallError:
        version = None
    state: service.State | None = None
    error = ""
    try:
        state = service.inspect()
    except InstallError as exc:
        error = str(exc)
    return Context(
        layout=layout,
        build=build,
        source=source,
        home=home or Path.home(),
        search_path=os.get_exec_path() if search_path is None else search_path,
        own_script=default_own_script() if own_script is None else own_script,
        own_python=Path(sys.executable),
        cursor_version=version,
        valid_events=cursor.KNOWN_VERSIONS.get(version) if version else None,
        state=state,
        state_error=error,
    )


def _not_checked(check_id: str, reason: str) -> Check:
    return Check(check_id, "warn", f"not checked: {reason}")


# ---------------------------------------------------------------- the install itself (D1, D5)


def check_record(ctx: Context) -> Check:
    record = records.read(ctx.layout)
    if record is None:
        return Check(
            "record",
            "fail",
            f"no readable hash record at {ctx.layout.record}; run `agentfly init -g`",
        )
    return Check(
        "record",
        "ok",
        f"hash record present (AgentFly {record.get('agentfly_version')}, "
        f"Cursor {record.get('cursor_version')})",
    )


def check_python(ctx: Context) -> Check:
    record = records.read(ctx.layout)
    if record is None:
        return _not_checked("python", "no hash record")
    layout = ctx.layout
    try:
        recorded = record["python"]
        if not layout.interpreter.is_file():
            return Check("python", "fail", f"the bundled Python is missing: {layout.interpreter}")
        if file_sha256(layout.interpreter) != recorded["interpreter_sha256"]:
            return Check(
                "python", "fail", "the bundled Python's interpreter differs from the record"
            )
        if tree_digest(layout.python_dir) != recorded["tree_sha256"]:
            return Check(
                "python", "fail", "files of the bundled Python differ from the record (changed)"
            )
        pinned = recorded["archive_sha256"] != ctx.build.sha256
    except (KeyError, TypeError):
        return Check(
            "python", "fail", "the hash record has no Python entry; run `agentfly init -g`"
        )
    if pinned:
        return Check(
            "python", "warn", "this AgentFly pins another Python build; run `agentfly init -g`"
        )
    return Check("python", "ok", f"bundled Python matches the record ({recorded['archive']})")


def check_lock(ctx: Context) -> Check:
    if not ctx.layout.system_root.is_dir():
        return _not_checked("lock", f"{ctx.layout.system_root} is missing")
    problems = installer.lock_problems(ctx.layout, check_owner=True)
    if problems:
        more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
        return Check("lock", "fail", f"{problems[0]}{more}")
    return Check("lock", "ok", "the bundled Python and hook client cannot be changed by your user")


def check_client(ctx: Context) -> Check:
    layout = ctx.layout
    if not layout.client.is_file():
        return Check(
            "client",
            "fail",
            f"the hook client {layout.client} is missing: Cursor blocks every action until "
            "`agentfly init -g` restores it (D5)",
        )
    record = records.read(layout)
    if record is None:
        return _not_checked("client", "no hash record")
    try:
        recorded = record["client"]["sha256"]
    except (KeyError, TypeError):
        return Check(
            "client", "fail", "the hash record has no client entry; run `agentfly init -g`"
        )
    actual = file_sha256(layout.client)
    if actual != recorded:
        return Check(
            "client", "fail", "the hook client differs from the record (changed since install)"
        )
    if actual != file_sha256(ctx.source):
        return Check(
            "client",
            "warn",
            "the installed hook client is older than this AgentFly's; run `agentfly init -g`",
        )
    return Check("client", "ok", "the hook client matches the record")


# ---------------------------------------------------------------- the hooks file (D2, D23)


def _our_entries(ctx: Context) -> list[HookEntry] | str:
    """Our entries in the system hooks file, or the reason there are none to read."""
    try:
        text = installer._read_hooks(ctx.layout)
    except InstallError as exc:
        return str(exc)
    if text is None:
        return f"{ctx.layout.hooks_file} does not exist"
    try:
        return hooks_file.our_entries(text, installer.prefix(ctx.layout))
    except InstallError as exc:
        return str(exc).removesuffix("; nothing was written")


def _names(entries: set[HookEntry]) -> str:
    return ", ".join(sorted({entry.event for entry in entries}))


def check_hooks(ctx: Context) -> Check:
    found = _our_entries(ctx)
    if isinstance(found, str):
        return Check("hooks", "fail", f"{found}; Cursor loads none of AgentFly's hooks")
    # An entry on an event Cursor does not know is the `events` line's finding, not this one's.
    valid = ctx.valid_events
    considered = [entry for entry in found if valid is None or entry.event in valid]
    wanted = installer.desired_entries(ctx.layout)
    if hooks_file.same_entries(considered, wanted):
        return Check("hooks", "ok", f"{len(wanted)} entries, as `agentfly init -g` wrote them")
    missing, extra = set(wanted) - set(considered), set(considered) - set(wanted)
    parts = []
    if missing:
        parts.append(f"missing or changed: {_names(missing)}")
    if extra:
        parts.append(f"unexpected: {_names(extra)}")
    return Check(
        "hooks",
        "fail",
        f"AgentFly's entries in {ctx.layout.hooks_file} differ ({'; '.join(parts)})",
    )


def check_events(ctx: Context) -> Check:
    found = _our_entries(ctx)
    if isinstance(found, str):
        return _not_checked("events", "no readable AgentFly entries")
    if not found:
        return Check("events", "warn", "no AgentFly entries are registered")
    if ctx.cursor_version is None:
        return _not_checked("events", "cannot read the Cursor version")
    if ctx.valid_events is None:
        known = ", ".join(sorted(cursor.KNOWN_VERSIONS))
        return Check(
            "events",
            "warn",
            f"Cursor {ctx.cursor_version} is not on AgentFly's verified list ({known}); "
            "its registered events could not be checked",
        )
    unknown = sorted({entry.event for entry in found} - ctx.valid_events)
    if unknown:
        return Check(
            "events",
            "fail",
            f"Cursor {ctx.cursor_version} does not accept {', '.join(unknown)}: it rejects the "
            "whole hooks file (D23)",
        )
    return Check(
        "events", "ok", f"every registered event is accepted by Cursor {ctx.cursor_version}"
    )


# ---------------------------------------------------------------- the service (D4, D8)


def check_service(ctx: Context) -> Check:
    state = ctx.state
    if state is None:
        return Check("service", "fail", f"cannot read the service state: {ctx.state_error}")
    if state.running:
        return Check("service", "ok", f"{state.manager.name}: {state.summary}")
    return Check("service", "fail", f"{state.manager.name}: {state.summary}; run `agentfly start`")


def check_service_file(ctx: Context) -> Check:
    state = ctx.state
    if state is None:
        return _not_checked("service-file", "the service state is unreadable")
    if state.manager.brew:
        return Check("service-file", "ok", "the service file is Homebrew's")
    if state.plist_path is None:
        return _not_checked("service-file", "there is no service file")
    if state.plist is None:
        return Check(
            "service-file", "fail", f"{state.plist_path} cannot be read as a property list"
        )
    # KeepAlive has its own line, so that turning it off fails one line.
    wanted, actual = service.expected_plist(), state.plist
    differing = sorted(
        key
        for key in wanted.keys() | actual.keys()
        if key != "KeepAlive" and wanted.get(key) != actual.get(key)
    )
    if differing:
        return Check(
            "service-file",
            "fail",
            f"{state.plist_path} differs from what `agentfly start` writes "
            f"({', '.join(differing)}); run `agentfly start`",
        )
    return Check("service-file", "ok", "the service file is what `agentfly start` writes")


def check_keepalive(ctx: Context) -> Check:
    state = ctx.state
    if state is None:
        return _not_checked("keepalive", "the service state is unreadable")
    if state.plist_path is None:
        if state.loaded:
            return Check("keepalive", "fail", "the service is loaded but has no service file")
        return Check("keepalive", "warn", "stopped: there is no service file")
    if not state.keepalive:
        return Check(
            "keepalive",
            "fail",
            f"KeepAlive is not set in {state.plist_path}: a killed recorder stays down (D4)",
        )
    if state.live_keepalive is False:
        return Check(
            "keepalive",
            "warn",
            "the loaded job has no KeepAlive although its file does; run `agentfly start`",
        )
    return Check("keepalive", "ok", "KeepAlive is set: launchd restarts a killed recorder")


# ---------------------------------------------------------------- PATH and Cursor


def _first_on_path(search_path: list[str]) -> Path | None:
    for folder in search_path:
        candidate = Path(folder) / "agentfly"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _shebang_python(script: Path) -> Path | None:
    try:
        with script.open("rb") as handle:
            first = handle.readline(300)
    except OSError:
        return None
    words = first[2:].decode("utf-8", errors="replace").split() if first.startswith(b"#!") else []
    return Path(words[0]) if words else None


def _is_ours(found: Path, ctx: Context) -> bool | None:
    """True or False when the command is provably ours or not, None when it cannot be told."""
    if ctx.own_script is not None and os.path.realpath(found) == os.path.realpath(ctx.own_script):
        return True
    interpreter = _shebang_python(found)
    if interpreter is None:
        return None if ctx.own_script is None else False
    return os.path.realpath(interpreter) == os.path.realpath(ctx.own_python)


def check_path(ctx: Context) -> Check:
    found = _first_on_path(ctx.search_path)
    if found is None:
        return Check(
            "path", "warn", "there is no `agentfly` on PATH (this run is from another place)"
        )
    ours = _is_ours(found, ctx)
    if ours:
        return Check("path", "ok", f"`agentfly` on PATH is this install's ({found})")
    if ours is None:
        return Check("path", "warn", f"cannot tell whether `agentfly` on PATH ({found}) is ours")
    return Check(
        "path",
        "fail",
        f"the first `agentfly` on PATH is {found}, not this install's; "
        "another program of that name (PyPI `agentfly`?) comes first",
    )


def check_hooks_log(ctx: Context) -> Check:
    folder, files = hookslog.latest(ctx.home)
    if folder is None:
        return Check("hooks-log", "warn", "Cursor has no logs yet (has it been started?)")
    if not files:
        return Check(
            "hooks-log", "warn", f"Cursor's newest log folder {folder.name} has no Hooks log yet"
        )
    ours = {entry.event for entry in installer.desired_entries(ctx.layout)}
    problems: list[str] = []
    loaded = 0
    for path in files:
        try:
            status = hookslog.status_of(hookslog.read_tail(path))
        except OSError:
            continue
        if status is None:
            continue
        if status.kind == "none":
            problems.append("Cursor says: No enterprise hooks configuration found")
        elif status.kind == "error":
            problems.append(f"Cursor says: {status.detail}")
        elif ours - set(status.steps):
            absent = ", ".join(sorted(ours - set(status.steps)))
            problems.append(f"Cursor loaded {len(status.steps)} hooks but not {absent}")
        else:
            loaded += 1
    if problems:
        return Check(
            "hooks-log",
            "fail",
            f"Cursor did not load AgentFly's hooks ({problems[0]}); quit and reopen Cursor",
        )
    if loaded:
        return Check(
            "hooks-log", "ok", f"Cursor loaded AgentFly's {len(ours)} hooks ({folder.name})"
        )
    return Check(
        "hooks-log", "warn", f"no line about the system hooks in Cursor's Hooks log ({folder.name})"
    )


def check_claude_settings(ctx: Context) -> Check:
    path = ctx.home / ".claude" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Check("claude-settings", "ok", "no ~/.claude/settings.json")
    except (OSError, ValueError):
        return Check("claude-settings", "warn", f"{path} cannot be read as JSON")
    hooks = data.get("hooks") if isinstance(data, dict) else None
    gated = sorted(
        name
        for name, entries in (hooks.items() if isinstance(hooks, dict) else [])
        if name.casefold() in GATE_EVENTS and entries
    )
    if gated:
        return Check(
            "claude-settings",
            "warn",
            f"{path} has hooks on {', '.join(gated)}; Cursor runs them next to AgentFly's, "
            "and the agent can write that file (D24)",
        )
    return Check("claude-settings", "ok", "~/.claude/settings.json has no hooks on a gate event")


CHECKS: list[Callable[[Context], Check]] = [
    check_record,
    check_python,
    check_lock,
    check_client,
    check_hooks,
    check_events,
    check_service,
    check_service_file,
    check_keepalive,
    check_path,
    check_hooks_log,
    check_claude_settings,
]


def run_all(ctx: Context) -> list[Check]:
    """Every check, in order. One that cannot run reports a failure; doctor goes on."""
    results: list[Check] = []
    for check in CHECKS:
        try:
            results.append(check(ctx))
        except (OSError, InstallError, ValueError) as exc:
            name = check.__name__.removeprefix("check_").replace("_", "-")
            results.append(
                Check(name, "fail", f"could not be checked: {type(exc).__name__}: {exc}")
            )
    return results
