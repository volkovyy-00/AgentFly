"""Cursor's Hooks log: did Cursor load AgentFly's system hooks? (V3a facts; SPEC 7, D23).

Cursor writes `~/Library/Application Support/Cursor/logs/<start time>/window*/output_*/
cursor.hooks.*.log`, one file per window. The newest start folder is the running Cursor. On every
(re)load a file gets one line per source: `Loaded N enterprise hook(s) for steps: a, b, ...`,
`No enterprise hooks configuration found`, or an `ERROR: Invalid <source> config: ...` followed by
`ERROR: Failed to parse <source> hooks configuration`. Seen sources are `user` and `project`; the
wording for the system file (Cursor calls it "enterprise") has not been seen, so an error line that
does not name a user, project, workspace or Claude source is taken to be about it. The last line
about the system file in a file is its current state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LOADED = re.compile(r"Loaded (\d+) enterprise hook\(s\) for steps: (.*?)\s*$")
NONE = re.compile(r"No enterprise hooks configuration found")
INVALID = re.compile(r"\bInvalid (?P<source>.*?)\s*config\b")
UNPARSED = re.compile(r"\bFailed to parse (?P<source>.*?)\s*hooks configuration\b")
_RELEVANT = re.compile(r"enterprise|Invalid|Failed to parse")
_OTHER_SOURCES: tuple[str, ...] = ("user", "project", "workspace", "claude", "plugin")
_START_FOLDER = re.compile(r"^\d{8}T\d{6}$")
_TAIL_BYTES = 4 << 20  # a long-running Cursor writes a lot; the last lines say how it stands


@dataclass(frozen=True)
class LogStatus:
    kind: str  # "loaded", "none" or "error"
    steps: tuple[str, ...] = ()
    detail: str = ""


def _about_other_files(source: str) -> bool:
    return any(word in source.casefold() for word in _OTHER_SOURCES)


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
            error = INVALID.search(line) or UNPARSED.search(line)
            if error and not _about_other_files(error["source"]):
                status = LogStatus("error", detail=line.split("] ", 1)[-1].strip())
    return status


def read_tail(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - _TAIL_BYTES))
        return handle.read().decode("utf-8", errors="replace")


def latest(home: Path) -> tuple[Path | None, list[Path]]:
    """The newest Cursor start folder and the Hooks logs in it (None when Cursor has no logs)."""
    root = home / "Library" / "Application Support" / "Cursor" / "logs"
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and _START_FOLDER.match(p.name))
    except OSError:
        folders = []
    if not folders:
        return None, []
    return folders[-1], sorted(folders[-1].glob("window*/output_*/cursor.hooks.*.log"))
