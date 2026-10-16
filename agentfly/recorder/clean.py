"""Clean shell commands before storage (SPEC section 4). Pure, no network."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from urllib.parse import urlparse

# On by default. Set CLEAN_COMMANDS=0|false|no|off to store raw commands (unsafe).
CLEAN_COMMANDS: bool = os.environ.get("CLEAN_COMMANDS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

_WEB_TOOLS: frozenset[str] = frozenset({"curl", "wget", "nc", "scp", "ssh", "rsync"})

# A long option name is kept only if it looks like a name; anything else may be a value.
_LONG_OPTION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
# A program name made of anything else (spaces, quotes, `$`) may be part of a secret.
_PROGRAM_NAME = re.compile(r"[\w./+-]+")


def command_for_storage(cmd: str, project_root: Path) -> str:
    """Return cleaned command when CLEAN_COMMANDS is on; otherwise raw cmd."""
    if not CLEAN_COMMANDS:
        return cmd
    return clean_command(cmd, project_root)


def clean_command(cmd: str, project_root: Path) -> str:
    """Redact secrets from a shell command for safe storage."""
    stripped: str = cmd.strip()
    if not stripped:
        return ""

    if _needs_unparsed(stripped):
        return f"{_first_program(stripped)} <unparsed>"

    parts: list[tuple[str, str]] = _split_keeping_seps(stripped)
    cleaned_bits: list[str] = []
    for text, sep in parts:
        cleaned_bits.append(_clean_segment(text.strip(), project_root))
        if sep:
            cleaned_bits.append(f" {sep} ")
    return "".join(cleaned_bits).strip()


def _needs_unparsed(cmd: str) -> bool:
    if "`" in cmd or "$(" in cmd or "<<" in cmd:
        return True
    return not _quotes_balanced(cmd)


def _quotes_balanced(cmd: str) -> bool:
    in_single: bool = False
    in_double: bool = False
    i: int = 0
    while i < len(cmd):
        ch: str = cmd[i]
        if ch == "\\" and in_double:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        i += 1
    return not in_single and not in_double


def _is_env_assign(token: str) -> bool:
    if "=" not in token or token.startswith("-"):
        return False
    name: str = token.split("=", 1)[0]
    if not name or not name[0].isalpha() and name[0] != "_":
        return False
    return all(c.isalnum() or c == "_" for c in name)


def _rough_tokens(cmd: str) -> list[str]:
    """Split on whitespace, | ; & outside quotes. Tolerates unbalanced quotes; keeps quotes."""
    tokens: list[str] = []
    buf: list[str] = []
    quote: str = ""
    i: int = 0
    while i < len(cmd):
        ch: str = cmd[i]
        if ch == "\\" and quote == '"' and i + 1 < len(cmd):
            buf.append(cmd[i : i + 2])
            i += 2
            continue
        if ch in {"'", '"'} and quote in {"", ch}:
            quote = "" if quote else ch
        elif not quote and (ch.isspace() or ch in "|;&"):
            if buf:
                tokens.append("".join(buf))
                buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def _first_program(cmd: str) -> str:
    for token in _rough_tokens(cmd):
        if _is_env_assign(token.split("=", 1)[0] + "=") and "=" in token:
            continue  # a quoted value stays inside its token, so no part of it is read
        bare: str = token.strip("'\"")
        name: str = Path(bare).name or bare
        return name if _PROGRAM_NAME.fullmatch(name) else "cmd"
    return "cmd"


def _split_keeping_seps(cmd: str) -> list[tuple[str, str]]:
    """Split on |, &&, ||, ; outside quotes; return (segment, following_sep)."""
    segments: list[tuple[str, str]] = []
    buf: list[str] = []
    in_single: bool = False
    in_double: bool = False
    i: int = 0
    while i < len(cmd):
        ch: str = cmd[i]
        if ch == "\\" and in_double:
            buf.append(ch)
            if i + 1 < len(cmd):
                buf.append(cmd[i + 1])
                i += 2
                continue
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            if cmd.startswith("||", i) or cmd.startswith("&&", i):
                sep: str = cmd[i : i + 2]
                segments.append(("".join(buf), sep))
                buf = []
                i += 2
                continue
            if ch in {"|", ";"}:
                segments.append(("".join(buf), ch))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    segments.append(("".join(buf), ""))
    return segments


def _clean_segment(segment: str, project_root: Path) -> str:
    if not segment:
        return ""
    try:
        tokens: list[str] = shlex.split(segment)
    except ValueError:
        return f"{_first_program(segment)} <unparsed>"

    out: list[str] = []
    idx: int = 0
    while idx < len(tokens) and _is_env_assign(tokens[idx]):
        name: str = tokens[idx].split("=", 1)[0]
        out.append(f"{name}=<removed>")
        idx += 1

    if idx >= len(tokens):
        return " ".join(out)

    program: str = tokens[idx]
    out.append(program)
    prog_base: str = Path(program).name.lower()
    web_tool: bool = prog_base in _WEB_TOOLS
    idx += 1

    while idx < len(tokens):
        word: str = tokens[idx]
        out.append(_classify_word(word, project_root, web_tool=web_tool))
        idx += 1

    return " ".join(out)


def _classify_word(word: str, project_root: Path, *, web_tool: bool) -> str:
    # (1) options: keep names, drop values, also a value stuck onto its option (-pSECRET)
    if word.startswith("--"):
        name: str = word[2:].split("=", 1)[0]
        if word == "--":
            return word
        if not _LONG_OPTION_NAME.fullmatch(name):
            return "<arg>"
        return f"--{name}=<arg>" if "=" in word else word
    if word.startswith("-") and word != "-":
        # -pX and -la look alike, so a cluster keeps only its first letter.
        return word if len(word) == 2 else f"{word[:2]}<arg>"

    # (2) web address
    if "://" in word or web_tool:
        site: str | None = _website_name(word)
        if site is not None:
            return site
        if "://" in word:
            return "<arg>"

    # (3) existing file inside project_root
    rel: str | None = _project_relative(word, project_root)
    if rel is not None:
        return rel

    # (4) everything else
    return "<arg>"


def website_name(word: str) -> str | None:
    """Public alias for host extraction from a command token."""
    return _website_name(word)


def _website_name(word: str) -> str | None:
    host: str | None = None
    if "://" in word:
        try:
            host = urlparse(word).hostname
        except ValueError:  # e.g. an unbalanced [ in the address
            return None
    else:
        # scp/rsync user@host:path
        candidate: str = word
        if "@" in candidate:
            candidate = candidate.rsplit("@", 1)[-1]
        if ":" in candidate and not candidate.startswith("["):
            # host:path or host:port — prefer left side if it looks like a name
            left: str = candidate.split(":", 1)[0]
            if left and "/" not in left:
                candidate = left
        # strip path-like suffix
        candidate = candidate.split("/")[0]
        if candidate and ("." in candidate or candidate == "localhost"):
            host = candidate

    if host is None or host == "":
        return None

    reduced: str = _reduce_host_labels(host)
    if _host_looks_encoded(reduced):
        return None
    return reduced


def _label_triggers_reduction(label: str) -> bool:
    if len(label) > 30:
        return True
    if len(label) >= 16 and any(c.isalpha() for c in label) and any(c.isdigit() for c in label):
        return True
    return False


def _reduce_host_labels(host: str) -> str:
    parts: list[str] = host.split(".")
    if len(parts) >= 3 and any(_label_triggers_reduction(p) for p in parts):
        return ".".join(parts[-2:])
    return host


def _host_looks_encoded(host: str) -> bool:
    return any(_label_triggers_reduction(p) for p in host.split("."))


def _project_relative(word: str, project_root: Path) -> str | None:
    root: Path = project_root.resolve()
    raw: Path = Path(word)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(root / raw)

    for cand in candidates:
        try:
            resolved: Path = cand.resolve()
        except OSError:
            continue
        try:
            rel: Path = resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.exists():
            return rel.as_posix()
    return None
