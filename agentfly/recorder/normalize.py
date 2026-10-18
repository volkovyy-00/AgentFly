"""Pure shell-command normaliser: one parse that every rule reads (SPEC section 5, D10).

`normalize(text)` turns a command line into a flat list of simple commands (argv lists) with
quotes removed and everything that would run looked into: `$(...)`, backticks, `<(...)`,
`bash -c '...'`, `eval`, and the bodies of heredocs read by a shell. It also reports the three
things R1 treats as outbound by themselves: text it could not parse (`unparsed`), a quoted
heredoc or herestring that a shell or interpreter reads (`code_heredoc`), and inline code
(`one_liner`). Wrappers such as `env`, `sudo`, `xargs` or `timeout` need no list: every word
of every simple command is kept, wherever it stands.

No I/O, no shell is ever run, and `normalize` never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

MAX_DEPTH: int = 16  # nested $(...) / backticks / -c strings deeper than this count as unparsed

SHELLS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# A quoted heredoc is literal data unless one of these reads it (D10, narrowed 2026-10-16).
_READERS: frozenset[str] = frozenset({"ruby", "perl"})
_INTERPRETERS: tuple[str, ...] = ("python", "node")  # name prefixes: python3.12, nodejs
_SHELL_VALUE_OPTIONS: frozenset[str] = frozenset({"--rcfile", "--init-file"})

_PLAIN = re.compile(r"[^ \t\r\n;&|()<>\\'\"$`]+")
_SEPARATORS = str.maketrans(dict.fromkeys(";|&()`$\n\r\t\"'{},\\<>", " "))
_ANSI_SIMPLE: dict[str, str] = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}


@dataclass(frozen=True)
class Parsed:
    """The result of `normalize`.

    `commands` holds every simple command found, nesting flattened. `unparsed` means the grammar
    broke (an unbalanced quote or `$(`, a heredoc with no end, nesting too deep); `loose` is then
    a plain word scan of the raw text, so such text still shows its words. `unquoted_heredoc`
    (`<<EOF`) parses fine but R1 counts it as unparseable (D10). `code_heredoc` is a heredoc or
    herestring that a shell or interpreter reads.
    """

    commands: tuple[tuple[str, ...], ...]
    unparsed: bool = False
    unquoted_heredoc: bool = False
    code_heredoc: bool = False
    loose: tuple[tuple[str, ...], ...] = ()

    def all_commands(self) -> tuple[tuple[str, ...], ...]:
        """The parsed commands, plus the loose scan when the text could not be parsed."""
        return self.commands + self.loose if self.unparsed else self.commands

    @property
    def one_liner(self) -> bool:
        return any(has_inline_code(argv) for argv in self.commands)


def base_name(word: str) -> str:
    """Lower-case program name of a path-like word: '/usr/bin/Curl' -> 'curl'."""
    return word.rsplit("/", 1)[-1].casefold()


def interpreter(name: str) -> str | None:
    """'python' for python, python3, python3.12; 'node' for node, nodejs, node18; else None."""
    for family in _INTERPRETERS:
        rest: str = name.removeprefix(family)
        if rest != name and (not rest.strip("0123456789.") or (family == "node" and rest == "js")):
            return family
    return None


def is_reader(name: str) -> bool:
    """A shell or interpreter: it runs what a heredoc or herestring feeds it."""
    return name in SHELLS or name.rstrip("0123456789.") in _READERS or interpreter(name) is not None


def _python_one_liner(args: list[str]) -> bool:
    """`-c` in python's own options, found letter by letter (`-Sc`, `-c1`, `-X dev -c`)."""
    options = iter(args)
    for arg in options:
        if arg == "--" or not arg.startswith("-") or arg.startswith("-m"):
            return False  # the script (first plain word), `--`, or `python -m module`
        if arg.startswith("--"):
            if arg == "--check-hash-based-pycs":
                next(options, None)
            continue
        for index, letter in enumerate(arg[1:], 1):
            if letter == "c":
                return True
            if letter == "m":
                return False
            if letter in "WXQ":  # the rest of the word, or the next word, is its value
                if index == len(arg) - 1:
                    next(options, None)
                break
    return False


