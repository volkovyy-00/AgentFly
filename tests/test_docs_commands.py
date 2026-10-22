"""Every command in AGENTS.md "Commands" and in README code blocks names files that exist.

Also: the two files every session loads stay small and import nothing by accident, and the wheel
install line names the Python the project is built for.
"""

from __future__ import annotations

import gc
import importlib.util
import re
import shlex
import time
from pathlib import Path

import pytest

from agentfly.cli import build_parser
from agentfly.install import cursor, packages

REPO = Path(__file__).resolve().parents[1]
_FILE_LIKE = re.compile(r"^\.?/?[\w./-]+\.(?:py|sh|toml|json)$|^(?:scripts|hooks|agentfly|ui)/")


def agents_commands() -> list[str]:
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    section = text.split("## Commands", 1)[1].split("\n## ", 1)[0]
    spans = re.findall(r"`([^`]+)`", section)
    # Only command lines: other backticks name generated files such as .cursor/hooks.json.
    return [c for c in spans if c.split()[0] in {"uv", "npm"} or c.startswith("./")]


def readme_commands() -> list[str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:bash|sh)\n(.*?)```", text, flags=re.S)
    lines = [line for block in blocks for line in block.splitlines()]
    return [line.split("#", 1)[0].strip() for line in lines if line.strip()]


def commands() -> list[str]:
    found: list[str] = []
    for raw in agents_commands() + readme_commands():
        for part in re.split(r"\s*&&\s*", raw):
            found.append(part.strip())
    return [c for c in found if c]


def subcommands() -> set[str]:
    return set(next(a.choices for a in build_parser()._actions if getattr(a, "choices", None)))


SUBCOMMANDS = subcommands()


@pytest.mark.parametrize("command", commands())
def test_command_names_exist(command: str) -> None:
    try:
        words = shlex.split(command)
    except ValueError:
        return  # prose in backticks, not a command
    for index, word in enumerate(words):
        if word == "-m" and index > 0 and words[index - 1].startswith("python"):
            assert importlib.util.find_spec(words[index + 1]) is not None, command
        elif word == "agentfly" and index + 1 < len(words) and not words[index + 1].startswith("-"):
            assert words[index + 1] in SUBCOMMANDS, command
        elif _FILE_LIKE.match(word) and not word.startswith(("http", "~")):
            candidate = word.removeprefix("./")
            if "<" in candidate or "*" in candidate:
                continue
            assert (REPO / candidate).exists(), f"{word} in `{command}`"


def test_the_docs_still_list_commands() -> None:
    # Guards the extraction above: an empty list would make the test above vacuous.
    assert any("agentfly serve" in c for c in commands())
    assert any("python -m agentfly.recorder.check_db" in c for c in commands())
    assert any("scripts/setup_credentials.sh" in c for c in commands())


# ------------------------------------------------------------ what every session loads (fix1)

AGENTS_MAX_BYTES = 14_000  # owner 2026-10-22: AGENTS.md and CLAUDE.md load into every session
IMPORT_LINE = "@AGENTS.md"  # the one import CLAUDE.md is meant to hold
_IMPORT = re.compile(r"(?<![^\W_])@\S+")  # an `@` after anything but a letter or digit, and a name
_LIST_ITEM = re.compile(r"(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]|$)")
_LINK_DEFINITION = re.compile(r" {0,3}\[[^\]]*+\]:")
_SPACES = re.compile(r"[ \t]*")
_HTML = re.compile(r"<(?![^\s<>`@]++@[^\s<>`]++>)[A-Za-z/!?`]")  # a tag, a comment; not <a@b.c>
_ODD_SPACE = re.compile(r"[^\S ]")  # a tab, a no-break space, a form feed
_NUL = "\x00"  # stands in for text that is code
_NO_CLOSER = "a backtick run with no closer (or an escaped one) is not modelled"
_UNCLOSED = "a fenced block is never closed"
_HTML_NOTE = "HTML is not modelled"


