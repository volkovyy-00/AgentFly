"""`.github/workflows/ci.yml` keeps the properties the owner approved (F7). Standard library only.

The workflow is read with a small YAML-subset parser that refuses what it cannot read (duplicate or
quoted keys, anchors, tags, flow maps, extra documents), so an edit cannot hide a trigger, a
permission or an action from these checks: it fails here until the parser is taught the new syntax.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import REPO

WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
AGENTS = REPO / "AGENTS.md"

GROUP = "ci-${{ github.event_name == 'pull_request' && github.ref || github.sha }}"
CANCEL = "${{ github.event_name == 'pull_request' }}"
TRIGGERS = {"push": {"branches": ["main"]}, "pull_request": None}
# The three AGENTS.md check commands, found by the label of their bullet, in the order CI runs them.
CHECK_LABELS = {
    "check": r"- Check \(run before",
    "web check": r"- Web check:",
    "stale-build check": r"- Stale-build check:",
}
# Default-deny: a key that is not listed (if, env, continue-on-error, shell, working-directory,
# defaults, strategy, ...) can switch a step off or change what it does, so it needs a deliberate
# edit of this test.
TOP_KEYS = {"name", "on", "permissions", "concurrency", "jobs"}
JOB_KEYS = {"runs-on", "timeout-minutes", "steps"}
STEP_KEYS = {"name", "uses", "with", "run"}
# AGENTS.md: ask before adding an action. A new one needs a deliberate edit of this table. Each
# action takes exactly these inputs: no token, and no cache (setup-uv and setup-node turn their
# cache on by themselves when the input is left out).
ACTION_INPUTS = {
    "actions/checkout": {"persist-credentials": "false"},
    "astral-sh/setup-uv": {"enable-cache": "false"},
    "actions/setup-node": {"node-version-file": "ui/.nvmrc", "package-manager-cache": "false"},
}
RUNNER = "macos-15"
FORBIDDEN_WORDS = ("secrets", "pull_request_target", "workflow_run")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

# ---------------------------------------------------------------- the YAML subset


class YamlError(ValueError):
    pass


_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?: +(.*))?$")
# Line breaks to a YAML parser that this one does not split on: after a comment they hide a key.
_OTHER_BREAK = re.compile("\r(?!\n)|[\x85\u2028\u2029]")
_NOT_A_PLAIN_START = "&*!{>%@`?|[],"


def _cut_comment(value: str) -> str:
    """A plain value ends at ' #'; a quoted one at its closing quote."""
    if value and value[0] in "'\"":
        quote, i = value[0], 1
        while i < len(value):
            if value[i] == quote and value[i + 1 : i + 2] == quote == "'":
                i += 2  # '' is a quote inside a single-quoted value
            elif value[i] == quote:
                break
            else:
                i += 1
        else:
            raise YamlError(f"unterminated quote in {value!r}")
        rest = value[i + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise YamlError(f"text after a quoted value: {value!r}")
        return value[: i + 1]
    index = value.find(" #")
    return (value[:index] if index >= 0 else value).rstrip()


def _scalar(value: str) -> str:
    value = _cut_comment(value.strip())
    if value and value[0] in "'\"":
        inner = value[1:-1]
        if "\\" in inner:
            raise YamlError(f"escapes in {value!r}")
        return inner.replace("''", "'") if value[0] == "'" else inner
    if value and value[0] in _NOT_A_PLAIN_START:
        raise YamlError(f"unsupported value {value!r}")
    if ": " in value or value.endswith(":"):
        raise YamlError(f"a key hidden in a value: {value!r}")
    return value


def _flow_list(value: str) -> list[str]:
    value = _cut_comment(value)
    if not value.endswith("]") or any(c in value[1:-1] for c in "[]{}"):
        raise YamlError(f"only flat [a, b] lists are read: {value!r}")
    return [_scalar(part) for part in value[1:-1].split(",") if part.strip()]


class _Parser:
    def __init__(self, text: str) -> None:
        if _OTHER_BREAK.search(text):
            raise YamlError("a line break other than LF or CRLF")
        self.lines = text.split("\n")
        self.i = 0

    def line(self) -> tuple[int, str] | None:
        """The next line with content as (indent, text), skipping blanks and comments."""
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            indent = len(raw) - len(raw.lstrip(" "))
            if "\t" in raw[: len(raw) - len(raw.lstrip())]:
                raise YamlError(f"line {self.i + 1}: tab in the indent")
            content = raw.strip()
            if content and not content.startswith("#"):
                if content.split(" ")[0] in ("---", "..."):
                    raise YamlError(f"line {self.i + 1}: document markers")
                return indent, content
            self.i += 1
        return None

    def document(self) -> Any:
        first = self.line()
        if first is None:
            return None
        node = self.block(first[0])
        if self.line() is not None:
            raise YamlError(f"line {self.i + 1}: unexpected indent")
        return node

    def block(self, indent: int) -> Any:
        current = self.line()
        assert current is not None
        if current[1] == "-" or current[1].startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    def mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while (cur := self.line()) is not None and cur[0] == indent:
            if cur[1] == "-" or cur[1].startswith("- "):
                raise YamlError(f"line {self.i + 1}: a list where a key was expected")
            found = _KEY.match(cur[1])
            if found is None:
                raise YamlError(f"line {self.i + 1}: cannot read {cur[1]!r} (quoted key?)")
            key = found.group(1)
            if key in result:
                raise YamlError(f"line {self.i + 1}: duplicate key {key!r}")
            self.i += 1
            result[key] = self.value((found.group(2) or "").strip(), indent)
        return result

    def value(self, rest: str, indent: int) -> Any:
        if rest.startswith("#"):
            rest = ""
        if rest in ("|", "|-"):
            return self.literal(indent)
        if rest.startswith("["):
            return _flow_list(rest)
        if rest:
            return _scalar(rest)
        following = self.line()
        if following is not None and following[0] > indent:
            return self.block(following[0])
        return None

    def literal(self, indent: int) -> str:
        body: list[str] = []
        base: int | None = None
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            if not raw.strip():
                body.append("")
            else:
                here = len(raw) - len(raw.lstrip(" "))
                if here <= indent:
                    break
                base = here if base is None else base
                if here < base:
                    raise YamlError(f"line {self.i + 1}: text left of its block")
                body.append(raw[base:])
            self.i += 1
        return "\n".join(body).rstrip("\n")

    def sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while (cur := self.line()) is not None and cur[0] == indent:
            content = cur[1]
            if not (content == "-" or content.startswith("- ")):
                break
            rest = content[1:].lstrip(" ")
            offset = indent + len(content) - len(rest)
            if not rest or rest.startswith("#"):
                self.i += 1
                following = self.line()
                items.append(
                    self.block(following[0]) if following and following[0] > indent else None
                )
            elif _KEY.match(rest):
                self.lines[self.i] = " " * offset + rest  # the mapping starts on the dash line
                items.append(self.mapping(offset))
            else:
                self.i += 1
                items.append(_flow_list(rest) if rest.startswith("[") else _scalar(rest))
        return items


def parse(text: str) -> Any:
    return _Parser(text).document()


# ---------------------------------------------------------------- the pinned properties


def strings(node: Any) -> Iterator[str]:
    """Every key and every value in the document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from strings(item)
    elif isinstance(node, str):
        yield node


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def agents_checks(agents: str) -> dict[str, str]:
    """The AGENTS.md check commands by label; a label whose bullet is gone is missing."""
    section = agents.split("## Commands", 1)[1].split("\n## ", 1)[0]
    found: dict[str, str] = {}
    for name, label in CHECK_LABELS.items():
        match = re.search(label + r"[^`]*`([^`]+)`", section)
        if match:
            found[name] = " ".join(match.group(1).split())
    return found


