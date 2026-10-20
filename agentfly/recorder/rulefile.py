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

import fnmatch
import os
import posixpath
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agentfly.install.layout import SYSTEM
from agentfly.recorder.names import hosts_in_command
from agentfly.recorder.normalize import Parsed, base_name, normalize

# The file the recorder reads once at start. Tests (and nothing else) point this elsewhere; it is
# always read as `rulefile.ACTIVE_RULES`, never copied. No flag or variable moves it (D3, D25).
ACTIVE_RULES: Path = SYSTEM.rules

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
MAX_LIST_ENTRIES: int = 500
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


def _glob(pattern: tuple[str, ...], segments: list[str]) -> bool:
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


def _resolved(path: str) -> str:
    """A path as the shell would hand it on: a leading `~`, `$HOME` or `${HOME}` is the home
    folder, and `..` and `//` are folded (the text only; no link is followed)."""
    for prefix in ("~", "$HOME", "${HOME}"):
        if path == prefix or path.startswith(prefix + "/"):
            path = os.path.expanduser("~") + path[len(prefix) :]
            break
    return posixpath.normpath(path) if ".." in path or "//" in path else path


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
        resolved: str = _resolved(path)
        segments: list[str] = _segments(resolved.casefold())
        if self.anchor == "home":
            home: list[str] = _segments(os.path.expanduser("~").casefold())
            if segments[: len(home)] != home:
                return False
            return _glob(self.parts, segments[len(home) :])
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
    host_not_in: tuple[str, ...] = ()

    def _path_hit(self, text: str) -> bool:
        name: str = PurePosixPath(text).name.casefold()
        return any(p.matches(text, name) for p in self.path) and not any(
            p.matches(text, name) for p in self.path_except
        )

    def _words_hit(self, parsed: Parsed) -> bool:
        for argv in parsed.all_commands():
            for word in argv:
                if "=" in word or "@" in word:  # `--env-file=.env`, `-d@.env`
                    candidates = {word, word.rsplit("=", 1)[-1], word.rsplit("@", 1)[-1]}
                else:
                    candidates = {word}
                if any(self._path_hit(candidate) for candidate in candidates):
                    return True
        return False

    def _command_hit(self, parsed: Parsed) -> bool:
        """Some word is the program (by base name, so wrappers do not hide it) and the later
        words include every extra word, in any order.

        Only the first word that is the program needs a look: what follows a later one is a
        part of what follows the first. So a command is read once, however often it repeats the
        program (this runs on the event loop, under the hook client's 0.5 s wait).
        """
        for argv in parsed.all_commands():
            first: dict[str, int] = {}
            for index, word in enumerate(argv):
                first.setdefault(base_name(word), index)
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
            host.casefold() not in self.host_not_in
            for argv in parsed.all_commands()
            for host in hosts_in_command(argv)
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


def summary(errors: tuple[str, ...]) -> str:
    """One short line for `/health` and `doctor`: the first problem and how many more."""
    first: str = " ".join(errors[0].split()) if errors else "no problem"
    more: str = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    text: str = first + more
    return text if len(text) <= MAX_SUMMARY_CHARS else text[: MAX_SUMMARY_CHARS - 3] + "..."


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


def _path_pattern(where: str, raw: str, problems: _Problems) -> Pattern | None:
    if len(raw) > MAX_PATTERN_CHARS or "\x00" in raw:
        problems.add(where, f"pattern {raw[:40]!r} is too long or holds a NUL")
    elif raw.count("*") > MAX_STARS:
        problems.add(where, f"pattern {raw!r} has more than {MAX_STARS} wildcards")
    elif "*" in raw and not raw.strip("*?/"):
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
    hosts = tuple(e.casefold() for e in _named(where, table, "host_not_in", lists, problems))
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
    lint: list[str] = [
        f"rule {s.id}: no inline test; add a [[rule.test]]" for s in specs if not s.tests
    ]
    if not any(s.id == MARK_RULE and s.kind == "after_then" for s in specs):
        lint.append(
            f"no rule {MARK_RULE} (an after_then): a secret read still marks the chat, but "
            "nothing blocks the send that follows"
        )
    return RuleFile(tuple(specs), tuple(problems.errors), tuple(lint))


def parse(text: str) -> RuleFile:
    """Read a rules file's text. Never raises: whatever is wrong comes back in `errors`."""
    try:
        return _parse(text)
    except Exception as exc:  # noqa: BLE001 - a rules file must never crash the recorder
        return _refused(f"could not be read ({type(exc).__name__})")


# ---------------------------------------------------------------- files


def default_path() -> Path:
    """The default rules inside the package (the wheel carries it)."""
    return Path(__file__).resolve().parent.parent / "rules" / "default.toml"


def default_text() -> str:
    """The default file's text, for `init -g` to install. Raises OSError if it is missing."""
    return default_path().read_text(encoding="utf-8")


def load_file(path: Path) -> RuleFile:
    """Read and parse a file. Never raises; a file that cannot be read is an error message.

    The messages do not name the file: whoever shows them says which file it was.
    """
    try:
        if not path.is_file():
            return _refused("cannot be read: not a file")
        with path.open("rb") as handle:
            raw: bytes = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        return _refused(f"cannot be read: {exc.strerror or type(exc).__name__}")
    if len(raw) > MAX_FILE_BYTES:
        return _refused(f"too large (over {MAX_FILE_BYTES} bytes)")
    try:
        text: str = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _refused("not UTF-8 text")
    return parse(text)


def load_default() -> RuleFile:
    return load_file(default_path())
