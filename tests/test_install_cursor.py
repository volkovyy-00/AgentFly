"""Which Cursor versions and events `init -g` accepts (D23, D32)."""

from __future__ import annotations

import os
import plistlib
import random
import re
import shutil
import subprocess
import sys
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from xml.parsers import expat

import pytest

from agentfly.cli import init, main
from agentfly.install import InstallError, cursor, elevate
from agentfly.install.layout import Layout
from tests.install_helpers import call_unless_it_hangs, make_cursor_app, make_layout

# The newest version AgentFly has checked, and one that is newer than it. The card that lists
# NEWER changes this one line.
NEWEST = "3.25.9"
NEWER = "3.26.13"

ADVICE = "quit and reopen Cursor, then run `agentfly doctor`"

TREE = Path(cursor.__file__).resolve().parents[2]  # the tree under test, wherever it is installed


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


def run_in_a_child(
    code: str, stdin: bytes, *, tree: Path = TREE, after: tuple[Path, ...] = ()
) -> None:
    """Run `code` (it reads stdin) in a fresh interpreter whose `agentfly` is THIS tree's.

    A child, killed after 20 s, because a regex holds the GIL: a thread could not be given up on, as
    `call_unless_it_hangs` does for a call that waits. `-I` keeps the environment and the current
    folder out of the child's path, which would put an installed `agentfly` (not this tree) first:
    the tree is put first by hand, and the child fails if it imported another. `after` are folders
    put right behind the tree (the test of that check puts a sibling of the tree there).
    """
    first = (
        "import pathlib, sys; sys.path[:0] = sys.argv[1:]\n"
        "import agentfly\n"
        "assert pathlib.Path(agentfly.__file__).is_relative_to(sys.argv[1]), agentfly.__file__\n"
    )
    subprocess.run(
        [sys.executable, "-I", "-c", first + code, str(tree), *map(str, after)],
        input=stdin,
        timeout=20,
        check=True,
    )


