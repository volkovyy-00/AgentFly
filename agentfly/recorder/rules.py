"""Rule engine: mark sessions and decide allow/block (pure checks)."""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from agentfly.recorder import DEFAULT_PORT
from agentfly.recorder.names import hosts_in_command, is_local_host, is_sensitive
from agentfly.recorder.normalize import SUB_PREFIX, Parsed, base_name, interpreter, normalize

Action = dict[str, Any]

R0_MESSAGE: str = (
    "Blocked by rule R0: this touches AgentFly's own files or controls the recorder, "
    "which only the owner may do."
)
R1_MESSAGE: str = (
    "Blocked by rule R1: a secret was read earlier in this session, and now data is being sent out."
)

WATCH_ONLY: bool = False

# R0 (SPEC section 5): the recorder's own process, as the kill check sees it. Tests patch these.
RECORDER_PID: int = os.getpid()
RECORDER_PPID: int = os.getppid()

# Tools that always count as outbound when marked (no local exception needed).
_ALWAYS_OUTBOUND: frozenset[str] = frozenset({"gh", "aws"})
# Tools that are outbound only when a non-local host appears in args.
_HOSTED_OUTBOUND: frozenset[str] = frozenset({"curl", "wget", "nc", "scp", "ssh", "rsync"})


@dataclass
class Session:
    id: str
    marked: bool
    start_time: str
    next_step: int
    # D21 A: the Task call that started this chat as a subagent, and the parent chat once known.
    parent_call: str = ""
    parent_id: str = ""
    # D21 fallback: the mark this chat inherited from its workspace holds until this time (epoch).
    inherited_until: float = 0.0
    # V5b: ids of the `after_then` rules (other than R1, whose trigger is `marked`) that fired in
    # this chat, and, per id, the time a trigger inherited through the workspace fallback ends.
    # `inherited_triggers` is replaced, never changed in place.
    triggers: frozenset[str] = frozenset()
    inherited_triggers: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    message: str
    check: Callable[[Action, Session], bool]


def _shell_command(action: Action) -> str | None:
    if str(action.get("hook_event_name", "")) != "beforeShellExecution":
        return None
    return str(action.get("command", ""))


def _argv_is_outbound(argv: tuple[str, ...]) -> bool:
    lower_argv: list[str] = [a.lower() for a in argv]
    base_names: list[str] = [base_name(a) for a in argv]

    if any(name in _ALWAYS_OUTBOUND for name in base_names):
        return True

    if "git" in base_names and "push" in lower_argv:
        return True

    if any(interpreter(name) for name in base_names) and any("http" in a for a in lower_argv):
        return True

    if any(name in _HOSTED_OUTBOUND for name in base_names):
        hosts: list[str] = hosts_in_command(argv)
        if not hosts:
            # Tool present but no host parsed — treat as outbound (safe for demo).
            return True
        return any(not is_local_host(h) for h in hosts)

    return False


def parsed_is_outbound(parsed: Parsed) -> bool:
    """SPEC section 5 'Blocking': unparseable text, code a shell reads, inline code, or a tool."""
    if parsed.unparsed or parsed.unquoted_heredoc or parsed.code_heredoc or parsed.one_liner:
        return True
    return any(_argv_is_outbound(argv) for argv in parsed.commands)


def is_outbound_send(action: Action) -> bool:
    """True if a shell command looks like sending data off-box (after normalisation)."""
    cmd: str | None = _shell_command(action)
    if cmd is None or not cmd.strip():
        return False
    return parsed_is_outbound(normalize(cmd))


def check_r1(action: Action, session: Session) -> bool:
    return session.marked and is_outbound_send(action)


# ---------------------------------------------------------------- R0: protect AgentFly itself

