"""Which Cursor versions and hook events `init -g` may write for (D9, D23).

One unknown event name makes Cursor reject the whole hooks.json (S5), so an unknown event means
nothing is written. A listed version is matched exactly. A version newer than the newest listed one
gets that one's events and a warning (D32); any other version is refused. The version comes from
Cursor.app's Info.plist, which the agent can rewrite, so it is compared only as dotted numbers.
"""

from __future__ import annotations

import plistlib
import re
from pathlib import Path
from xml.parsers.expat import ExpatError

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
_MAX_LENGTH = 32  # a real version is "3.26.13"; a longer one is not compared at all
_SHOWN = 40  # how much of a version a message prints


def installed_version(app: Path) -> str:
    """The version in Cursor.app's Info.plist, or InstallError."""
    plist: Path = app / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as handle:
            info = plistlib.load(handle)
        version = info["CFBundleShortVersionString"]
    except (OSError, plistlib.InvalidFileException, ExpatError, KeyError, ValueError) as exc:
        raise InstallError(
            f"cannot read the Cursor version from {plist} ({type(exc).__name__}); "
            "is Cursor installed in /Applications?"
        ) from exc
    if not isinstance(version, str):
        raise InstallError(f"{plist} has no Cursor version string")
    return version


def parts(version: str) -> tuple[int, ...] | None:
    """The numbers of a dotted version, or None: the length is tested before anything else."""
    if len(version) > _MAX_LENGTH or not _DOTTED.fullmatch(version):
        return None
    return tuple(int(part) for part in version.split("."))


def newest_verified() -> str:
    return max(KNOWN_VERSIONS, key=lambda version: parts(version) or ())


def listed() -> str:
    return ", ".join(sorted(KNOWN_VERSIONS, key=lambda version: parts(version) or ()))


def _newer(mine: tuple[int, ...], than: tuple[int, ...]) -> bool:
    """Part by part and numerically; a missing part is 0, so 3.25.9.0 is not newer than 3.25.9."""
    width = max(len(mine), len(than))
    return mine + (0,) * (width - len(mine)) > than + (0,) * (width - len(than))


def verified_as(version: str) -> str | None:
    """The listed version whose events `version` gets, or None when it is refused (D32).

    A listed version gets its own. One newer than the newest listed gets the newest's. One that is
    older, lies between listed versions, or is not dotted numbers gets none.
    """
    if version in KNOWN_VERSIONS:
        return version
    mine, newest = parts(version), newest_verified()
    if mine is not None and _newer(mine, parts(newest) or ()):
        return newest
    return None


def accepted_events(version: str) -> frozenset[str] | None:
    """The events Cursor `version` is checked against; None when AgentFly refuses the version."""
    verified = verified_as(version)
    return KNOWN_VERSIONS[verified] if verified is not None else None


def shown(version: str) -> str:
    """`version` as a message may print it: cut, and each unprintable character escaped."""
    cut = version if len(version) <= _SHOWN else version[:_SHOWN] + "\u2026"
    return packages.visible(cut)


def warning(version: str) -> str | None:
    """The one line `init -g` prints for a version it accepts without having checked it."""
    verified = verified_as(version)
    if verified is None or verified == version:
        return None
    return (
        f"warning: Cursor {shown(version)} is newer than the newest version AgentFly has checked "
        f"({verified}), so it registered {verified}'s events. If Cursor dropped one of them it may "
        f"ignore the whole hooks file. {ADVICE}"
    )


def check(app: Path, events: tuple[str, ...] = EVENTS) -> str:
    """The installed Cursor version if AgentFly accepts it and every event, else InstallError."""
    version: str = installed_version(app)
    accepted: frozenset[str] | None = accepted_events(version)
    if accepted is None:
        newest = newest_verified()
        if parts(version) is None:
            raise InstallError(
                f"Cursor {shown(version)} is not a plain dotted version number (like {newest}), "
                f"so AgentFly cannot tell whether it is newer than {newest}; nothing was written."
            )
        raise InstallError(
            f"Cursor {shown(version)} is not on AgentFly's list of verified versions ({listed()}) "
            f"and is not newer than {newest}; nothing was written. A new AgentFly release adds a "
            "version once it is checked."
        )
    unknown: list[str] = [event for event in events if event not in accepted]
    if unknown:
        verified = verified_as(version)
        against = "" if verified == version else f" (checked against {verified}'s events)"
        raise InstallError(
            f"Cursor {shown(version)} does not accept the event(s) {', '.join(unknown)}{against}; "
            "nothing was written (one unknown event disables the whole hooks file)."
        )
    return version
