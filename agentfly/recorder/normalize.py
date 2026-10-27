"""Pure shell-command normaliser: one parse that every rule reads (SPEC section 5, D10).

`normalize(text)` turns a command line into a flat list of simple commands (argv lists) with
quotes removed and everything that would run looked into: `$(...)`, backticks, `<(...)`,
`bash -c '...'`, `eval`, and the bodies of heredocs read by a shell. It also reports the three
things R1 treats as outbound by themselves: text it could not parse (`unparsed`), a quoted
heredoc or herestring that a shell or interpreter reads (`code_heredoc`), and inline code
(`one_liner`: a `-c`/`-e` one-liner, or code piped into an interpreter that names no script).
Wrappers such as `env`, `sudo`, `xargs` or `timeout` need no list: every word of every simple
command is kept, wherever it stands. Which command feeds which (pipes, substitutions, groups) is
kept in `links` (V5c).

No I/O, no shell is ever run, and `normalize` never raises.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

# The word that stands for a substitution; R0 reads the program names after the prefix.
SUB_PREFIX: str = "@sub:"
SUB_EMPTY: str = "@sub@"

MAX_SCANS: int = 256  # nested -c / eval / herestring scans in one command
MAX_DEPTH: int = 16  # nested $(...) / backticks / -c strings deeper than this count as unparsed
# Past this many links a line's links count as unknown (toward firing): groups nested in groups
# link a command once for each pipe around them, and the parse must stay within the client's wait.
MAX_LINKS: int = 20_000

SHELLS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh"})
# A quoted heredoc is literal data unless one of these reads it (D10, narrowed 2026-10-16).
_READERS: frozenset[str] = frozenset({"ruby", "perl"})
_INTERPRETERS: tuple[str, ...] = ("python", "node")  # name prefixes: python3.12, nodejs
_SHELL_VALUE_OPTIONS: frozenset[str] = frozenset({"--rcfile", "--init-file"})

_DQ_RUN = re.compile(r'[^"\\$`]+')  # plain text inside double quotes
_BT_RUN = re.compile(r"[^`\\]+")  # plain text inside backticks
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

    `links` (V5c) are the edges of "what this command writes, that one reads": (from, to), where a
    node is an index into `commands` or a hub (a negative number) that stands for one pipe. A pipe
    links each command of the part before it to its hub, and the hub to each command of the part
    after it (a part is everything between two operators: a group, a loop and the substitutions
    inside count). A substitution (`$(…)`, backticks, `<(…)`, in a herestring or a heredoc body)
    links each command inside it to the command it stands in; `>(…)` the other way. When the text
    can hide what feeds what (a function, `coproc`, an opener or closer that does not match, groups
    nested too deep), `links_unknown` says so. `piped_code` is code read from a pipe: a command fed
    by one (`programs` names an interpreter or a shell) that names no script (`reads_stdin`).
    """

    commands: tuple[tuple[str, ...], ...]
    unparsed: bool = False
    unquoted_heredoc: bool = False
    code_heredoc: bool = False
    loose: tuple[tuple[str, ...], ...] = ()
    # Not hashed (it is compared): a long line's links would make every cache look-up slow.
    links: tuple[tuple[int, int], ...] = field(default=(), hash=False)
    # For each command, the positions of its redirect targets (`2>/dev/null sh`: /dev/null).
    targets: tuple[frozenset[int], ...] = field(default=(), hash=False)
    links_unknown: bool = False
    piped_code: bool = False

    def all_commands(self) -> tuple[tuple[str, ...], ...]:
        """The parsed commands, plus the loose scan when the text could not be parsed."""
        return self.commands + self.loose if self.unparsed else self.commands

    @property
    def one_liner(self) -> bool:
        return self.piped_code or any(has_inline_code(argv) for argv in self.commands)


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


# What a one-liner walk does at one word of an interpreter's options: CODE (inline code, yes),
# END (the options end here, no), or how many words it moves on (2 when the word's option takes
# the next word as its value). A walk is these steps from the word after the interpreter's name.
_CODE: int = -1
_END: int = 0


def _python_step(arg: str) -> int:
    """`-c` in python's own options, found letter by letter (`-Sc`, `-c1`, `-X dev -c`)."""
    if arg == "--" or not arg.startswith("-") or arg.startswith("-m"):
        return _END  # the script (first plain word), `--`, or `python -m module`
    if arg.startswith("--"):
        return 2 if arg == "--check-hash-based-pycs" else 1
    for index, letter in enumerate(arg[1:], 1):
        if letter == "c":
            return _CODE
        if letter == "m":
            return _END
        if letter in "WXQ":  # the rest of the word, or the next word, is its value
            return 2 if index == len(arg) - 1 else 1
    return 1