def test_the_child_fails_if_it_imports_an_agentfly_from_a_folder_next_to_the_tree(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "tree"
    sibling = tmp_path / "tree-installed"  # its name starts with the tree's
    for folder in (tree, sibling):
        (folder / "agentfly").mkdir(parents=True)
        (folder / "agentfly" / "__init__.py").write_text("")
    run_in_a_child("", b"", tree=tree, after=(sibling,))  # the tree's own `agentfly` comes first
    shutil.rmtree(tree / "agentfly")  # now only the sibling has one: found, and not the tree's
    with pytest.raises(subprocess.CalledProcessError):
        run_in_a_child("", b"", tree=tree, after=(sibling,))


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


# The start of Cursor 3.26.13's own Info.plist, byte for byte: an XML declaration and Apple's
# DOCTYPE, which has no `[`, so it declares nothing of its own.
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'
REAL_DOCTYPE = (
    b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
    b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
)
REAL_HEADER = XML_DECLARATION + b"\n" + REAL_DOCTYPE + b"\n"
# 10,000 empty elements: with the ATTLIST below, pyexpat decodes the long default for each of them.
EMPTY_ELEMENTS = (
    b'<plist version="1.0"><dict><key>CFBundleShortVersionString</key>'
    + f"<string>{NEWER}</string>".encode()
    + b"<key>l</key><array>"
    + b"<a/>" * 10_000
    + b"</array></dict></plist>"
)
# A default of 10,000 characters of three bytes each (ASCII is decoded about twenty times faster):
# 70 KB in all, and 0.6 s of CPU: the cost is the default's length times the number of elements.
ATTLIST = b'<!ATTLIST a x CDATA "' + "漢".encode() * 10_000 + b'">'
SHORT_ATTLIST = b'<!ATTLIST a x CDATA "d">'


def hostile_subset(before: bytes) -> bytes:
    """An XML declaration, `before` (it ends where a DOCTYPE's internal subset would open) and an
    internal subset holding the long ATTLIST."""
    return XML_DECLARATION + before + b"[" + ATTLIST + b"]>"


# Headers with more than Cursor's, each followed by the same plist: every one is refused before the
# parser sees the file. The first five hide a real internal subset behind something that a check
# for `<!DOCTYPE plist [` (or one for the first `>`) would be fooled by.
FOREIGN_HEADERS = {
    "an internal subset with an ATTLIST": hostile_subset(b"<!DOCTYPE plist "),
    "after a comment holding <!DOCTYPE plist>": hostile_subset(
        b"<!-- <!DOCTYPE plist> --><!DOCTYPE plist "
    ),
    "after a comment holding <plist": hostile_subset(b"<!-- <plist --><!DOCTYPE plist "),
    "after a SYSTEM ID holding >": hostile_subset(b'<!DOCTYPE plist SYSTEM "a>b" '),
    "after a PUBLIC ID holding >": hostile_subset(
        b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://x/y>z" '
    ),
    "an internal subset after Apple's IDs": hostile_subset(
        b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd" '
    ),
    "with no XML declaration": b"<!DOCTYPE plist [" + ATTLIST + b"]>",
    "an entity declaration": XML_DECLARATION + b'<!DOCTYPE plist [<!ENTITY a "aaaa">]>',
    "an ID holding > and no subset": XML_DECLARATION
    + b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/a>b.dtd">',
    "a comment before <plist>": XML_DECLARATION + b"<!-- hello -->",
    "a processing instruction before <plist>": XML_DECLARATION + b"<?pi x?>",
    "another name in the DOCTYPE": XML_DECLARATION + b'<!DOCTYPE html PUBLIC "a" "b">',
    "two DOCTYPEs": XML_DECLARATION + REAL_DOCTYPE + REAL_DOCTYPE,
    "a SYSTEM ID and no subset": XML_DECLARATION + b'<!DOCTYPE plist SYSTEM "x.dtd">',
    "a bare DOCTYPE": XML_DECLARATION + b"<!DOCTYPE plist>",
    "single-quoted IDs": XML_DECLARATION
    + b"<!DOCTYPE plist PUBLIC '-//Apple//DTD PLIST 1.0//EN' 'x.dtd'>",
}
FOREIGN_HEADER_PLISTS = {name: head + EMPTY_ELEMENTS for name, head in FOREIGN_HEADERS.items()}


def test_the_header_plist_is_a_real_one() -> None:
    """The input below must be what the brief says, or the tests that refuse it pass by
    construction: every one of its 10,000 empty elements is handed the 10,000-character default
    (a hundred million characters decoded from 70 KB), and plistlib still reads the version."""
    data = FOREIGN_HEADER_PLISTS["an internal subset with an ATTLIST"]
    assert len(data) < cursor.MAX_PLIST_BYTES
    handed = 0

    def element(name: str, attributes: dict[str, str]) -> None:
        nonlocal handed
        handed += len(attributes.get("x", ""))

    parser = expat.ParserCreate()
    parser.StartElementHandler = element
    parser.Parse(data, True)
    assert handed == 10_000 * 10_000
    assert plistlib.loads(data, fmt=plistlib.FMT_XML)["CFBundleShortVersionString"] == NEWER


@pytest.mark.parametrize("data", FOREIGN_HEADER_PLISTS.values(), ids=FOREIGN_HEADER_PLISTS.keys())
def test_a_header_with_more_than_cursors_is_refused_before_the_parser_sees_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    layout = make_layout(tmp_path)
    write_plist(layout, data)
    parsed: list[object] = []
    real = plistlib.loads
    monkeypatch.setattr(plistlib, "loads", lambda *a, **k: parsed.append(a) or real(*a, **k))
    with pytest.raises(InstallError) as caught:
        cursor.check(layout.cursor_app)
    assert parsed == []  # the parser was never called
    message = str(caught.value)
    assert re.search(r"cannot read the Cursor version from .*\(XML header is not Apple's", message)
    assert "DOCTYPE" in message and message.isprintable()  # one line, and it names the cause


N = cursor.MAX_PLIST_BYTES - 100
HOSTILE_HEADERS = {  # each is a megabyte; the check must not look at a byte more than a few times
    "a declaration that never ends": b"<?xml " + b"a" * N,
    "a declaration of question marks": b"<?xml " + b"?" * N,
    "blanks after the declaration, then junk": XML_DECLARATION + b" " * N + b"x",
    "a DOCTYPE whose ID never ends": XML_DECLARATION + b'<!DOCTYPE plist PUBLIC "' + b"x" * N,
    "blanks inside the DOCTYPE": XML_DECLARATION + b"<!DOCTYPE plist " + b" " * N + b"PUBLIC",
    "blanks after the DOCTYPE, then junk": XML_DECLARATION + REAL_DOCTYPE + b" " * N + b"x",
}


@pytest.mark.parametrize("data", HOSTILE_HEADERS.values(), ids=HOSTILE_HEADERS.keys())
def test_the_header_check_takes_no_longer_on_a_hostile_megabyte(data: bytes) -> None:
    code = (
        "from agentfly.install import cursor\n"
        "try: cursor._require_plist_header(sys.stdin.buffer.read())\n"
        "except cursor._Refused: pass\n"
    )
    run_in_a_child(code, data)


def test_init_refuses_every_foreign_header_in_one_line_before_the_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    monkeypatch.setattr(init, "SYSTEM", layout)
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    parsed: list[object] = []
    real = plistlib.loads
    monkeypatch.setattr(plistlib, "loads", lambda *a, **k: parsed.append(a) or real(*a, **k))
    for name, data in FOREIGN_HEADER_PLISTS.items():
        write_plist(layout, data)
        assert main(["init", "-g"]) == 1, name
        captured = capsys.readouterr()
        assert captured.out == "" and len(captured.err.strip().splitlines()) == 1, name
        assert captured.err.startswith("agentfly init: cannot read the Cursor version"), name
        assert "XML header is not Apple's" in captured.err, name
    assert parsed == [] and not layout.system_root.exists() and not layout.hooks_file.exists()


def declarations_expat_sees(data: bytes) -> list[str]:
    """What expat reports of `data` that is more than a bare DOCTYPE: a subset or a declaration."""
    seen: list[str] = []
    parser = expat.ParserCreate()

    def doctype(name: str, system: str | None, public: str | None, subset: int) -> None:
        if subset:
            seen.append("internal subset")

    parser.StartDoctypeDeclHandler = doctype
    parser.AttlistDeclHandler = lambda *args: seen.append("ATTLIST")
    parser.EntityDeclHandler = lambda *args: seen.append("ENTITY")
    parser.ElementDeclHandler = lambda *args: seen.append("ELEMENT")
    parser.NotationDeclHandler = lambda *args: seen.append("NOTATION")
    try:
        parser.Parse(data, True)
    except expat.ExpatError:
        pass  # malformed: what it reported before failing still counts
    return seen


HEADER_PIECES = [
    XML_DECLARATION, REAL_DOCTYPE, REAL_DOCTYPE, b"<!DOCTYPE plist ", b"PUBLIC ", b"SYSTEM ",
    b'"a"', b'"a>b"', b"'x'", b"[", b"]", b">", b"<", b" ", b"\n", b"\r\n", b"\t",
    SHORT_ATTLIST, b'<!ENTITY e "v">', b"<!-- ", b" -->", b"<!-- <!DOCTYPE plist> -->",
    b"<?pi x?>", b"<!ELEMENT a ANY>", b"<!NOTATION n SYSTEM 'x'>",
]  # fmt: skip


def random_doctype(rng: random.Random) -> bytes:
    """A DOCTYPE that is Apple's, or one with an ID, a name or a subset that is not."""
    ids = rng.choice(
        [
            b'PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"',
            b'PUBLIC "a" "b"',
            b'PUBLIC "a>" "b"',
            b'PUBLIC "a" "b>c"',
            b'SYSTEM "a"',
            b'SYSTEM "a>b"',
            b"PUBLIC 'a' 'b'",
            b"",
        ]
    )
    subset = rng.choice(
        [
            b"",
            b"",
            b" [" + SHORT_ATTLIST + b"]",
            b'[<!ENTITY e "v">]',
            b"[]",
            b" [ ]",
            b"[<!-- ]> -->]",
        ]
    )
    name = rng.choice([b"plist", b"plist", b"html"])
    return b"<!DOCTYPE " + name + b" " + ids + subset + rng.choice([b"", b" "]) + b">"


def random_header(rng: random.Random) -> bytes:
    """Either pieces strung together at random, or a prolog with a few things in the wrong place."""
    if rng.random() < 0.4:
        return b"".join(rng.choice(HEADER_PIECES) for _ in range(rng.randint(1, 6)))
    blanks = [b"", b"\n", b" ", b"\r\n\t"]
    parts = [rng.choice([XML_DECLARATION, b"<?xml version='1.0'?>", b""]), rng.choice(blanks)]
    for _ in range(rng.randint(0, 2)):
        parts += [rng.choice([random_doctype(rng), b"<!-- a -->", b"<?pi x?>"]), rng.choice(blanks)]
    return b"".join(parts)


def test_nothing_the_header_check_lets_through_declares_anything() -> None:
    """Whatever the check accepts, expat sees no internal subset and no declaration in it."""
    rng = random.Random(11)
    accepted = with_doctype = 0
    for _ in range(40_000):
        data = random_header(rng) + b'<plist version="1.0"><dict/></plist>'
        try:
            cursor._require_plist_header(data)
        except cursor._Refused:
            continue
        accepted += 1
        with_doctype += b"<!DOCTYPE" in data
        assert declarations_expat_sees(data) == [], data[:200]
    assert accepted > 500 and with_doctype > 100  # the loop must reach the check's far side


def test_cursors_real_header_with_a_doctype_gives_its_version(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    body = plist_bytes(NEWER)  # plistlib writes the same header Cursor's Info.plist has
    assert b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"' in body
    write_plist(layout, body)
    assert cursor.installed_version(layout.cursor_app) == NEWER
    write_plist(layout, b"\xef\xbb\xbf" + body)  # a UTF-8 byte-order mark is fine too
    assert cursor.installed_version(layout.cursor_app) == NEWER
    write_plist(layout, body[body.index(b"<plist") :])  # and so is a file with no declaration
    assert cursor.installed_version(layout.cursor_app) == NEWER


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"], ids=["no BOM", "a BOM"])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_the_header_of_cursors_real_info_plist_gives_its_version(
    tmp_path: Path, bom: bytes, newline: bytes
) -> None:
    layout = make_layout(tmp_path)
    header = REAL_HEADER.replace(b"\n", newline)
    write_plist(layout, bom + header + EMPTY_ELEMENTS)
    assert cursor.installed_version(layout.cursor_app) == NEWER


def test_the_header_in_this_files_literal_is_the_one_plistlib_writes() -> None:
    assert plist_bytes(NEWER).startswith(REAL_HEADER + b'<plist version="1.0">')


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