def steps_of(job: Any) -> list[dict[str, Any]]:
    steps = job.get("steps") if isinstance(job, dict) else None
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def unknown_keys(where: str, node: Any, allowed: set[str]) -> list[str]:
    extra = sorted(set(node) - allowed) if isinstance(node, dict) else []
    return [f"{where} has keys this test does not allow: {extra}"] if extra else []


def job_problems(name: str, job: Any) -> list[str]:
    if not isinstance(job, dict):
        return [f"job {name} is not a mapping"]
    found = unknown_keys(f"job {name}", job, JOB_KEYS)
    if job.get("runs-on") != RUNNER:
        found.append(f"job {name}: runs-on must be exactly {RUNNER}, got {job.get('runs-on')!r}")
    steps = steps_of(job)
    for step in steps:
        found += unknown_keys(f"a step of job {name}", step, STEP_KEYS)
        uses = step.get("uses")
        if uses is None:
            continue
        action = str(uses).split("@")[0]
        if not (isinstance(uses, str) and PINNED.match(uses)):
            found.append(f"uses must be pinned to a 40-character commit SHA, got {uses!r}")
        elif action not in ACTION_INPUTS:
            found.append(f"action not approved in AGENTS.md: {uses!r}")
        elif step.get("with") != ACTION_INPUTS[action]:
            found.append(f"{action} takes exactly {ACTION_INPUTS[action]}, got {step.get('with')}")
    if not any(str(step.get("uses", "")).startswith("actions/checkout@") for step in steps):
        found.append(f"job {name}: no actions/checkout step")
    return found