def _node_stop(arg: str) -> bool:
    """`--` or a word that names a script file: node's options end there."""
    return arg == "--" or arg.endswith((".js", ".mjs", ".cjs", ".ts"))


def _node_code(arg: str) -> bool:
    """`-e`, `-p` (alone or clustered), `--eval[=]`, `--print[=]`."""
    if arg.startswith(("--eval", "--print")):
        return True
    letters: str = arg[1:]
    return (
        arg.startswith("-")
        and not arg.startswith("--")
        and letters.isalpha()
        and ("e" in letters or "p" in letters)
    )


def _node_step(arg: str) -> int:
    """Node has too many options that take a value to walk past them, so its options end at the
    first word that names a script file or at `--`, and a `-e`, `-p`, `--eval` or `--print`
    before that is code."""
    return _END if _node_stop(arg) else _CODE if _node_code(arg) else 1


def script_family(name: str) -> str | None:
    """'perl' for perl, perl5.34; 'ruby' for ruby, ruby3.2; else None (`perldoc` is neither)."""
    base: str = name.rstrip("0123456789.")
    return base if base in ("perl", "ruby") else None


# What `-M`, `-m`, `-d:` and `-dt:` may name in perl and still be a module (`Foo::Bar`, `-strict`,
# `Foo=a,b`); anything else is code perl runs (`-MIO::Socket;print 1`), V5c.
PERL_MODULE = re.compile(r"-?[A-Za-z_]\w*(?:::\w+)*(?:=[\w:]+(?:,[\w:]+)*)?", re.ASCII)


def _perl_value(arg: str, index: int) -> str | None:
    """The module a `-d:` or `-dt:` at `index` names, else None."""
    for lead in (":", "t:"):
        if arg.startswith(lead, index + 1):
            return arg[index + 1 + len(lead) :]
    return None


def _perl_step(arg: str) -> int:
    """`-e` or `-E` in perl's own options, found letter by letter (`-lane`, `-MIO::Socket -e`).

    `-M` and `-m` take the rest of their word (`-MIO::Socket` holds an `e`), as do `-d:` and
    `-dt:`, and that rest is code unless it is a module name (`PERL_MODULE`); `-I` takes the rest
    or, alone, the next word; a long option (`--version`) takes nothing. The script (the first
    plain word), `-` or `--` ends the options.
    """
    if arg in ("-", "--") or not arg.startswith("-"):
        return _END
    if arg.startswith("--"):
        return 1
    for index, letter in enumerate(arg[1:], 1):
        if letter in "eE":
            return _CODE
        if letter in "Mm":
            return 1 if PERL_MODULE.fullmatch(arg[index + 1 :]) else _CODE
        if letter == "I":
            return 2 if index == len(arg) - 1 else 1
        value: str | None = _perl_value(arg, index) if letter == "d" else None
        if value is not None:
            return 1 if PERL_MODULE.fullmatch(value) else _CODE
    return 1


# Ruby's long options that take the next word as their value (unless it is glued on with `=`).
_RUBY_VALUE_OPTIONS: frozenset[str] = frozenset(
    {
        "--enable",
        "--disable",
        "--dump",
        "--encoding",
        "--external-encoding",
        "--internal-encoding",
        "--backtrace-limit",
        "--parser",
        "--crash-report",
    }
)


def _ruby_step(arg: str) -> int:
    """`-e` in ruby's own options, found letter by letter (`-ne`, `-rnet/http -e`, `-We`).

    `-r`, `-I`, `-C`, `-X` and `-E` (an encoding, not code) take the rest of their word or, alone,
    the next word; `-x`, `-F`, `-i` and `-W:` take the rest of their word; `-K` takes one
    character (`-Ke` is a character set) and `-0`, `-T` and `-W` their digits, and the letters
    after those are options again (`-0e` is code). The script (the first plain word), `-` or `--`
    ends the options.
    """
    if arg in ("-", "--") or not arg.startswith("-"):
        return _END
    if arg.startswith("--"):
        return 2 if arg in _RUBY_VALUE_OPTIONS else 1
    index: int = 1
    while index < len(arg):
        letter: str = arg[index]
        index += 1
        if letter == "e":
            return _CODE
        if letter in "rICXE":
            return 2 if index == len(arg) else 1
        if letter in "xFi" or (letter == "W" and arg[index : index + 1] == ":"):
            return 1
        if letter == "K":
            index += 1
        elif letter in "0TW":
            while index < len(arg) and arg[index].isdigit():
                index += 1
    return 1


