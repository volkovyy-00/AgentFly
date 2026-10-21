"""Which Cursor versions and events `init -g` accepts (D23, D32)."""

from __future__ import annotations

import os
import plistlib
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pytest

from agentfly.install import InstallError, cursor
from agentfly.install.layout import Layout
from tests.install_helpers import call_unless_it_hangs, make_cursor_app, make_layout

# The newest version AgentFly has checked, and one that is newer than it. The card that lists
# NEWER changes this one line.
NEWEST = "3.25.9"
NEWER = "3.26.13"

ADVICE = "quit and reopen Cursor, then run `agentfly doctor`"


ESCAPE_VERSION = "3.26\x1b[2K"  # an XML plist cannot hold it: expat refuses the character


def plist_bytes(version: str) -> bytes:
    """An Info.plist holding `version`, as XML (the only format AgentFly reads)."""
    return plistlib.dumps({"CFBundleShortVersionString": version})


def write_plist(layout: Layout, data: bytes) -> None:
    plist = layout.cursor_app / "Contents" / "Info.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(data)


def write_version(layout: Layout, version: str) -> None:
    write_plist(layout, plist_bytes(version))


def open_descriptors() -> int:
    return len(os.listdir("/dev/fd"))


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


def test_a_dotted_version_is_compared_up_to_32_characters_and_refused_beyond(
    tmp_path: Path,
) -> None:
    longest = "9." * 15 + "99"  # 32 characters, numerically newer than anything listed
    assert len(longest) == 32 and check_version(tmp_path, longest) == longest
    assert cursor.verified_as(longest) == NEWEST
    assert cursor.verified_as(longest + "9") is None  # 33 characters: not compared at all


