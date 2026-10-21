"""Which Cursor versions and hook events `init -g` may write for (D9, D23).

One unknown event name makes Cursor reject the whole hooks.json (S5), so an unknown event means
nothing is written. A listed version is matched exactly. A version newer than the newest listed one
gets that one's events and a warning (D32); any other version is refused. The version comes from
Cursor.app's Info.plist, which the agent can rewrite, so the file is read as XML only, at most
MAX_PLIST_BYTES of it, and the version is compared only as dotted numbers.
"""

from __future__ import annotations

import os
import plistlib
import re
import stat
from pathlib import Path

from agentfly.install import InstallError, packages

# D9 A with D21 A: the four gates, afterFileEdit, sessionStart, sessionEnd, subagentStart.
EVENTS: tuple[str, ...] = (
    "beforeShellExecution",
    "beforeReadFile",
    "beforeMCPExecution",
    "preToolUse",
    "afterFileEdit",
    "sessionStart",
    "sessionEnd",
    "subagentStart",
)

# The 21 names Cursor 3.24.12 listed as valid in its own error message (S5 section 2).
_S5_VALID: frozenset[str] = frozenset(
    """sessionStart sessionEnd preToolUse postToolUse postToolUseFailure subagentStart
    subagentStop beforeShellExecution afterShellExecution beforeMCPExecution afterMCPExecution
    beforeReadFile afterFileEdit beforeSubmitPrompt preCompact stop afterAgentResponse
    afterAgentThought beforeTabFileRead afterTabFileEdit workspaceOpen""".split()
)

KNOWN_VERSIONS: dict[str, frozenset[str]] = {
    "3.24.12": _S5_VALID,  # verified by spike S5
    # V3a manual check (2026-10-18): Cursor logged "Loaded 8 enterprise hook(s)" for all eight
    # events and ran them on real actions.
    "3.25.9": _S5_VALID,
}

ADVICE = "After any Cursor update, quit and reopen Cursor, then run `agentfly doctor`."

_DOTTED = re.compile(r"[0-9]+(?:\.[0-9]+)*")  # [0-9]: `\d` also takes other scripts' digits
_MAX_LENGTH = 32  # a real version is "3.26.13"; a longer one is not compared, and printed cut
MAX_PLIST_BYTES = 1 << 20  # Cursor's Info.plist is a few KB; the agent can write a huge one
_BOM = b"\xef\xbb\xbf"
_XML_START = (b"<?xml", b"<plist")  # what plistlib itself takes for XML


class _Refused(ValueError):
    """A file the Cursor version is not read from; the text says why."""