_STEPS: dict[str, Callable[[str], int]] = {
    "python": _python_step,
    "node": _node_step,
    "perl": _perl_step,
    "ruby": _ruby_step,
}


def _one_liner_table(args: Sequence[str], step: Callable[[str], int]) -> list[bool]:
    """For every position i: does a walk of these steps over `args[i:]` find code?

    Worked out once for the whole command, from the right, so each word is stepped on once
    however many interpreter names the command holds (`perl -I perl -I perl ...`, `-/ruby`): a
    walk from each name would read the rest again.
    """
    found: list[bool] = [False] * (len(args) + 2)
    for at in range(len(args) - 1, -1, -1):
        move: int = step(args[at])
        found[at] = move == _CODE or (move != _END and found[at + move])
    return found


def has_inline_code(argv: tuple[str, ...] | list[str]) -> bool:
    """An inline one-liner anywhere in the command: `python -c`, `node -e`, `perl -e`, `ruby -e`
    (SPEC sections 5 and 9).

    Only the words after the interpreter are looked at, so the `-c` of `bash -c 'python3 x.py'`
    or of `python3 -m pytest -c cfg` is not taken for it.
    """
    args: list[str] = list(argv)
    tables: dict[str, list[bool]] = {}  # `_one_liner_table`, one per family, made when needed
    for index, word in enumerate(args):
        name: str = base_name(word)
        family: str | None = interpreter(name) or script_family(name)
        if family is None:
            continue
        if family not in tables:
            tables[family] = _one_liner_table(args, _STEPS[family])
        if tables[family][index + 1]:
            return True
    return False


# ---------------------------------------------------------------- programs and piped code (V5c)

# The runners that start a tool from their own environment (`uv run python`, `bundle exec ruby`,
# `arch -arm64 python3`), and the words that may stand between one and the tool.
RUNNERS: frozenset[str] = frozenset(
    {"uv", "uvx", "arch", "xcrun", "bundle", "poetry", "pipenv", "pdm", "hatch", "conda"}
    | {"pyenv", "rbenv", "nodenv", "mise", "asdf", "npx", "pnpm", "yarn"}
)
RUNNER_VERBS: frozenset[str] = frozenset({"run", "exec", "x", "dlx", "tool"})
# Programs that run the words after them as a command (`sudo -u me bash`, `xargs -n1 sh`), the
# runners among them.
WRAPPERS: frozenset[str] = RUNNERS | frozenset(
    {"sudo", "doas", "env", "xargs", "parallel", "timeout", "gtimeout", "nice", "nohup"}
    | {"command", "builtin", "exec", "time", "stdbuf", "caffeinate", "script"}
)
_DURATION = re.compile(r"\d+(?:\.\d+)?[smhd]?")  # `timeout 5s`
# Shell words that stand before or around a command and are no program.
_KEYWORDS: frozenset[str] = frozenset(
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done", "esac"}
)
_HEADS: frozenset[str] = frozenset({"for", "select", "case"})  # their words are no command
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")


def programs(argv: Sequence[str], *, narrow: bool = False) -> tuple[int, ...]:
    """Where a program stands in a simple command: the first word after assignments and shell
    keywords, and, when that word is a wrapper (`WRAPPERS`), every word after it too. A `for`,
    `select` or `case` head has none. So `grep python3` has one (`grep`), `sudo -u me bash` all.

    `narrow` (piped code; owner 2026-10-23): a wrapper whose next word is plainly a program adds
    only that word, and so on down the chain; `env` and `sudo` assignments, `timeout`'s duration
    and a runner's verb (`uv run`) are skipped. An option there, or `parallel`, keeps every word.
    So `xargs grep -l node` has two (`xargs`, `grep`), `xargs -0 grep -l sh` all."""
    for index, word in enumerate(argv):
        if word in _KEYWORDS or _ASSIGNMENT.match(word):
            continue
        if word in _HEADS:
            return ()
        if base_name(word) not in WRAPPERS:
            return (index,)
        return _chain(argv, index) if narrow else tuple(range(index, len(argv)))
    return ()