def _node_one_liner(args: list[str]) -> bool:
    """`-e`, `-p`, `--eval[=]`, `--print[=]` before node's script.

    Node has too many options that take a value to walk past them, so the options end at the
    first word that names a script file or at `--`.
    """
    for arg in args:
        if arg == "--" or arg.endswith((".js", ".mjs", ".cjs", ".ts")):
            return False
        if arg.startswith(("--eval", "--print")):
            return True
        if arg.startswith("-") and not arg.startswith("--") and arg[1:].isalpha():
            if "e" in arg[1:] or "p" in arg[1:]:
                return True
    return False


def has_inline_code(argv: tuple[str, ...] | list[str]) -> bool:
    """An inline one-liner anywhere in the command: `python -c`, `node -e` (SPEC section 9).

    Only the words after the interpreter are looked at, so the `-c` of `bash -c 'python3 x.py'`
    or of `python3 -m pytest -c cfg` is not taken for it.
    """
    args: list[str] = list(argv)
    for index, word in enumerate(args):
        family: str | None = interpreter(base_name(word))
        if family == "python" and _python_one_liner(args[index + 1 :]):
            return True
        if family == "node" and _node_one_liner(args[index + 1 :]):
            return True
    return False


def loose_commands(text: str) -> tuple[tuple[str, ...], ...]:
    """Plain word scan, one tuple per `;`, `|`, `&` or line: quotes and `$( ` only split words."""
    for escape in ("\\n", "\\r", "\\t"):  # `\n` written out inside JSON text
        text = text.replace(escape, "\n")
    out: list[tuple[str, ...]] = []
    for part in re.split(r"[;|&\n(`]", text):
        words: list[str] = part.translate(_SEPARATORS).split()
        if words:
            out.append(tuple(words))
    return tuple(out)


@dataclass
class _Heredoc:
    delimiter: str
    quoted: bool
    strip_tabs: bool
    owner: list[str]  # the words of the simple command that owns the redirect


class _Out:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.unparsed: bool = False
        self.unquoted_heredoc: bool = False
        self.code_heredoc: bool = False