def run_problems(jobs: dict[str, Any], agents: str) -> list[str]:
    checks = agents_checks(agents)
    if len(checks) != len(CHECK_LABELS):
        return [f"AGENTS.md Commands must hold the three check commands, found {len(checks)}"]
    wanted = ["uv sync --locked", *checks.values()]
    found = []
    for name, job in jobs.items():
        runs = [step["run"] for step in steps_of(job) if "run" in step]
        # One command per step: in a block, GitHub's `bash -e` goes on past a failed `a && b` line.
        found += [
            f"job {name}: a run value must be one line, one command per step: {run!r}"
            for run in runs
            if not isinstance(run, str) or "\n" in run
        ]
        lines = [re.sub(r"[ \t]+", " ", run.strip()) for run in runs if isinstance(run, str)]
        absent = [cmd for cmd in wanted if cmd not in lines]
        found += [f"job {name} lacks the step: {cmd}" for cmd in absent]
        found += [
            f"job {name} runs a command outside AGENTS.md: {x}" for x in lines if x not in wanted
        ]
        places = [lines.index(cmd) for cmd in wanted if cmd in lines]
        if not absent and places != sorted(places):
            found.append(f"job {name}: run uv sync, then the AGENTS.md commands in order")
    return found


def problems(text: str, agents: str) -> list[str]:
    try:
        doc = parse(text)
    except YamlError as exc:
        return [f"outside the YAML subset this test reads: {exc}"]
    if not isinstance(doc, dict):
        return ["the workflow is not a mapping"]
    found = unknown_keys("the workflow", doc, TOP_KEYS)
    if doc.get("on") != TRIGGERS:
        found.append(
            f"trigger: only `push: branches: [main]` and `pull_request`, got {doc.get('on')}"
        )
    if doc.get("permissions") != {"contents": "read"}:
        found.append(f"permissions must be exactly `contents: read`, got {doc.get('permissions')}")
    if doc.get("concurrency") != {"group": GROUP, "cancel-in-progress": CANCEL}:
        found.append(f"concurrency must cancel an older pull-request run: {doc.get('concurrency')}")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [*found, "no jobs"]
    for name, job in jobs.items():
        found += job_problems(name, job)
    found += run_problems(jobs, agents)
    for text_ in strings(doc):
        for word in FORBIDDEN_WORDS:
            if re.search(rf"\b{word}\b", text_, re.IGNORECASE):
                found.append(f"`{word}` appears in {text_!r}")
    return found


# ---------------------------------------------------------------- tests


def test_the_workflow_keeps_its_approved_properties() -> None:
    assert problems(read(WORKFLOW), read(AGENTS)) == []


def test_the_three_check_commands_are_found_in_agents_md() -> None:
    checks = agents_checks(read(AGENTS))
    assert {label: command.split()[0] for label, command in checks.items()} == {
        "check": "uv",
        "web check": "npm",
        "stale-build check": "npm",
    }


ENV_SECRET = "- run: uv sync --locked\n        env:\n          T: ${{ SECRETS.TOKEN }}"


def pinned(action: str) -> str:
    """`owner/name@<sha>` as ci.yml pins it now, so a Dependabot bump leaves the cases below valid.

    With no pin to find (or no ci.yml) the text is one that is not in the file: only the cases that
    use it fail, and this module still imports.
    """
    try:
        text = read(WORKFLOW)
    except OSError:
        text = ""
    found = re.search(rf"{re.escape(action)}@[0-9a-f]{{40}}", text)
    return found.group(0) if found else f"{action}@<no pin in ci.yml>"


CHECKOUT, SETUP_UV, SETUP_NODE = (
    pinned(action) for action in ("actions/checkout", "astral-sh/setup-uv", "actions/setup-node")
)

