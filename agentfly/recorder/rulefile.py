"""The rules file (D10, SPEC section 5): read it, check it, match its patterns.

A rules file is TOML with `schema = 1`, one `[lists]` table of named lists and any number of
`[[rule]]` tables of kind `match` or `after_then`, each with inline `[[rule.test]]` tables. This
module is the data layer: `parse` turns text into `RuleSpec`s (or says what is wrong, naming the
rule), and a `Clause` answers "does this action fit?". It knows nothing about sessions or the
decision; `rules.py` builds the checks from these specs.

Nothing here raises on bad input and nothing reads an environment variable but `HOME` (through
`expanduser`). A file can be hostile or broken (it is root's file, but it is also read by a
recorder that must keep deciding), so every failure becomes a message. The program supplies the
engine-only command classes (`outbound`).
"""

from __future__ import annotations

import dataclasses
import errno
import fnmatch
import hashlib
import os
import posixpath
import re
import stat
import sys
import tomllib
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import accumulate
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

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
# slowest shapes tried (55 one-pattern rules; 5 floating "**" patterns; 7 ten-part patterns; paths
# 20 folders deep) take about 110 ms, a fifth of the wait. Deeper paths cost more: the same shapes
# at 40 folders take up to 0.3 s. The weights below are fitted to those measurements.
MAX_WORK: int = 200
WORK_CLAUSE: int = 2  # a clause with path patterns looks at every word of the command once
WORK_NAME: int = 1  # a pattern without "/" is one comparison per word
WORK_SLASH: int = 4  # a pattern with "/" is a walk through the path's folders ...
WORK_STAR: int = 12  # ... and each "**" (an unanchored pattern has one more) multiplies it
WORK_PARTS_FREE: int = 4  # WORK_SLASH covers a walk of this many folders and a file name ...
WORK_PART: int = 1  # ... each part past them is a step more for every position reached
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


class _Blocks(NamedTuple):
    """A pattern's parts split at each `**` into blocks of fixed length (see `_glob`).

    `head` is the part run before the first `**` (the whole pattern when there is none), `tail` the
    run after the last, `middle` the non-empty runs between two `**`. `fixed` is the number of
    parts that take one segment each, the length of the shortest path the pattern can match.
    """

    fixed: int
    star: bool  # some `**`; otherwise the path has to be exactly `fixed` long
    head: tuple[str, ...]
    middle: tuple[tuple[str, ...], ...]
    tail: tuple[str, ...]

    @property
    def floats(self) -> bool:
        """Some run has a `**` on each side: the only shape that has to walk the path."""
        return bool(self.middle)


def _split(pattern: Sequence[str]) -> _Blocks:
    runs: list[list[str]] = [[]]
    for part in pattern:
        if part == "**":
            runs.append([])
        else:
            runs[-1].append(part)
    fixed: int = sum(len(run) for run in runs)
    if len(runs) == 1:
        return _Blocks(fixed, False, tuple(runs[0]), (), ())
    middle: tuple[tuple[str, ...], ...] = tuple(tuple(run) for run in runs[1:-1] if run)
    return _Blocks(fixed, True, tuple(runs[0]), middle, tuple(runs[-1]))


def _part_hit(segment: str, part: str) -> bool:
    """One part against one segment; a bare `*` is any segment and needs no `fnmatch`."""
    return part == "*" or fnmatch.fnmatchcase(segment, part)


def _run_hit(block: Sequence[str], segments: Sequence[str], at: int) -> bool:
    """The parts of a block against the segments from `at`, each part once."""
    for offset, part in enumerate(block):
        if not _part_hit(segments[at + offset], part):
            return False
    return True


def _priced_run(block: Sequence[str], segments: Sequence[str], at: int) -> tuple[bool, int, int]:
    """`_run_hit` on the floating path: whether the block fits at `at`, what the compares made
    cost (§4.2: `compare_cost`, a bare `*` 1) and how many of them were a bare `*`."""
    steps: int = 0
    stars: int = 0
    for offset, part in enumerate(block):
        if part == "*":
            stars += 1
            continue
        segment: str = segments[at + offset]
        steps += 1 + len(segment) * len(part) // DIV  # compare_cost, inline: this is the hot loop
        if not fnmatch.fnmatchcase(segment, part):
            return False, steps + stars, stars
    return True, steps + stars, stars