class _Scanner:
    """One pass over `text`. Nested `$(...)` shares the position, so heredocs inside it work."""

    def __init__(self, text: str, out: _Out, depth: int) -> None:
        self.s: str = text
        self.n: int = len(text)
        self.i: int = 0
        self.out: _Out = out
        self.depth: int = depth

    # ------------------------------------------------------------ commands

    def parse_list(self, closer: str | None) -> bool:
        """Parse commands until `closer` (consumed) or the end. True if the closer was found."""
        s, n = self.s, self.n
        words: list[str] = []
        herestrings: list[str] = []
        heredocs: list[_Heredoc] = []

        def end_command() -> None:
            nonlocal words, herestrings
            if words:
                self.finish_command(words, herestrings)
            words, herestrings = [], []

        while self.i < n:
            c: str = s[self.i]
            if c == "\n":
                self.i += 1
                end_command()
                if heredocs:
                    self.read_bodies(heredocs, closer)
                    heredocs = []
                continue
            if c in " \t\r":
                self.i += 1
                continue
            if c == "\\" and s.startswith("\n", self.i + 1):
                self.i += 2
                continue
            if c == "#":  # a comment, since a word cannot start inside a word
                end: int = s.find("\n", self.i)
                self.i = n if end < 0 else end
                continue
            if c in ";&|" and not s.startswith("&>", self.i):
                end_command()
                self.i += 1
                while self.i < n and s[self.i] in ";&|":
                    self.i += 1
                continue
            if c == "(":
                end_command()
                self.i += 1
                continue
            if c == ")":
                end_command()
                self.i += 1
                if closer == ")":
                    if heredocs:
                        self.out.unparsed = True
                    return True
                continue
            if c in "<>&":
                self.redirect(words, herestrings, heredocs)
                continue
            word: str = self.word()
            if word.isdigit() and self.i < n and s[self.i] in "<>":
                continue  # the fd of `2>&1`
            words.append(word)
        end_command()
        if heredocs:
            self.out.unparsed = True  # a heredoc whose body never began
        return False

    def finish_command(self, words: list[str], herestrings: list[str]) -> None:
        self.out.commands.append(tuple(words))
        names: list[str] = [base_name(w) for w in words]
        reader: bool = any(is_reader(name) for name in names)
        if herestrings and reader:
            self.out.code_heredoc = True
        for index, name in enumerate(names):
            if name in SHELLS:
                script: str | None = shell_script(words[index + 1 :])
                if script is not None:
                    self.sub_scan(script)
                for text in herestrings:
                    self.sub_scan(text)
            elif name == "eval" and index + 1 < len(words):
                self.sub_scan(" ".join(words[index + 1 :]))

    def sub_scan(self, text: str) -> None:
        if self.depth >= MAX_DEPTH:
            self.out.unparsed = True
            return
        _Scanner(text, self.out, self.depth + 1).parse_list(None)

    def nested(self) -> str:
        """After `$(` or `<(`: parse to the matching `)`. Returns the placeholder word."""
        if self.depth >= MAX_DEPTH:
            self.out.unparsed = True
            self.i = self.n
            return "@sub@"
        before: int = len(self.out.commands)
        self.depth += 1
        found: bool = self.parse_list(")")
        self.depth -= 1
        if not found:
            self.out.unparsed = True
        return placeholder(self.out.commands[before:])

    # ------------------------------------------------------------ redirects, heredocs

    def redirect(self, words: list[str], herestrings: list[str], heredocs: list[_Heredoc]) -> None:
        s, n = self.s, self.n
        c: str = s[self.i]
        if c in "<>" and s.startswith("(", self.i + 1):  # process substitution: a word
            self.i += 2
            words.append(self.nested())
            return
        if s.startswith("<<<", self.i):
            self.i += 3
            self.skip_blanks()
            herestrings.append(self.word())
            return
        if s.startswith("<<", self.i):
            self.i += 2
            strip: bool = s.startswith("-", self.i)
            if strip:
                self.i += 1
            self.skip_blanks()
            delimiter, quoted = self.delimiter_word()
            if not delimiter:
                self.out.unparsed = True
                return
            heredocs.append(_Heredoc(delimiter, quoted, strip, words))
            return
        self.i += 1  # `>`, `>>`, `>&`, `<&`, `&>`, `>|`, `<>`: the target stays a word
        while self.i < n and s[self.i] in "<>&|":
            self.i += 1
        while s[self.i - 1 : self.i] == "&" and self.i < n and s[self.i] in "0123456789-":
            self.i += 1  # the fd of `>&2`

    def skip_blanks(self) -> None:
        while self.i < self.n and self.s[self.i] in " \t":
            self.i += 1

    def delimiter_word(self) -> tuple[str, bool]:
        """The heredoc delimiter with quotes removed; quoted if any part is quoted or escaped."""
        s, n = self.s, self.n
        parts: list[str] = []
        quoted: bool = False
        while self.i < n and s[self.i] not in " \t\n;&|()<>":
            c = s[self.i]
            if c == "\\":
                quoted = True
                if self.i + 1 < n:
                    parts.append(s[self.i + 1])
                self.i += 2
            elif c in "'\"":
                quoted = True
                end: int = s.find(c, self.i + 1)
                if end < 0:
                    self.out.unparsed = True
                    parts.append(s[self.i + 1 :])
                    self.i = n
                else:
                    parts.append(s[self.i + 1 : end])
                    self.i = end + 1
            else:
                parts.append(c)
                self.i += 1
        return "".join(parts), quoted

    def read_bodies(self, heredocs: list[_Heredoc], closer: str | None) -> None:
        for doc in heredocs:
            self.read_body(doc, closer)

    def read_body(self, doc: _Heredoc, closer: str | None) -> None:
        s, n = self.s, self.n
        names: list[str] = [base_name(w) for w in doc.owner]
        reader: bool = any(is_reader(name) for name in names)
        pos: int = self.i
        body: list[str] = []
        while True:
            if pos >= n:
                self.out.unparsed = True  # no terminator line
                self.i = n
                break
            end: int = s.find("\n", pos)
            line: str = s[pos:] if end < 0 else s[pos:end]
            lead: int = len(line) - len(line.lstrip("\t")) if doc.strip_tabs else 0
            probe: str = line[lead:].rstrip("\r")
            if probe == doc.delimiter:
                self.i = n if end < 0 else end + 1
                break
            if closer == ")" and probe.startswith(doc.delimiter):
                rest: str = probe[len(doc.delimiter) :]
                gap: int = len(rest) - len(rest.lstrip(" \t"))
                if rest[gap : gap + 1] == ")":  # `EOF)` closes the heredoc and the substitution
                    self.i = pos + lead + len(doc.delimiter) + gap
                    break
            body.append(line)
            pos = n if end < 0 else end + 1
        text: str = "\n".join(body)
        if not doc.quoted:
            self.out.unquoted_heredoc = True  # D10: counts as unparseable for R1
            self.expansions(text)  # the shell expands $(...) and backticks in the body
        if reader:
            self.out.code_heredoc = True  # D10: a quoted body is data unless something runs it
            if any(name in SHELLS for name in names):
                self.sub_scan(text)

    def expansions(self, body: str) -> None:
        """Parse the substitutions of an unquoted heredoc body, as inside double quotes."""
        if self.depth >= MAX_DEPTH:
            self.out.unparsed = True
            return
        quoted: str = body.replace('"', '\\"') + ' "'  # a `\` at the end must not eat the quote
        _Scanner(quoted, self.out, self.depth + 1).double_quoted()

    # ------------------------------------------------------------ words

    def word(self) -> str:
        s, n = self.s, self.n
        parts: list[str] = []
        while self.i < n:
            plain = _PLAIN.match(s, self.i)
            if plain is not None:
                parts.append(plain.group())
                self.i = plain.end()
                continue
            c: str = s[self.i]
            if c in " \t\r\n;&|()<>":
                break
            if c == "\\":
                if s.startswith("\n", self.i + 1):
                    self.i += 2
                elif self.i + 1 < n:
                    parts.append(s[self.i + 1])
                    self.i += 2
                else:
                    self.i += 1
            elif c == "'":
                end: int = s.find("'", self.i + 1)
                if end < 0:
                    self.out.unparsed = True
                    parts.append(s[self.i + 1 :])
                    self.i = n
                else:
                    parts.append(s[self.i + 1 : end])
                    self.i = end + 1
            elif c == '"':
                self.i += 1
                parts.append(self.double_quoted())
            elif c == "`":
                self.i += 1
                parts.append(self.backticks())
            elif s.startswith("$(", self.i):
                self.i += 2
                parts.append(self.nested())
            elif s.startswith("$'", self.i):
                self.i += 2
                parts.append(self.ansi_c())
            else:
                parts.append(c)
                self.i += 1
        return "".join(parts)

    def double_quoted(self) -> str:
        s, n = self.s, self.n
        parts: list[str] = []
        while self.i < n:
            c: str = s[self.i]
            if c == '"':
                self.i += 1
                return "".join(parts)
            if c == "\\" and self.i + 1 < n:
                nxt: str = s[self.i + 1]
                if nxt == "\n":
                    pass
                elif nxt in '$`"\\':
                    parts.append(nxt)
                else:
                    parts.append("\\" + nxt)
                self.i += 2
            elif s.startswith("$(", self.i):
                self.i += 2
                parts.append(self.nested())
            elif c == "`":
                self.i += 1
                parts.append(self.backticks())
            else:
                parts.append(c)
                self.i += 1
        self.out.unparsed = True  # no closing quote
        return "".join(parts)

    def backticks(self) -> str:
        """After an opening backtick: scan the body to the closing one and parse it."""
        s, n = self.s, self.n
        inner: list[str] = []
        while self.i < n:
            c: str = s[self.i]
            if c == "`":
                self.i += 1
                return self.parse_inner("".join(inner))
            if c == "\\" and self.i + 1 < n and s[self.i + 1] in "`\\$":
                inner.append(s[self.i + 1])
                self.i += 2
            else:
                inner.append(c)
                self.i += 1
        self.out.unparsed = True
        return self.parse_inner("".join(inner))

    def parse_inner(self, text: str) -> str:
        before: int = len(self.out.commands)
        self.sub_scan(text)
        return placeholder(self.out.commands[before:])

    def ansi_c(self) -> str:
        """After `$'`: decode C escapes, so `$'\\x63url'` is `curl`."""
        s, n = self.s, self.n
        parts: list[str] = []
        while self.i < n:
            c: str = s[self.i]
            if c == "'":
                self.i += 1
                return "".join(parts)
            if c != "\\" or self.i + 1 >= n:
                parts.append(c)
                self.i += 1
                continue
            nxt: str = s[self.i + 1]
            self.i += 2
            if nxt in _ANSI_SIMPLE:
                parts.append(_ANSI_SIMPLE[nxt])
            elif nxt in "xuU":
                width: int = {"x": 2, "u": 4, "U": 8}[nxt]
                digits: str = ""
                while self.i < n and len(digits) < width and s[self.i] in "0123456789abcdefABCDEF":
                    digits += s[self.i]
                    self.i += 1
                parts.append(_chr(int(digits, 16)) if digits else "\\" + nxt)
            elif nxt in "01234567":
                digits = nxt
                while self.i < n and len(digits) < 3 and s[self.i] in "01234567":
                    digits += s[self.i]
                    self.i += 1
                parts.append(_chr(int(digits, 8)))
            else:
                parts.append("\\" + nxt)
        self.out.unparsed = True
        return "".join(parts)