# Case-folded. `hooks.json` also covers `.cursor/hooks.json` in any folder and
# `/Library/Application Support/Cursor/hooks.json` (and a bare name after a `cd`). The last three
# are the recorder's launchd labels (its own, Homebrew's current and legacy): they name the service
# file in `~/Library/LaunchAgents` with or without `.plist`, which `defaults` adds on its own.
# The package `init -g` and `uninstall` run as root (V3c): its tool environment under `uv tool`,
# `pipx` and Homebrew (`site-packages/agentfly` also catches a `cd` first and a custom
# `UV_TOOL_DIR`), and the two entry scripts in `~/.local/bin` (`agentfly` and `agentfly-hook`).
# Running `~/.local/bin/agentfly status` by its full path is denied too; `agentfly status` is not.
# agentfly/hook_client.py `_GUARD_PATHS` is the same list.
_R0_PATHS: tuple[str, ...] = (
    ".config/agentfly",
    ".local/share/agentfly",
    "/library/application support/agentfly",
    "hooks.json",
    "dev.agentfly.recorder",
    "homebrew.mxcl.agentfly",
    "sh.brew.agentfly",
    "uv/tools/agentfly-recorder",
    "pipx/venvs/agentfly-recorder",
    "site-packages/agentfly",
    "/cellar/agentfly",
    "/homebrew/opt/agentfly",
    "/local/opt/agentfly",
    ".local/bin/agentfly",
)
_R0_SUBCOMMANDS: frozenset[str] = frozenset({"serve", "stop", "uninstall", "wipe"})
# `uv tool`, `pipx` and `brew` verbs that install, change or remove a tool (V3c). Denied when
# they could reach AgentFly: its name, a file or URL, a variable, or every tool at once.
_PACKAGE_VERBS: dict[str, frozenset[str]] = {
    "uv": frozenset({"install", "upgrade", "uninstall"}),
    "pipx": frozenset(
        {"install", "install-all", "upgrade", "upgrade-all", "reinstall", "reinstall-all"}
        | {"uninstall", "uninstall-all", "inject", "uninject", "runpip"}
    ),
    "brew": frozenset(
        {"install", "upgrade", "reinstall", "uninstall", "remove", "rm", "link", "unlink"}
    ),
}
_ARCHIVE_SUFFIXES: tuple[str, ...] = (".whl", ".tar.gz", ".tgz", ".zip")
# Options whose value is a Python, not a tool: `uv tool install --python /opt/x/python3 ruff`.
_PYTHON_OPTIONS: frozenset[str] = frozenset({"--python", "-p"})
# Programs that hand their input to a command as operands the text does not show.
_FEEDERS: frozenset[str] = frozenset({"xargs", "parallel"})
_EXEC_FLAGS: frozenset[str] = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_R0_KILLERS: frozenset[str] = frozenset({"pkill", "killall"})
_R0_RECORDER_WORDS: tuple[str, ...] = ("agentfly", "uvicorn", "recorder")
_PROCESS_LOOKUPS: tuple[str, ...] = ("pgrep", "pidof", "lsof", "ps", "fuser")
_R0_LOOKUPS: tuple[str, ...] = (*_PROCESS_LOOKUPS, "agentfly")
_PORT = re.compile(
    rf"(?<![a-z0-9])(?<!\d\.){DEFAULT_PORT}(?![a-z0-9])(?!\.\d)"
)  # D25; not inside a hex id
_INT = re.compile(r"-?\d+")
_LOOKUP = re.compile(rf"(?<![a-z0-9_])({'|'.join(_PROCESS_LOOKUPS)})(?![a-z0-9_])")


def _fold_path(text: str) -> str:
    """Case-folded text with `\\`, repeated `/` and `/./` removed (`Application\\ Support`)."""
    plain: str = text.casefold().replace("\\", "")
    while "//" in plain:
        plain = plain.replace("//", "/")
    return plain.replace("/./", "/")


def _path_forms(text: str) -> list[str]:
    """The text folded, and again with `..` resolved when it looks like a path."""
    forms: list[str] = [_fold_path(text)]
    if "/" in text and ".." in text:
        forms.append(_fold_path(posixpath.normpath(text)))
    return forms


def _could_be_agentfly(word: str, manager: str) -> bool:
    """An operand that is not a plain tool name: a file, a URL, a variable or a pattern."""
    if any(mark in word for mark in "$`*?{") or word.endswith(_ARCHIVE_SUFFIXES):
        return True
    if manager == "brew":  # `user/tap/formula` is a plain name to brew; a path or URL is not
        return word.startswith((".", "/", "~")) or "://" in word or word.endswith(".rb")
    return "/" in word or ":" in word or word.startswith(".")


