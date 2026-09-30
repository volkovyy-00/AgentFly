"""Rule engine: mark sessions and decide allow/block (pure checks)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from recorder.names import host_of, is_local_host, is_sensitive, words

Action = dict[str, Any]

R1_MESSAGE: str = (
    "Blocked by rule R1: a secret was read earlier in this session, and now data is being sent out."
)

WATCH_ONLY: bool = False

# Tools that always count as outbound when marked (no local exception needed).
_ALWAYS_OUTBOUND: frozenset[str] = frozenset({"gh", "aws"})
# Tools that are outbound only when a non-local host appears in args.
_HOSTED_OUTBOUND: frozenset[str] = frozenset({"curl", "wget", "nc", "scp", "ssh", "rsync"})
_INTERPRETERS: frozenset[str] = frozenset({"python", "python3", "node"})


@dataclass
class Session:
    id: str
    marked: bool
    start_time: str
    next_step: int


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    message: str
    check: Callable[[Action, Session], bool]


def _looks_like_host_token(token: str) -> str | None:
    """Return a hostname if token looks like a URL, host:path, or bare host."""
    if "://" in token:
        return host_of(token)

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


def _hosts_in_command(cmd: str) -> list[str]:
    found: list[str] = []
    for token in words(cmd):
        host: str | None = _looks_like_host_token(token)
        if host is not None:
            found.append(host)
        # Also catch URL without needing full token parse
        if "://" in token:
            parsed_host: str | None = urlparse(token).hostname
            if parsed_host is not None and parsed_host not in found:
                found.append(parsed_host)
    return found


def is_outbound_send(action: Action) -> bool:
    """True if a shell command looks like sending data off-box."""
    if str(action.get("hook_event_name", "")) != "beforeShellExecution":
        return False
    cmd: str = str(action.get("command", ""))
    argv: list[str] = words(cmd)
    if not argv:
        return False

    lower_argv: list[str] = [a.lower() for a in argv]
    base_names: list[str] = [a.split("/")[-1].lower() for a in argv]

    if any(name in _ALWAYS_OUTBOUND for name in base_names):
        return True

    if "git" in base_names and "push" in lower_argv:
        return True

    if any(name in _INTERPRETERS for name in base_names) and "http" in cmd.lower():
        return True

    if any(name in _HOSTED_OUTBOUND for name in base_names):
        hosts: list[str] = _hosts_in_command(cmd)
        if not hosts:
            # Tool present but no host parsed — treat as outbound (safe for demo).
            return True
        return any(not is_local_host(h) for h in hosts)

    return False


def check_r1(action: Action, session: Session) -> bool:
    return session.marked and is_outbound_send(action)


RULES: list[Rule] = [
    Rule(id="R1", severity="block", message=R1_MESSAGE, check=check_r1),
]


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
        for token in words(cmd):
            if is_sensitive(token):
                return replace(session, marked=True)

    return session


def decide(action: Action, session: Session) -> tuple[str, str | None]:
    """Return (verdict, rule_id). Pure: does not mark. Call mark() first."""
    for rule in RULES:
        if rule.check(action, session):
            if WATCH_ONLY:
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