def size_problem(data: bytes) -> str | None:
    """Bytes, not characters: the file holds `§` and `→`, which take two and three."""
    if len(data) > AGENTS_MAX_BYTES:
        return f"AGENTS.md is {len(data)} bytes; the cap is {AGENTS_MAX_BYTES}"
    return None


def _indent(line: str) -> int:
    """Columns of leading space, counted up to 4: all that any caller compares."""
    head = line[:4].expandtabs(4)
    return min(4, len(head) - len(head.lstrip(" ")))


def _fence(line: str) -> str | None:
    """The run of backticks or tildes a line opens a fenced block with, or None."""
    text = line.lstrip(" ")
    if _indent(line) > 3 or text[:1] not in ("`", "~"):
        return None
    run = text[: len(text) - len(text.lstrip(text[0]))]
    if len(run) < 3 or (run[0] == "`" and "`" in text[len(run) :]):  # a span, not a fence
        return None
    return run


def _closes(line: str, fence: str) -> bool:
    text = line.strip(" \t")
    return _indent(line) <= 3 and text.startswith(fence) and not text.strip(fence[0])


def _block_kind(line: str) -> str:
    """`single` (a block of one line), `start` (a block that may go on) or `text`.

    A paragraph ends at a blank line and, here, also at a heading, a setext or thematic line, an
    indented line, a quote and a list item. Ending one too early cannot hide text: a span that
    crosses the cut leaves its opener with no closer, which `stray_imports` reports.
    """
    text = line.strip(" \t")
    if not text or _indent(line) >= 4:
        return "single"
    compact = text.replace(" ", "")
    ruled = compact == compact[0] * len(compact) and compact[0] in "=-*_"
    if text[0] == "#" or (ruled and (len(compact) >= 3 or compact[0] in "=-")):
        return "single"
    return "start" if text[0] == ">" or _LIST_ITEM.match(text) else "text"


def _container_start(line: str) -> bool:
    """A quote or list marker, then a heading, fence, code or link definition: in a container."""
    at, marked = _SPACES.match(line).end(), False
    while True:
        if line[at : at + 1] == ">":
            at += 2 if line[at + 1 : at + 2] == " " else 1
        elif item := _LIST_ITEM.match(line, at):
            at = item.end()
        else:
            break
        marked = True
        if _indent(line[at : at + 4]) >= 4:
            return True
        at = _SPACES.match(line, at).end()
    return marked and (
        line[at : at + 1] == "#"
        or line[at : at + 3] in ("```", "~~~")
        or _LINK_DEFINITION.match(line, at) is not None
    )


def _hide(text: str) -> str:
    return re.sub(r"[^\n]", _NUL, text)


def _blank_spans(paragraph: str) -> str:
    """`paragraph` with every code span overwritten by NUL characters (line breaks stay).

    A run of n backticks opens a span that the next run of exactly n closes. One backward pass
    finds each run's closer, one forward pass blanks: the work is linear. A run that nothing
    closes, or one after a backslash, is plain text (and `stray_imports` reports it).
    """
    runs = [m.span() for m in re.finditer(r"`+", paragraph)]
    closer: list[int | None] = [None] * len(runs)
    latest: dict[int, int] = {}  # run length -> the nearest run of that length to the right
    for at in range(len(runs) - 1, -1, -1):
        length = runs[at][1] - runs[at][0]
        closer[at] = latest.get(length)
        latest[length] = at
    parts: list[str] = []
    done = at = 0
    while at < len(runs):
        start, end = runs[at][0], closer[at]
        if end is None or paragraph[start - 1 : start] == "\\":
            at += 1
            continue
        stop = runs[end][1]
        parts += [paragraph[done:start], _hide(paragraph[start:stop])]
        done, at = stop, end + 1
    return "".join(parts) + paragraph[done:]


