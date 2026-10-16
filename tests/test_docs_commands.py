"""Every command in AGENTS.md "Commands" and in README code blocks names files that exist."""

from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

from agentfly.cli import build_parser

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
