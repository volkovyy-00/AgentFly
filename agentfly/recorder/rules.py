"""Rule engine: mark sessions and decide allow/block (pure checks)."""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from agentfly.recorder import DEFAULT_PORT
from agentfly.recorder.names import host_of, is_local_host, is_sensitive
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


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    message: str
    check: Callable[[Action, Session], bool]


def _looks_like_host_token(token: str) -> str | None:
    """Return a hostname if token looks like a URL, host:path, or bare host.

    Also finds a URL glued to an option: `--url=https://host`, `--url=host`, `-d@https://host`.
    """
    if "://" in token:
        return host_of("//" + token.split("://", 1)[1])
    if token.startswith("-") and "=" in token:
        return _looks_like_host_token(token.split("=", 1)[1])

    # scp/rsync style user@host:path or host:path (not a bare flag)
    if ":" in token and not token.startswith("-"):
        left: str = token.split(":", 1)[0]
        if "@" in left:
            left = left.rsplit("@", 1)[-1]
        # Avoid treating port-only or Windows drives; require a hostname-ish left.
        if left and not left.isdigit() and "/" not in left:
            return left

    # bare hostname / IP (wget x.com, nc x.com 80, ssh x.com)
    if token.startswith("-") or "/" in token or "=" in token:
        return None
    if "." in token or token in {"localhost"} or token.count(":") >= 1:
        # IPv6 or dotted name; reject pure numbers
        if token.replace(".", "").isdigit():
            return token  # IPv4
        if any(c.isalpha() for c in token) or ":" in token:
            return token
    return None


def _hosts_in_command(argv: Iterable[str]) -> list[str]:
    found: list[str] = []
    for token in argv:
        host: str | None = _looks_like_host_token(token)
        if host is not None:
            found.append(host)
    return found


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
        hosts: list[str] = _hosts_in_command(argv)
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
# `/Library/Application Support/Cursor/hooks.json` (and a bare name after a `cd`).
_R0_PATHS: tuple[str, ...] = (
    ".config/agentfly",
    ".local/share/agentfly",
    "/library/application support/agentfly",
    "hooks.json",
)
_R0_SUBCOMMANDS: frozenset[str] = frozenset({"serve", "stop", "uninstall", "wipe"})
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


def _r0_command_hit(argv: tuple[str, ...]) -> bool:
    """`agentfly serve|stop|uninstall|wipe`, `brew services`, `launchctl`, `pkill`, `kill`."""
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
    if any(_r0_command_hit(argv) for argv in parsed.all_commands()):
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
