"""Clean shell commands before storage (SPEC section 4). Pure, no network."""

from __future__ import annotations

import os
import posixpath
import re
import shlex
import stat
from functools import cached_property
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
# What the words of one command may cost the file system (V5d): a step for each `lstat` and each
# `readlink` that is not answered from what the hook already learned. Measured on the author's
# Mac, a call takes 4.6 us on a short path and 8.5 us on one of 753 characters, so the price is
# per call. A test pins the number.
LOOKUP_STEPS: int = 4_000
# A word's links are followed at most this often (the system's own limit is near it).
MAX_LINK_HOPS: int = 32

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


def clean_command(cmd: str, project_root: Path, lookups: Lookups | None = None) -> str:
    """Redact secrets from a shell command for safe storage.

    `lookups` is the hook's budget of file-system look-ups; the caller that goes on to ask more
    about the same words (the step record) passes the one it also uses. Without one the command
    gets a budget of its own.
    """
    stripped: str = cmd.strip()
    if not stripped:
        return ""

    if _needs_unparsed(stripped):
        return f"{_first_program(stripped)} <unparsed>"

    disk: Lookups = lookups if lookups is not None else Lookups(project_root)
    parts: list[tuple[str, str]] = _split_keeping_seps(stripped)
    cleaned_bits: list[str] = []
    for text, sep in parts:
        cleaned_bits.append(_clean_segment(text.strip(), disk))
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


def cleaned_words(command: str) -> list[str]:
    """The words of a cleaned command as `names.words` gives them (`shlex.split`, and a plain
    `split` when the quoting does not balance), at regular-expression speed: the cleaner already
    has the same words as `shlex.split`, and a command of 300 long paths takes `shlex` 0.35 s."""
    try:
        return _shell_words(command)
    except ValueError:
        return command.split()


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


def _clean_segment(segment: str, disk: Lookups) -> str:
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
        out.append(_classify_word(word, disk, web_tool=web_tool))
        idx += 1

    return " ".join(out)


def _classify_word(word: str, disk: Lookups, *, web_tool: bool) -> str:
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
    rel: str | None = disk.project_relative(word)
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


def _folded(text: str) -> str:
    """An absolute path with `.` and `..` folded as text, no file system."""
    return posixpath.normpath("/" + text.lstrip("/"))  # normpath keeps a leading `//`


class _OverBudget(Exception):
    """The hook's look-ups are used up; the word being walked is not looked up."""


class Lookups:
    """The file-system look-ups of one hook's command words (V5d). One per hook, shared by the
    cleaner and the step record, so the words of a command spend one budget between them.

    A word is judged as text first, with no file-system call: joined to the root when it is
    relative, `.` and `..` folded, `~` not expanded, and tried against the root as sent and as
    resolved. A word outside both is outside; a link from outside that leads into the project does
    not make it inside. Only a word inside as text is walked: one `lstat` per part below the root,
    a link followed by its target's parts, a missing part ends the walk, and the end must still be
    inside the resolved root. It answers as `os.path.realpath(strict=True)` does (a test compares
    them). Each call is a step of the budget; a word that does not fit is left unresolved, which
    reads as "not a project file", so the record holds less, never more. What the walk learned
    (folders that are not links, links and their targets, each word's answer) is not asked again.
    """

    def __init__(self, project_root: Path, steps: int | None = None) -> None:
        self.left: int = LOOKUP_STEPS if steps is None else steps  # read now: a test lowers it
        self._project_root: Path = project_root
        self._sent: str | None = _folded(str(project_root)) if project_root.is_absolute() else None
        self._answers: dict[str, str | None] = {}
        self._plain: set[str] = set()  # paths seen to be no link (so every part above is a folder)
        self._links: dict[str, str] = {}

    def project_relative(self, word: str) -> str | None:
        """The word as a path inside the project when it names an existing file there, else None.
        Never raises; a word over `MAX_PATH_WORD` characters is not looked up."""
        if len(word) > MAX_PATH_WORD:
            return None
        if word not in self._answers:
            try:
                self._answers[word] = self._look_up(word)
            except _OverBudget:
                self._answers[word] = None
        return self._answers[word]

    def names_file(self, word: str) -> bool:
        return self.project_relative(word) is not None

    @cached_property
    def _root(self) -> str | None:
        """The resolved root, worked out once: None when the system cannot say or it is gone."""
        resolved: Path | None = resolved_or_none(self._project_root)
        if resolved is None:
            return None
        try:
            os.lstat(resolved)
        except (OSError, ValueError):
            return None
        self._plain.add(resolved.as_posix())
        return resolved.as_posix()

    def _look_up(self, word: str) -> str | None:
        root: str | None = self._root
        if root is None:
            return None
        absolute: bool = word.startswith("/")
        bases: tuple[str, ...] = (root,)
        if self._sent is not None and self._sent != root:
            bases = (self._sent, root)  # a word may sit in either
        if not any(
            contained_relative(_folded(word if absolute else f"{base}/{word}"), base) is not None
            for base in bases
        ):
            return None  # outside as text: never looked up
        # A word that starts with the root as typed walks from the resolved root, whose parts are
        # known; any other absolute word walks from `/`.
        start, rest = ("/", word) if absolute else (root, word)
        for base in bases if absolute else ():
            rel: str | None = contained_relative(word, base)
            if rel is not None:
                start, rest = root, rel
                break
        # Words in one folder share all but the last part: when the folder is already known to be
        # plain (no link above it), only the last part is looked at.
        head, _, leaf = f"{start.rstrip('/')}/{rest.lstrip('/')}".rpartition("/")
        if leaf not in ("", ".", "..") and (head or "/") in self._plain:
            start, rest = head or "/", leaf
        end: str | None = self._walk(start, rest.split("/"))
        return None if end is None else contained_relative(end, root)

    def _spend(self, steps: int) -> None:
        if self.left < steps:
            raise _OverBudget
        self.left -= steps

    def _walk(self, start: str, parts: list[str]) -> str | None:
        """The physical path `parts` lead to from `start`, or None when a part is missing or a
        call fails or there are too many links. Raises `_OverBudget` when the calls do not fit."""
        here: str = start
        pending: list[str] = parts[::-1]
        hops: int = 0
        while pending:
            name: str = pending.pop()
            if name in ("", "."):
                continue
            if name == "..":
                here = posixpath.dirname(here)
                continue
            path: str = f"{here}{name}" if here.endswith("/") else f"{here}/{name}"
            if path in self._plain:
                here = path
                continue
            target: str | None = self._links.get(path)
            if target is None:
                self._spend(1)
                try:
                    if not stat.S_ISLNK(os.lstat(path).st_mode):
                        self._plain.add(path)
                        here = path
                        continue
                    self._spend(1)
                    target = os.readlink(path)
                except (OSError, ValueError):
                    return None
                self._links[path] = target
            hops += 1
            if hops > MAX_LINK_HOPS:
                return None
            if target.startswith("/"):
                here = "/"
            pending.extend(target.split("/")[::-1])
        return here


def _project_relative(word: str, project_root: Path) -> str | None:
    """`Lookups.project_relative` for one word, with a budget of its own."""
    return Lookups(project_root).project_relative(word)