def _chain(argv: Sequence[str], at: int) -> tuple[int, ...]:
    """`programs(narrow=True)` from the wrapper at `at`."""
    found: list[int] = [at]
    while (name := base_name(argv[at])) in WRAPPERS:
        if name == "parallel":
            return tuple(range(found[0], len(argv)))
        at += 1
        if name in ("timeout", "gtimeout") and at < len(argv) and _DURATION.fullmatch(argv[at]):
            at += 1
        while at < len(argv) and (
            (name in RUNNERS and argv[at] in RUNNER_VERBS)
            or (name in ("env", "sudo") and _ASSIGNMENT.match(argv[at]))
        ):
            at += 1
        if at >= len(argv):
            break
        if argv[at].startswith("-"):
            return tuple(range(found[0], len(argv)))
        found.append(at)
    return tuple(found)


def _stdin_family(name: str) -> str | None:
    """The family whose stdin walk reads this program: an interpreter, or "shell"."""
    if name.rstrip("0123456789.") in SHELLS:
        return "shell"
    return interpreter(name) or script_family(name)


_STDIN: int = -1  # a stdin walk ends here: the code comes from stdin
_SCRIPT: int = 0  # ... or a script is named
_DEV_FD = re.compile(r"/dev/fd/\d+")
# Node options that take the next word (unless glued on with `=`): a plain word after them is no
# script.
_NODE_VALUE_OPTIONS: frozenset[str] = frozenset(
    {"-r", "--require", "-C", "--conditions", "--import", "--loader", "--experimental-loader"}
    | {"--input-type", "--env-file", "--env-file-if-exists", "--title"}
)
_NODE_SCRIPT = re.compile(r"/|\.[cm]?[jt]s$")  # a word that looks like a script, not a value


def _is_stdin(word: str) -> bool:
    return word == "-" or _is_stdin_device(word)


def _is_stdin_device(word: str) -> bool:
    """`/dev/stdin` or `/dev/fd/N`: as a script or as `<`'s file, the code may be the pipe."""
    return word == "/dev/stdin" or _DEV_FD.fullmatch(word) is not None


def holds_substitution(word: str) -> bool:
    """Does the word hold the output of a `$(…)` or backticks (`placeholder`)?"""
    return SUB_PREFIX in word or SUB_EMPTY in word


def _shell_stdin_step(words: Sequence[str], at: int) -> int:
    """A shell's options: `-c` takes the next word as the script (code the command does not name
    when that word holds a substitution: `cat x | bash -c "$(cat)"`), `-s` reads stdin, `-o`/`-O`
    and `--rcfile`/`--init-file` take a value, and a plain word is a script file."""
    arg: str = words[at]
    if not arg.startswith(("-", "+")):
        return _SCRIPT
    if arg.startswith("--"):
        return 2 if arg in _SHELL_VALUE_OPTIONS else 1
    letters: str = arg[1:]
    if "c" in letters:
        return _STDIN if at + 1 < len(words) and holds_substitution(words[at + 1]) else _SCRIPT
    if "s" in letters:
        return _STDIN
    return 2 if ("o" in letters or "O" in letters) else 1


def _stdin_step(family: str, words: Sequence[str], at: int) -> int:
    """One step of a stdin walk: _STDIN, _SCRIPT, or how many words it moves on."""
    arg: str = words[at]
    if _is_stdin(arg):
        return _STDIN
    if arg == "--":  # what follows is the script, if anything does
        return _STDIN if at + 1 >= len(words) or _is_stdin(words[at + 1]) else _SCRIPT
    if family == "shell":
        return _shell_stdin_step(words, at)
    if not arg.startswith("-"):
        return _SCRIPT
    if family == "node":
        return _STDIN if _node_code(arg) else 2 if _node_takes_value(words, at) else 1
    move: int = _STEPS[family](arg)
    return _STDIN if move == _CODE else _SCRIPT if move == _END else move


def _node_takes_value(words: Sequence[str], at: int) -> bool:
    """A node option that takes the next word: a known one, or a long option the walk does not
    know when the next word does not look like a script (toward firing: in
    `node --disable-warning X` the X is no script, and node reads its code from stdin)."""
    arg: str = words[at]
    if arg in _NODE_VALUE_OPTIONS:
        return True
    if not arg.startswith("--") or "=" in arg or at + 1 >= len(words):
        return False
    return _NODE_SCRIPT.search(words[at + 1]) is None