def _package_command_hit(words: list[str], names: list[str], *, lossy: bool = False) -> bool:
    """`uv tool install --force dist/*.whl`, `pipx reinstall agentfly-recorder`, `brew upgrade`.

    `lossy`: the words come from text that could not be parsed, so an operand may have been lost
    (`brew upgrade $(x`); any such verb is then taken for aimed at AgentFly.
    """
    managers: list[int] = [i for i, name in enumerate(names) if name in _PACKAGE_VERBS]
    if not managers:
        return False
    # `echo x.whl | xargs uv tool install`, `find . -exec uv tool install {} \;`: operands unseen.
    lossy = lossy or any(n in _FEEDERS for n in names) or any(w in _EXEC_FLAGS for w in words)
    named: bool = any("agentfly" in w for w in words)
    end: int = len(words)
    for manager in {names[i] for i in managers}:
        verbs: frozenset[str] = _PACKAGE_VERBS[manager]
        # Tables read from the right, so each manager word costs O(1): a long command must not
        # keep R0 busy past the hook client's wait (it would then answer with the offline guard).
        verb_at, tool_at = [end] * (end + 1), [end] * (end + 1)
        all_from, operand_from, aimed_from = ([False] * (end + 1) for _ in range(3))
        for k in range(end - 1, -1, -1):
            word: str = words[k]
            operand: bool = not word.startswith("-") and (
                k == 0 or words[k - 1] not in _PYTHON_OPTIONS
            )
            verb_at[k] = k if word in verbs else verb_at[k + 1]
            tool_at[k] = k if word == "tool" else tool_at[k + 1]
            all_from[k] = all_from[k + 1] or word == "--all"
            operand_from[k] = operand_from[k + 1] or operand
            aimed_from[k] = aimed_from[k + 1] or (operand and _could_be_agentfly(word, manager))
        for index in (i for i in managers if names[i] == manager):
            start: int = index + 1
            if manager == "uv":
                if tool_at[start] == end:
                    continue
                start = tool_at[start] + 1
            at: int = verb_at[start]
            if at == end:
                continue
            if (
                lossy
                or named
                or words[at].endswith("-all")
                or all_from[start]
                or aimed_from[at + 1]
                or (words[at] == "upgrade" and not operand_from[at + 1])
            ):
                return True
    return False


def _r0_command_hit(argv: tuple[str, ...], *, lossy: bool = False) -> bool:
    """`agentfly serve|stop|uninstall|wipe`, `brew services`, `launchctl`, `pkill`, `kill`, and
    `uv tool`, `pipx` or `brew` installing, upgrading or removing a tool. `lossy`: the text could
    not be parsed, so these words are a plain scan of it."""
    words: list[str] = [w.casefold() for w in argv]
    names: list[str] = [base_name(w) for w in argv]
    for index, name in enumerate(names):
        if (name == "agentfly" or name.startswith("agentfly.")) and any(
            w in _R0_SUBCOMMANDS for w in words[index + 1 :]
        ):
            return True
    if "brew" in names and "services" in words:
        if any("agentfly" in w or w == "--all" for w in words):
            return True
    if "launchctl" in names and any("agentfly" in w for w in words):
        return True
    if _package_command_hit(words, names, lossy=lossy):
        return True
    if any(name in _R0_KILLERS for name in names):
        rest: list[str] = [w for w, n in zip(words, names, strict=True) if n not in _R0_KILLERS]
        if any(key in w for w in rest for key in _R0_RECORDER_WORDS):
            return True
    if "kill" in names:
        return _kill_hits_recorder(words, names.index("kill"))
    return False


def _kill_hits_recorder(words: list[str], at: int) -> bool:
    """`kill` of the recorder's PID, of every process (`0`, `-1`), or of something looked up."""
    own: set[int] = {RECORDER_PID} | ({RECORDER_PPID} if RECORDER_PPID > 1 else set())
    args: list[str] = words[at + 1 :]
    for position, arg in enumerate(args):
        if any(f"{SUB_PREFIX}{key}" in arg or f",{key}" in arg for key in _R0_LOOKUPS):
            return True
        if not _INT.fullmatch(arg):
            continue
        number: int = int(arg)
        if abs(number) in own or arg == "0":  # `kill -0 PID` only probes
            return True
        if number == -1 and position > 0:  # `kill -1 123` is SIGHUP, `kill -9 -1` is everything
            return True
    return False


