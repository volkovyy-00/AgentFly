"""Cursor's Hooks log: did Cursor load AgentFly's system hooks? (V3a facts; SPEC 7, D23).

Cursor writes `~/Library/Application Support/Cursor/logs/<start time>/window*/output_*/
cursor.hooks.*.log`, one file per window. The newest start folder is the running Cursor. On every
(re)load a file gets one line per source: `Loaded N enterprise hook(s) for steps: a, b, ...`,
`No enterprise hooks configuration found`, or an `ERROR: Invalid <source> config: ...` followed by
`ERROR: Failed to parse <source> hooks configuration`. Seen sources are `user` and `project`; the
wording for the system file (Cursor calls it "enterprise") has not been seen, so an error line that
does not name a user, project, workspace or Claude source is taken to be about it. The last line
about the system file in a file is its current state.

The agent's user can write that folder, also while `doctor` walks it, so what is read from it is
bounded by counts: at most MAX_LOGS logs (none when there are more), each only if it is a plain
file once opened without blocking, at most _TAIL_BYTES from its end, and every line is matched in
time linear in its length. Every folder is opened once, without following a link, and the ones
below it are listed and opened through that open descriptor; a folder swapped for a link or a
non-folder is skipped, as a missing log is, and none is opened that was not there.
"""

from __future__ import annotations

import contextlib
import errno
import fnmatch
import os
import re
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

LOADED = re.compile(r"Loaded (\d+) enterprise hook\(s\) for steps: (.*)")
NONE = re.compile(r"No enterprise hooks configuration found")
# `Invalid <source> config` and `Failed to parse <source> hooks configuration`, as the pair of
# patterns `_between` takes: where the line names its source, and where the source ends.
INVALID = (re.compile(r"\bInvalid "), re.compile(r"config\b"))
UNPARSED = (re.compile(r"\bFailed to parse "), re.compile(r"hooks configuration\b"))
_RELEVANT = re.compile(r"enterprise|Invalid|Failed to parse")
_OTHER_SOURCES: tuple[str, ...] = ("user", "project", "workspace", "claude", "plugin")
_START_FOLDER = re.compile(r"[0-9]{8}T[0-9]{6}")  # fullmatch: `$` would take a trailing newline
_OPEN = os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC  # never wait, never a terminal
_FOLDER = _OPEN | os.O_DIRECTORY
_TAIL_BYTES = 4 << 20  # a long-running Cursor writes a lot; the last lines say how it stands
MAX_LOGS = 64  # a real start folder holds at most 4, one per window
_LOG_NAME = "cursor.hooks.*.log"  # in `<start folder>/window*/output_*/`


@dataclass(frozen=True)
class LogStatus:
    kind: str  # "loaded", "none" or "error"
    steps: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class Logs:
    folder: Path | None  # the newest Cursor start folder; None when Cursor has no logs
    files: tuple[Path, ...] = ()  # its Hooks logs, sorted; none when there are too many
    too_many: bool = False  # more than MAX_LOGS: none of them is listed


def _about_other_files(source: str) -> bool:
    return any(word in source.casefold() for word in _OTHER_SOURCES)


def _between(line: str, head: re.Pattern[str], tail: re.Pattern[str]) -> str | None:
    """The text between the first `head` and the first `tail` after it, stripped; None if either
    is missing.

    This stands in for the one pattern `\\bInvalid (.*?)\\s*config\\b`, which tries every
    `Invalid ` in the line and scans on to the line's end each time: a few thousand blanks make it
    cost seconds, and a megabyte of them hours, in a log the agent's user can write. Two searches
    look at no part of the line twice: if the first `head` has no `tail` after it, no later one has.
    """
    start = head.search(line)
    end = tail.search(line, start.end()) if start else None
    return line[start.end() : end.start()].strip() if start and end else None


def _error_source(line: str) -> str | None:
    """The source an `Invalid .. config` or `Failed to parse .. hooks configuration` line names."""
    source = _between(line, *INVALID)
    return source if source is not None else _between(line, *UNPARSED)


