"""The rules file (D10, SPEC section 5): read it, check it, match its patterns.

A rules file is TOML with `schema = 1`, one `[lists]` table of named lists and any number of
`[[rule]]` tables of kind `match` or `after_then`, each with inline `[[rule.test]]` tables. This
module is the data layer: `parse` turns text into `RuleSpec`s (or says what is wrong, naming the
rule), and a `Clause` answers "does this action fit?". It knows nothing about sessions or the
decision; `rules.py` builds the checks from these specs.

Nothing here raises on bad input and nothing reads the environment. A file can be hostile or
broken (it is root's file, but it is also read by a recorder that must keep deciding), so every
failure becomes a message. The program supplies the engine-only command classes (`outbound`).
"""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import os
import posixpath
import re
import stat
import string
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from agentfly.install.layout import SYSTEM
from agentfly.recorder.names import hosts_in_command
from agentfly.recorder.normalize import Parsed, base_name, normalize

# The file the recorder reads once at start. Tests (and nothing else) point this elsewhere; it is
# always read as `rulefile.ACTIVE_RULES`, never copied. No flag or variable moves it (D3, D25).
ACTIVE_RULES: Path = SYSTEM.rules
# Who must own the active file: root, as D3 has it. Read at call time. Tests (and nothing else)
# set their own user id, as they set `ACTIVE_RULES`; `tests/conftest.py` checks the value here.
ACTIVE_OWNER_UID: int = SYSTEM.owner[0] if SYSTEM.owner is not None else 0

SCHEMA: int = 1
RESERVED_ID: str = "R0"  # built into the program; a rules file may not list it
MARK_RULE: str = "R1"  # the after_then rule whose trigger is the chat's secret mark
KINDS: tuple[str, ...] = ("match", "after_then")
SEVERITIES: tuple[str, ...] = ("block", "warn", "highlight")
EVENTS: tuple[str, ...] = ("read", "write", "shell")
EXPECTS: tuple[str, ...] = (*SEVERITIES, "allow")
CLAUSE_FIELDS: tuple[str, ...] = (
    "event",
    "path",
    "path_except",
    "command",
    "command_class",
    "host_not_in",
)
COMMAND_CLASSES: frozenset[str] = frozenset({"outbound"})  # implemented by rules.py