def _chr(code: int) -> str:
    try:
        return chr(code)
    except (ValueError, OverflowError):
        return "�"


def placeholder(inner: list[tuple[str, ...]]) -> str:
    """The word that stands for a substitution; it names the programs inside (R0 looks at it)."""
    names: list[str] = sorted({base_name(argv[0]) for argv in inner if argv})
    return "@sub:" + ",".join(names) + "@" if names else "@sub@"


def shell_script(args: list[str]) -> str | None:
    """The `-c` string among a shell's arguments, walking past its options; None if none.

    `-lc`, `-ec`, `-c` end the walk at the script. `-o name`, `-O name`, `--rcfile f` take a value.
    The first plain word is a script file, so the options end there.
    """
    index: int = 0
    while index < len(args):
        arg: str = args[index]
        if arg == "--" or not arg.startswith(("-", "+")):
            return None
        if arg.startswith("--"):
            index += 2 if arg in _SHELL_VALUE_OPTIONS else 1
            continue
        letters: str = arg[1:]
        if "c" in letters:
            return args[index + 1] if index + 1 < len(args) else None
        index += 2 if ("o" in letters or "O" in letters) else 1
    return None


@lru_cache(maxsize=16)  # mark, R0 and R1 parse the same command in one request
def normalize(text: str) -> Parsed:
    """Parse a shell command line. Never raises: trouble becomes `unparsed`."""
    out = _Out()
    try:
        _Scanner(text, out, 0).parse_list(None)
    except Exception:  # noqa: BLE001 - a rule must never lose its verdict to a parser bug
        out.unparsed = True
    loose: tuple[tuple[str, ...], ...] = ()
    if out.unparsed:
        loose = loose_commands(text)
    return Parsed(
        commands=tuple(out.commands),
        unparsed=out.unparsed,
        unquoted_heredoc=out.unquoted_heredoc,
        code_heredoc=out.code_heredoc,
        loose=loose,
    )
