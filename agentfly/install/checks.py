"""The checks behind `agentfly doctor` (SPEC section 7, D1, D4, D5, D23, D24).

Each check looks at one thing and gives one finding: `ok`, `warn` or `fail` with a line of text;
`run_all` puts the check's name in front of it. A check that needs
something another check is already failing on (the hash record, the service file) answers
`warn "not checked: ..."`, so one fault turns one line to fail and not a column of them. Nothing
here changes anything.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

from agentfly.install import (
    InstallError,
    cursor,
    hooks_file,
    hookslog,
    installer,
    packages,
    records,
    service,
)
from agentfly.install.hooks_file import HookEntry
from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild, file_sha256, tree_digest
from agentfly.recorder import rulefile

Level = Literal["ok", "warn", "fail"]

# D24: events that can allow or deny an action. A hook on one of them in a file the agent can write
# runs next to ours. Claude Code's own names for them differ only in case (`PreToolUse`).
GATE_EVENTS: frozenset[str] = frozenset(
    {"pretooluse", "beforeshellexecution", "beforereadfile", "beforemcpexecution"}
)


class Finding(NamedTuple):
    level: Level
    text: str


@dataclass(frozen=True)
class Check:
    """A `doctor` line: the id is the function name (`check_hooks_log` is `hooks-log`)."""

    id: str
    level: Level
    text: str


def ok(text: str) -> Finding:
    return Finding("ok", text)


def warn(text: str) -> Finding:
    return Finding("warn", text)


def fail(text: str) -> Finding:
    return Finding("fail", text)


@dataclass(frozen=True)
class Context:
    layout: Layout
    build: PythonBuild
    source: Path  # the hook client this AgentFly ships
    home: Path
    search_path: list[str]
    own_script: Path | None  # the `agentfly` command of this install
    cursor_version: str | None
    state: service.State | None
    state_error: str
    environment: packages.Environment | None  # the tool environment this AgentFly runs from
    environment_error: str
    health: dict[str, Any] | None = None  # what the recorder's /health answers; None: nothing

    @property
    def version_is_listed(self) -> bool:
        """Whether Cursor's version is one AgentFly has verified; an unreadable one is not (D32)."""
        return self.cursor_version is not None and self.cursor_version in cursor.KNOWN_VERSIONS

    @property
    def valid_events(self) -> frozenset[str] | None:
        """What this Cursor version is checked against; None when AgentFly refuses it (D32)."""
        return cursor.accepted_events(self.cursor_version) if self.cursor_version else None


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
    try:
        environment: packages.Environment | None = packages.tool_environment()
        environment_error = ""
    except InstallError as exc:
        environment, environment_error = None, str(exc)
    return Context(
        layout=layout,
        build=build,
        source=source,
        home=home or Path.home(),
        search_path=os.get_exec_path() if search_path is None else search_path,
        own_script=default_own_script() if own_script is None else own_script,
        cursor_version=version,
        state=state,
        state_error=error,
        environment=environment,
        environment_error=environment_error,
        health=service.health(),
    )


def _not_checked(reason: str) -> Finding:
    return warn(f"not checked: {reason}")


# ---------------------------------------------------------------- the install itself (D1, D5)


def check_record(ctx: Context) -> Finding:
    record = records.read(ctx.layout)
    if record is None:
        return fail(f"no readable hash record at {ctx.layout.record}; run `agentfly init -g`")
    # The versions come from a file: `visible` keeps a control character off the terminal.
    return ok(
        packages.visible(
            f"hash record present (AgentFly {record.get('agentfly_version')}, "
            f"Cursor {record.get('cursor_version')})"
        )
    )


def check_python(ctx: Context) -> Finding:
    record = records.read(ctx.layout)
    if record is None:
        return _not_checked("no hash record")
    layout = ctx.layout
    try:
        recorded = record["python"]
        if not layout.interpreter.is_file():
            return fail(f"the bundled Python is missing: {layout.interpreter}")
        if file_sha256(layout.interpreter) != recorded["interpreter_sha256"]:
            return fail("the bundled Python's interpreter differs from the record")
        if tree_digest(layout.python_dir) != recorded["tree_sha256"]:
            return fail("files of the bundled Python differ from the record (changed)")
        pinned = recorded["archive_sha256"] != ctx.build.sha256
    except (KeyError, TypeError):
        return fail("the hash record has no Python entry; run `agentfly init -g`")
    if pinned:
        return warn("this AgentFly pins another Python build; run `agentfly init -g`")
    return ok("bundled Python matches the record")


def check_lock(ctx: Context) -> Finding:
    if not ctx.layout.system_root.is_dir():
        return _not_checked(f"{ctx.layout.system_root} is missing")
    problems = installer.lock_problems(ctx.layout, check_owner=True)
    if problems:
        more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
        return fail(f"{problems[0]}{more}")
    return ok("the bundled Python and hook client cannot be changed by your user")