def _outside_code(text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """The lines of `text` with fenced blocks and code spans overwritten by NUL characters.

    Every line keeps its length. A span may cross a line break but not the end of its paragraph
    (see `_block_kind`). The second value lists (line, what) for constructs this scan does not
    model, where it cannot tell what CommonMark would call code: a fence that never closes, a
    heading, fence or code block in a quote or list item, a link reference definition, a line
    that starts with an HTML tag, a fence in a list item that a less indented line may end.
    """
    out: list[str] = []
    paragraph: list[str] = []
    notes: list[tuple[int, str]] = []
    fence: str | None = None
    opened = fence_indent = 0

    def end_paragraph() -> None:
        if paragraph:
            out.extend(_blank_spans("\n".join(paragraph)).split("\n"))
            paragraph.clear()

    for number, line in enumerate(text.split("\n"), 1):
        if fence is not None:
            out.append(_NUL * len(line))
            if _closes(line, fence):
                fence = None
            elif line.strip(" \t") and _indent(line) < fence_indent:
                notes.append((number, "a fence in a list item may end early"))
            continue
        opening = _fence(line)
        kind = _block_kind(line)
        if opening or kind != "text":
            end_paragraph()
        if opening:
            fence, opened, fence_indent = opening, number, _indent(line)
            out.append(_NUL * len(line))
            continue
        if kind == "single":
            out.append(_blank_spans(line))
        else:
            paragraph.append(line)
        if _LINK_DEFINITION.match(line):
            notes.append((number, "a link reference definition is not modelled"))
        if _container_start(line):
            notes.append((number, "a heading, fence or code block in a quote or list item"))
        if _HTML.match(line.lstrip()):  # a block may start here even inside what looks like a span
            notes.append((number, _HTML_NOTE))
    end_paragraph()
    if fence is not None:
        notes.append((opened, _UNCLOSED))
    return out, notes


def stray_imports(text: str, allowed: str | None = None) -> list[str]:
    """Each `@name` Claude Code would import from `text`; `allowed` may open one line, once.

    Unsure means a finding: so is anything the scan does not model (HTML, a tab or other odd
    space, a backtick run with no closer, and what `_outside_code` lists). One pass over the
    text; the named file is never opened.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    rows, problems = _outside_code(text)
    found: list[tuple[int, str]] = []
    for number, (row, original) in enumerate(zip(rows, text.split("\n"), strict=True), 1):
        if "`" in row:
            problems.append((number, _NO_CLOSER))
        if _HTML.search(row):
            problems.append((number, _HTML_NOTE))
        if _ODD_SPACE.search(row):
            problems.append((number, "a tab or other odd space is not modelled"))
        for match in _IMPORT.finditer(row):
            name = original[match.start() : match.end()]
            if allowed and name == allowed and match.start() == 0:
                allowed = None  # that line, once
                continue
            found.append((number, name[:40]))
    return [f"line {number}: {what}" for number, what in sorted({*problems, *found})]


def test_agents_md_stays_under_its_size_cap() -> None:
    assert size_problem((REPO / "AGENTS.md").read_bytes()) is None


@pytest.mark.parametrize(
    ("data", "fails"),
    [
        pytest.param(b"x" * 14_000, False, id="14000 bytes"),
        pytest.param(b"x" * 14_001, True, id="14001 bytes"),
        pytest.param("§".encode() * 7_001, True, id="7001 characters, 14002 bytes"),
    ],
)
def test_the_size_cap_counts_bytes(data: bytes, fails: bool) -> None:
    assert (size_problem(data) is not None) is fails


@pytest.mark.parametrize(("name", "allowed"), [("AGENTS.md", None), ("CLAUDE.md", IMPORT_LINE)])
def test_the_files_every_session_loads_import_only_what_they_mean_to(
    name: str, allowed: str | None
) -> None:
    assert stray_imports((REPO / name).read_text(encoding="utf-8"), allowed) == []


def test_claude_md_still_imports_agents_md() -> None:
    """Without that line every AGENTS.md rule drops out of every session."""
    findings = stray_imports((REPO / "CLAUDE.md").read_text(encoding="utf-8"))
    assert [finding.split(": ", 1)[1] for finding in findings] == [IMPORT_LINE]


NOT_IMPORTS = {
    "a trailer": "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>",
    "a digit then an at sign": "a1@b and x@y",
    "a code span": "`@x`",
    "a double-backtick span": "`` `@x` ``",
    "a span with a longer run inside": "``a ` @x``",
    "a span over a line break": "see `uv run\n@x` here",
    "a span over a wrapped list item line": "- the `uv run\n  @x` command",
    "a fenced block": "```\n@x\n```",
    "a tilde block": "~~~sh\n@x\n~~~",
    "a block that a shorter run does not close": "````\n```\n@x\n```\n````",
    "a block closed by a longer run": "```\n@x\n`````",
    "a block inside a list item": "- item\n  ```\n  @x\n  ```\n- next",
    "an at sign with no name": "an @ sign, a trailing @",
    "a span after a closed one": "`a` and `@x`",
    "a less-than sign in prose": "if a < b and c <= d",
}


@pytest.mark.parametrize("text", NOT_IMPORTS.values(), ids=NOT_IMPORTS.keys())
def test_text_that_imports_nothing_passes(text: str) -> None:
    assert stray_imports(text) == []


IMPORTS = {
    "after a space": "see @SPEC.md",
    "in brackets": "(@SPEC.md)",
    "in bold": "**@SPEC.md**",
    "in quotes": '"@SPEC.md"',
    "at the start of a wrapped line": "a line that wraps\n@SPEC.md and goes on",
    "at the start of the file": "@SPEC.md",
    "after an underscore": "snake_@SPEC.md",
    "after a closed span": "`a`@x",
    "between two spans": "`a` @SPEC.md `b`",
    "after an unclosed backtick": "a lone ` then @x",
    "in a paragraph after an unclosed backtick": "ends in a lone `\n\nsee @x and `y`",
    "in a list item after one with an unclosed backtick": "- one `lone\n- see @x and `y`",
    "in a line after a heading with an unclosed backtick": "# a `b\nsee @x `c`",
    "in a line after a setext underline with an unclosed backtick": "Title `a\n===\nsee @x `c`",
    "in a line after indented code with an unclosed backtick": "    code `a\nsee @x `c`",
    "in a line after a tab-indented line with an unclosed backtick": "\tcode `a\nsee @x `c`",
    "in a line after a space and a tab with an unclosed backtick": " \tcode `a\nsee @x `c`",
    "in a quote after a line with an unclosed backtick": "a `b\n> see @x `c`",
    "in a heading line with paired backticks around the break": "# a `\n@x`",
    "in a line after a setext heading with paired backticks": "Title `\n===\n@x`",
    "in a line after a thematic break with paired backticks": "a `\n***\n@x`",
    "in a quote with paired backticks around the break": "`\n> @x`",
    "in a list item with paired backticks around the break": "`\n- @x`",
    "before a list item with paired backticks around the break": "`@x\n- `",
    "in a numbered item with paired backticks around the break": "`\n1. @x`",
    "in a line after indented code with paired backticks": "    code `\n@x`",
    "in a line after tab-indented code with paired backticks": "\tcode `\n@x`",
    "after a span wrapped onto a no-break-space line": "word `\n\xa0\ncode` @x `y`",
    "after an escaped backtick": "\\`@x\\`",
    "after a tab that does not close a fence": "```\n\t```\nx\n```\nsee @x\n```",
    "a name in a link": "[SPEC](@SPEC.md)",
    "two imports on one line": "see @AGENTS.md and @AGENTS.md",
}


# The scan cannot tell here whether the `@x` is code (CommonMark could read the text another
# way, or the text holds what the scan does not model), so it fails; it need not name the `@x`.
AMBIGUOUS = {
    "after a span wrapped onto an indented line": "- the `uv run\n    agentfly serve` is @x `y`",
    "after a span wrapped onto a tab line": "word `\n\tcode` @x `y`",
    "after a span wrapped onto a numbered line": "word `\n2. c` @x `y`",
    "after a span wrapped onto a hash with no space": "word `\n#12 c` @x `y`",
    "after a heading in a list item": "- # heading `a\nsee @x `b`",
    "after a heading in a quote": "> # heading `a\nsee @x `b`",
    "after a list item that ends a fence": "- one:\n  ```sh\n  cmd\n- two, see @x\n```",
    "after a fence in a quote": "> ```\nsee @x ```",
    "after a fence on a list marker": "- ```\n@x```",
    "after a link reference definition": "[a]: </x`y>\nsee @x `z`",
    "after a link reference definition in a quote": "> [a]: /u`\n@x`",
    "after an even number of backslashes": "\\\\`a` @x `b`",
    "after an escaped first backtick of a longer run": "\\`` x ` @x `",
    "after an HTML comment": "<!-- a ` -->\nsee @x `c`",
    "after an HTML tag": '<a title="`"> see @x `c`',
    "after an autolink with a backtick": "<http://a.b/`c> see @x `d`",
    "after an HTML block that hides a fence": "<div>\n```\n\nsee @x\n\n```",
    "after a tag that opens inside a span": "`@x\n<pre>`",
    "after a comment that opens inside a span": "`@x``\n<!-- `",
    "after a tag in a quote": ">```@x\n<div>```",
    "after an autolink whose address is a backtick run": "<```@x>```",
    "after indented code in a quote": ">     `\n@x`",
    "after indented code in a list item": "-     `\n@x`",
}


@pytest.mark.parametrize("text", IMPORTS.values(), ids=IMPORTS.keys())
def test_text_that_imports_a_file_names_the_import(text: str) -> None:
    findings = stray_imports(text)
    assert any(finding.split(": ", 1)[1].startswith("@") for finding in findings), findings


@pytest.mark.parametrize("text", AMBIGUOUS.values(), ids=AMBIGUOUS.keys())
def test_text_that_may_import_a_file_fails(text: str) -> None:
    assert stray_imports(text) != []


def test_a_span_does_not_cross_a_blank_line() -> None:
    """The two backticks pair only if the span crosses the break; then `@x` would be hidden."""
    found = stray_imports("a lone `\n\nsee @x `y")
    assert "line 3: @x" in found and f"line 1: {_NO_CLOSER}" in found


NOT_MODELLED = {
    "a tab": "a\tb",
    "a no-break space": "a\u00a0b",
    "a form feed": "a\x0cb",
    "an HTML tag": "<b>x</b>",
    "an HTML comment": "<!-- x -->",
    "a tag at the start of a line": "x\n<pre>\ny",
    "a backtick run with no closer": "a ` b",
    "an escaped backtick": "a \\` b",
    "a link reference definition": "[a]: /u",
    "a link reference definition in a list item": "- [a]: /u",
    "a heading in a quote": "> # h",
    "a heading in a list item": "- # h",
    "a fence in a list item's marker line": "- ```\ncode\n```",
    "indented code in a quote": ">     code",
    "a fence in a list item that a shallower line may end": "- a\n  ```\ncode\n  ```",
    "a fence that never closes": "```\nx",
}


@pytest.mark.parametrize("text", NOT_MODELLED.values(), ids=NOT_MODELLED.keys())
def test_text_the_scan_does_not_model_fails_even_without_an_import(text: str) -> None:
    assert stray_imports(text) != []


FENCES = {
    "a backtick in the info string opens no block": (
        "```a`b\n@x",
        [f"line 1: {_NO_CLOSER}", "line 2: @x"],
    ),
    "a shorter run does not close a block": ("````\n@x\n```\n@y\n````\n@z", ["line 6: @z"]),
    "backticks do not close a tilde block": ("~~~\n@x\n```\n@y\n~~~\n@z", ["line 6: @z"]),
    "a closing fence carries no words": ("```\n@x\n``` tail\n@y\n```\n@z", ["line 6: @z"]),
    "a closing fence is indented three spaces at most": (
        "```\n@x\n    ```\n@y\n```\n@z",
        ["line 6: @z"],
    ),
    "a tab does not close a block": ("```\n@x\n\t```\n@y\n```\n@z", ["line 6: @z"]),
    "a no-break space does not close a block": ("```\n@x\n```\u00a0\n@y\n```\n@z", ["line 6: @z"]),
    "a block that never closes is a finding": ("```\n@x", [f"line 1: {_UNCLOSED}"]),
    "a block that closes hides nothing after it": ("```\nx\n```\n@x", ["line 4: @x"]),
}


@pytest.mark.parametrize(("text", "found"), FENCES.values(), ids=FENCES.keys())
def test_a_fenced_block_ends_where_commonmark_ends_it(text: str, found: list[str]) -> None:
    assert stray_imports(text) == found


def test_claude_md_may_import_agents_md_once_on_a_line_of_its_own() -> None:
    title = "# CLAUDE.md\n\n"
    assert stray_imports(f"{title}@AGENTS.md\n\n## Roles\n", IMPORT_LINE) == []
    assert stray_imports(f"{title}@AGENTS.md\n", None) == ["line 3: @AGENTS.md"]
    assert stray_imports(f"{title}@AGENTS.md\n\n@AGENTS.md\n", IMPORT_LINE) == [
        "line 5: @AGENTS.md"
    ]
    assert stray_imports(f"{title}see @AGENTS.md\n", IMPORT_LINE) == ["line 3: @AGENTS.md"]
    assert stray_imports(f"{title}@AGENTS.md.bak\n", IMPORT_LINE) == ["line 3: @AGENTS.md.bak"]
    assert stray_imports(f"{title}@SPEC.md\n", IMPORT_LINE) == ["line 3: @SPEC.md"]


def test_a_finding_names_its_line() -> None:
    text = "one\n`two\nthree`\n\nfour @x\n- five\n```\n@y\n```\n@z"
    assert stray_imports(text) == ["line 5: @x", "line 10: @z"]
    assert stray_imports("a\r\nb\r\n\r\nsee @x") == [
        "line 4: @x"
    ]  # line ends as read_text sees them


def test_every_byte_goes_through_the_span_scan_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan that went back over earlier lines, or over a block twice, would not be one pass."""
    sizes: list[int] = []
    real = _blank_spans

    def spy(paragraph: str) -> str:
        sizes.append(len(paragraph))
        return real(paragraph)

    monkeypatch.setitem(globals(), "_blank_spans", spy)  # this module, however pytest imported it
    wrapped = "\n".join(f"line {n} `{'`' * (n % 7)} @x{n} ``" for n in range(300))
    headings = "\n".join(f"# head {n} `x` @y" for n in range(300))
    unclosed = "`" * 3_000 + " a `\n" + "a `b\n" * 300  # a long run that opens no fence
    text = "\n\n".join([wrapped, headings, unclosed])
    stray_imports(text)
    # Every line is scanned once, but the line breaks between blocks are not part of any block.
    assert 0.9 * len(text) <= sum(sizes) <= len(text), (sum(sizes), len(text))


@pytest.mark.parametrize(
    ("prefix", "unit"),
    [
        ("", "> "),
        ("", "- "),
        ("", "1. "),
        ("<", "a@"),
        ("", "[a"),
        ("", "`"),
        ("", "@"),
        ("", "```\n"),
        ("", "a `\n"),
        ("", "# `\n"),
        ("", "\t"),
    ],
)
def test_the_scan_takes_time_in_proportion_to_the_text(prefix: str, unit: str) -> None:
    """Four times the text costs about four times as much (a quadratic scan: sixteen)."""
    fastest = {5_000: float("inf"), 20_000: float("inf")}
    was_on = gc.isenabled()
    gc.disable()  # CPU time and no collector pauses: a busy machine leaves it alone
    try:
        for _ in range(5):
            for count in fastest:  # in turns, so that nothing favours one size
                text = prefix + unit * count
                started = time.process_time()
                stray_imports(text)
                fastest[count] = min(fastest[count], time.process_time() - started)
    finally:
        if was_on:
            gc.enable()
    short, long = fastest.values()
    assert long < 8 * short, f"4 times the text took {long / short:.1f} times as long"


_WHEEL_INSTALL = re.compile(r"uv tool install (?:(?!uv tool install)[^`])*?dist/\S*")


def wheel_installs(text: str) -> list[str]:
    """Each `uv tool install ... dist/...` command in `text`; a wrapped one is joined first."""
    return _WHEEL_INSTALL.findall(" ".join(text.split()))


def names_the_python(command: str) -> bool:
    """Without `--python`, uv picks its newest Python (3.14 on one Mac), not `.python-version`."""
    python = (REPO / ".python-version").read_text(encoding="utf-8").strip()
    return re.search(rf"(?:--python|-p)[ =]{re.escape(python)}\b", command) is not None


@pytest.mark.parametrize("name", ["README.md", "AGENTS.md", "SPEC.md", "WHEEL_HINT"])
def test_each_wheel_install_line_names_the_python_the_project_uses(name: str) -> None:
    text = packages.WHEEL_HINT if name == "WHEEL_HINT" else (REPO / name).read_text("utf-8")
    commands = wheel_installs(text)
    assert commands, "no wheel install line found"
    for command in commands:
        assert names_the_python(command), command


def test_no_markdown_file_in_the_root_installs_the_wheel_without_it() -> None:
    for path in sorted(REPO.glob("*.md")):
        for command in wheel_installs(path.read_text(encoding="utf-8")):
            assert names_the_python(command), f"{path.name}: {command}"


@pytest.mark.parametrize(
    ("text", "pinned"),
    [
        ("uv tool install --python 3.12 dist/*.whl", [True]),
        ("uv tool install -p 3.12 dist/*.whl", [True]),
        ("uv tool install --force --python=3.12 dist/x.whl", [True]),
        ("uv tool install dist/*.whl", [False]),
        ('uv tool install "dist/x.whl"', [False]),
        ("uv tool install --python 3.13 dist/*.whl", [False]),
        ("uv tool install\n  --python 3.12 dist/*.whl", [True]),
        ("uv tool install --python 3.12 ruff\nuv tool install dist/*.whl", [False]),
        ("uv tool install ruff", []),
    ],
)
def test_the_wheel_install_check_reads_commands_the_way_a_shell_would(
    text: str, pinned: list[bool]
) -> None:
    assert [names_the_python(command) for command in wheel_installs(text)] == pinned


def wired_events() -> list[str]:
    """The events `./install.sh` writes into `.cursor/hooks.json`."""
    script = (REPO / "install.sh").read_text(encoding="utf-8")
    return re.findall(r'^    "(\w+)": \[', script, flags=re.M)


def test_install_sh_wires_five_of_the_events_init_g_registers() -> None:
    wired = wired_events()
    assert len(wired) == 5
    assert set(wired) < set(cursor.EVENTS)  # `init -g` registers more: those arrive once


@pytest.mark.parametrize("name", ["AGENTS.md", "README.md", "SPEC.md", "install.sh"])
def test_the_twice_claim_names_the_events_install_sh_wires(name: str) -> None:
    text = " ".join((REPO / name).read_text(encoding="utf-8").split())
    claims = re.finditer(r"\b(?:arrive|arrives|reach|reaches)\b[^.]{0,30}\btwice\b", text)
    starts = [claim.start() for claim in claims]
    assert starts, "no claim that events arrive twice"
    for start in starts:
        around = text[max(0, start - 400) : start + 400]
        assert "every event" not in around
        for event in wired_events():
            assert event in around, f"{name} does not name {event}"
