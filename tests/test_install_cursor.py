"""Which Cursor versions and events `init -g` accepts (D23, D32)."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from agentfly.install import InstallError, cursor
from agentfly.install.layout import Layout
from tests.install_helpers import make_cursor_app, make_layout

# The newest version AgentFly has checked, and one that is newer than it. The card that lists
# NEWER changes this one line.
NEWEST = "3.25.9"
NEWER = "3.26.13"

ADVICE = "quit and reopen Cursor, then run `agentfly doctor`"


def plist_bytes(version: str) -> bytes:
    """An Info.plist holding `version`; binary, because XML cannot hold a control character."""
    return plistlib.dumps({"CFBundleShortVersionString": version}, fmt=plistlib.FMT_BINARY)


def write_plist(layout: Layout, data: bytes) -> None:
    plist = layout.cursor_app / "Contents" / "Info.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(data)


def write_version(layout: Layout, version: str) -> None:
    write_plist(layout, plist_bytes(version))


def check_version(tmp_path: Path, version: str, *events: str) -> str:
    layout = make_layout(tmp_path)
    write_version(layout, version)
    return cursor.check(layout.cursor_app, events or cursor.EVENTS)


@pytest.mark.parametrize("version", ["3.24.12", "3.25.9"])
def test_a_listed_version_passes_with_its_own_events_and_no_warning(
    tmp_path: Path, version: str
) -> None:
    assert check_version(tmp_path, version) == version
    assert cursor.verified_as(version) == version
    assert cursor.accepted_events(version) == cursor.KNOWN_VERSIONS[version]
    assert cursor.warning(version) is None


NEWER_VERSIONS = {
    "next release": NEWER,
    "next patch": "3.25.10",
    "four parts": "3.25.9.1",
    "leading zero": "3.025.10",
    "next major": "4.0",
    "far ahead": "9.9.9",
}


@pytest.mark.parametrize("version", NEWER_VERSIONS.values(), ids=NEWER_VERSIONS.keys())
def test_a_version_newer_than_the_newest_listed_gets_the_newest_events_and_a_warning(
    tmp_path: Path, version: str
) -> None:
    assert check_version(tmp_path, version) == version  # the real version, not the listed one
    assert cursor.verified_as(version) == NEWEST
    assert cursor.accepted_events(version) == cursor.KNOWN_VERSIONS[NEWEST]
    warning = cursor.warning(version)
    assert warning is not None and "\n" not in warning
    assert version in warning and NEWEST in warning and ADVICE in warning


REFUSED = {
    "older than every listed": "1.0.0",
    "between listed ones": "3.25.0",
    "just under the newest": "3.24.13",
    "the newest with a zero part": "3.25.9.0",
    "the newest with a leading zero": "3.025.9",
    "a beta tag": "3.26.13-beta",
    "letters": "x.y",
    "empty": "",
    "a trailing dot": "3.26.",
    "an empty part": "3..1",
    "a leading space": " 3.26.13",
    "a trailing newline": "3.26.13\n",
    "an embedded newline": "3.26\n13",
    "an escape sequence": "3.26\x1b[2K",
    "non-ASCII digits": "٣.٢٦.١٣",
    "10,000 digits": "9" * 10_000,
    "10,000 characters of newer parts": "9." * 5_000 + "9",
}


@pytest.mark.parametrize("version", REFUSED.values(), ids=REFUSED.keys())
def test_any_other_version_is_refused_in_one_line_and_nothing_is_written(
    tmp_path: Path, version: str
) -> None:
    assert cursor.verified_as(version) is None
    assert cursor.warning(version) is None
    with pytest.raises(InstallError) as caught:
        check_version(tmp_path, version)
    message = str(caught.value)
    assert "nothing was written" in message
    assert "\n" not in message and "\x1b" not in message  # shown escaped, as the F13 names are
    assert len(message) < 500  # a 10,000-character version is cut, not printed


def test_a_version_is_shown_with_its_control_characters_escaped(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match=r"Cursor 3\.26\\n13 "):
        check_version(tmp_path, "3.26\n13")
    with pytest.raises(InstallError, match=r"Cursor 3\.26\\x1b\[2K "):
        check_version(tmp_path, "3.26\x1b[2K")


def test_a_version_that_cannot_be_compared_is_not_called_not_newer(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match=r"Cursor 3\.26\.13-beta is not a plain dotted version"):
        check_version(tmp_path, "3.26.13-beta")


def test_a_refusal_names_the_listed_versions_and_the_newest(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match=r"Cursor 1\.0\.0 .*\(3\.24\.12, 3\.25\.9\).*3\.25\.9"):
        check_version(tmp_path, "1.0.0")


def nested_binary_plist(depth: int) -> bytes:
    """`depth` arrays each holding the next, then an integer; written flat, so no recursion here."""
    body = b"".join(b"\xa1" + (i + 1).to_bytes(2, "big") for i in range(depth)) + b"\x10\x01"
    offsets = b"".join((8 + 3 * i).to_bytes(2, "big") for i in range(depth + 1))
    trailer = bytes(6) + bytes([2, 2]) + (depth + 1).to_bytes(8, "big") + bytes(8)
    return b"bplist00" + body + offsets + trailer + (8 + len(body)).to_bytes(8, "big")


MALFORMED_PLISTS = {
    "a mismatched tag": b'<?xml version="1.0"?><plist version="1.0"><dict><key>a</key>'
    b"<string>x</dict></plist>",
    "a truncated file": b'<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundle',
    "a control character reference": b'<?xml version="1.0"?><plist version="1.0"><dict>'
    b"<key>CFBundleShortVersionString</key><string>3.26&#x1b;</string></dict></plist>",
    "not a plist": b"\xff\xfe junk",
    "empty": b"",
    "a list, not a dictionary": plistlib.dumps(["3.26.13"], fmt=plistlib.FMT_BINARY),
    "a date plistlib cannot read": b'<?xml version="1.0"?><plist version="1.0"><dict>'
    b"<key>CFBundleShortVersionString</key><date>9999999-01-01T00:00:00Z</date></dict></plist>",
    "nested deeper than plistlib reads": nested_binary_plist(2_000),
}


@pytest.mark.parametrize("data", MALFORMED_PLISTS.values(), ids=MALFORMED_PLISTS.keys())
def test_a_plist_that_cannot_be_read_is_one_refusal_not_a_traceback(
    tmp_path: Path, data: bytes
) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, data)
    with pytest.raises(InstallError, match="cannot read the Cursor version"):
        cursor.check(layout.cursor_app)


def test_a_plist_without_a_version_is_refused(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, plistlib.dumps({"CFBundleShortVersionString": 3}))
    with pytest.raises(InstallError, match="no Cursor version string"):
        cursor.check(layout.cursor_app)


def test_an_event_the_cursor_does_not_accept_is_refused_and_named(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    with pytest.raises(InstallError, match="afBogusEvent"):
        cursor.check(layout.cursor_app, (*cursor.EVENTS, "afBogusEvent"))


def test_an_event_the_newest_version_does_not_accept_is_refused_for_a_newer_cursor_too(
    tmp_path: Path,
) -> None:
    with pytest.raises(InstallError, match=rf"afBogusEvent.*{NEWEST}.*nothing was written"):
        check_version(tmp_path, NEWER, *cursor.EVENTS, "afBogusEvent")


def test_a_missing_cursor_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match="cannot read the Cursor version"):
        cursor.check(tmp_path / "Cursor.app")


def test_every_listed_version_is_dotted_numbers_and_the_newest_is_the_largest() -> None:
    parsed = {version: cursor.parts(version) for version in cursor.KNOWN_VERSIONS}
    assert all(parsed.values()), "a listed version that is not dotted numbers cannot be compared"
    assert cursor.newest_verified() == NEWEST == max(cursor.KNOWN_VERSIONS, key=parsed.__getitem__)
    assert NEWEST in cursor.KNOWN_VERSIONS and cursor.verified_as(NEWER) == NEWEST


def test_the_registered_events_are_the_d9_list_and_all_in_the_s5_dump() -> None:
    assert set(cursor.EVENTS) == {
        "beforeShellExecution",
        "beforeReadFile",
        "beforeMCPExecution",
        "preToolUse",
        "afterFileEdit",
        "sessionStart",
        "sessionEnd",
        "subagentStart",
    }
    assert set(cursor.EVENTS) <= cursor.KNOWN_VERSIONS["3.24.12"]
    for never in ("beforeSubmitPrompt", "afterAgentResponse", "afterAgentThought"):
        assert never not in cursor.EVENTS  # they carry prompts and replies