def check_client(ctx: Context) -> Finding:
    layout = ctx.layout
    if not layout.client.is_file():
        return fail(
            f"the hook client {layout.client} is missing: Cursor blocks every action until "
            "`agentfly init -g` restores it (D5)"
        )
    record = records.read(layout)
    if record is None:
        return _not_checked("no hash record")
    try:
        recorded = record["client"]["sha256"]
    except (KeyError, TypeError):
        return fail("the hash record has no client entry; run `agentfly init -g`")
    actual = file_sha256(layout.client)
    if actual != recorded:
        return fail("the hook client differs from the record (changed since install)")
    if actual != file_sha256(ctx.source):
        return warn(
            "the installed hook client is older than this AgentFly's; run `agentfly init -g`"
        )
    return ok("the hook client matches the record")


def check_package(ctx: Context) -> Finding:
    """The package root runs on `init -g` and `uninstall` is what `init -g` hashed (V3c)."""
    record = records.read(ctx.layout)
    if record is None:
        return _not_checked("no hash record")
    if ctx.environment is None:
        return _not_checked(ctx.environment_error)
    if packages.stored_from(record) is None:
        return fail("the hash record has no package hashes; run `agentfly init -g`")
    check = packages.inspect(ctx.environment, record)
    if check.problems:
        fix = packages.advice(check)
        return fail(f"{packages.lead(check.problems)}; {fix}, then run `agentfly init -g`")
    if check.changes:
        return warn(f"{packages.lead(check.changes)}; run `agentfly init -g` to record it")
    return ok(f"AgentFly and its {len(check.distributions) - 1} dependencies match the record")


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


def check_hooks(ctx: Context) -> Finding:
    found = _our_entries(ctx)
    if isinstance(found, str):
        return fail(f"{found}; Cursor loads none of AgentFly's hooks")
    # An entry on an event Cursor does not know is the `events` line's finding, not this one's.
    valid = ctx.valid_events
    considered = [entry for entry in found if valid is None or entry.event in valid]
    wanted = installer.desired_entries(ctx.layout)
    if hooks_file.same_entries(considered, wanted):
        return ok(f"{len(wanted)} entries, as `agentfly init -g` wrote them")
    missing, extra = set(wanted) - set(considered), set(considered) - set(wanted)
    parts = []
    if missing:
        parts.append(f"missing or changed: {_names(missing)}")
    if extra:
        parts.append(f"unexpected: {_names(extra)}")
    return fail(f"AgentFly's entries in {ctx.layout.hooks_file} differ ({'; '.join(parts)})")


def check_events(ctx: Context) -> Finding:
    found = _our_entries(ctx)
    if isinstance(found, str):
        return _not_checked("no readable AgentFly entries")
    if not found:
        return warn("no AgentFly entries are registered")
    if ctx.cursor_version is None:
        return _not_checked("cannot read the Cursor version")
    version = cursor.shown(ctx.cursor_version)
    verified = cursor.verified_as(ctx.cursor_version)
    if verified is None:
        return warn(
            f"Cursor {version} {cursor.refusal(ctx.cursor_version)}; "
            "its registered events could not be checked"
        )
    unknown = sorted({entry.event for entry in found} - cursor.KNOWN_VERSIONS[verified])
    if unknown:
        return fail(
            f"Cursor {version} does not accept {', '.join(unknown)}"
            f"{cursor.checked_against(ctx.cursor_version)}: it rejects the whole hooks file (D23)"
        )
    stand = cursor.stand_in(ctx.cursor_version)
    if stand:
        return warn(
            f"unchecked Cursor version: Cursor {version} is newer than the newest AgentFly has "
            f"checked ({stand}); its registered events are compared with {stand}'s. "
            f"{cursor.ADVICE}"
        )
    return ok(f"every registered event is accepted by Cursor {version}")


# ---------------------------------------------------------------- the service (D4, D8)


def check_service(ctx: Context) -> Finding:
    state = ctx.state
    if state is None:
        return fail(f"cannot read the service state: {ctx.state_error}")
    if state.agent_loaded:
        return fail(
            f"{state.manager.name} and AgentFly's own LaunchAgent {service.LABEL} are both loaded, "
            f"so two recorders fight over port {service.HEALTH_PORT}; run `agentfly start`, "
            "which removes ours"
        )
    if state.running:
        return ok(f"{state.manager.name}: {state.summary}")
    return fail(f"{state.manager.name}: {state.summary}; run `agentfly start`")