# (what is edited, the text to replace, its replacement, a fragment of the problem it must raise)
MUTATIONS = [
    ("a third trigger", "  pull_request:\n", "  pull_request:\n  workflow_dispatch:\n", "trigger"),
    ("pull_request_target", "  pull_request:\n", "  pull_request_target:\n", "pull_request_target"),
    ("push to other branches", "branches: [main]", "branches: [main, dev]", "trigger"),
    ("push of tags", "branches: [main]", "branches: [main]\n    tags: [v1]", "trigger"),
    ("a PR filter", "  pull_request:\n", "  pull_request:\n    branches: [main]\n", "trigger"),
    ("a second on key", "\npermissions:", "\non:\n  workflow_dispatch:\npermissions:", "duplicate"),
    ("a quoted on key", "\non:\n", '\n"on":\n', "quoted key"),
    ("a write permission", "contents: read", "contents: write", "permissions"),
    ("an extra permission", "contents: read", "contents: read\n  id-token: write", "permissions"),
    (
        "a job permission",
        "    timeout-minutes",
        "    permissions:\n      contents: write\n    timeout-minutes",
        "does not allow",
    ),
    ("a tag instead of a SHA", CHECKOUT, "actions/checkout@v7", "pinned"),
    ("a short SHA", SETUP_UV, SETUP_UV[: SETUP_UV.index("@") + 8], "pinned"),
    (
        "a local action",
        "- run: uv sync --locked",
        "- uses: ./local\n      - run: uv sync --locked",
        "pinned",
    ),
    (
        "a secret",
        "- run: uv sync --locked",
        "- run: uv sync --locked\n        env:\n          T: ${{ secrets.TOKEN }}",
        "secrets",
    ),
    (
        "kept credentials",
        "persist-credentials: false",
        "persist-credentials: true",
        "persist-credentials",
    ),
    (
        "no checkout setting",
        "        with:\n          persist-credentials: false\n",
        "",
        "persist-credentials",
    ),
    ("a Linux runner", "runs-on: macos-15", "runs-on: ubuntu-latest", "macos-15"),
    ("a runner list", "runs-on: macos-15", "runs-on: [macos-15, ubuntu-latest]", "macos-15"),
    ("an older macOS runner", "runs-on: macos-15", "runs-on: macos-14", "macos-15"),
    ("a moving macOS label", "runs-on: macos-15", "runs-on: macos-latest", "macos-15"),
    ("no cancel", "  cancel-in-progress: " + CANCEL + "\n", "", "concurrency"),
    (
        "an inverted cancel",
        "cancel-in-progress: " + CANCEL,
        "cancel-in-progress: ${{ github.event_name != 'pull_request' }}",
        "concurrency",
    ),
    ("a group by sha only", GROUP, "ci-${{ github.sha }}", "concurrency"),
    ("an unapproved action", SETUP_NODE, "actions/cache@" + "0" * 40, "not approved"),
    ("an unlocked sync", "- run: uv sync --locked", "- run: uv sync", "uv sync --locked"),
    (
        "a non-breaking space in a command",
        "- run: uv sync --locked",
        "- run: uv sync\xa0--locked",
        "lacks the step",
    ),
    (
        "a carriage return that hides a key",
        "      - name: Check\n",
        "      - name: Check # x\r        continue-on-error: true\n",
        "line break",
    ),
    ("an upper-case secret", "- run: uv sync --locked", ENV_SECRET, "secrets"),
    (
        "a switched-off step",
        "      - name: Check\n",
        "      - name: Check\n        continue-on-error: true\n",
        "does not allow",
    ),
    (
        "a switched-off job",
        "    timeout-minutes: 30\n",
        "    timeout-minutes: 30\n    if: false\n",
        "does not allow",
    ),
    (
        "a job env",
        "    timeout-minutes: 30\n",
        "    timeout-minutes: 30\n    env:\n      PYTEST_ADDOPTS: -k nothing\n",
        "does not allow",
    ),
    (
        "a step env",
        "- run: uv sync --locked",
        "- run: uv sync --locked\n        env:\n          PYTEST_ADDOPTS: -k nothing",
        "does not allow",
    ),
    (
        "a working directory",
        "- run: uv sync --locked",
        "- run: uv sync --locked\n        working-directory: ui",
        "does not allow",
    ),
    ("a shell", "- name: Check\n", "- name: Check\n        shell: bash {0}\n", "does not allow"),
    (
        "top-level defaults",
        "\njobs:\n",
        "\ndefaults:\n  run:\n    shell: bash {0}\njobs:\n",
        "does not allow",
    ),
    (
        "an early exit",
        "- run: uv sync --locked",
        "- run: |\n          exit 0\n          uv sync --locked",
        "outside AGENTS.md",
    ),
    ("a check made harmless", "--dist loadgroup", "--dist loadgroup || true", "lacks the step"),
    (
        "another checkout input",
        "persist-credentials: false",
        "persist-credentials: false\n          ref: x",
        "takes exactly",
    ),
    ("uv cache switched on", "enable-cache: false", "enable-cache: true", "takes exactly"),
    (
        "no uv cache setting",
        "        with:\n          enable-cache: false\n",
        "",
        "takes exactly",
    ),
    (
        "a token for setup-uv",
        "enable-cache: false",
        "enable-cache: false\n          github-token: abc",
        "takes exactly",
    ),
    (
        "npm cache switched on",
        "package-manager-cache: false",
        "package-manager-cache: true",
        "takes exactly",
    ),
    (
        "another setup-node input",
        "package-manager-cache: false",
        "package-manager-cache: false\n          cache: npm",
        "takes exactly",
    ),
    (
        "two checks in one run block",
        "run: npm --prefix ui ci && npm --prefix ui run check\n      - name: Stale-build check\n"
        "        run: ",
        "run: |\n          npm --prefix ui ci && npm --prefix ui run check\n          ",
        "one line",
    ),
    (
        "every step in one run block",
        "      - run: uv sync --locked\n      - name: Check\n        run: ",
        "      - run: |\n          uv sync --locked\n          ",
        "one line",
    ),
]