def _place_middle(
    middle: Sequence[Sequence[str]], segments: Sequence[str], start: int, end: int
) -> bool:
    """Find each middle block, left to right, at the earliest place from `start` to `end` that
    follows the one before. Between `**` a block has a fixed length, so the earliest place is
    always the safe one. This is the only walk through the path: every start position tried is a
    step, charged with the compares it made once the block's walk is done, and a pattern with no
    middle block never gets here. A walk that has spent what the meter had left when it began is
    charged there and then (the charge raises), so it ends at most one start's work past the
    budget, however deep the path."""
    at: int = start
    for block in middle:
        last: int = end - len(block)  # the last place the block can start
        room: int = _room()
        starts: int = 0
        steps: int = 0
        stars: int = 0
        hit: bool = False
        while at <= last:
            starts += 1
            hit, cost, star = _priced_run(block, segments, at)
            steps += 1 + cost
            stars += star
            if hit:
                break
            at += 1
            if steps > room:  # a test that lifts the bound walks on, charging as it goes
                _tally(starts, stars)
                _charge(steps)
                room, starts, steps, stars = _room(), 0, 0, 0
        _tally(starts, stars)
        _charge(steps)
        if not hit:
            return False
        at += len(block)
    return True


def _float_glob(shape: _Blocks, segments: Sequence[str], tail_at: int) -> bool:
    """`_glob` for a pattern with a middle block: the same checks in the same order, priced.

    The head and the tail are charged together before any walk, so once the meter is spent a
    floating test raises before it walks, even when both are empty."""
    hit, steps, stars = _priced_run(shape.head, segments, 0)
    if hit:
        tail_hit, tail_steps, tail_stars = _priced_run(shape.tail, segments, tail_at)
        hit, steps, stars = tail_hit, steps + tail_steps, stars + tail_stars
    _tally(0, stars)
    _charge(steps)
    return hit and _place_middle(shape.middle, segments, len(shape.head), tail_at)


def _glob(pattern: Sequence[str], segments: Sequence[str], blocks: _Blocks | None = None) -> bool:
    """Match path segments against pattern segments; `**` is zero or more whole folders.

    The parts are split at each `**` into blocks of fixed length, and the block kinds are checked
    in a pinned order: the head at the start of the path, the tail at its end, then the middle
    blocks. A path whose end does not fit is refused after a few compares, and a pattern with no
    middle block (a head, a tail, or both) compares each part at most once, whatever the depth of
    the path, and is never charged. Every part but `**` takes exactly one segment, so a path that
    is too short (or, with no `**`, not exactly as long) is refused before any part is tried.

    When `blocks` is given, `pattern` is not read: `Pattern` passes the blocks it made once (for
    an unanchored pattern, those of its parts with the implicit `**` in front).
    """
    shape: _Blocks = blocks if blocks is not None else _split(pattern)
    total: int = len(segments)
    if total < shape.fixed or (not shape.star and total != shape.fixed):
        return False
    tail_at: int = total - len(shape.tail)
    if shape.middle:  # floating: the only shape that walks, and the only one the meter sees
        return _float_glob(shape, segments, tail_at)
    return _run_hit(shape.head, segments, 0) and _run_hit(shape.tail, segments, tail_at)


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
def _last_positions(argv: tuple[str, ...]) -> dict[str, int]:
    """Where each case-folded word of a command last stands (read only; shared by every clause),
    so that "this word comes after position p" is one comparison, not a scan of the rest."""
    return {word.casefold(): index for index, word in enumerate(argv)}


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


