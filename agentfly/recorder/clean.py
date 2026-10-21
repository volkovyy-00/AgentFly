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
_PROGRAM_NAME = re.compile(r"[\w./+~-]+")
# `NAME=`, `NAME+=` and `NAME[i]=` set a variable; the index is dropped, it is not a name.
_ASSIGN_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]=]*\])?\+?")
# What a host written without a scheme may look like. A data argument (`token=a.b`, `hi a.com`)
# is not one.
_HOST_WORD = re.compile(r"[A-Za-z0-9._-]+")
# A word longer than this (in characters) is never looked up as a file (V5b-fix2 §5).
MAX_PATH_WORD: int = 1024

# The scans below read a command in C-speed regular expressions where the old loops read one
# character at a time in Python (V5b-fix2 §4.5); their answers are the same, character for
# character. A quoted run: single quotes hold everything up to the next `'`; in double quotes a
# backslash keeps the character after it.
_SINGLE: str = r"'[^']*+"
_DOUBLE: str = r'"[^"\\]*+(?:\\.[^"\\]*+)*+'
# A closed quoted run, or a quote that is never closed (it runs to the end).
_QUOTE_SCAN = re.compile(rf"""{_SINGLE}'|{_DOUBLE}"|['"]""", re.DOTALL)
# What `_split_keeping_seps` cuts on, and the quoted runs it skips (an unclosed one runs to the
# end, a lone backslash at the end with it).
_SPLIT_SCAN = re.compile(rf"""{_SINGLE}(?:'|\Z)|{_DOUBLE}(?:"|\\?\Z)|\|\||&&|[|;]""", re.DOTALL)
# `shlex.split` (POSIX, no comments) cuts words on these four characters only, not on every
# character `str.split` calls a space.
_SHELL_SPACE: str = " \t\r\n"
_PLAIN_WORD = re.compile(r"[^ \t\r\n]+")
# A whole word, then the space after it or the end.
_SHELL_WORD = re.compile(
    rf"""((?:[^ \t\r\n'"\\]++|\\.|{_SINGLE}'|{_DOUBLE}")++)(?:[ \t\r\n]++|\Z)""", re.DOTALL
)
# One piece of a whole shell word: a character after a backslash, the inside of a single- or
# double-quoted run, or plain text.
_WORD_PIECE = re.compile(
    r"""\\(.)|'([^']*+)'|"([^"\\]*+(?:\\.[^"\\]*+)*+)"|([^'"\\]++)""", re.DOTALL
)
# In double quotes a backslash goes only before `"` and before another backslash.
_DOUBLE_ESCAPE = re.compile(r'\\(["\\])')


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
    return all(len(run.group()) > 1 for run in _QUOTE_SCAN.finditer(cmd))


def _assign_name(token: str) -> str | None:
    """The variable name if the token is an assignment (`K=v`, `K+=v`, `K[i]=v`), else None."""
    if "=" not in token:
        return None
    match = _ASSIGN_NAME.fullmatch(token.split("=", 1)[0])
    return match.group(1) if match else None


def _is_env_assign(token: str) -> bool:
    return _assign_name(token) is not None


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
        if _is_env_assign(token):
            continue  # a quoted value stays inside its token, so no part of it is read
        bare: str = token.strip("'\"")
        name: str = Path(bare).name or bare
        return name if _PROGRAM_NAME.fullmatch(name) else "cmd"
    return "cmd"


def _split_keeping_seps(cmd: str) -> list[tuple[str, str]]:
    """Split on |, &&, ||, ; outside quotes; return (segment, following_sep)."""
    segments: list[tuple[str, str]] = []
    start: int = 0
    for found in _SPLIT_SCAN.finditer(cmd):
        sep: str = found.group()
        if sep[0] in "'\"":
            continue
        segments.append((cmd[start : found.start()], sep))
        start = found.end()
    segments.append((cmd[start:], ""))
    return segments


def _shell_words(segment: str) -> list[str]:
    """`shlex.split(segment)`, the same words. A segment that is not whole words (an unclosed
    quote, a backslash at the end) goes to `shlex.split`, which raises `ValueError` as before."""
    if not _has_quoting(segment):
        return _PLAIN_WORD.findall(segment)
    words: list[str] = []
    at: int = len(segment) - len(segment.lstrip(_SHELL_SPACE))
    while at < len(segment):
        found = _SHELL_WORD.match(segment, at)
        if found is None:
            return shlex.split(segment)
        words.append(_unquote(found.group(1)))
        at = found.end()
    return words


def _has_quoting(text: str) -> bool:
    return "'" in text or '"' in text or "\\" in text


def _unquote(word: str) -> str:
    """A whole shell word's text as shlex gives it: the quotes go, a backslash outside quotes
    keeps the character after it, and one in double quotes goes only before `"` or `\\`."""
    if not _has_quoting(word):
        return word
    texts: list[str] = []
    for piece in _WORD_PIECE.finditer(word):
        text: str = piece.group(piece.lastindex or 0)
        texts.append(_DOUBLE_ESCAPE.sub(r"\1", text) if piece.lastindex == 3 else text)
    return "".join(texts)


def _clean_segment(segment: str, project_root: Path) -> str:
    if not segment:
        return ""
    try:
        tokens: list[str] = _shell_words(segment)
    except ValueError:
        return f"{_first_program(segment)} <unparsed>"

    out: list[str] = []
    idx: int = 0
    while idx < len(tokens) and (name := _assign_name(tokens[idx])) is not None:
        out.append(f"{name}=<removed>")
        idx += 1

    if idx >= len(tokens):
        return " ".join(out)

    program: str = tokens[idx]
    out.append(program if _PROGRAM_NAME.fullmatch(program) else "<arg>")
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
    if word == "--":
        return word
    if word.startswith("--"):
        name: str = word[2:].split("=", 1)[0]
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
        if word.startswith("@"):  # curl -d @file is a file, not a host
            return None
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
        if _HOST_WORD.fullmatch(candidate) and ("." in candidate or candidate == "localhost"):
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


def resolved_or_none(path: Path) -> Path | None:
    """`path.resolve()`, or None when the system cannot say: a part over its name limit, a lone
    surrogate or a NUL (`OSError`, `ValueError`), a link that leads back to itself
    (`RuntimeError`)."""
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def contained_relative(path: str, root: str) -> str | None:
    """`path` relative to `root`, both resolved and written with `/`, or None when it is outside.

    A string test: `Path.relative_to` is quadratic in the depth on Python 3.12. The root itself is
    ".". A root that already ends in "/" (the folder "/") is used as it is.
    """
    if path == root:
        return "."
    prefix: str = root if root.endswith("/") else root + "/"
    return path[len(prefix) :] if path.startswith(prefix) else None


def _project_relative(word: str, project_root: Path) -> str | None:
    """The word as a path inside the project when it names an existing file there, else None.

    Never raises (V5b-fix2 §5). A word over `MAX_PATH_WORD` characters is not looked up: it is
    cheap to refuse and costly to resolve, one system call per part.
    """
    if len(word) > MAX_PATH_WORD:
        return None
    root: Path | None = resolved_or_none(project_root)
    if root is None:
        return None
    raw: Path = Path(word)
    resolved: Path | None = resolved_or_none(raw if raw.is_absolute() else root / raw)
    if resolved is None:
        return None
    rel: str | None = contained_relative(resolved.as_posix(), root.as_posix())
    if rel is None:
        return None
    try:
        return rel if resolved.exists() else None
    except (OSError, ValueError):
        return None