def _stdin_table(family: str, words: Sequence[str]) -> list[bool]:
    """For every position i: does a stdin walk over `words[i:]` end with no script named (it ran
    out, or reached `-`, `/dev/stdin`, code, ...)? Worked out once, from the right (linear), as
    `_one_liner_table`."""
    found: list[bool] = [True] * (len(words) + 2)  # ran out: no script
    for at in range(len(words) - 1, -1, -1):
        move: int = _stdin_step(family, words, at)
        found[at] = move == _STDIN or (move > 0 and found[at + move])
    return found


def reads_stdin(words: Sequence[str]) -> bool:
    """Does an interpreter or a shell at a program position read its code from stdin?"""
    tables: dict[str, list[bool]] = {}
    for at in programs(words, narrow=True):
        family: str | None = _stdin_family(base_name(words[at]))
        if family is None:
            continue
        if family not in tables:
            tables[family] = _stdin_table(family, words)
        if tables[family][at + 1]:
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
    index: int = -1  # that command's index, once it is made


# A substitution as the scanner meets it: "in" (its output goes into the command it stands in) or
# "out" (`>(…)`), and the range of command indices it holds.
_Sub = tuple[str, int, int]


@dataclass
class _Cmd:
    """The simple command being read. `targets`: positions of words that are redirect targets;
    `stdin`: "file" or "sub" when stdin is redirected (`< f`, `< <(…)`); `subs`: the
    substitutions in its words and herestrings; `start`: no program word yet (only keywords such
    as `then` or `!`)."""

    words: list[str] = field(default_factory=list)
    herestrings: list[str] = field(default_factory=list)
    targets: list[int] = field(default_factory=list)
    stdin: str = ""
    subs: list[_Sub] = field(default_factory=list)
    start: bool = True


@dataclass(frozen=True)
class _Meta:
    targets: frozenset[int]
    stdin: str


_NO_META: _Meta = _Meta(frozenset(), "")  # most commands: one shared, it is frozen


@dataclass
class _Frame:
    """A list of commands being read: the whole text, a substitution's, or a group's (`(`, `{`,
    or the keyword that opened it). `start` is the first command of the part being read, `hub` the
    pipe that feeds it; `pattern`: a `case` that is reading a pattern, where `)` ends it."""

    kind: str
    start: int
    hub: int | None = None
    pattern: bool = False


# Group words at the start of a command, what closes each, and the words after which the next one
# still starts a command.
_OPENERS: dict[str, str] = {
    "{": "}",
    "if": "fi",
    "while": "done",
    "until": "done",
    "for": "done",
    "select": "done",
    "case": "esac",
}
_CLOSERS: frozenset[str] = frozenset(_OPENERS.values())
_STARTERS: frozenset[str] = frozenset(
    {"then", "do", "else", "elif", "!", "time", "if", "while", "until", "{"}
)
_HIDERS: frozenset[str] = frozenset({"function", "coproc"})  # what runs, and where, is unseen


class _Out:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.meta: list[_Meta] = []
        self.unparsed: bool = False
        self.unquoted_heredoc: bool = False
        self.code_heredoc: bool = False
        self.scans: int = 0  # nested scans so far; MAX_SCANS caps the work of one command
        self.links: list[tuple[int, int]] = []
        self.hubs: int = 0
        self.fed: set[int] = set()  # commands that read a pipe (or `>(…)`, or `< <(…)`)
        self.links_unknown: bool = False

    def hub(self) -> int:
        self.hubs += 1
        return -self.hubs

    def feed(self, hub: int, start: int) -> None:
        """The hub feeds every command from `start` on (a part after a pipe). Once the links are
        unknown every command counts as fed, and no more are kept (groups nested past MAX_DEPTH
        would make them quadratic)."""
        if self.links_unknown:
            return
        self.link((hub, index) for index in range(start, len(self.commands)))
        self.fed.update(range(start, len(self.commands)))

    def link(self, pairs: Iterable[tuple[int, int]]) -> None:
        """Keep these links; past MAX_LINKS drop them all and count them as unknown."""
        if self.links_unknown:
            return
        self.links.extend(pairs)
        if len(self.links) > MAX_LINKS:
            self.links_unknown = True
            self.links.clear()