def _effective(anchor: str, parts: tuple[str, ...]) -> tuple[str, ...]:
    """The parts as matched: a pattern that may start anywhere has an implicit `**` in front."""
    return parts if anchor else ("**", *parts)


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
    # The parts split at `**` once, here, not at every test. It follows from `anchor` and `parts`,
    # so it is no part of the pattern's identity (as `Clause._index`).
    _blocks: _Blocks = dataclasses.field(init=False, hash=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_blocks", _split(_effective(self.anchor, self.parts)))

    def blocks(self) -> _Blocks:
        return self._blocks

    def matches(self, path: str, name: str | None = None, home: str | None = None) -> bool:
        """`name` is the path's folded file name when the caller has it already (one per path),
        `home` the home folder when the caller has it already (one per clause)."""
        if self.name_only:
            folded: str = name if name is not None else PurePosixPath(path).name.casefold()
            return fnmatch.fnmatchcase(folded, self.text)
        if home is None:
            home = os.path.expanduser("~")
        resolved, segments = _folded_segments(path, home)
        if self.anchor == "home":
            base: tuple[str, ...] = _home_segments(home)
            if segments[: len(base)] != base:
                return False
            return _glob(self.parts, segments[len(base) :], self._blocks)
        if self.anchor == "root":
            return resolved.startswith("/") and _glob(self.parts, segments, self._blocks)
        return _glob(self.parts, segments, self._blocks)


def floating(pattern: Pattern) -> bool:
    """True when the pattern has a run of parts with `**` on both sides (an unanchored pattern
    has an implicit `**` in front): `.ssh/**`, `a/**/b`, `**/x/**`. Only such a pattern walks the
    path; every other one compares each part at most once whatever the depth."""
    return not pattern.name_only and pattern._blocks.floats


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


# ---------------------------------------------------------------- meter

# What floating patterns may cost in one hook (spec §4.2). Every other pattern compares each part at
# most once per word, which `MAX_WORK` bounds; a floating one walks the path, so its tests are
# priced in steps and charged to the hook's meter. One `fnmatch` compare of a segment of n
# characters with a part of m costs `1 + n * m // DIV` (n * m = 2,048 measured at most 4.1 us,
# priced 9); a bare `*` and a start tried for a middle block cost 1. FLOAT_STEPS is priced so that a
# whole budget of the slowest kind of step takes at most 20 ms on the author's Mac. Measured on 300
# words 60 folders deep, best of three: short compares walking every folder (`d*/d*/d*/z0/**`) are
# the slowest, about 0.44 us a step, and a whole budget of them took 19.7 ms; a long compare (255
# characters against `*a*b*c`) costs about a third of its price, so DIV stays.
# Command lists charge the same meter (owner, 2026-10-21): a bucket of the index costs one step an
# entry and one a word left in it, charged before it is walked, and a run of key probes one step
# for four (a run of fewer charges nothing). Measured by the advisor: 0.35 us a step for one-word
# entries, 0.09 for long ones, at most 0.4 for probes, so a whole budget stays inside 20 ms.
# The walk over a line's simple commands is charged too (V5d): a clause makes at most one look-up
# of a program a word, so on a hook of 300 words it makes at most 300, and those are free; past
# that each costs PROGRAM_LOOKUP_STEPS, charged for the whole clause before it is walked. The free
# part is for each clause, not for the hook: 198 clauses can make 59,400 look-ups (about 130 ms)
# that the meter never sees, which real shapes need (198 rules on 150 `cat zN y` are never
# charged). Measured 2.2 us a look-up against 0.4 us a step. Tests pin all of these numbers.
DIV: int = 256
FLOAT_STEPS: int = 45_000
PROBES_PER_STEP: int = 4
PROGRAM_LOOKUPS_FREE: int = 300
PROGRAM_LOOKUP_STEPS: int = 4


class WorkLimit(Exception):
    """This hook's floating patterns and command lists have used up their steps; the rule being
    run is unfinished."""


@dataclass
class Meter:
    """One hook's budget of steps (floating patterns and command lists), and the rules it left
    unfinished (in order, once)."""

    left: int
    unfinished: list[str] = dataclasses.field(default_factory=list)

    def note(self, rule_id: str) -> None:
        if rule_id not in self.unfinished:
            self.unfinished.append(rule_id)


# This hook's meter, or None: then nothing is charged (pure tests, `rules test`, `doctor`, D27).
_METER: ContextVar[Meter | None] = ContextVar("agentfly_rules_meter", default=None)


@contextmanager
def metered(meter: Meter) -> Iterator[Meter]:
    """Run the block with `meter` as the hook's meter; the one before is back afterwards."""
    token = _METER.set(meter)
    try:
        yield meter
    finally:
        _METER.reset(token)


def current_meter() -> Meter | None:
    return _METER.get()


def compare_cost(n: int, m: int) -> int:
    """The steps one `fnmatch` compare costs: a segment of `n` characters, a part of `m`."""
    return 1 + n * m // DIV


def _charge(steps: int) -> None:
    """Every charge of a floating test or a command list comes here (a test replaces it to lift
    the bound). A charge that leaves the meter below 0 raises, so once it is spent every later
    charge raises too."""
    meter: Meter | None = _METER.get()
    if meter is None:
        return
    meter.left -= steps
    if meter.left < 0:
        raise WorkLimit


def _room() -> int:
    """What the meter has left, read once before a walk (with no meter, more than any walk)."""
    meter: Meter | None = _METER.get()
    return sys.maxsize if meter is None else meter.left


def _tally(starts: int, stars: int) -> None:
    """A seam for tests, called with each charge: the middle-block starts tried and the bare `*`
    compares made since the last one (a test counts the `fnmatch` compares by wrapping
    `fnmatch.fnmatchcase`). Does nothing."""


@lru_cache(maxsize=64)
def distinct_candidates(parsed: Parsed) -> tuple[str, ...]:
    """Every word of a command and what follows its last `=` and `@` (`_candidates`), each once,
    in first-seen order: a command that parses only partly repeats its words in the loose scan,
    and every clause with path patterns reads this one tuple."""
    return tuple(
        dict.fromkeys(
            candidate
            for argv in parsed.all_commands()
            for word in argv
            for candidate in _candidates(word)
        )
    )


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


class _Bucket(NamedTuple):
    """The entries under one key: their other extra words, and what reading them all costs (spec
    §4.2): a step an entry and one a word, charged before the bucket is walked."""

    weight: int
    rests: tuple[tuple[str, ...], ...]


# A clause's command list as the clause looks it up (spec §4.7): program -> key -> the bucket of
# entries under it. The key of an entry is its rarest extra word among that program's entries (the
# first of them on a tie), or None for an entry with no extra word.
_Keys = dict[str | None, _Bucket]
_Index = dict[str, _Keys]


def _bucket(rests: list[tuple[str, ...]]) -> _Bucket:
    kept: tuple[tuple[str, ...], ...] = tuple(dict.fromkeys(rests))
    return _Bucket(sum(1 + len(rest) for rest in kept), kept)


def _command_index(command: tuple[tuple[str, ...], ...]) -> _Index:
    """Index a command list. Identical entries are kept once. An entry waits under its rarest word,
    so it is looked at only in a command that has that word: entries that share a program and a
    first word (`cat w a0` ... `cat w a199`) are keyed apart. What is stored under a key is the
    entry's other extra words; the key word itself is known to hold by then."""
    entries: dict[str, list[tuple[str, ...]]] = {}
    for program, *extras in dict.fromkeys(command):
        entries.setdefault(program, []).append(tuple(extras))
    index: _Index = {}
    for program, listed in entries.items():
        held: Counter[str] = Counter(word for extras in listed for word in set(extras))
        keyed: dict[str | None, list[tuple[str, ...]]] = {}
        for extras in listed:
            key: str | None = min(extras, key=held.__getitem__) if extras else None
            keyed.setdefault(key, []).append(tuple(word for word in extras if word != key))
        index[program] = {key: _bucket(rests) for key, rests in keyed.items()}
    return index


def _key_lookups(count: int) -> None:
    """A seam for tests, called with the number of keys about to be looked up for one program of
    one simple command (a test counts them). Does nothing."""


def _probe(count: int) -> None:
    """Charge a run of `count` key probes before it is made: a step for four, nothing for fewer
    (so a short run still answers once the meter is spent)."""
    if count >= PROBES_PER_STEP:
        _charge(count // PROBES_PER_STEP)
    _key_lookups(count)


def _entry_follows(last: Mapping[str, int], at: int, extras: tuple[str, ...]) -> bool:
    """Every extra word of an entry stands after position `at` (`last`: `_last_positions`). Every
    entry the index cannot rule out comes here, so a test counts the calls."""
    return all(last.get(extra, -1) > at for extra in extras)


class _Simple(NamedTuple):
    """One simple command as the command lists read it (read only): where each program first
    stands, where each case-folded word last stands, and those words ordered by where they last
    stand with the positions. The words after position p are the tail from
    `bisect_right(positions, p)`, so how many there are is one search, not a scan."""

    first: dict[str, int]
    last: dict[str, int]
    words: tuple[str, ...]
    positions: tuple[int, ...]


def _simple_view(argv: tuple[str, ...]) -> _Simple:
    last: dict[str, int] = _last_positions(argv)
    ordered: list[str] = sorted(last, key=last.__getitem__)
    return _Simple(
        _first_positions(argv), last, tuple(ordered), tuple(last[word] for word in ordered)
    )


@lru_cache(maxsize=4)  # as `normalize`: mark, decide and the history flag read one line
def _simple_commands(parsed: Parsed) -> tuple[_Simple, ...]:
    """The views of a line's distinct simple commands, built once for all the clauses of the hook
    (a memo per simple command would be worked out again for every clause on a line with more
    of them than it holds). Equal simple commands share a view."""
    return tuple(_simple_view(argv) for argv in dict.fromkeys(parsed.all_commands()))


class _Sizes(NamedTuple):
    """The program counts of a line's simple commands, sorted, with their running sums: a clause
    that lists `L` programs makes at most `min(L, size)` look-ups in a simple command, so all of
    them at most `looked_up(L)`, in one search."""

    sizes: tuple[int, ...]
    sums: tuple[int, ...]  # sums[k] is the total of the k smallest sizes

    @classmethod
    def of(cls, counts: Iterable[int]) -> _Sizes:
        sizes: tuple[int, ...] = tuple(sorted(counts))
        return cls(sizes, tuple(accumulate(sizes, initial=0)))

    def looked_up(self, listed: int) -> int:
        below: int = bisect_right(self.sizes, listed)
        return self.sums[below] + listed * (len(self.sizes) - below)


@lru_cache(maxsize=4)  # as `_simple_commands`: one line, all the clauses of a hook
def _program_sizes(parsed: Parsed) -> _Sizes:
    return _Sizes.of(len(view.first) for view in _simple_commands(parsed))


def _charge_program_walk(listed: int, parsed: Parsed) -> None:
    """Charge a clause that lists `listed` programs for its walk over the line, before it walks."""
    over: int = _program_sizes(parsed).looked_up(listed) - PROGRAM_LOOKUPS_FREE
    if over > 0:
        _charge(PROGRAM_LOOKUP_STEPS * over)


def _bucket_hit(bucket: _Bucket, last: Mapping[str, int], at: int) -> bool:
    _charge(bucket.weight)
    return any(_entry_follows(last, at, rest) for rest in bucket.rests)


def _program_hit(keys: _Keys, view: _Simple, at: int) -> bool:
    """One listed program, first standing at `at` in a simple command: some entry holds. Of the
    program's keys and the distinct words after `at`, the smaller side is walked; the probes and
    each bucket walked are charged (spec §4.2)."""
    if None in keys:  # an entry with no extra word fires on the program alone
        return True
    last: dict[str, int] = view.last
    if len(keys) > 1:  # one key is looked up at once; more are weighed against the words after
        start: int = bisect_right(view.positions, at)
        if len(view.words) - start < len(keys):
            _probe(len(view.words) - start)
            for word in view.words[start:]:
                bucket = keys.get(word)
                if bucket is not None and _bucket_hit(bucket, last, at):
                    return True
            return False
    _probe(len(keys))
    for key, bucket in keys.items():
        if last.get(key, -1) > at and _bucket_hit(bucket, last, at):
            return True
    return False


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
    # `command` as a look-up table, made here (a clause built by hand has one too). It follows from
    # `command`, so it is no part of the clause's identity (a clause is hashed to cache a file).
    _index: _Index = dataclasses.field(
        default_factory=dict, init=False, hash=False, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", _command_index(self.command))

    def _path_hit(self, text: str, home: str) -> bool:
        name: str = _folded_name(text)
        return any(p.matches(text, name, home) for p in self.path) and not any(
            p.matches(text, name, home) for p in self.path_except
        )

    def _words_hit(self, parsed: Parsed) -> bool:
        home: str = os.path.expanduser("~")  # once for the clause, not for each pattern test
        return any(self._path_hit(candidate, home) for candidate in distinct_candidates(parsed))

    def _command_hit(self, parsed: Parsed) -> bool:
        """Some word is the program (by base name, so wrappers do not hide it) and the later
        words include every extra word, in any order.

        Only the first word that is the program needs a look: what follows a later one is a
        part of what follows the first. So a simple command is read once, however often it
        repeats the program or stands in the line, and its views are built once for the hook
        (this runs on the event loop, under the hook client's 0.5 s wait). `_index` says which
        entries to look at.
        """
        listed: _Index = self._index
        _charge_program_walk(len(listed), parsed)
        for view in _simple_commands(parsed):
            first: dict[str, int] = view.first
            if len(listed) <= len(first):  # walk the smaller side, look up the other
                for program, keys in listed.items():
                    at: int | None = first.get(program)
                    if at is not None and _program_hit(keys, view, at):
                        return True
            else:
                for program, at in first.items():
                    found: _Keys | None = listed.get(program)
                    if found is not None and _program_hit(found, view, at):
                        return True
        return False

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
            return not self.path or self._path_hit(
                _action_path(action, event), os.path.expanduser("~")
            )
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
    steps: int = len(pattern.parts) - pattern.parts.count("**")
    return WORK_SLASH + WORK_STAR * stars + WORK_PART * max(0, steps - WORK_PARTS_FREE)


def clause_work(clause: Clause | None) -> int:
    """What a clause costs per hook: a fixed part and its path patterns, which are tried on every
    word. A command is read once for all its clauses (where each program first, and each word
    last, stands; the host names), so an entry is a look-up and a long list of them costs
    nothing worth counting (measured: 198 rules of 200 entries on the command's own program
    take 31-35 ms for the whole hook, as the default alone does)."""
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
        pattern: Pattern = compile_pattern(raw)
        if not _every_path(pattern):
            return pattern
        problems.add(where, f"pattern {raw!r} matches every path")
    return None


def _every_path(pattern: Pattern) -> bool:
    """`/`, `./` and `./.` have no `*` in them, yet a trailing slash means "the folder and all in
    it", and a pattern that may start anywhere and names no folder is every path. (`~/` is the
    home folder, not every path.)"""
    if pattern.name_only or pattern.anchor == "home":
        return False
    return pattern.parts == ("**",) or (not pattern.anchor and not pattern.parts)


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
    for pattern in _patterns_of((clause, after, then), "path_except"):
        if floating(pattern):  # spec §4.6: it would walk every word of every command
            problems.add(where, f"exception {pattern.text!r} {FLOATING_EXCEPTION}")
    tests: tuple[InlineTest, ...] = _tests(where, raw.get("test"), problems)
    if len(problems.errors) > start:
        return None
    return RuleSpec(rid, kind, severity, message, clause, after, then, tests)


FLOATING_EXCEPTION: str = (
    "is checked at every folder of a path; an exception must be a name, anchored ('~/...' or "
    "'/...'), or end at the file name"
)


def _patterns_of(clauses: Sequence[Clause | None], field: str) -> tuple[Pattern, ...]:
    """The patterns of one field (`path` or `path_except`) in a rule's clauses, each once."""
    found: dict[Pattern, None] = {}
    for clause in clauses:
        if clause is not None:
            found.update(dict.fromkeys(getattr(clause, field)))
    return tuple(found)


def _floating_lint(spec: RuleSpec) -> list[str]:
    """Spec §4.4: a floating `path` pattern loads, and `rules check` says what it may cost."""
    return [
        f"rule {spec.id}: pattern {pattern.text!r} is checked at every folder of a path; on long, "
        f"deep commands it may reach the rules limit, which then blocks the action if {spec.id} "
        "is a block rule, asks if it is a warn, and skips it if it is a highlight; anchor it if "
        "you can"
        for pattern in _patterns_of((spec.clause, spec.after, spec.then), "path")
        if floating(pattern)
    ]


# A bucket heavier than this gets a `rules check` line (spec §4.4): ten entries of one word left.
HEAVY_BUCKET: int = 20


def _list_lint(spec: RuleSpec, raw: Mapping[str, Any]) -> list[str]:
    """Spec §4.4: a command list with a heavy bucket loads, and `rules check` says what it may
    cost, once per list the rule names, at its heaviest bucket."""
    tables: tuple[tuple[Clause | None, Any], ...] = (
        (spec.clause, raw),
        (spec.after, raw.get("after")),
        (spec.then, raw.get("then")),
    )
    heaviest: dict[str, tuple[int, int, str]] = {}  # list -> weight, entries, key
    for clause, table in tables:
        if clause is None or not clause.command:
            continue
        name: str = table["command"]
        for keys in clause._index.values():
            for key, bucket in keys.items():
                if key is not None and bucket.weight > heaviest.get(name, (HEAVY_BUCKET,))[0]:
                    heaviest[name] = (bucket.weight, len(bucket.rests), key)
    return [
        f"rule {spec.id}: {entries} entries of list {name!r} share the word {key!r} and are each "
        "checked when a command holds it; on long commands the rule may reach the rules limit"
        for name, (_, entries, key) in heaviest.items()
    ]


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
    heavy_lists: list[str] = []
    for number, raw in enumerate(raw_rules, 1):
        if (spec := _rule(number, raw, lists, seen, problems)) is not None:
            specs.append(spec)
            heavy_lists += _list_lint(spec, raw)
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
    lint += [line for spec in specs for line in _floating_lint(spec)]
    lint += heavy_lists
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
# refused (the packaged default runs). It is judged by the shape of R1's patterns, so no spelling of
# a list slips past it. Widening and rewording are fine.
# Measured against this, not against `default.toml`, so a wider later default never refuses an
# older file. A local exception (a company host) waits for the reviewed path (V7).


@dataclass(frozen=True)
class Family:
    """One bullet of SPEC section 5's secret file names, as the shape of a name (case folded).

    A name is in the family when it starts with `start`, ends with `end`, is at least as long as
    both together and does not end with one of `unless`. An `exact` family is the one name `start`,
    and its `end` is that same name, so the rule "a prefix of `start`, a suffix of `end`" reads the
    same on every family. `bullet` is SPEC's wording, for messages.
    """

    bullet: str
    start: str
    end: str
    exact: bool = False
    unless: tuple[str, ...] = ()

    def has(self, folded: str) -> bool:
        """Is this case-folded file name one SPEC section 5 counts as secret under this bullet?"""
        if self.exact:
            return folded == self.start
        return (
            folded.startswith(self.start)
            and folded.endswith(self.end)
            and len(folded) >= len(self.start) + len(self.end)
            and not folded.endswith(self.unless)
        )


# SPEC section 5's name bullets, in its order; the one place that says what counts as secret.
SECRET_FAMILIES: tuple[Family, ...] = (
    Family("any file named .env", ".env", ".env", exact=True),
    Family(
        "any file starting with .env. (for example .env.local), except ones ending in .example, "
        ".sample or .template",
        ".env.",
        "",
        unless=(".example", ".sample", ".template"),
    ),
    Family("any file ending in .pem", "", ".pem"),
    Family("any file ending in .key", "", ".key"),
    Family("any file whose name starts with id_rsa (but not .pub)", "id_rsa", "", unless=(".pub",)),
    Family("any file whose name starts with credentials", "credentials", ""),
)
# The two exceptions SPEC section 5 makes: `.env.*` but not a template, `id_rsa*` but not a public
# key. An exception in R1 may be no wider, so it starts with one of the two and ends with its own
# endings: then it cannot match `credentials-prod.example` or any other name SPEC counts as secret,
# which no list of sample names could prove for a pattern. Derived from the table; a pattern is
# written `.env*.example`, so it starts with `.env.` less its dot.
EXEMPTIONS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (family.start.removesuffix("."), family.unless) for family in SECRET_FAMILIES if family.unless
)


def spec_secret(name: str) -> bool:
    """Does SPEC section 5 count this file *name* as a secret? (Read from `SECRET_FAMILIES`.)"""
    folded: str = name.casefold()
    return any(family.has(folded) for family in SECRET_FAMILIES)


# R1's `after.path` is judged by the shape of its patterns, not on sample names (V5b-fix2 §6.2): for
# every family one name pattern must cover it. No `?`, no `[`, so a pattern is a literal or one `*`
# between two literals, and what it matches is plain: a name that starts with P, ends with Q and is
# at least as long as both. A union of narrower patterns that happens to cover is refused: no
# automaton, no samples.


def covers(text: str, family: Family) -> bool:
    """Does this case-folded name pattern (no `/`) match every name of the family?

    `P` (a literal) covers only the exact family, and only when it is that name. `P*Q` covers a
    family when P is a prefix of its start and Q a suffix of its end: every name of the family
    starts with its start, ends with its end and is at least as long as both, so it starts with P,
    ends with Q and leaves the `*` the rest. For the exact `.env` P and Q must also fit inside it.
    """
    if "?" in text or "[" in text or text.count("*") > 1:
        return False
    if "*" not in text:
        return family.exact and text == family.start
    head, tail = text.split("*")
    if not (family.start.startswith(head) and family.end.endswith(tail)):
        return False
    return not family.exact or len(head) + len(tail) <= len(family.start)


def _spelling(family: Family) -> str:
    """How the packaged default writes a pattern that covers the family (`.env`, `*.pem`)."""
    return family.start if family.exact else f"{family.start}*{family.end}"


def _anchored_hint(pattern: Pattern) -> str:
    """The pattern anchored at home, if that stops it floating; else the shape of one."""
    anchored: str = "~/" + pattern.text
    return repr(anchored) if not floating(compile_pattern(anchored)) else "'~/...'"


@lru_cache(maxsize=16)  # the same file is loaded again and again (a clause is hashable): once
def _coverage_problems(after: Clause) -> tuple[str, ...]:
    """R1's `after.path` by shape (D27): one error for each family no pattern covers, one for each
    floating folder pattern (§6.3: R1 is never cut short by the rules limit, so it may not walk)."""
    where: str = f"rule {MARK_RULE}"
    names: tuple[str, ...] = tuple(p.text for p in after.path if p.name_only)
    found: list[str] = [
        f"{where}: no pattern in its 'after' marks every name SPEC section 5 counts as secret "
        f"under {family.bullet!r}; add one such as {_spelling(family)!r} (a single `*` and no `?` "
        "or `[`) (D27)"
        for family in SECRET_FAMILIES
        if not any(covers(text, family) for text in names)
    ]
    found += [
        f"{where}: pattern {pattern.text!r} costs more the deeper a path is, and R1 is never cut "
        f"short; anchor it ({_anchored_hint(pattern)} or '/...') or put it in a rule of its own "
        "(D27)"
        for pattern in after.path
        if floating(pattern)
    ]
    return tuple(found)


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
        elif not any(
            pattern.text.startswith(start) and pattern.text.endswith(ends)
            for start, ends in EXEMPTIONS
        ):
            problems.append(
                f"{where}: exception {pattern.text!r} must be .env... ending in .example, .sample "
                "or .template, or id_rsa... ending in .pub: the two SPEC section 5 allows"
            )
    if _then_problem(r1.then):
        problems.append(
            f"{where}: its 'then' must be exactly event = [\"shell\"] and command_class = "
            '"outbound", with no other condition (D27)'
        )
    problems += _coverage_problems(after)
    return problems


def _with_minimum(parsed: RuleFile) -> RuleFile:
    """The file with D27's findings added to its errors.

    Not run when it would only echo something already said: a file refused before its rules were
    read (no rules to judge), or one whose R1 already has an error of its own. Another rule's
    error does not stop it, so `rules check` prints every problem at once.
    """
    # R1's own errors read `rule R1: …` or, from a clause or a test, `rule R1 after: …`,
    # `rule R1 then: …`, `rule R1 test #N: …`. The colon or the space: `rule R10: …` is another
    # rule's (an id has no space).
    ours: tuple[str, ...] = (f"rule {MARK_RULE}:", f"rule {MARK_RULE} ", WORK_ERROR)
    if parsed.errors and (
        not parsed.rules
        or any(e.startswith(ours) for e in parsed.errors)  # a file too heavy to run is
    ):  # refused already; what R1 lacks would only add words
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


def _check_trusted(fd: int, uid: int) -> None:
    """Is the open file regular, owned by `uid` and writable by no one else? (`fstat`; no read)"""
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


def _trust_fd(path: Path, uid: int) -> int:
    """Open the active file and check it; return the descriptor, which the caller closes.

    One descriptor does it all, so nothing can be swapped between the check and the read:
    `O_NOFOLLOW` refuses a link in the last place, `O_NONBLOCK` lets a named pipe open (and then
    fail the type check) instead of hanging the recorder at its start, and `fstat` looks at the
    file that was opened. A folder above it is not checked: the installer made it root's. The
    recorder, `doctor` and the installer all judge trust through this one function. A refused
    file is closed here and raises `_Untrusted`.
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
        _check_trusted(fd, uid)
    except _Untrusted:
        os.close(fd)
        raise
    except OSError as exc:
        os.close(fd)
        raise _Untrusted(f"cannot be read: {exc.strerror or type(exc).__name__}") from exc
    return fd


def trust_problem(path: Path, uid: int) -> str | None:
    """Why the recorder would not believe the file at `path`, or None if it would. Reads nothing.

    The same open and checks as the recorder's read of the active file (a plain file owned by
    `uid`, which no one else can write), and the same words.
    """
    try:
        fd: int = _trust_fd(path, uid)
    except _Untrusted as exc:
        return str(exc)
    os.close(fd)
    return None


def _trusted_bytes(path: Path, uid: int) -> bytes:
    """The active file's bytes, if it is a plain file owned by `uid` that only `uid` can write."""
    fd: int = _trust_fd(path, uid)
    try:
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