_RULE_FIELDS: frozenset[str] = frozenset({"id", "kind", "severity", "message", "test"})
_TOP_FIELDS: frozenset[str] = frozenset({"schema", "lists", "rule"})
_TEST_FIELDS: frozenset[str] = frozenset({"steps", "expect"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_FIELDS_OF: dict[str, frozenset[str]] = {
    "match": _RULE_FIELDS | set(CLAUSE_FIELDS),
    "after_then": _RULE_FIELDS | {"after", "then"},
}
_ANY_FIELDS: frozenset[str] = _FIELDS_OF["match"] | _FIELDS_OF["after_then"]

MAX_FILE_BYTES: int = 256 * 1024
MAX_RULES: int = 200
MAX_LIST_ENTRIES: int = 200
# What one hook may cost in matching: the sum, over every clause of every rule, of `clause_work`.
# The decision runs under the hook client's 0.5 s wait, and a command is up to hundreds of words.
# Measured for a 300-word command (3 candidates a word) through the whole hook on the author's Mac:
# about 32 ms with the packaged default, then about 0.5 ms for each unit below. At the limit the
# slowest shapes tried (55 one-pattern rules; 5 floating "**" patterns; paths 20 folders deep) take
# about 110 ms, a fifth of the wait. The weights below are fitted to those measurements.
MAX_WORK: int = 200
WORK_CLAUSE: int = 2  # a clause with path patterns looks at every word of the command once
WORK_NAME: int = 1  # a pattern without "/" is one comparison per word
WORK_SLASH: int = 4  # a pattern with "/" is a walk through the path's folders ...
WORK_STAR: int = 12  # ... and each "**" (an unanchored pattern has one more) multiplies it
WORK_ERROR: str = "asks for too much matching work per hook"
MAX_PATTERN_CHARS: int = 200
MAX_STARS: int = 8
MAX_MESSAGE_CHARS: int = 500
MAX_TESTS: int = 50
MAX_STEPS: int = 20
MAX_STEP_CHARS: int = 2000
MAX_SUMMARY_CHARS: int = 300

CommandClass = Callable[[Parsed], bool]


# ---------------------------------------------------------------- patterns


def _segments(text: str) -> list[str]:
    return [part for part in text.split("/") if part and part != "."]


def _glob(pattern: Sequence[str], segments: Sequence[str]) -> bool:
    """Match path segments against pattern segments; `**` is zero or more whole folders.

    Linear in pattern times path: it tracks the set of positions reached, with no backtracking.
    """
    positions: set[int] = {0}
    for part in pattern:
        if part == "**":
            reached: set[int] = set(range(min(positions), len(segments) + 1))
        else:
            reached = {
                i + 1
                for i in positions
                if i < len(segments) and fnmatch.fnmatchcase(segments[i], part)
            }
        if not reached:
            return False
        positions = reached
    return len(segments) in positions


def _resolved(path: str, home: str) -> str:
    """A path as the shell would hand it on: a leading `~`, `$HOME` or `${HOME}` is the home
    folder, and `..` and `//` are folded (the text only; no link is followed)."""
    for prefix in ("~", "$HOME", "${HOME}"):
        if path == prefix or path.startswith(prefix + "/"):
            path = home + path[len(prefix) :]
            break
    return posixpath.normpath(path) if ".." in path or "//" in path else path


# The decision runs on the event loop, under the hook client's 0.5 s wait, and every clause of every
# rule looks at every word of the command. What is worked out about a word is worked out once,
# whatever the number of patterns and clauses: a command of 300 words with up to 3 candidates each
# is 900 entries, so these hold more than that. They keep text of recent commands in memory only.
_WORD_MEMO = 2048


@lru_cache(maxsize=_WORD_MEMO)
def _folded_segments(path: str, home: str) -> tuple[str, tuple[str, ...]]:
    """The resolved path and its case-folded segments, worked out once per word however many
    patterns look at it."""
    resolved: str = _resolved(path, home)
    return resolved, tuple(_segments(resolved.casefold()))


@lru_cache(maxsize=_WORD_MEMO)
def _folded_name(text: str) -> str:
    """The case-folded file name of a path (or of a word that may be one)."""
    return PurePosixPath(text).name.casefold()


@lru_cache(maxsize=64)
def _first_positions(argv: tuple[str, ...]) -> dict[str, int]:
    """Where each program name first appears in a command (read only; shared by every clause)."""
    first: dict[str, int] = {}
    for index, word in enumerate(argv):
        first.setdefault(base_name(word), index)
    return first


@lru_cache(maxsize=64)
def _hosts_of(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The case-folded host names a command names."""
    return tuple(host.casefold() for host in hosts_in_command(argv))


@lru_cache(maxsize=_WORD_MEMO)
def _candidates(word: str) -> tuple[str, ...]:
    """A shell word and, if it holds `=` or `@`, what follows its last one (`--env-file=.env`,
    `-d@.env`): each is looked at as a path."""
    if "=" in word or "@" in word:
        return tuple(dict.fromkeys((word, word.rsplit("=", 1)[-1], word.rsplit("@", 1)[-1])))
    return (word,)


@lru_cache(maxsize=4)
def _home_segments(home: str) -> tuple[str, ...]:
    return tuple(_segments(home.casefold()))


@dataclass(frozen=True)
class Pattern:
    """One entry of a path list, case-folded.

    No `/`: the file *name* only (`.env`, `*.pem`). With `/`: the whole path, segment by
    segment; `**` crosses folders (and may match none); a leading `/` or `~/` anchors it at the
    root or the home folder, any other slash pattern may start anywhere in the path.
    """

    text: str
    name_only: bool
    anchor: str  # "", "root" or "home"
    parts: tuple[str, ...]

    def matches(self, path: str, name: str | None = None) -> bool:
        """`name` is the path's folded file name when the caller has it already (one per path)."""
        if self.name_only:
            folded: str = name if name is not None else PurePosixPath(path).name.casefold()
            return fnmatch.fnmatchcase(folded, self.text)
        home: str = os.path.expanduser("~")
        resolved, segments = _folded_segments(path, home)
        if self.anchor == "home":
            base: tuple[str, ...] = _home_segments(home)
            if segments[: len(base)] != base:
                return False
            return _glob(self.parts, segments[len(base) :])
        if self.anchor == "root":
            return resolved.startswith("/") and _glob(self.parts, segments)
        return _glob(("**", *self.parts), segments)


def compile_pattern(raw: str) -> Pattern:
    text: str = raw.casefold()
    if "/" not in text:
        return Pattern(text, True, "", ())
    anchor: str = ""
    rest: str = text
    if text.startswith("~/"):
        anchor, rest = "home", text[2:]
    elif text.startswith("/"):
        anchor = "root"
    parts: list[str] = []
    for part in _segments(rest):
        if part != "**" or not parts or parts[-1] != "**":  # `**/**` is `**`
            parts.append(part)
    if text.endswith("/") and parts[-1:] != ["**"]:  # `~/.ssh/` is the folder and all in it
        parts.append("**")
    return Pattern(text, False, anchor, tuple(parts))


# ---------------------------------------------------------------- clauses


def event_of(action: Mapping[str, Any]) -> str | None:
    """The rules' name for what an action is: `read`, `shell`, `write`, else None."""
    event: Any = action.get("hook_event_name")
    if event == "beforeReadFile":
        return "read"
    if event == "beforeShellExecution":
        return "shell"
    if event == "preToolUse" and str(action.get("tool_name", "")).casefold() == "write":
        return "write"
    return None


def _action_path(action: Mapping[str, Any], event: str) -> str:
    value: Any = action.get("file_path")
    if event == "write":
        tool_input: Any = action.get("tool_input")
        value = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class Clause:
    """The conditions of a `match` rule, or of the `after` / `then` table of an `after_then`.

    Every condition that is present must hold. `path` applies to a read or write's file and, in a
    shell command, to every word (and to the text after the last `=` and the last `@` of a word,
    so `--env-file=.env` and `-d@.env` count). The others apply to shell commands only.
    """

    events: tuple[str, ...]
    path: tuple[Pattern, ...] = ()
    path_except: tuple[Pattern, ...] = ()
    command: tuple[tuple[str, ...], ...] = ()  # program, then extra whole words; case-folded
    command_class: str = ""
    host_not_in: frozenset[str] = frozenset()

    def _path_hit(self, text: str) -> bool:
        name: str = _folded_name(text)
        return any(p.matches(text, name) for p in self.path) and not any(
            p.matches(text, name) for p in self.path_except
        )

    def _words_hit(self, parsed: Parsed) -> bool:
        return any(
            self._path_hit(candidate)
            for argv in parsed.all_commands()
            for word in argv
            for candidate in _candidates(word)
        )

    def _command_hit(self, parsed: Parsed) -> bool:
        """Some word is the program (by base name, so wrappers do not hide it) and the later
        words include every extra word, in any order.

        Only the first word that is the program needs a look: what follows a later one is a
        part of what follows the first. So a command is read once, however often it repeats the
        program (this runs on the event loop, under the hook client's 0.5 s wait).
        """
        for argv in parsed.all_commands():
            first: dict[str, int] = _first_positions(argv)
            for program, *extras in self.command:
                at: int | None = first.get(program)
                if at is not None and self._extras_after(argv, at, extras):
                    return True
        return False

    @staticmethod
    def _extras_after(argv: tuple[str, ...], at: int, extras: list[str]) -> bool:
        if not extras:
            return True
        later: set[str] = {w.casefold() for w in argv[at + 1 :]}
        return all(extra in later for extra in extras)

    def _host_hit(self, parsed: Parsed) -> bool:
        return any(
            host not in self.host_not_in
            for argv in parsed.all_commands()
            for host in _hosts_of(argv)
        )

    def matches(self, action: Mapping[str, Any], classes: Mapping[str, CommandClass]) -> bool:
        event: str | None = event_of(action)
        if event is None or event not in self.events:
            return False
        if event != "shell":
            return not self.path or self._path_hit(_action_path(action, event))
        command: str = str(action.get("command", ""))
        if not command.strip():
            return False
        parsed: Parsed = normalize(command)
        return (
            (not self.path or self._words_hit(parsed))
            and (not self.command or self._command_hit(parsed))
            and (not self.host_not_in or self._host_hit(parsed))
            and (not self.command_class or classes[self.command_class](parsed))
        )


def pattern_work(pattern: Pattern) -> int:
    """What one path pattern costs per word (see `MAX_WORK`)."""
    if pattern.name_only:
        return WORK_NAME
    stars: int = pattern.parts.count("**") + (0 if pattern.anchor else 1)  # unanchored: `**/`
    return WORK_SLASH + WORK_STAR * stars


def clause_work(clause: Clause | None) -> int:
    """What a clause costs per hook: a fixed part and its path patterns, which are tried on every
    word. Command entries and host names are looked up once per command and shared by all the
    clauses, so a long list of them costs nothing worth counting (measured: 190 rules of 200
    entries add 14 ms)."""
    if clause is None or not (clause.path or clause.path_except):
        return 0
    return WORK_CLAUSE + sum(pattern_work(p) for p in (*clause.path, *clause.path_except))


def rule_work(spec: RuleSpec) -> int:
    """What a rule costs per hook. R1's `after` is run twice for a shell command: once to mark the
    chat, once to flag the step in the history (`store.build_step_record`)."""
    twice: int = 2 if spec.id == MARK_RULE else 1
    return clause_work(spec.clause) + twice * clause_work(spec.after) + clause_work(spec.then)


def file_work(specs: Sequence[RuleSpec]) -> int:
    return sum(rule_work(spec) for spec in specs)


# ---------------------------------------------------------------- specs


@dataclass(frozen=True)
class InlineTest:
    steps: tuple[tuple[str, str], ...]  # (event, value), in order
    expect: str  # what the last step gets: block, warn, highlight or allow


@dataclass(frozen=True)
class RuleSpec:
    id: str
    kind: str
    severity: str
    message: str
    clause: Clause | None  # match
    after: Clause | None  # after_then
    then: Clause | None
    tests: tuple[InlineTest, ...]


@dataclass(frozen=True)
class RuleFile:
    rules: tuple[RuleSpec, ...]
    errors: tuple[str, ...]  # a file with any of these is not used
    lint: tuple[str, ...]  # `rules check` prints these; the file is still used
    sha256: str = ""  # of the bytes that were read, BOM and all; "" for a file never read


def summary(errors: tuple[str, ...], limit: int = MAX_SUMMARY_CHARS) -> str:
    """One short line for `/health` and `doctor`: the first problem and how many more."""
    first: str = " ".join(errors[0].split()) if errors else "no problem"
    more: str = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    text: str = first + more
    return text if len(text) <= limit else text[: limit - 3] + "..."


DEFAULT_IN_FORCE: str = "the packaged default rules are in force"
MAX_PROBLEM_CHARS: int = 400  # what `/health` sends: the tail must never be cut off


def refusal(path: Path | str, errors: tuple[str, ...]) -> str:
    """The one line that says a file was not used and what runs instead (`/health`, the API).

    Always ends with `DEFAULT_IN_FORCE` and is at most `MAX_PROBLEM_CHARS` long: a long path or
    a long first problem is shortened, never the part that says what is running.
    """
    shown: str = str(path)
    if len(shown) > 150:
        shown = "..." + shown[-147:]
    tail: str = f"; {DEFAULT_IN_FORCE}"
    room: int = MAX_PROBLEM_CHARS - len(shown) - len(": ") - len(tail)  # at least 200
    return f"{shown}: {summary(errors, room)}{tail}"


def rules_word(count: int) -> str:
    return f"{count} rule" if count == 1 else f"{count} rules"


def _refused(message: str) -> RuleFile:
    """A file that cannot be used at all, for one reason."""
    return RuleFile((), (message,), ())


# ---------------------------------------------------------------- parse


class _Problems:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}" if where else message)

    def unknown(self, where: str, table: Any, allowed: Any, hint: str = "") -> None:
        """One error per key of `table` that is not allowed (a rules file is typed by a person)."""
        for field in table:
            if field not in allowed:
                extra = hint if field in CLAUSE_FIELDS else ""
                self.add(where, f"unknown field {field!r}{extra}")


def _strings(value: Any, limit: int) -> list[str] | None:
    """A non-empty array of strings of at most `limit` entries, else None."""
    ok = isinstance(value, list) and 0 < len(value) <= limit
    return list(value) if ok and all(isinstance(v, str) for v in value) else None


def _lists(raw: Any, problems: _Problems) -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    if raw is None:
        return found
    if not isinstance(raw, dict):
        problems.add("", "[lists] must be a table of named arrays")
        return found
    for name, value in raw.items():
        entries: list[str] | None = _strings(value, MAX_LIST_ENTRIES)
        if entries is None or any(not e.strip() for e in entries):
            problems.add(
                f"list {name}",
                f"must be a non-empty array of non-empty strings (at most {MAX_LIST_ENTRIES})",
            )
        else:
            found[name] = tuple(entries)
    return found


# One `fnmatch` class: `[`, an optional `!`, an optional first `]` (a member, not the end), then up
# to the closing `]`. Possessive, so a `[` that never closes stays a plain character.
_CLASS = re.compile(r"\[!?+\]?+[^\]]*+\]")


def _wildcards_only(raw: str) -> bool:
    """Is every character of this pattern a wildcard, so that it matches nearly every name?

    Read the way `fnmatch` reads it: `*` and `?` match anything, `[...]` is one character out of
    a set (`[!x]` is any but one), and a `[` that never closes is a plain character. Only a
    pattern with a `*` or a `[...]` in it counts (`???` matches names of three characters, no
    more); `/` only separates folders. `[!x]*` and `*[a-z]*` have nothing a name must contain.
    """
    reduced: str = _CLASS.sub("*", raw)
    return "*" in reduced and not reduced.strip("*?/")


def _path_pattern(where: str, raw: str, problems: _Problems) -> Pattern | None:
    if len(raw) > MAX_PATTERN_CHARS or "\x00" in raw:
        problems.add(where, f"pattern {raw[:40]!r} is too long or holds a NUL")
    elif raw.count("*") > MAX_STARS:
        problems.add(where, f"pattern {raw!r} has more than {MAX_STARS} wildcards")
    elif _wildcards_only(raw):
        problems.add(where, f"pattern {raw!r} matches every path")
    else:
        return compile_pattern(raw)
    return None


def _command_entry(where: str, raw: str, problems: _Problems) -> tuple[str, ...] | None:
    words: list[str] = raw.casefold().split()
    if not words or len(raw) > MAX_PATTERN_CHARS:
        problems.add(where, f"command pattern {raw[:40]!r} needs a program name")
    elif any(c in raw for c in "*?["):
        problems.add(where, f"command pattern {raw!r}: wildcards are not supported yet")
    else:
        return (base_name(words[0]), *words[1:])
    return None


def _named(
    where: str, table: dict[str, Any], field: str, lists: dict[str, tuple[str, ...]], p: _Problems
) -> tuple[str, ...]:
    """The entries of the list a field names; () if the field is absent or wrong (reported)."""
    if field not in table:
        return ()
    name: Any = table[field]
    if not isinstance(name, str):
        p.add(where, f"'{field}' must be the name of a list in [lists], a string")
    elif name not in lists:
        p.add(where, f"'{field}' names the list {name!r}, which [lists] does not define")
    else:
        return lists[name]
    return ()


def _compiled(where: str, entries: tuple[str, ...], make: Any, p: _Problems) -> tuple[Any, ...]:
    return tuple(c for e in entries if (c := make(where, e, p)) is not None)


def _clause(
    where: str,
    table: Any,
    lists: dict[str, tuple[str, ...]],
    problems: _Problems,
    *,
    needs_condition: bool,
) -> Clause | None:
    """One clause. `then` may be event-only (a lockdown); `match` and `after` need a condition."""
    if not isinstance(table, dict):
        problems.add(where, "must be a table")
        return None
    start: int = len(problems.errors)
    problems.unknown(where, table, CLAUSE_FIELDS)
    events: list[str] = _strings(table.get("event"), len(EVENTS)) or []
    if not events or not set(events) <= set(EVENTS) or len(set(events)) != len(events):
        problems.add(
            where,
            f"'event' must list some of {', '.join(EVENTS)}, each once "
            f"(got {table.get('event')!r})",
        )
        events = []
    path = _compiled(where, _named(where, table, "path", lists, problems), _path_pattern, problems)
    path_except = _compiled(
        where, _named(where, table, "path_except", lists, problems), _path_pattern, problems
    )
    command = _compiled(
        where, _named(where, table, "command", lists, problems), _command_entry, problems
    )
    hosts = frozenset(e.casefold() for e in _named(where, table, "host_not_in", lists, problems))
    command_class: Any = table.get("command_class", "")
    if "command_class" in table and not (
        isinstance(command_class, str) and command_class in COMMAND_CLASSES
    ):
        problems.add(
            where, f"command_class {command_class!r} is not one of {sorted(COMMAND_CLASSES)}"
        )
        command_class = ""
    if path_except and not path:
        problems.add(where, "'path_except' needs a 'path'")
    if hosts and not (command or command_class):
        # Alone it would fire on any dotted word (`README.md`, `script.py`): a host is judged
        # only inside a command that sends something.
        problems.add(where, "'host_not_in' needs a 'command' or a 'command_class' beside it")
    if (command or hosts or command_class) and events and events != ["shell"]:
        problems.add(where, "'command', 'command_class' and 'host_not_in' need event = [\"shell\"]")
    if needs_condition and not (path or command or hosts or command_class):
        problems.add(where, f"matches every {'/'.join(events) or 'action'} action; add a condition")
    if len(problems.errors) > start:
        return None
    return Clause(tuple(events), path, path_except, command, command_class, hosts)


def _tests(where: str, raw: Any, problems: _Problems) -> tuple[InlineTest, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_TESTS:
        problems.add(where, f"'test' must be [[rule.test]] tables, at most {MAX_TESTS}")
        return ()
    found: list[InlineTest] = []
    for number, item in enumerate(raw, 1):
        label: str = f"{where} test #{number}"
        if not isinstance(item, dict):
            problems.add(label, "must be a table")
            continue
        problems.unknown(label, item, _TEST_FIELDS)
        expect: Any = item.get("expect")
        if expect not in EXPECTS:
            problems.add(label, f"'expect' must be one of {', '.join(EXPECTS)} (got {expect!r})")
        steps: list[str] | None = _strings(item.get("steps"), MAX_STEPS)
        parsed: list[tuple[str, str]] = []
        for step in steps or []:
            event, _, value = step.partition(":")
            if event not in EVENTS or not value.strip() or len(step) > MAX_STEP_CHARS:
                problems.add(label, f"step {step[:40]!r} must read '<{'|'.join(EVENTS)}>: <value>'")
            else:
                parsed.append((event, value.strip()))
        if steps is None:
            problems.add(label, f"'steps' must be 1 to {MAX_STEPS} strings")
        elif len(parsed) == len(steps) and expect in EXPECTS:
            found.append(InlineTest(tuple(parsed), expect))
    return tuple(found)


def _rule(
    number: int,
    raw: Any,
    lists: dict[str, tuple[str, ...]],
    seen: set[str],
    problems: _Problems,
) -> RuleSpec | None:
    if not isinstance(raw, dict):
        problems.add(f"rule #{number}", "must be a table ([[rule]])")
        return None
    start: int = len(problems.errors)
    rid: Any = raw.get("id")
    named: bool = isinstance(rid, str) and bool(_ID.fullmatch(rid))
    where: str = f"rule {rid}" if named else f"rule #{number}"
    if not named:
        problems.add(where, "'id' must be letters, digits, '.', '_' or '-' (at most 64)")
    elif rid.casefold() == RESERVED_ID.casefold():
        problems.add(
            where, f"{RESERVED_ID} is built into AgentFly and cannot be listed in a rules file"
        )
    elif rid.casefold() in seen:
        problems.add(where, "duplicate id")
    else:
        seen.add(rid.casefold())
    kind: Any = raw.get("kind")
    if kind not in KINDS:
        problems.add(where, f"'kind' must be one of {', '.join(KINDS)} (got {kind!r})")
    severity: Any = raw.get("severity")
    if severity not in SEVERITIES:
        problems.add(where, f"'severity' must be one of {', '.join(SEVERITIES)} (got {severity!r})")
    message: Any = raw.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_CHARS:
        problems.add(where, f"'message' must be text of 1 to {MAX_MESSAGE_CHARS} characters")
    # An unusable `kind` is reported above; its other fields are then judged against every kind.
    allowed = _FIELDS_OF[kind] if kind in KINDS else _ANY_FIELDS
    problems.unknown(where, raw, allowed, " (conditions go inside 'after' and 'then')")
    clause = after = then = None
    if kind == "match":
        condition = {k: raw[k] for k in CLAUSE_FIELDS if k in raw}
        clause = _clause(where, condition, lists, problems, needs_condition=True)
    elif kind == "after_then":
        for field in ("after", "then"):
            if field not in raw:
                problems.add(where, f"an after_then rule needs '{field}'")
        if "after" in raw:
            after = _clause(f"{where} after", raw["after"], lists, problems, needs_condition=True)
        if "then" in raw:
            then = _clause(f"{where} then", raw["then"], lists, problems, needs_condition=False)
    tests: tuple[InlineTest, ...] = _tests(where, raw.get("test"), problems)
    if len(problems.errors) > start:
        return None
    return RuleSpec(rid, kind, severity, message, clause, after, then, tests)


def _parse(text: str) -> RuleFile:
    problems = _Problems()
    if len(text) > MAX_FILE_BYTES:  # `load_file` checks bytes; this is for callers of `parse`
        return _refused(f"too large (over {MAX_FILE_BYTES} bytes)")
    try:
        data: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return _refused(f"not valid TOML ({exc})")
    except RecursionError:
        return _refused("nested too deeply to read")
    for key in data:
        if key not in _TOP_FIELDS:
            problems.add("", f"unknown top-level key {key!r}")
    schema: Any = data.get("schema")
    if isinstance(schema, bool) or schema != SCHEMA:
        problems.add("", f"needs schema = {SCHEMA} on its own line near the top")
    lists: dict[str, tuple[str, ...]] = _lists(data.get("lists"), problems)
    raw_rules: Any = data.get("rule", [])
    if not isinstance(raw_rules, list):
        problems.add("", "rules are written as [[rule]] tables, one per rule")
        raw_rules = []
    if len(raw_rules) > MAX_RULES:
        problems.add("", f"has more than {MAX_RULES} rules")
        raw_rules = []
    seen: set[str] = set()
    specs: list[RuleSpec] = []
    for number, raw in enumerate(raw_rules, 1):
        if (spec := _rule(number, raw, lists, seen, problems)) is not None:
            specs.append(spec)
    total: int = file_work(specs)
    if total > MAX_WORK:
        heaviest: RuleSpec = max(specs, key=rule_work)
        problems.add(
            "",
            f"{WORK_ERROR} ({total} units; at most {MAX_WORK}); the heaviest is rule "
            f"{heaviest.id} with {rule_work(heaviest)}. Use fewer or shorter lists, names without "
            f"'/' where a name will do, and fewer '**'",
        )
    lint: list[str] = [
        f"rule {s.id}: no inline test; add a [[rule.test]]" for s in specs if not s.tests
    ]
    return RuleFile(tuple(specs), tuple(problems.errors), tuple(lint))


def parse(text: str) -> RuleFile:
    """Read a rules file's text. Never raises: whatever is wrong comes back in `errors`."""
    try:
        return _parse(text)
    except Exception as exc:  # noqa: BLE001 - a rules file must never crash the recorder
        return _refused(f"could not be read ({type(exc).__name__})")


# ---------------------------------------------------------------- the minimum for R1 (D27)

# SPEC section 5 makes R0 and R1 the two rules v1 must have. R0 is in code; R1 sits in the file, so
# the program holds the least it may say, as it holds R0: a file whose R1 is missing or weaker is
# refused (the packaged default runs), however it spells its lists. Widening and rewording are fine.
# Measured against this, not against `default.toml`, so a wider later default never refuses an
# older file. A local exception (a company host) waits for the reviewed path (V7).
EXEMPTION_ENDINGS: tuple[str, ...] = (".example", ".sample", ".template", ".pub")
_FAMILIES: tuple[str, ...] = (".env", "x.pem", ".pem", "k.key", ".key", "id_rsa", "credentials")
_TAILS: tuple[str, ...] = (
    "",
    ".local",
    ".production",
    ".1",
    "-w",
    "_w",
    "~",
    ".x.y",
    ".bak",
    ".test",
    ".dist",
    ".yml",
    ".md",
    ".example",
    ".sample",
    ".template",
    ".pub",
)
_SWEEP: str = string.ascii_letters + string.digits + "_-~.@+,%\u00e9"
_LITERALS: tuple[str, ...] = (
    "prod.pem",
    "server.key",
    ".env.staging",
    "credentials.json",
    "id_rsa2",
    ".env._x",
    ".env.example.local",
)
_FOLDERS: tuple[str, ...] = ("", "cfg/", "a/b/", "/Users/me/proj/", "~/")


def spec_secret(name: str) -> bool:
    """Does SPEC section 5 count this file *name* as a secret? (Written from its bullets.)"""
    folded: str = name.casefold()
    if folded == ".env" or (
        folded.startswith(".env.") and not folded.endswith((".example", ".sample", ".template"))
    ):
        return True
    if folded.endswith((".pem", ".key")):
        return True
    if folded.startswith("id_rsa") and not folded.endswith(".pub"):
        return True
    return folded.startswith("credentials")


def _secret_names() -> tuple[str, ...]:
    """Names SPEC section 5 counts as secrets, in the shapes a list is likely to get wrong: every
    family with every kind of tail, one character after each stem, and a few whole names."""
    names: set[str] = {family + tail for family in _FAMILIES for tail in _TAILS}
    for stem in (".env.", "id_rsa", "credentials"):
        names |= {stem + char for char in _SWEEP}
    for char in _SWEEP:
        names |= {char + ".pem", char + ".key", f".env.{char}x"}
    names |= set(_LITERALS)
    return tuple(sorted(name for name in names if spec_secret(name)))


SECRET_NAMES: tuple[str, ...] = _secret_names()


@lru_cache(maxsize=16)  # the same file is loaded again and again (a clause is hashable): once
def _unmarked(after: Clause) -> tuple[str, ...]:
    """Secret names (in several places) that R1's `after` clause does not fire on."""
    left: list[str] = []
    for name in SECRET_NAMES:
        forms: list[str] = [folder + name for folder in _FOLDERS]
        forms += [name.upper(), "cfg/" + name.upper()]
        if any(not after.matches(_read_of(form), {}) for form in forms):
            left.append(name)
    for name in SECRET_NAMES[:: max(len(SECRET_NAMES) // 12, 1)]:  # a shell word counts too
        word: dict[str, Any] = {"hook_event_name": "beforeShellExecution", "command": f"cat {name}"}
        if name not in left and not after.matches(word, {}):
            left.append(name)
    return tuple(left)


def _read_of(path: str) -> dict[str, Any]:
    return {"hook_event_name": "beforeReadFile", "file_path": path}


def _then_problem(then: Clause) -> bool:
    return (
        then.events != ("shell",)
        or then.command_class != "outbound"
        or bool(then.path or then.path_except or then.command or then.host_not_in)
    )


def _minimum_problems(specs: Sequence[RuleSpec]) -> list[str]:
    """What is weaker in the file's R1 than SPEC section 5 allows; empty if nothing is."""
    where: str = f"rule {MARK_RULE}"
    r1: RuleSpec | None = next((spec for spec in specs if spec.id == MARK_RULE), None)
    if r1 is None:
        return [
            f"{where}: missing. Every rules file carries R1, the rule that blocks a send after a "
            "secret was read; AgentFly will not run without it (D27)"
        ]
    if r1.kind != "after_then" or r1.after is None or r1.then is None:
        return [f"{where}: must be an after_then rule (it is {r1.kind!r}), as in the default (D27)"]
    problems: list[str] = []
    if r1.severity != "block":
        problems.append(f'{where}: severity must stay "block" (it is {r1.severity!r}) (D27)')
    after: Clause = r1.after
    if after.command or after.command_class or after.host_not_in:
        problems.append(f"{where}: its 'after' may hold only event, path and path_except (D27)")
    if not {"read", "shell"} <= set(after.events):
        problems.append(f"{where}: its 'after' must fire on both read and shell (D27)")
    for pattern in after.path_except:
        if "/" in pattern.text:
            problems.append(
                f"{where}: exception {pattern.text!r} names a folder; R1 judges the file name only"
            )
        elif not pattern.text.endswith(EXEMPTION_ENDINGS):
            problems.append(
                f"{where}: exception {pattern.text!r} must end in a plain "
                f"{', '.join(EXEMPTION_ENDINGS)} (SPEC section 5 allows no other)"
            )
    if _then_problem(r1.then):
        problems.append(
            f"{where}: its 'then' must be exactly event = [\"shell\"] and command_class = "
            '"outbound", with no other condition (D27)'
        )
    left: tuple[str, ...] = _unmarked(after)
    if left:
        more: str = f" (and {len(left) - 1} more)" if len(left) > 1 else ""
        problems.append(
            f"{where}: its 'after' leaves {left[0]!r} unmarked{more}, but SPEC section 5 counts "
            "it as a secret; widen the lists or narrow the exceptions"
        )
    return problems


def _with_minimum(parsed: RuleFile) -> RuleFile:
    """The file with D27's findings added to its errors.

    Not run when it would only echo something already said: a file refused before its rules were
    read (no rules to judge), or one whose R1 already has an error of its own. Another rule's
    error does not stop it, so `rules check` prints every problem at once.
    """
    own: str = f"rule {MARK_RULE}"
    if parsed.errors and (
        not parsed.rules
        or any(e.startswith((own, WORK_ERROR)) for e in parsed.errors)  # its grid runs R1 hundreds
    ):  # of times: not on a clause that is already too heavy
        return parsed
    found: list[str] = _minimum_problems(parsed.rules)
    return replace(parsed, errors=(*parsed.errors, *found)) if found else parsed


# ---------------------------------------------------------------- files


# The sha256 of every `default.toml` the package has carried, oldest first, the current one last
# (D28). `init -g` replaces the installed rules file only when it is byte for byte one of these:
# nobody edited it. Add the new hash here, and keep the old ones, whenever `default.toml` changes;
# `tests/test_rules_shipped.py` fails until you do. The three earlier files are kept under
# `tests/fixtures/shipped_defaults/` so the hashes can be checked against the text.
SHIPPED_DEFAULTS: tuple[str, ...] = (
    "1b066ff522dd2f00cfaa451f62a1dc88071198b98d2296cbf4671fb85fe3beb9",  # V5b, R1 only
    "185c15585c6646cb25e146eeca328051b5ec714daf992436437784222f357d8d",  # V5b, + npm publish
    "50872ebe24b5cf25fb580523f2f541cd9a1dd0c92629d3accb5f86a873c93912",  # V5b, audit fixes
    "680680ea54608082a0fbcdaa713ed5a00c51424c20038f961dc08bf0f76968e8",  # V5b, review fixes
)


def is_older_default(sha: str) -> bool:
    """Is this the hash of a default the package once carried and no longer does? (D28)"""
    return sha in SHIPPED_DEFAULTS[:-1]


def default_path() -> Path:
    """The default rules inside the package (the wheel carries it)."""
    return Path(__file__).resolve().parent.parent / "rules" / "default.toml"


def default_text() -> str:
    """The default file's text. Raises OSError if it is missing. (`init -g` reads the bytes.)"""
    return default_path().read_text(encoding="utf-8")


def sha256_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_bytes(raw: bytes) -> RuleFile:
    """Read a rules file's bytes: size, UTF-8, TOML, then the checks. Never raises.

    Every reader of a rules file in the program comes through here, so no reader can skip a check.
    """
    return replace(_checked(raw), sha256=sha256_of(raw))


def _checked(raw: bytes) -> RuleFile:
    if len(raw) > MAX_FILE_BYTES:
        return _refused(f"too large (over {MAX_FILE_BYTES} bytes)")
    try:
        text: str = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _refused("not UTF-8 text")
    return _with_minimum(parse(text))


def load_file(path: Path) -> RuleFile:
    """Read and check a file (a draft, or the packaged default). Never raises.

    The messages do not name the file: whoever shows them says which file it was. The active file
    is read by `load_active_file`, which also checks who owns it.
    """
    try:
        if not path.is_file():
            return _refused("cannot be read: not a file")
        with path.open("rb") as handle:
            raw: bytes = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        return _refused(f"cannot be read: {exc.strerror or type(exc).__name__}")
    return load_bytes(raw)


class _Untrusted(Exception):
    """The active file is not one the recorder may believe; the text says why and what to do."""


def _who(uid: int) -> str:
    return "root" if uid == 0 else f"user id {uid}"


def _trusted_bytes(path: Path, uid: int) -> bytes:
    """The active file's bytes, if it is a plain file owned by `uid` that only `uid` can write.

    One descriptor does it all, so nothing can be swapped between the check and the read:
    `O_NOFOLLOW` refuses a link in the last place, `O_NONBLOCK` lets a named pipe open (and then
    fail the type check) instead of hanging the recorder at its start, and `fstat` looks at the
    file that was opened. A folder above it is not checked: the installer made it root's.
    """
    flags: int = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
    try:
        fd: int = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # also a link that points nowhere
            raise _Untrusted(
                "is a symbolic link; the recorder does not read a rules file through a link"
            ) from exc
        raise _Untrusted(f"cannot be read: {exc.strerror or type(exc).__name__}") from exc
    try:
        info: os.stat_result = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _Untrusted("is not a regular file")
        if info.st_uid != uid:
            raise _Untrusted(
                f"is owned by {_who(info.st_uid)}, not {_who(uid)}; if you trust what it says, "
                f"give it to {_who(uid)} (sudo chown, sudo chmod 644)"
            )
        if info.st_mode & 0o022:
            raise _Untrusted(
                f"can be written by group or others (mode {stat.S_IMODE(info.st_mode):04o}); "
                f"review what it says first, then sudo chmod 644 it"
            )
        chunks: list[bytes] = []
        total: int = 0
        while total <= MAX_FILE_BYTES:
            chunk: bytes = os.read(fd, MAX_FILE_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise _Untrusted(f"cannot be read: {exc.strerror or type(exc).__name__}") from exc
    finally:
        os.close(fd)


def load_active_file(path: Path, uid: int | None = None) -> RuleFile:
    """Read the active rules file the way the recorder does, trust check first. Never raises.

    `uid` is who must own it (default `ACTIVE_OWNER_UID`, read now). A file that is a link, not
    that user's, or writable by anyone else is refused like one with a syntax error.
    """
    try:
        raw: bytes = _trusted_bytes(path, ACTIVE_OWNER_UID if uid is None else uid)
    except _Untrusted as exc:
        return _refused(str(exc))
    return load_bytes(raw)


def is_active_path(path: Path) -> bool:
    """Is this the active file? (`rules check` and `rules test` then read it like the recorder.)"""
    if path == ACTIVE_RULES:
        return True
    try:
        return os.path.samefile(path, ACTIVE_RULES)
    except OSError:
        return False


def in_force_path() -> tuple[Path, bool]:
    """The file a recorder started now would read, and whether it is the active file.

    The active file counts as there when anything is at that path (a dangling link too: it is
    reported, not hidden); otherwise the packaged default is read.
    """
    if os.path.lexists(ACTIVE_RULES):
        return ACTIVE_RULES, True
    return default_path(), False


def load_default() -> RuleFile:
    return load_file(default_path())