def _read_plist(plist: Path) -> bytes:
    """The bytes of a plain file of at most MAX_PLIST_BYTES, else _Refused or OSError.

    `O_NONBLOCK` lets a named pipe open and then fail the type check, where a plain `open` would
    wait for a writer for ever (the same care as the rules file's, `rulefile._trust_fd`). The type
    is checked on the descriptor before it is wrapped: `os.fdopen` on a folder raises and keeps the
    descriptor open.
    """
    fd = os.open(plist, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _Refused("not a regular file")
        handle = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        data = handle.read(MAX_PLIST_BYTES + 1)
    if len(data) > MAX_PLIST_BYTES:
        raise _Refused("too large")
    return data


def _require_xml(data: bytes) -> bytes:
    """`data` if it starts as an XML property list, else _Refused.

    A binary plist is refused unparsed: plistlib's binary reader copies an object once for each
    object number that points at it, so under 1 MiB can cost hundreds. XML has no shared objects.
    """
    if not data.removeprefix(_BOM).startswith(_XML_START):
        raise _Refused("not XML: AgentFly reads only an XML property list")
    return data


def installed_version(app: Path) -> str:
    """The version in Cursor.app's Info.plist, or InstallError.

    The agent can write the file, and plistlib raises whatever a malformed one makes it raise
    (ExpatError, LookupError, IndexError, TypeError, AttributeError, ...): whatever it is, the
    answer is a version or this one error, so `init -g` and `doctor` never end in a traceback.
    A named pipe, a file over MAX_PLIST_BYTES and a file that is not XML are refused unparsed.
    """
    plist: Path = app / "Contents" / "Info.plist"
    try:
        info = plistlib.loads(_require_xml(_read_plist(plist)), fmt=plistlib.FMT_XML)
        version = info["CFBundleShortVersionString"]
    except Exception as exc:
        reason = str(exc) if isinstance(exc, _Refused) else type(exc).__name__
        raise InstallError(
            f"cannot read the Cursor version from {plist} ({reason}); "
            "is Cursor installed in /Applications?"
        ) from exc
    if not isinstance(version, str):
        raise InstallError(f"{plist} has no Cursor version string")
    return version


def parts(version: str) -> tuple[int, ...]:
    """The numbers of a dotted version, or () when it is not one: the length is tested first."""
    if len(version) > _MAX_LENGTH or not _DOTTED.fullmatch(version):
        return ()
    return tuple(int(part) for part in version.split("."))


def newest_verified() -> str:
    return max(KNOWN_VERSIONS, key=parts)


def listed() -> str:
    return ", ".join(sorted(KNOWN_VERSIONS, key=parts))


def _newer(mine: tuple[int, ...], than: tuple[int, ...]) -> bool:
    """Part by part and numerically; a missing part is 0, so 3.25.9.0 is not newer than 3.25.9."""
    width = max(len(mine), len(than))
    return mine + (0,) * (width - len(mine)) > than + (0,) * (width - len(than))


def stand_in(version: str) -> str | None:
    """The newest listed version, whose events an unlisted `version` newer than it gets (D32)."""
    newest = newest_verified()
    mine = parts(version)
    return newest if mine and _newer(mine, parts(newest)) else None


def verified_as(version: str) -> str | None:
    """The listed version whose events `version` gets, or None when AgentFly refuses it.

    A listed version gets its own, a newer one the newest's. One that is older, lies between
    listed versions, or is not dotted numbers gets none.
    """
    return version if version in KNOWN_VERSIONS else stand_in(version)


def accepted_events(version: str) -> frozenset[str] | None:
    """The events Cursor `version` is checked against; None when AgentFly refuses the version."""
    verified = verified_as(version)
    return KNOWN_VERSIONS[verified] if verified is not None else None


def refusal(version: str) -> str:
    """Why AgentFly refuses `version` (one `verified_as` gives None for), as a clause."""
    newest = newest_verified()
    if not parts(version):
        return (
            f"is not a plain dotted version number (like {newest}), so AgentFly cannot tell "
            f"whether it is newer than {newest}"
        )
    return (
        f"is not on AgentFly's list of verified versions ({listed()}) "
        f"and is not newer than {newest}"
    )


def checked_against(version: str) -> str:
    """A clause for a message about events: whose events an unchecked `version` stands on."""
    stand = stand_in(version)
    return f" (checked against {stand}'s events)" if stand else ""


def shown(version: str) -> str:
    """`version` as a message may print it: cut, and each unprintable character escaped."""
    cut = version if len(version) <= _MAX_LENGTH else version[:_MAX_LENGTH] + "\u2026"
    return packages.visible(cut)


def warning(version: str) -> str | None:
    """The one line `init -g` prints for a version it accepts without having checked it."""
    stand = stand_in(version)
    if stand is None:
        return None
    return (
        f"warning: Cursor {shown(version)} is newer than the newest version AgentFly has checked "
        f"({stand}), so AgentFly's hooks use {stand}'s events. If Cursor dropped one of them it "
        f"may ignore the whole hooks file. {ADVICE}"
    )


def check(app: Path, events: tuple[str, ...] = EVENTS) -> str:
    """The installed Cursor version if AgentFly accepts it and every event, else InstallError."""
    version: str = installed_version(app)
    verified: str | None = verified_as(version)
    if verified is None:
        raise InstallError(
            f"Cursor {shown(version)} {refusal(version)}; nothing was written. "
            "A new AgentFly release adds a version once it is checked."
        )
    unknown: list[str] = [event for event in events if event not in KNOWN_VERSIONS[verified]]
    if unknown:
        raise InstallError(
            f"Cursor {shown(version)} does not accept the event(s) {', '.join(unknown)}"
            f"{checked_against(version)}; nothing was written "
            "(one unknown event disables the whole hooks file)."
        )
    return version
