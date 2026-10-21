"""Cursor's Hooks log: did Cursor load AgentFly's system hooks? (V3a facts; SPEC 7, D23).

Cursor writes `~/Library/Application Support/Cursor/logs/<start time>/window*/output_*/
cursor.hooks.*.log`, one file per window. The newest start folder is the running Cursor. On every
(re)load a file gets one line per source: `Loaded N enterprise hook(s) for steps: a, b, ...`,
`No enterprise hooks configuration found`, or an `ERROR: Invalid <source> config: ...` followed by
`ERROR: Failed to parse <source> hooks configuration`. Seen sources are `user` and `project`; the
wording for the system file (Cursor calls it "enterprise") has not been seen, so an error line that
does not name a user, project, workspace or Claude source is taken to be about it. The last line
about the system file in a file is its current state.

The agent's user can write that folder, so what is read from it is bounded by counts: at most
MAX_LOGS logs (none when there are more), each only if it is a plain file once opened without
blocking, at most _TAIL_BYTES from its end, and every line is matched in time linear in its length.
"""

from __future__ import annotations

import errno
import itertools
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

LOADED = re.compile(r"Loaded (\d+) enterprise hook\(s\) for steps: (.*)")
NONE = re.compile(r"No enterprise hooks configuration found")
# `Invalid <source> config` and `Failed to parse <source> hooks configuration`: see `_between`.
INVALID = ("Invalid ", "config")
UNPARSED = ("Failed to parse ", "hooks configuration")
_RELEVANT = re.compile(r"enterprise|Invalid|Failed to parse")
_OTHER_SOURCES: tuple[str, ...] = ("user", "project", "workspace", "claude", "plugin")
_START_FOLDER = re.compile(r"^\d{8}T\d{6}$")
_TAIL_BYTES = 4 << 20  # a long-running Cursor writes a lot; the last lines say how it stands
MAX_LOGS = 64  # a real start folder holds at most 4, one per window
_LOG_PATTERN = "window*/output_*/cursor.hooks.*.log"


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


def _word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _between(line: str, head: str, tail: str) -> str | None:
    """The text between the first `head` that starts a word and the first `tail` after it that
    ends one, stripped; None when there is no such pair.

    This stands in for the regex `\\bhead(.*?)\\s*tail\\b`, which tries every `head` in the line and
    scans on to the line's end each time: a few thousand spaces make it cost seconds, and a
    megabyte of them hours, in a log the agent's user can write. Here no part of the line is looked
    at twice: if the first `head` has no `tail` after it, no later `head` has one either.
    """
    start = line.find(head)
    while start > 0 and _word_char(line[start - 1]):
        start = line.find(head, start + 1)
    if start < 0:
        return None
    begin = start + len(head)
    end = line.find(tail, begin)
    while end >= 0 and _word_char(line[end + len(tail) : end + len(tail) + 1]):
        end = line.find(tail, end + 1)
    return line[begin:end].strip() if end >= 0 else None


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
    or read. The type is checked before the descriptor is wrapped: `os.fdopen` on a folder raises
    and keeps the descriptor open. The same care as `cursor._read_plist` and the rules file's
    `rulefile._trust_fd`.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "not a plain file", str(path))
        handle = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.seek(max(0, info.st_size - _TAIL_BYTES))
        return handle.read(_TAIL_BYTES).decode("utf-8", errors="replace")


def latest(home: Path) -> Logs:
    """The newest Cursor start folder and its Hooks logs: none of them when there are too many."""
    root = home / "Library" / "Application Support" / "Cursor" / "logs"
    try:
        folders = [p for p in root.iterdir() if _START_FOLDER.match(p.name) and p.is_dir()]
    except OSError:
        folders = []
    if not folders:
        return Logs(None)
    newest = max(folders)  # the names are start times
    found = list(itertools.islice(newest.glob(_LOG_PATTERN), MAX_LOGS + 1))
    if len(found) > MAX_LOGS:
        return Logs(newest, too_many=True)
    return Logs(newest, tuple(sorted(found)))