def check_service_file(ctx: Context) -> Finding:
    state = ctx.state
    if state is None:
        return _not_checked("the service state is unreadable")
    if state.manager.brew:
        return ok("the service file is Homebrew's")
    if state.plist_path is None:
        return _not_checked("there is no service file")
    if state.plist is None:
        return fail(f"{state.plist_path} cannot be read as a property list")
    # KeepAlive has its own line, so that turning it off fails one line.
    differing = [key for key in service.plist_drift(state.plist) if key != "KeepAlive"]
    if differing:
        return fail(
            f"{state.plist_path} differs from what `agentfly start` writes "
            f"({', '.join(differing)}); run `agentfly start`"
        )
    return ok("the service file is what `agentfly start` writes")


def check_keepalive(ctx: Context) -> Finding:
    state = ctx.state
    if state is None:
        return _not_checked("the service state is unreadable")
    if state.plist_path is None:
        if state.loaded:
            return fail("the service is loaded but has no service file")
        return warn("stopped: there is no service file")
    if state.plist is None:  # `service-file` reports the unreadable file
        return _not_checked("the service file cannot be read")
    if not state.keepalive:
        return fail(
            f"KeepAlive is not set in {state.plist_path}: a killed recorder stays down (D4)"
        )
    if state.live_keepalive is False:
        return warn("the loaded job has no KeepAlive although its file does; run `agentfly start`")
    return ok("KeepAlive is set: launchd restarts a killed recorder")


# ---------------------------------------------------------------- PATH and Cursor


def _shebang_python(script: Path) -> Path | None:
    try:
        with script.open("rb") as handle:
            first = handle.readline(300)
    except OSError:
        return None
    words = first[2:].decode("utf-8", errors="replace").split() if first.startswith(b"#!") else []
    return Path(words[0]) if words else None


def _environment(python: Path) -> Path:
    """The environment `python` runs in: its venv, else the installation it belongs to.

    A venv's `python` is a symlink to the base Python, so two venvs resolve to one interpreter.
    `pyvenv.cfg` beside the unresolved path (or in its parent) is what tells them apart.
    """
    for folder in (python.parent, python.parent.parent):
        if os.path.isfile(folder / "pyvenv.cfg"):
            return Path(os.path.realpath(folder))
    return Path(os.path.realpath(python))


def _is_ours(found: Path, ctx: Context) -> bool | None:
    """True or False when the command is provably ours or not, None when it cannot be told."""
    if ctx.own_script is not None and os.path.realpath(found) == os.path.realpath(ctx.own_script):
        return True
    interpreter = _shebang_python(found)
    if interpreter is not None and _environment(interpreter) == _environment(Path(sys.executable)):
        return True
    if ctx.own_script is None:
        return None
    # A wrapper script (Homebrew's `write_exec_script`) runs our command by its path.
    try:
        with found.open("rb") as handle:
            head = handle.read(4096)
    except OSError:
        return None
    return f"{ctx.own_script.parent}/".encode() in head


def check_path(ctx: Context) -> Finding:
    on_path = shutil.which("agentfly", path=os.pathsep.join(ctx.search_path))
    found = Path(on_path) if on_path else None
    if found is None:
        return warn("there is no `agentfly` on PATH (this run is from another place)")
    ours = _is_ours(found, ctx)
    if ours:
        return ok(f"`agentfly` on PATH is this install's ({found})")
    if ours is None:
        return warn(f"cannot tell whether `agentfly` on PATH ({found}) is ours")
    return fail(
        f"the first `agentfly` on PATH is {found}, not this install's; "
        "another program of that name (PyPI `agentfly`?) comes first"
    )


_SHOWN_LOG_LINE = 300  # a real line is about 100; the agent's user can write a megabyte


def _log_problem(status: hookslog.LogStatus, ours: set[str]) -> str | None:
    """Why one window's log says Cursor did not load our hooks, or None when it did."""
    if status.kind == "none":
        return "Cursor says: No enterprise hooks configuration found"
    if status.kind == "error":
        # Cut, and each unprintable character escaped: it is printed to the owner's terminal.
        line = status.detail[:_SHOWN_LOG_LINE] + (
            "\u2026" if len(status.detail) > _SHOWN_LOG_LINE else ""
        )
        return f"Cursor says: {packages.visible(line)}"
    absent = sorted(ours - set(status.steps))
    if absent:
        return f"Cursor loaded {len(status.steps)} hooks but not {', '.join(absent)}"
    return None


def _unconfirmed(ctx: Context, what: str) -> Finding:
    """A Hooks-log result that shows neither that Cursor loaded our hooks nor that it refused them.

    On a verified Cursor version it is a warning. On any other (newer, refused or unreadable: the
    agent can make the version unreadable) the log is the only sign that the hooks run (D32), so
    not being able to confirm it from the log fails.
    """
    if ctx.version_is_listed:
        return warn(what)
    if ctx.cursor_version is None:
        why = "AgentFly cannot read the Cursor version"
    else:
        version = cursor.shown(ctx.cursor_version)
        why = f"Cursor {version} is not on AgentFly's list of verified versions"
    return fail(
        f"{what}; {why}, so it cannot confirm that Cursor loaded its hooks. {cursor.ADVICE}"
    )