class _Scanner:
    """One pass over `text`. Nested `$(...)` shares the position, so heredocs inside it work."""

    def __init__(self, text: str, out: _Out, depth: int) -> None:
        self.s: str = text
        self.n: int = len(text)
        self.i: int = 0
        self.out: _Out = out
        self.depth: int = depth
        self.subs: list[_Sub] = []  # substitutions read and not yet given to their command
        self.target: str = ""  # "<" or ">": the next word is a redirect's target
        self.fd: str = ""  # the fd written before the next redirect (`3<`), if any

    # ------------------------------------------------------------ commands

    def parse_list(self, closer: str | None) -> bool:
        """Parse commands until `closer` (consumed) or the end. True if the closer was found."""
        s, n, out = self.s, self.n, self.out
        cmd: _Cmd = _Cmd()
        heredocs: list[_Heredoc] = []
        frames: list[_Frame] = [_Frame("", len(out.commands))]

        def end_command() -> None:
            nonlocal cmd
            if cmd.words:
                # This command's heredocs are the last ones listed: a scan of all of them at every
                # command would be quadratic on a line of many `c<<A;`.
                for doc in reversed(heredocs):
                    if doc.owner is not cmd.words:
                        break
                    doc.index = len(out.commands)
                self.finish_command(cmd)
            cmd = _Cmd()
            self.target = ""

        def end_part(frame: _Frame) -> None:
            if frame.hub is not None:
                out.feed(frame.hub, frame.start)
            frame.start, frame.hub = len(out.commands), None

        def pipe(frame: _Frame) -> None:
            if frame.hub is not None:
                out.feed(frame.hub, frame.start)
            hub: int = out.hub()
            out.link((index, hub) for index in range(frame.start, len(out.commands)))
            frame.start, frame.hub = len(out.commands), hub

        def open_group(kind: str) -> None:
            if len(frames) > MAX_DEPTH:
                out.links_unknown = True
            frames.append(_Frame(kind, len(out.commands), pattern=kind == "case"))

        def close_group(word: str) -> None:
            if len(frames) > 1 and _OPENERS.get(frames[-1].kind) == word:
                end_part(frames.pop())
            else:
                out.links_unknown = True  # a closer that closes nothing

        def take(added: int) -> None:
            """Give the substitutions just read to the command; mark a redirect's target."""
            cmd.subs += self.subs
            self.subs.clear()
            if added and self.target:
                at: int = len(cmd.words) - 1
                cmd.targets.append(at)
                if self.target == "<" and not _is_stdin_device(cmd.words[at]):
                    cmd.stdin = "sub" if cmd.words[at].startswith(SUB_PREFIX) else "file"
                self.target = ""

        def finish() -> None:
            end_command()
            for frame in reversed(frames):
                end_part(frame)
            if len(frames) > 1:
                out.links_unknown = True  # an opener that is never closed

        while self.i < n:
            c: str = s[self.i]
            if c == "\n":
                self.i += 1
                top: _Frame = frames[-1]
                end_command()
                piping: bool = top.hub is not None and len(out.commands) == top.start
                if heredocs:
                    self.read_bodies(heredocs, closer)
                    heredocs = []
                if not piping:  # a pipe at the end of a line goes on to the next
                    end_part(top)
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
                first: int = self.i
                self.i += 1
                while self.i < n and s[self.i] in ";&|":
                    self.i += 1
                operator: str = s[first : self.i]
                if operator in ("|", "|&"):
                    pipe(frames[-1])
                else:
                    end_part(frames[-1])
                    if frames[-1].kind == "case" and operator.startswith((";;", ";&")):
                        frames[-1].pattern = True
                continue
            if c == "(":
                if frames[-1].kind == "case" and frames[-1].pattern:
                    self.i += 1  # `case x in (a)`: the pattern's optional parenthesis
                    continue
                after: int = self.i + 1
                while after < n and s[after] in " \t":  # each blank once: one `(` before it
                    after += 1
                if cmd.words and not cmd.words[-1].endswith("=") and s.startswith(")", after):
                    out.links_unknown = True  # `name ( )`: a function, called by name later
                end_command()
                self.i += 1
                open_group("(")
                continue
            if c == ")":
                end_command()
                self.i += 1
                top = frames[-1]
                if top.kind == "(":
                    end_part(frames.pop())
                elif top.kind == "case" and top.pattern:
                    top.pattern = False  # the end of a pattern
                elif closer == ")":
                    finish()
                    if heredocs:
                        self.out.unparsed = True
                    return True
                else:
                    out.links_unknown = True  # a `)` that closes nothing
                continue
            if c in "<>&":
                before: int = len(cmd.words)
                self.redirect(cmd, heredocs)
                take(len(cmd.words) - before)
                continue
            word: str = self.word()
            if word.isdigit() and self.i < n and s[self.i] in "<>":
                self.subs.clear()
                self.fd = word
                continue  # the fd of `2>&1`
            if cmd.start:
                if word in _CLOSERS:
                    close_group(word)
                elif word in _OPENERS:
                    open_group(word)
                elif word in _HIDERS:
                    out.links_unknown = True
                cmd.start = word in _STARTERS
            cmd.words.append(word)
            take(1)
        finish()
        if heredocs:
            self.out.unparsed = True  # a heredoc whose body never began
        return False

    def finish_command(self, cmd: _Cmd) -> None:
        out: _Out = self.out
        index: int = len(out.commands)
        words, herestrings = cmd.words, cmd.herestrings
        out.commands.append(tuple(words))
        out.meta.append(
            _Meta(frozenset(cmd.targets), cmd.stdin) if cmd.targets or cmd.stdin else _NO_META
        )
        if cmd.stdin == "sub":
            out.fed.add(index)
        for kind, first, last in cmd.subs:
            for inner in range(first, last):
                if kind == "out":  # `>(…)` reads what the command writes
                    out.link(((index, inner),))
                    out.fed.add(inner)
                else:
                    out.link(((inner, index),))
        names: list[str] = [base_name(w) for w in words]
        if herestrings and any(is_reader(name) for name in names):
            self.out.code_heredoc = True
        # Each distinct text once, and only the first `eval` (it already holds the later ones):
        # `eval eval eval ... curl x` or `bash bash bash -c ...` must not multiply the work, nor
        # may each word walk a copy of the words after it (F18).
        # A shell runs what a herestring holds, as it runs a `-c` script: what runs there writes to
        # the shell's output, not into the shell, so it links to nothing (`bash <<< 'curl x'`).
        texts: dict[str, None] = {}
        scripts: list[int | None] = []  # `script_indexes(words)`, at the first shell
        evaled: bool = False
        for position, name in enumerate(names):
            if name in SHELLS:
                first_shell: bool = not scripts
                if first_shell:
                    scripts = script_indexes(words)
                if (script := scripts[position + 1]) is not None:
                    texts[words[script]] = None
                if first_shell:
                    texts.update(dict.fromkeys(herestrings))
            elif name == "eval":
                if not evaled and position + 1 < len(words):
                    texts[" ".join(words[position + 1 :])] = None
                evaled = True
        for text in texts:
            self.sub_scan(text)

    def sub_scan(self, text: str) -> None:
        self.out.scans += 1
        if self.depth >= MAX_DEPTH or self.out.scans > MAX_SCANS:
            self.out.unparsed = True
            return
        _Scanner(text, self.out, self.depth + 1).parse_list(None)

    def nested(self, kind: str = "in") -> str:
        """After `$(`, `<(` or (`kind` "out") `>(`: parse to the matching `)`. Returns the
        placeholder word; the range of commands inside waits in `subs` for its command."""
        if self.depth >= MAX_DEPTH:
            self.out.unparsed = True
            self.i = self.n
            return SUB_EMPTY
        before: int = len(self.out.commands)
        subs, target = self.subs, self.target  # the outer command's, kept out of the inner list
        self.subs, self.target = [], ""
        self.depth += 1
        found: bool = self.parse_list(")")
        self.depth -= 1
        self.subs, self.target = subs, target
        if not found:
            self.out.unparsed = True
        self.subs.append((kind, before, len(self.out.commands)))
        return placeholder(self.out.commands[before:])

    # ------------------------------------------------------------ redirects, heredocs

    def redirect(self, cmd: _Cmd, heredocs: list[_Heredoc]) -> None:
        s, n = self.s, self.n
        c: str = s[self.i]
        stdin: bool = self.fd in ("", "0")  # `3<` opens fd 3: stdin stays the pipe
        self.fd = ""
        if c in "<>" and s.startswith("(", self.i + 1):  # process substitution: a word
            self.i += 2
            cmd.words.append(self.nested("out" if c == ">" else "in"))
            return
        if s.startswith("<<<", self.i):
            self.i += 3
            self.skip_blanks()
            cmd.herestrings.append(self.word())
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
            heredocs.append(_Heredoc(delimiter, quoted, strip, cmd.words))
            return
        first: int = self.i
        self.i += 1  # `>`, `>>`, `>&`, `<&`, `&>`, `>|`, `<>`: the target stays a word
        while self.i < n and s[self.i] in "<>&|":
            self.i += 1
        operator: str = s[first : self.i]
        fd: bool = False
        while s[self.i - 1 : self.i] == "&" and self.i < n and s[self.i] in "0123456789-":
            self.i += 1  # the fd of `>&2`
            fd = True
        self.target = "" if fd else "<" if operator in ("<", "<>") and stdin else ">"

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
        # What `$(…)` or backticks in the body print feeds the command the body is for; what a
        # shell runs from the body writes to the shell's output, and links to nothing.
        inner: list[tuple[int, int]] = []
        if not doc.quoted:
            self.out.unquoted_heredoc = True  # D10: counts as unparseable for R1
            inner += self.expansions(text)  # the shell expands $(...) and backticks in the body
        if reader:
            self.out.code_heredoc = True  # D10: a quoted body is data unless something runs it
            if any(name in SHELLS for name in names):
                self.sub_scan(text)
        if doc.index >= 0:
            self.out.link((i, doc.index) for first, last in inner for i in range(first, last))

    def expansions(self, body: str) -> list[tuple[int, int]]:
        """Parse the substitutions of an unquoted heredoc body, as inside double quotes; return
        the ranges of commands they hold."""
        if self.depth >= MAX_DEPTH:
            self.out.unparsed = True
            return []
        quoted: str = body.replace('"', '\\"') + ' "'  # a `\` at the end must not eat the quote
        scanner = _Scanner(quoted, self.out, self.depth + 1)
        scanner.double_quoted()
        return [(first, last) for _, first, last in scanner.subs]

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
            run = _DQ_RUN.match(s, self.i)
            if run is not None:
                parts.append(run.group())
                self.i = run.end()
                continue
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
            run = _BT_RUN.match(s, self.i)
            if run is not None:
                inner.append(run.group())
                self.i = run.end()
                continue
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
        self.subs.append(("in", before, len(self.out.commands)))
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
    return SUB_PREFIX + ",".join(names) + "@" if names else SUB_EMPTY


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