def xml_version_plist(version_xml: str) -> bytes:
    """An XML Info.plist whose version is `version_xml`, given as XML text (references allowed)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        f"<key>CFBundleShortVersionString</key><string>{version_xml}</string></dict></plist>"
    ).encode()


# What an XML plist can hold that a terminal would act on, and how the refusal prints it.
ESCAPED = {
    "a newline": ("3.26\n13", "3.26\\n13"),
    "a carriage return": ("3.26&#13;13", "3.26\\r13"),
    "U+009B, a one-character escape": ("3.26&#x9b;13", "3.26\\x9b13"),
    "U+202E, right-to-left override": ("3.26&#x202e;13", "3.26\\u202e13"),
}


@pytest.mark.parametrize("held, shown", ESCAPED.values(), ids=ESCAPED.keys())
def test_a_version_is_shown_with_its_control_characters_escaped(
    tmp_path: Path, held: str, shown: str
) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, xml_version_plist(held))
    with pytest.raises(InstallError) as caught:
        cursor.check(layout.cursor_app)
    message = str(caught.value)
    assert message.startswith(f"Cursor {shown} is not a plain dotted")
    assert message.isprintable()


def test_an_escape_character_is_shown_escaped_where_a_version_comes_from_elsewhere() -> None:
    assert cursor.shown(ESCAPE_VERSION) == r"3.26\x1b[2K"


def test_a_version_that_cannot_be_compared_is_not_called_not_newer(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match=r"Cursor 3\.26\.13-beta is not a plain dotted version"):
        check_version(tmp_path, "3.26.13-beta")


def test_a_refusal_names_the_listed_versions_and_the_newest(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match=r"Cursor 1\.0\.0 .*\(3\.24\.12, 3\.25\.9\).*3\.25\.9"):
        check_version(tmp_path, "1.0.0")


def blowup_plist() -> bytes:
    """A binary plist just under 1 MiB: 300 object numbers that all point at one data blob.

    plistlib's binary reader caches per object number, not per offset, so it copies the blob once
    for each: 300 references to a blob of about 1 MiB take about 300 MiB. (`plistlib.dumps` cannot
    write this: it gives equal objects one number.) Layout: header, the blob, an array of the
    references, the offset table (object 0 is the array, objects 1..refs are the blob) and the
    32-byte trailer.
    """
    refs, size = 300, (1 << 20) - 1
    blob_len = size - (8 + (2 + 4) + (2 + 2 + 2 * refs) + 4 * (refs + 1) + 32)
    blob = b"\x4f\x12" + blob_len.to_bytes(4, "big") + b"x" * blob_len
    array = bytes([0xAF, 0x11]) + refs.to_bytes(2, "big")
    array += b"".join(number.to_bytes(2, "big") for number in range(1, refs + 1))
    array_at = 8 + len(blob)
    table_at = array_at + len(array)
    table = array_at.to_bytes(4, "big") + (8).to_bytes(4, "big") * refs
    trailer = bytes(6) + bytes([4, 2]) + (refs + 1).to_bytes(8, "big") + bytes(8)
    return b"bplist00" + blob + array + table + trailer + table_at.to_bytes(8, "big")


BLOWUP_PLIST = blowup_plist()

# Files that are not XML: the read stops at the first bytes, before any parser sees them.
NOT_XML_PLISTS = {
    "a binary plist": plistlib.dumps(
        {"CFBundleShortVersionString": NEWER}, fmt=plistlib.FMT_BINARY
    ),
    "a binary plist built to blow up the parse": BLOWUP_PLIST,
    "not a plist": b"\xff\xfe junk",
    "empty": b"",
    "XML after a blank line": b"\n" + plist_bytes(NEWER),
}

# Files that start as XML and fail in the parser or after it, each with another exception.
MALFORMED_PLISTS = {
    "a mismatched tag": b'<?xml version="1.0"?><plist version="1.0"><dict><key>a</key>'
    b"<string>x</dict></plist>",
    "a truncated file": b'<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundle',
    "a control character reference": xml_version_plist("3.26&#x1b;"),
    "an escape character": xml_version_plist(ESCAPE_VERSION),
    "an encoding Python does not know": b'<?xml version="1.0" encoding="UTFa8"?>'
    b'<plist version="1.0"><dict><key>CFBundleShortVersionString</key>'
    b"<string>3.26.13</string></dict></plist>",
    "a tag plistlib does not know": b'<?xml version="1.0"?><plist version="1.0">'
    b"<dact><key>CFBundleShortVersionString</key><string>3.26.13</string></dict></plist>",
    "a list, not a dictionary": plistlib.dumps([NEWER]),
    "a date plistlib cannot read": b'<?xml version="1.0"?><plist version="1.0"><dict>'
    b"<key>CFBundleShortVersionString</key><date>9999999-01-01T00:00:00Z</date></dict></plist>",
    "an entity declaration": b'<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY a "aaaa">]>'
    b'<plist version="1.0"><dict><key>CFBundleShortVersionString</key><string>&a;</string>'
    b"</dict></plist>",
}


@pytest.mark.parametrize("data", MALFORMED_PLISTS.values(), ids=MALFORMED_PLISTS.keys())
def test_a_plist_that_cannot_be_read_is_one_refusal_not_a_traceback(
    tmp_path: Path, data: bytes
) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, data)
    with pytest.raises(InstallError, match=r"cannot read the Cursor version") as caught:
        cursor.check(layout.cursor_app)
    assert str(caught.value).isprintable()  # one line, and no raw character from the file


@pytest.mark.parametrize("data", NOT_XML_PLISTS.values(), ids=NOT_XML_PLISTS.keys())
def test_a_plist_that_is_not_xml_is_refused_and_the_message_says_so(
    tmp_path: Path, data: bytes
) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, data)
    with pytest.raises(InstallError, match=r"cannot read the Cursor version.*\(not XML") as caught:
        cursor.check(layout.cursor_app)
    assert "\n" not in str(caught.value)


def test_cursors_real_header_with_a_doctype_gives_its_version(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    body = plist_bytes(NEWER)  # plistlib writes the same header Cursor's Info.plist has
    assert b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"' in body
    write_plist(layout, body)
    assert cursor.installed_version(layout.cursor_app) == NEWER
    write_plist(layout, b"\xef\xbb\xbf" + body)  # a UTF-8 byte-order mark is fine too
    assert cursor.installed_version(layout.cursor_app) == NEWER


def peak_mib(call: Callable[[], object]) -> tuple[object, float]:
    """What `call` returns (or raises), and the most Python memory it held at once, in MiB."""
    tracemalloc.start()
    try:
        try:
            outcome: object = call()
        except InstallError as exc:
            outcome = exc
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return outcome, peak / (1 << 20)


def full_xml_plist(fill: Callable[[int], bytes]) -> bytes:
    """An XML plist of just under MAX_PLIST_BYTES: NEWER, then a second value `fill(room)` makes."""
    head = xml_version_plist(NEWER).removesuffix(b"</dict></plist>") + b"<key>p</key>"
    tail = b"</dict></plist>"
    return head + fill(cursor.MAX_PLIST_BYTES - len(head) - len(tail)) + tail


XML_SHAPES = {  # the worst an XML plist can do with a megabyte: no reference is shared in XML
    "empty arrays in one array": lambda room: (
        b"<array>" + b"<array/>" * ((room - 15) // 8) + b"</array>"
    ),
    "arrays nested to the limit": lambda room: (
        b"<array>" * (room // 15) + b"</array>" * (room // 15)
    ),
    "dictionaries nested to the limit": lambda room: (
        b"<dict><key>a</key>" * ((room - 7) // 25) + b"<dict/>" + b"</dict>" * ((room - 7) // 25)
    ),
}
PEAK_LIMIT_MIB = 64


def test_the_blow_up_plist_is_a_real_one() -> None:
    """The input below must cost what the brief says, or the memory test passes by construction."""
    assert len(BLOWUP_PLIST) < cursor.MAX_PLIST_BYTES
    _, peak = peak_mib(lambda: plistlib.loads(BLOWUP_PLIST))  # format auto-detected: binary reader
    assert peak > 200


def test_reading_a_binary_plist_built_to_blow_up_stays_under_64_mib(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, BLOWUP_PLIST)
    outcome, peak = peak_mib(lambda: cursor.installed_version(layout.cursor_app))
    assert peak < PEAK_LIMIT_MIB, peak  # first: the memory, whatever the message says
    assert isinstance(outcome, InstallError) and "not XML" in str(outcome)


@pytest.mark.parametrize("fill", XML_SHAPES.values(), ids=XML_SHAPES.keys())
def test_reading_the_worst_xml_plist_stays_under_64_mib_and_gives_its_version(
    tmp_path: Path, fill: Callable[[int], bytes]
) -> None:
    layout = make_layout(tmp_path)
    data = full_xml_plist(fill)
    assert cursor.MAX_PLIST_BYTES - 100 < len(data) <= cursor.MAX_PLIST_BYTES
    write_plist(layout, data)
    outcome, peak = peak_mib(lambda: cursor.installed_version(layout.cursor_app))
    assert outcome == NEWER
    assert peak < PEAK_LIMIT_MIB, peak


def test_a_folder_in_place_of_the_plist_is_refused_and_leaks_no_descriptor(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    (layout.cursor_app / "Contents" / "Info.plist").mkdir(parents=True)

    before = open_descriptors()
    for _ in range(20):
        with pytest.raises(InstallError, match="cannot read the Cursor version"):
            cursor.installed_version(layout.cursor_app)
    assert open_descriptors() == before


def padded_plist(size: int) -> bytes:
    """A plist that holds NEWER and is exactly `size` bytes long."""
    base = {"CFBundleShortVersionString": NEWER, "pad": ""}
    return plistlib.dumps({**base, "pad": "x" * (size - len(plistlib.dumps(base)))})


def test_a_plist_is_read_up_to_the_size_limit_and_refused_one_byte_over(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, padded_plist(cursor.MAX_PLIST_BYTES))
    assert cursor.check(layout.cursor_app) == NEWER
    write_plist(layout, padded_plist(cursor.MAX_PLIST_BYTES + 1))
    with pytest.raises(InstallError, match="cannot read the Cursor version"):
        cursor.check(layout.cursor_app)


def test_a_named_pipe_in_place_of_the_plist_is_refused_not_waited_for(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    plist = layout.cursor_app / "Contents" / "Info.plist"
    plist.parent.mkdir(parents=True)
    os.mkfifo(plist)  # an open() with no writer would block for ever
    with pytest.raises(InstallError, match="cannot read the Cursor version"):
        call_unless_it_hangs(lambda: cursor.check(layout.cursor_app), plist)


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