def _action_paths(action: Action) -> list[str]:
    """Every file the action names: a Read, a Write or Edit (`tool_input`), an after-edit."""
    found: list[str] = []
    value: Any = action.get("file_path")
    if isinstance(value, str):
        found.append(value)
    tool_input: Any = action.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "target_file"):
            if isinstance(tool_input.get(key), str):
                found.append(tool_input[key])
    attachments: Any = action.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                found += [str(item[key]) for key in ("file_path", "path") if key in item]
            elif isinstance(item, str):
                found.append(item)
    return found


def check_r0(action: Action, session: Session) -> bool:  # noqa: ARG001 - a rule gets the session
    """AgentFly's own files and process: always, marked or not (SPEC section 5)."""
    texts: list[str] = list(_action_paths(action))
    cmd: str | None = _shell_command(action)
    if cmd is not None:
        texts.append(cmd)
        cwd: Any = action.get("cwd")
        if isinstance(cwd, str):
            texts.append(cwd)
    haystack: str = "\n".join(form for text in texts for form in _path_forms(text))
    if any(path in haystack for path in _R0_PATHS):
        return True
    if cmd is None:
        return False
    parsed: Parsed = normalize(cmd)
    # Word by word too: `~/.config/"agentfly"`, `$'..'`, `a/../.config/agentfly`.
    words: list[str] = [w for argv in parsed.all_commands() for w in argv]
    word_forms: str = "\n".join(form for w in words for form in _path_forms(w))
    if any(path in word_forms for path in _R0_PATHS):
        return True
    if _PORT.search(haystack) or _PORT.search(word_forms):
        return True
    if any(_r0_command_hit(argv, lossy=parsed.unparsed) for argv in parsed.all_commands()):
        return True
    if parsed.unparsed and _LOOKUP.search(cmd.casefold()):
        # Substitutions are lost in text that cannot be parsed: a `kill` next to a lookup is aimed.
        return any("kill" in {base_name(w) for w in argv} for argv in parsed.all_commands())
    return False


RULES: list[Rule] = [
    Rule(id="R0", severity="block", message=R0_MESSAGE, check=check_r0),
    Rule(id="R1", severity="block", message=R1_MESSAGE, check=check_r1),
]


def _names_secret(word: str) -> bool:
    """A word that is a sensitive file, or has one glued on: `--env-file=.env`, `-d@.env`."""
    return is_sensitive(word) or any(
        is_sensitive(part) for part in (word.rsplit("=", 1)[-1], word.rsplit("@", 1)[-1])
    )


def mark(action: Action, session: Session) -> Session:
    """Return session, marking if this action touches a sensitive file name."""
    if session.marked:
        return session

    event: str = str(action.get("hook_event_name", ""))
    if event == "beforeReadFile":
        path: str = str(action.get("file_path", ""))
        if path and is_sensitive(path):
            return replace(session, marked=True)

    if event == "beforeShellExecution":
        cmd: str = str(action.get("command", ""))
        for argv in normalize(cmd).all_commands():
            if any(_names_secret(word) for word in argv):
                return replace(session, marked=True)

    return session


def decide(action: Action, session: Session) -> tuple[str, str | None]:
    """Return (verdict, rule_id). Pure: does not mark. Call mark() first."""
    for rule in RULES:
        if rule.check(action, session):
            if WATCH_ONLY and rule.id != "R0":  # R0 cannot be switched down
                return ("warned", rule.id)
            return ("blocked", rule.id)
    return ("allow", None)


def deny_messages(rule_id: str) -> tuple[str, str]:
    """user_message, agent_message for a blocked rule."""
    message: str = R1_MESSAGE
    for rule in RULES:
        if rule.id == rule_id:
            message = rule.message
            break
    agent: str = f"{message} Do not retry with another tool or language. Stop and tell the user."
    return message, agent