def script_indexes(args: Sequence[str]) -> list[int | None]:
    """For each index of `args` (and the two past its end), the index of the script the walk of
    `shell_script` finds from there, or None. Worked out from the right in one pass (F18): a
    shell word at every other index (`sh -o sh -o …`) then costs no walk of its own."""
    found: list[int | None] = [None] * (len(args) + 2)
    for index in range(len(args) - 1, -1, -1):
        arg: str = args[index]
        if arg == "--" or not arg.startswith(("-", "+")):
            continue  # a plain word is a script file: no `-c` script
        letters: str = arg[1:]
        if arg.startswith("--"):
            found[index] = found[index + (2 if arg in _SHELL_VALUE_OPTIONS else 1)]
        elif "c" in letters:
            found[index] = index + 1 if index + 1 < len(args) else None
        else:
            found[index] = found[index + (2 if ("o" in letters or "O" in letters) else 1)]
    return found


@lru_cache(maxsize=4)  # mark, R0 and R1 parse the same command in one request
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
    try:
        piped: bool = _piped_code(out)
    except Exception:  # noqa: BLE001 - as above: the text then counts as unparsed
        out.unparsed, piped = True, False
        loose = loose_commands(text)
    return Parsed(
        commands=tuple(out.commands),
        unparsed=out.unparsed,
        unquoted_heredoc=out.unquoted_heredoc,
        code_heredoc=out.code_heredoc,
        loose=loose,
        links=tuple(out.links),
        targets=tuple(meta.targets for meta in out.meta),
        links_unknown=out.links_unknown,
        piped_code=piped,
    )


def _piped_code(out: _Out) -> bool:
    """Some command that reads a pipe (every command, when the links are unknown) is an
    interpreter or a shell that reads its code from stdin (`reads_stdin`). Its redirect targets
    are no words of its own, and stdin redirected from a file names a script."""
    for index in range(len(out.commands)) if out.links_unknown else out.fed:
        meta: _Meta = out.meta[index]
        if meta.stdin == "file":
            continue
        argv: Sequence[str] = out.commands[index]
        if meta.targets:
            argv = [word for at, word in enumerate(argv) if at not in meta.targets]
        if reads_stdin(argv):
            return True
    return False