@pytest.mark.parametrize(
    ("old", "new", "fragment"), [m[1:] for m in MUTATIONS], ids=[m[0] for m in MUTATIONS]
)
def test_the_checks_notice_an_edit_that_breaks_a_property(
    old: str, new: str, fragment: str
) -> None:
    text = read(WORKFLOW)
    assert old in text, f"the mutation no longer applies to ci.yml: {old!r}"
    found = problems(text.replace(old, new, 1), read(AGENTS))
    assert any(fragment in problem for problem in found), (fragment, found)


@pytest.mark.parametrize("label", list(CHECK_LABELS))
def test_the_checks_notice_a_missing_agents_md_command(label: str) -> None:
    text = read(WORKFLOW)
    command = agents_checks(read(AGENTS))[label]
    assert command in text, command
    found = problems(text.replace(command, "true", 1), read(AGENTS))
    assert any(command in problem for problem in found), found


def test_the_checks_notice_commands_run_out_of_order() -> None:
    checks = agents_checks(read(AGENTS))
    web, stale = checks["web check"], checks["stale-build check"]
    swapped = read(WORKFLOW).replace(web, "@@").replace(stale, web).replace("@@", stale)
    found = problems(swapped, read(AGENTS))
    assert any("in order" in problem for problem in found), found


# ---------------------------------------------------------------- the parser itself


def test_the_parser_reads_nesting_lists_comments_and_block_text() -> None:
    sample = (
        "# top comment\n"
        "on:\n"
        "  push:\n"
        "    branches: [main, 'dev one']  # trailing\n"
        "  pull_request:\n"
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - uses: x/y@abc # tag\n"
        "        with:\n"
        '          k: "v # not a comment"\n'
        "      - run: |\n"
        "          one\n"
        "          # kept\n"
        "\n"
        "          two\n"
        "      - plain\n"
    )
    assert parse(sample) == {
        "on": {"push": {"branches": ["main", "dev one"]}, "pull_request": None},
        "jobs": {
            "a": {
                "steps": [
                    {"uses": "x/y@abc", "with": {"k": "v # not a comment"}},
                    {"run": "one\n# kept\n\ntwo"},
                    "plain",
                ]
            }
        },
    }


@pytest.mark.parametrize(
    "text",
    [
        "a: 1\na: 2\n",
        "<<: *base\n",
        "a: &anchor 1\n",
        "a: !tag 1\n",
        "a: {b: 1}\n",
        "a: [b, [c]]\n",
        "---\na: 1\n",
        "a: 1\n---\nb: 2\n",
        "\ta: 1\n",
        "a:\n  b: 1\n    c: 2\n",
        "'a': 1\n",
        "? a\n: 1\n",
        "a: 'open\n",
        "a: 1 # x\rb: 2\n",
        "a: 1 # x\u2028b: 2\n",
        "a: 1 # x\x85b: 2\n",
    ],
)
def test_the_parser_refuses_what_it_does_not_read(text: str) -> None:
    with pytest.raises(YamlError):
        parse(text)


def test_the_parser_reads_windows_line_endings() -> None:
    assert parse("a: 1\r\nb:\r\n  c: 2\r\n") == {"a": "1", "b": {"c": "2"}}
