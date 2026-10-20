"""The matchers as they were before V5b-fix2, kept as the reference the new ones are held to.

`old_glob` and `old_matches` are `rulefile._glob` and `Pattern.matches` as they stood at the end of
V5b-fix, copied word for word (the method takes its pattern as the first argument). They are linear
in pattern times path, which is the cost the new matcher drops for patterns that do not float
(`tests/test_rules_matcher.py`).

`old_command_hit` is `Clause._command_hit` as it stood after the meter task (a loop over every entry
for every simple command), with its two helpers, copied word for word; the method's `self.command`
is its first argument (`tests/test_rules_meter.py` holds the index to it).
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import PurePosixPath

from agentfly.recorder.normalize import Parsed, base_name
from agentfly.recorder.rulefile import Pattern, _folded_segments, _home_segments


def old_glob(pattern: Sequence[str], segments: Sequence[str]) -> bool:
    """Match path segments against pattern segments; `**` is zero or more whole folders.

    Linear in pattern times path: it tracks the set of positions reached, with no backtracking.
    Every other part takes exactly one segment, so a position from which the parts still to come
    do not fit in the path is dropped at once, and a path that is too short (or, with no `**`,
    not exactly as long) is refused before any part is tried: a long pattern costs almost
    nothing on the short paths that make up most words.
    """
    total: int = len(segments)
    left: int = len(pattern) - pattern.count(
        "**"
    )  # parts that take one segment each, still to come
    if total < left or (left == len(pattern) and total != left):
        return False
    positions: set[int] = {0}
    for part in pattern:
        if part == "**":
            reached: set[int] = set(range(min(positions), total - left + 1))
        else:
            left -= 1
            last: int = total - left  # from a later position the rest cannot fit
            reached = {
                i + 1 for i in positions if i < last and fnmatch.fnmatchcase(segments[i], part)
            }
        if not reached:
            return False
        positions = reached
    return total in positions


def old_matches(self: Pattern, path: str, name: str | None = None) -> bool:
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
        return old_glob(self.parts, segments[len(base) :])
    if self.anchor == "root":
        return resolved.startswith("/") and old_glob(self.parts, segments)
    return old_glob(("**", *self.parts), segments)


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


def old_command_hit(command: tuple[tuple[str, ...], ...], parsed: Parsed) -> bool:
    """Some word is the program (by base name, so wrappers do not hide it) and the later
    words include every extra word, in any order.

    Only the first word that is the program needs a look: what follows a later one is a
    part of what follows the first. So a command is read once, however often it repeats the
    program (this runs on the event loop, under the hook client's 0.5 s wait).
    """
    for argv in parsed.all_commands():
        first: dict[str, int] = _first_positions(argv)
        last: dict[str, int] = _last_positions(argv)
        for program, *extras in command:
            at: int | None = first.get(program)
            if at is not None and all(last.get(extra, -1) > at for extra in extras):
                return True
    return False