def check_hooks_log(ctx: Context) -> Finding:
    logs = hookslog.latest(ctx.home)
    if logs.folder is None:
        return _unconfirmed(ctx, "Cursor has no logs yet (has it been started?)")
    name = logs.folder.name
    if logs.too_many:
        return _unconfirmed(
            ctx,
            f"Cursor's newest log folder {name} holds more than {hookslog.MAX_LOGS} Hooks logs, "
            "and AgentFly reads none of them",
        )
    if not logs.files:
        return _unconfirmed(ctx, f"Cursor's newest log folder {name} has no Hooks log yet")
    ours = {entry.event for entry in installer.desired_entries(ctx.layout)}
    answered = False  # some log has a line about the system hooks
    problem: str | None = None  # why the first log that refused them did
    for path in logs.files:
        try:
            status = hookslog.status_of(hookslog.read_tail(path))
        except OSError:  # a pipe, a device or a folder among them is skipped, never waited on
            continue
        if status is not None:  # kept as a short verdict: a status can hold a whole 4 MiB line
            answered = True
            problem = problem or _log_problem(status, ours)
    if problem:
        return fail(f"Cursor did not load AgentFly's hooks ({problem}); quit and reopen Cursor")
    if answered:
        return ok(f"Cursor loaded AgentFly's {len(ours)} hooks ({name})")
    return _unconfirmed(ctx, f"no line about the system hooks in Cursor's Hooks log ({name})")


def check_claude_settings(ctx: Context) -> Finding:
    path = ctx.home / ".claude" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ok("no ~/.claude/settings.json")
    except (OSError, ValueError, RecursionError):  # the last: nested deeper than json allows
        return warn(f"{path} cannot be read as JSON")
    hooks = data.get("hooks") if isinstance(data, dict) else None
    gated = sorted(
        name
        for name, entries in (hooks.items() if isinstance(hooks, dict) else [])
        if name.casefold() in GATE_EVENTS and entries
    )
    if gated:
        return warn(
            f"{path} has hooks on {', '.join(gated)}; Cursor runs them next to AgentFly's, "
            "and the agent can write that file (D24)"
        )
    return ok("~/.claude/settings.json has no hooks on a gate event")


# ---------------------------------------------------------------- the rules file (D3, D10)


def check_rules(ctx: Context) -> Finding:
    """The active rules file: there, trusted, valid, and not refused by the running recorder.

    It reads the file as the recorder does (`load_active_file`, who owns it included). The only
    thing it learns from the running recorder is `/health.rules_problem`, which is there only
    when the recorder rejected the file at its start; it cannot see which rules the recorder
    holds, and a recorder that is down proves nothing either way, so it never fails this line.
    """
    path = ctx.layout.rules
    reported = ctx.health.get("rules_problem") if ctx.health else None
    if not os.path.lexists(path):
        return warn(
            f"{path} is missing, so the packaged default rules are in force; run `agentfly init -g`"
        )
    owner = ctx.layout.owner[0] if ctx.layout.owner is not None else None
    loaded = rulefile.load_active_file(path, owner)
    if loaded.errors:
        problem = rulefile.summary(loaded.errors)
        if reported:
            return fail(f"{path}: {problem}; the default rules are in force")
        if ctx.health is None:
            return fail(f"{path}: {problem}; the recorder will start on the default rules")
        return fail(
            f"{path}: {problem}; the running recorder still has the rules it read at its start "
            "and will use the default at its next start; fix the file, then restart it"
        )
    if reported:
        return fail(
            f"{path} is valid now, but the recorder started without it and runs the default "
            "rules; restart it (`agentfly stop`, `agentfly start`)"
        )
    if rulefile.is_older_default(loaded.sha256):  # the owner never edited it (D28)
        return warn(
            f"{path} is an older default than this version carries; run `agentfly init -g` to "
            "replace it, then restart the recorder"
        )
    return ok(f"{path}: {rulefile.rules_word(len(loaded.rules))}, plus R0, all valid")


CHECKS: list[Callable[[Context], Finding]] = [
    check_record,
    check_python,
    check_lock,
    check_client,
    check_rules,
    check_package,
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
        name = check.__name__.removeprefix("check_").replace("_", "-")
        try:
            results.append(Check(name, *check(ctx)))
        except Exception as exc:  # a check that blows up is a failed line, not a lost report
            results.append(
                Check(name, "fail", f"could not be checked: {type(exc).__name__}: {exc}")
            )
    return results