def status_of(text: str) -> LogStatus | None:
    """The state the last line about the system file gives, or None when there is none."""
    status: LogStatus | None = None
    for line in text.splitlines():
        if not _RELEVANT.search(line):  # a long log is mostly other lines: skip them cheaply
            continue
        loaded = LOADED.search(line)
        if loaded:
            steps = tuple(step.strip() for step in loaded[2].split(",") if step.strip())
            status = LogStatus("loaded", steps)
        elif NONE.search(line):
            status = LogStatus("none")
        else:
            source = _error_source(line)
            if source is not None and not _about_other_files(source):
                status = LogStatus("error", detail=line.split("] ", 1)[-1].strip())
    return status


def read_tail(path: Path) -> str:
    """The last _TAIL_BYTES of a plain file, decoded; OSError for anything else.

    The file is opened without blocking and judged on the descriptor, so a named pipe, a link to
    one, a device such as `/dev/zero` (also behind a link) or a folder is refused, never waited on
    or read. One `pread` takes at most _TAIL_BYTES, however much the file grows meanwhile. The
    same care as `cursor._read_plist` and the rules file's `rulefile._trust_fd`.
    """
    fd = os.open(path, _OPEN)
    try:
        size = os.fstat(fd)
        if not stat.S_ISREG(size.st_mode):
            raise OSError(errno.EINVAL, "not a plain file", str(path))
        tail = os.pread(fd, _TAIL_BYTES, max(0, size.st_size - _TAIL_BYTES))
    finally:
        os.close(fd)
    return tail.decode("utf-8", errors="replace")


@contextlib.contextmanager
def _folder(name: str | Path, parent: int | None = None) -> Iterator[int | None]:
    """The descriptor of the folder `name`, opened once; None when it is not one or cannot be.

    With `parent` (an open folder) `name` is looked up in it and a link is refused, not followed;
    without one a link is followed, as for any path. A pipe or a file fails `O_DIRECTORY` before
    anything is read or waited for.
    """
    flags = _FOLDER if parent is None else _FOLDER | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent)
    except OSError:
        yield None
        return
    try:
        yield fd
    finally:
        os.close(fd)


def _entries(fd: int) -> Iterator[os.DirEntry[str]]:
    """The entries of the open folder `fd`; none if it cannot be listed."""
    try:
        with os.scandir(fd) as entries:
            yield from entries
    except OSError:
        return


def _subfolders(fd: int, prefix: str = "") -> Iterator[str]:
    """The names in the open folder `fd` that start with `prefix` and are folders (not links)."""
    for entry in _entries(fd):
        try:
            wanted = entry.name.startswith(prefix) and entry.is_dir(follow_symlinks=False)
        except OSError:  # gone since the listing (a type is looked up only where none was given)
            continue
        if wanted:
            yield entry.name


def _hooks_logs(start_fd: int, start: Path) -> list[Path]:
    """`<start>/window*/output_*/cursor.hooks.*.log`, up to one more than MAX_LOGS: names only, no
    log is opened. Each folder is opened once, through the one above it, so the folders opened
    are among those that were listed."""
    found: list[Path] = []
    for window in _subfolders(start_fd, "window"):
        with _folder(window, start_fd) as window_fd:
            if window_fd is None:
                continue
            for output in _subfolders(window_fd, "output_"):
                with _folder(output, window_fd) as output_fd:
                    if output_fd is None:
                        continue
                    for entry in _entries(output_fd):
                        if fnmatch.fnmatchcase(entry.name, _LOG_NAME):
                            found.append(start / window / output / entry.name)
                            if len(found) > MAX_LOGS:
                                return found
    return found


def latest(home: Path) -> Logs:
    """The newest Cursor start folder and its Hooks logs: none of them when there are too many."""
    root = home / "Library" / "Application Support" / "Cursor" / "logs"
    # The path to Cursor's logs is the owner's (it may run through a link they made): `_folder`
    # follows it. Nothing below it is followed.
    with _folder(root) as root_fd:
        if root_fd is None:
            return Logs(None)
        # One pass, no list of the folders: the names are start times, so the largest is the newest.
        newest = max(
            (name for name in _subfolders(root_fd) if _START_FOLDER.fullmatch(name)), default=None
        )
        if newest is None:
            return Logs(None)
        folder = root / newest
        with _folder(newest, root_fd) as start_fd:
            if start_fd is None:  # swapped for a link or a non-folder since it was listed
                return Logs(folder)
            found = _hooks_logs(start_fd, folder)
    if len(found) > MAX_LOGS:
        return Logs(folder, too_many=True)
    return Logs(folder, tuple(sorted(found)))
