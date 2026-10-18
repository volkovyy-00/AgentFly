"""Which Cursor versions and hook events `init -g` may write for (D9, D23).

One unknown event name makes Cursor reject the whole hooks.json (S5), so an unknown version or
event means nothing is written. Versions are matched exactly (owner decision for V3a).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from agentfly.install import InstallError

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
    # UNVERIFIED (pending the V3a manual check): the owner's Mac runs 3.25.9. Remove this line
    # if AgentFly's hooks do not fire there.
    "3.25.9": _S5_VALID,
}


def installed_version(app: Path) -> str:
    """The version in Cursor.app's Info.plist, or InstallError."""
    plist: Path = app / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as handle:
            info = plistlib.load(handle)
        version = info["CFBundleShortVersionString"]
    except (OSError, plistlib.InvalidFileException, KeyError, ValueError) as exc:
        raise InstallError(
            f"cannot read the Cursor version from {plist} ({type(exc).__name__}); "
            "is Cursor installed in /Applications?"
        ) from exc
    if not isinstance(version, str):
        raise InstallError(f"{plist} has no Cursor version string")
    return version


def check(app: Path, events: tuple[str, ...] = EVENTS) -> str:
    """The installed Cursor version if it and every event are known, else InstallError."""
    version: str = installed_version(app)
    accepted: frozenset[str] | None = KNOWN_VERSIONS.get(version)
    if accepted is None:
        known: str = ", ".join(sorted(KNOWN_VERSIONS))
        raise InstallError(
            f"Cursor {version} is not on AgentFly's list of verified versions ({known}); "
            "nothing was written. A new AgentFly release adds a version once it is checked."
        )
    unknown: list[str] = [event for event in events if event not in accepted]
    if unknown:
        raise InstallError(
            f"Cursor {version} does not accept the event(s) {', '.join(unknown)}; "
            "nothing was written (one unknown event disables the whole hooks file)."
        )
    return version
