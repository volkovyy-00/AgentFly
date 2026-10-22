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
_LIST_ITEM = re.compile(r"(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]|$)")
_NUL = "\x00"  # stands in for text that is code


def size_problem(data: bytes) -> str | None:
    """Bytes, not characters: the file holds `§` and `→`, which take two and three."""
    if len(data) > AGENTS_MAX_BYTES:
        return f"AGENTS.md is {len(data)} bytes; the cap is {AGENTS_MAX_BYTES}"
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


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
    text = line.strip()
    return _indent(line) <= 3 and text.startswith(fence) and not text.strip(fence[0])


def _block_kind(line: str) -> str:
    """`single` (a block of one line), `start` (a block that may go on) or `text`.

    Calling a line a block of its own when CommonMark does not only ends a code span early, which
    checks more text. Calling one `text` when it starts a block would let a stray backtick hide
    the lines after it: so a blank line, a heading, a setext or thematic line and an indented
    (code) line are `single`; a quote and a list item are `start`.
    """
    text = line.strip()
    if not text or line.startswith(("    ", "\t")):
        return "single"
    compact = text.replace(" ", "")
    ruled = compact == compact[0] * len(compact) and compact[0] in "=-*_"
    if text[0] == "#" or (ruled and (len(compact) >= 3 or compact[0] in "=-")):
        return "single"
    return "start" if text[0] == ">" or _LIST_ITEM.match(text) else "text"


def _hide(text: str) -> str:
    return re.sub(r"[^\n]", _NUL, text)


def _blank_spans(paragraph: str) -> str:
    """`paragraph` with every code span overwritten by NUL characters (line breaks stay).

    A run of n backticks opens a span that the next run of exactly n closes. One backward pass
    finds each run's closer, one forward pass blanks: the work is linear. A run that nothing
    closes, or one after a backslash, is plain text.
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


def _outside_code(text: str) -> tuple[list[str], int | None]:
    """The lines of `text` with fenced blocks and code spans overwritten by NUL characters.

    Every line keeps its length. A span may cross a line break but not the end of its paragraph
    (see `_block_kind`). The second value is the line of a fence that never closes, or None.
    """
    out: list[str] = []
    paragraph: list[str] = []
    fence: str | None = None
    opened = 0

    def end_paragraph() -> None:
        if paragraph:
            out.extend(_blank_spans("\n".join(paragraph)).split("\n"))
            paragraph.clear()

    for number, line in enumerate(text.split("\n"), 1):
        if fence is not None:
            out.append(_NUL * len(line))
            if _closes(line, fence):
                fence = None
            continue
        opening = _fence(line)
        kind = _block_kind(line)
        if opening or kind != "text":
            end_paragraph()
        if opening:
            fence, opened = opening, number
            out.append(_NUL * len(line))
        elif kind == "single":
            out.append(_blank_spans(line))
        else:
            paragraph.append(line)
    end_paragraph()
    return out, (opened if fence is not None else None)


def stray_imports(text: str, allowed: str | None = None) -> list[str]:
    """Each `@name` Claude Code would import from `text`; `allowed` may open one line, once.

    One pass over the text. Unsure means a finding: an unclosed backtick run is plain text, and a
    fenced block that never closes is itself a finding. The named file is never opened.
    """
    rows, unclosed = _outside_code(text)
    problems = [f"line {unclosed}: a fenced block is never closed"] if unclosed else []
    for number, (row, original) in enumerate(zip(rows, text.split("\n"), strict=True), 1):
        for found in _IMPORT.finditer(row):
            name = original[found.start() : found.end()]
            if allowed and name == allowed and found.start() == 0:
                allowed = None  # that line, once
                continue
            problems.append(f"line {number}: {name[:40]}")
    return problems


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
    "in a line after a setext underline with an unclosed backtick": "Title `a\n===\nsee @x `c`",
    "in a line after indented code with an unclosed backtick": "    code `a\nsee @x `c`",
    "in a line after a tab-indented line with an unclosed backtick": "\tcode `a\nsee @x `c`",
    "in a quote after a line with an unclosed backtick": "a `b\n> see @x `c`",
    "after an escaped backtick": "\\`@x\\`",
    "a name in a link": "[SPEC](@SPEC.md)",
    "two imports on one line": "see @AGENTS.md and @AGENTS.md",
}


@pytest.mark.parametrize("text", IMPORTS.values(), ids=IMPORTS.keys())
def test_text_that_imports_a_file_fails(text: str) -> None:
    assert stray_imports(text) != []


FENCES = {
    "a backtick in the info string opens no block": ("```a`b\n@x", ["line 2: @x"]),
    "a shorter run does not close a block": ("````\n@x\n```\n@y\n````\n@z", ["line 6: @z"]),
    "backticks do not close a tilde block": ("~~~\n@x\n```\n@y\n~~~\n@z", ["line 6: @z"]),
    "a closing fence carries no words": ("```\n@x\n``` tail\n@y\n```\n@z", ["line 6: @z"]),
    "a closing fence is indented three spaces at most": (
        "```\n@x\n    ```\n@y\n```\n@z",
        ["line 6: @z"],
    ),
    "a block that never closes is a finding": (
        "```\n@x",
        ["line 1: a fenced block is never closed"],
    ),
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


_WHEEL_INSTALL = re.compile(r"uv tool install [^`\"]*?dist/\S*")


def wheel_installs(text: str) -> list[str]:
    """Each `uv tool install ... dist/...` command in `text`; a wrapped one is joined first."""
    return _WHEEL_INSTALL.findall(" ".join(text.split()))


def names_the_python(command: str) -> bool:
    """Without `--python`, uv picks its newest Python (3.14 on one Mac), not `.python-version`."""
    python = (REPO / ".python-version").read_text(encoding="utf-8").strip()
    return re.search(rf"--python[ =]{re.escape(python)}\b", command) is not None


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
