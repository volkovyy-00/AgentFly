"""Every command in AGENTS.md "Commands" and in README code blocks names files that exist.

Also: the two files every session loads stay small and import nothing by accident, and the wheel
install line names the Python the project is built for.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

from agentfly.cli import build_parser
from agentfly.install import packages

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


def size_problem(data: bytes) -> str | None:
    """Bytes, not characters: the file holds `§` and `→`, which take two and three."""
    if len(data) > AGENTS_MAX_BYTES:
        return f"AGENTS.md is {len(data)} bytes; the cap is {AGENTS_MAX_BYTES}"
    return None


def _fence(line: str) -> tuple[str, int] | None:
    """The character and length of the fence a line opens, or None."""
    text = line.lstrip(" ")
    if len(line) - len(text) > 3 or text[:1] not in ("`", "~"):
        return None
    length = len(text) - len(text.lstrip(text[0]))
    if length < 3 or (text[0] == "`" and "`" in text[length:]):  # a span, not a fence
        return None
    return text[0], length


def _closes(line: str, fence: tuple[str, int]) -> bool:
    text = line.strip()
    return (
        len(line) - len(line.lstrip(" ")) <= 3
        and len(text) >= fence[1]
        and (text == fence[0] * len(text))
    )


def _block_kind(line: str) -> str:
    """`blank` or `single` (one line, no continuation), `start` (a block that may go on), `text`.

    Calling a line a block start when CommonMark does not only ends a code span early, which
    checks more text. Calling one `text` when it starts a block would let a stray backtick hide
    the lines after it.
    """
    text = line.strip()
    if not text:
        return "blank"
    compact = text.replace(" ", "")
    if text[0] == "#" or (
        len(compact) >= 3 and compact[0] in "-*_" and compact == compact[0] * len(compact)
    ):
        return "single"  # a heading or a thematic break
    digits = len(text) - len(text.lstrip("0123456789"))
    bullet = text[0] in "-*+" and text[1:2] in ("", " ", "\t")
    numbered = (
        0 < digits <= 9
        and text[digits : digits + 1] in (".", ")")
        and (text[digits + 1 : digits + 2] in ("", " ", "\t"))
    )
    return "start" if text[0] == ">" or bullet or numbered else "text"


def _blank_spans(paragraph: str) -> str:
    """`paragraph` with every code span overwritten by NUL characters (line breaks stay).

    A run of n backticks opens a span that the next run of exactly n closes. One backward pass
    finds each run's closer, one forward pass blanks: the work is linear. A run that nothing
    closes, or one after a backslash, is plain text.
    """
    runs = [(m.start(), m.end() - m.start()) for m in re.finditer(r"`+", paragraph)]
    closer: list[int | None] = [None] * len(runs)
    latest: dict[int, int] = {}
    for at in range(len(runs) - 1, -1, -1):
        closer[at] = latest.get(runs[at][1])
        latest[runs[at][1]] = at
    blanked = list(paragraph)
    at = 0
    while at < len(runs):
        start = runs[at][0]
        end = closer[at]
        if end is None or paragraph[start - 1 : start] == "\\":
            at += 1
            continue
        for index in range(start, runs[end][0] + runs[end][1]):
            if blanked[index] != "\n":
                blanked[index] = "\x00"
        at = end + 1
    return "".join(blanked)


def _outside_code(text: str) -> tuple[str, int | None]:
    """`text` with fenced blocks and code spans overwritten by NUL characters.

    The result has the length and the line breaks of `text`. A span may cross a line break but
    not the end of its paragraph (a blank line, a heading, a list item, a quote). The second
    value is the line of a fence that never closes, or None.
    """
    out: list[str] = []
    paragraph: list[str] = []
    fence: tuple[str, int] | None = None
    opened = 0

    def end_paragraph() -> None:
        if paragraph:
            out.extend(_blank_spans("\n".join(paragraph)).split("\n"))
            paragraph.clear()

    for number, line in enumerate(text.split("\n"), 1):
        if fence is not None:
            out.append("\x00" * len(line))
            if _closes(line, fence):
                fence = None
            continue
        opening = _fence(line)
        kind = "fence" if opening else _block_kind(line)
        if kind != "text":
            end_paragraph()
        if opening:
            fence, opened = opening, number
            out.append("\x00" * len(line))
        elif kind in ("blank", "single"):
            out.append(_blank_spans(line))
        else:
            paragraph.append(line)
    end_paragraph()
    return "\n".join(out), (opened if fence else None)


def stray_imports(text: str, allowed: str | None = None) -> list[str]:
    """Each `@name` Claude Code would import from `text`; `allowed` may open one line, once.

    One pass over the text. Unsure means a finding: an unclosed backtick run is plain text, and a
    fenced block that never closes is itself a finding. The named file is never opened.
    """
    outside, unclosed = _outside_code(text)
    problems = [f"line {unclosed}: a fenced block is never closed"] if unclosed else []
    line, line_start, seen = 1, 0, 0
    for found in _IMPORT.finditer(outside):
        start = found.start()
        breaks = text.count("\n", seen, start)
        if breaks:
            line += breaks
            line_start = text.rfind("\n", seen, start) + 1
        seen = start
        name = text[start : found.end()]
        if allowed and name == allowed and start == line_start:
            allowed = None  # that line, once
            continue
        problems.append(f"line {line}: {name[:40]}")
    return problems


def test_agents_md_stays_under_its_size_cap() -> None:
    assert size_problem((REPO / "AGENTS.md").read_bytes()) is None


@pytest.mark.parametrize(
    ("data", "fails"),
    [
        (b"x" * 14_000, False),
        (b"x" * 14_001, True),
        ("§".encode() * 7_000, False),  # 7 000 characters, 14 000 bytes
        ("§".encode() * 7_001, True),  # 7 001 characters, 14 002 bytes
        ("→".encode() * 4_667, True),  # 4 667 characters, 14 001 bytes
        (b"", False),
    ],
    ids=[
        "14000 bytes",
        "14001 bytes",
        "14000 bytes of §",
        "14002 bytes of §",
        "14001 of →",
        "empty",
    ],
)
def test_the_size_cap_counts_bytes(data: bytes, fails: bool) -> None:
    assert (size_problem(data) is not None) is fails


@pytest.mark.parametrize("name", ["AGENTS.md", "CLAUDE.md"])
def test_the_files_every_session_loads_import_only_what_they_mean_to(name: str) -> None:
    text = (REPO / name).read_text(encoding="utf-8")
    assert stray_imports(text, IMPORT_LINE if name == "CLAUDE.md" else None) == []


NOT_IMPORTS = {
    "an address": "mail noreply@anthropic.com now",
    "a trailer": "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>",
    "a letter then an at sign": "a1@b and x@y",
    "a code span": "`@x`",
    "a double-backtick span": "`` `@x` ``",
    "a span with a longer run inside": "``a ` @x``",
    "a span over a line break": "see `uv run\n@x` here",
    "a fenced block": "```\n@x\n```",
    "a tilde block": "~~~sh\n@x\n~~~",
    "a block that a shorter run does not close": "````\n```\n@x\n```\n````",
    "a block closed by a longer run": "```\n@x\n`````",
    "a block inside a list item": "- item\n  ```\n  @x\n  ```\n- next",
    "an at sign with no name": "an @ sign, a trailing @",
    "a span after a closed one": "`a` and `@x`",
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
    "in a quote after a line with an unclosed backtick": "a `b\n> see @x `c`",
    "after an escaped backtick": "\\`@x\\`",
    "after a fence line with a backtick in its info": "```a`b\n@x",
    "after a fence that a shorter run does not close": "````\n@x\n```\n@y\n",
    "after a tilde block closed by backticks": "~~~\nz\n```\n@y",
    "a name in a link": "[SPEC](@SPEC.md)",
    "two imports on one line": "see @AGENTS.md and @AGENTS.md",
}


@pytest.mark.parametrize("text", IMPORTS.values(), ids=IMPORTS.keys())
def test_text_that_imports_a_file_fails(text: str) -> None:
    assert stray_imports(text) != []


def test_a_fence_that_never_closes_is_a_finding_not_a_hiding_place() -> None:
    assert stray_imports("```\n@x") == ["line 1: a fenced block is never closed"]
    assert stray_imports("```\nx\n```\n@x") == ["line 4: @x"]


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


def test_every_byte_goes_through_the_span_scan_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The file is scanned in one pass: a scan that went back over earlier lines would not be."""
    sizes: list[int] = []
    real = _blank_spans

    def spy(paragraph: str) -> str:
        sizes.append(len(paragraph))
        return real(paragraph)

    monkeypatch.setitem(globals(), "_blank_spans", spy)  # this module, however pytest imported it
    hostile = "\n".join(f"line {n} `{'`' * (n % 7)} @x{n} ``" for n in range(600))
    text = hostile + "\n\n" + "`" * 3_000 + "\n" + "a `b\n" * 600
    stray_imports(text)
    assert sizes, "the span scan never ran"
    assert sum(sizes) <= len(text)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param((REPO / "README.md").read_text(encoding="utf-8"), id="README.md"),
        pytest.param((REPO / "AGENTS.md").read_text(encoding="utf-8"), id="AGENTS.md"),
        pytest.param((REPO / "SPEC.md").read_text(encoding="utf-8"), id="SPEC.md"),
        pytest.param(packages.WHEEL_HINT, id="WHEEL_HINT"),
    ],
)
def test_every_wheel_install_line_names_the_python_the_project_uses(source: str) -> None:
    """Without `--python`, uv picks its newest Python (3.14 on one Mac), not `.python-version`."""
    python = (REPO / ".python-version").read_text(encoding="utf-8").strip()
    lines = [line for line in source.splitlines() if "tool install" in line and "dist/" in line]
    assert lines, "no wheel install line found"
    for line in lines:
        assert f"uv tool install --python {python} dist/*.whl" in line, line
