"""R1G (owner 2026-10-23): the one-liner walks cost a fixed multiple of the command's words.

Each interpreter name used to start a walk over a copy of the later words, and a walk read on
past other interpreter names (node to its script, `perl -I perl -I perl ...`, `-/ruby`), so 20,000
copies of `node` took 70-87 s on main, in the recorder and in the offline guard alike. Each
family's answer is now worked out once for the whole command, from the right
(`_one_liner_table`). The work is counted, not timed (tests/README.md): the words each family's
steps look at, and how many tables are made over how many words (a copy of the rest of the
command per name would be a table per name).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Sequence
from types import ModuleType

import pytest

import agentfly.hook_client as guard
from agentfly.recorder import normalize
from tests.cases import MARKED_ALLOWED, NAMED_OUTBOUND, RECORDER_ONLY, SCRIPT_NOT_INLINE

# ---------------------------------------------------------------- the reference walks


def old_python(args: Iterable[str]) -> bool:
    """`normalize._python_one_liner` as at 809eac5, copied word for word."""
    options = iter(args)
    for arg in options:
        if arg == "--" or not arg.startswith("-") or arg.startswith("-m"):
            return False
        if arg.startswith("--"):
            if arg == "--check-hash-based-pycs":
                next(options, None)
            continue
        for index, letter in enumerate(arg[1:], 1):
            if letter == "c":
                return True
            if letter == "m":
                return False
            if letter in "WXQ":
                if index == len(arg) - 1:
                    next(options, None)
                break
    return False


def old_node(args: Iterable[str]) -> bool:
    """`normalize._node_one_liner` as at 809eac5, copied word for word."""
    for arg in args:
        if arg == "--" or arg.endswith((".js", ".mjs", ".cjs", ".ts")):
            return False
        if arg.startswith(("--eval", "--print")):
            return True
        if arg.startswith("-") and not arg.startswith("--") and arg[1:].isalpha():
            if "e" in arg[1:] or "p" in arg[1:]:
                return True
    return False


def old_perl(args: Iterable[str]) -> bool:
    """`normalize._perl_one_liner` as at 0b92b4f, with a long option skipped (`--version`), and
    (V5c) a `-M`, `-m`, `-d:` or `-dt:` value that is no module name counted as code."""
    options = iter(args)
    for arg in options:
        if arg in ("-", "--") or not arg.startswith("-"):
            return False
        if arg.startswith("--"):
            continue
        for index, letter in enumerate(arg[1:], 1):
            if letter in "eE":
                return True
            rest = arg[index + 1 :]
            if letter == "d" and rest.startswith((":", "t:")):
                rest = rest.split(":", 1)[1]
            elif letter not in "MmI":
                continue
            if letter != "I" and not normalize.PERL_MODULE.fullmatch(rest):
                return True
            if letter == "I" and index == len(arg) - 1:
                next(options, None)
            break
    return False


def old_ruby(args: Iterable[str]) -> bool:
    """`normalize._ruby_one_liner` as at 0b92b4f, copied word for word."""
    options = iter(args)
    for arg in options:
        if arg in ("-", "--") or not arg.startswith("-"):
            return False
        if arg.startswith("--"):
            if arg in normalize._RUBY_VALUE_OPTIONS:
                next(options, None)
            continue
        index: int = 1
        while index < len(arg):
            letter: str = arg[index]
            index += 1
            if letter == "e":
                return True
            if letter in "rICXE":
                if index == len(arg):
                    next(options, None)
                break
            if letter in "xFi" or (letter == "W" and arg[index : index + 1] == ":"):
                break
            if letter == "K":
                index += 1
            elif letter in "0TW":
                while index < len(arg) and arg[index].isdigit():
                    index += 1
    return False


REFERENCE: dict[str, Callable[[Iterable[str]], bool]] = {
    "python": old_python,
    "node": old_node,
    "perl": old_perl,
    "ruby": old_ruby,
}
OPTION_WORDS = [
    "-e", "-E", "-p", "-pe", "-c", "-Sc", "-m", "-mx", "-W", "-X", "-Q", "-I", "-Ilib", "-M", "-Mx",
    "-r", "-rx", "-C", "-Ce", "-0", "-0e", "-K", "-Ke", "-W2e", "-W:x", "-x", "-F", "-i", "-lane",
    "--", "-", "--eval", "--eval=x", "--print", "--version", "--disable", "--parser", "--dump",
    "--check-hash-based-pycs", "--enable=gems", "app.js", "x.ts", "--eval.js", "--print=x.ts",
    "x.pl", "x.rb", "lib", "dev", "x", "perl", "ruby", "node", "python3", "-/ruby",
    "-MIO::Socket;1", "-MFoo=a,b", "-M-strict", "-d:Foo", "-dt:Foo", "-d:F;1", "-mFoo qw(x)", "-dx",
]  # fmt: skip


def word_lists() -> list[list[str]]:
    """The shared cases' words, and random runs of options, values and interpreter names."""
    commands = NAMED_OUTBOUND + RECORDER_ONLY + MARKED_ALLOWED + SCRIPT_NOT_INLINE
    found: list[list[str]] = [
        list(argv) for command in commands for argv in normalize.normalize(command).all_commands()
    ]
    rng = random.Random(17)
    found += [[rng.choice(OPTION_WORDS) for _ in range(rng.randint(0, 12))] for _ in range(3000)]
    return found


@pytest.mark.parametrize("family", list(REFERENCE))
@pytest.mark.parametrize("module", [normalize, guard], ids=["recorder", "guard"])
def test_the_table_gives_the_reference_walks_answer_at_every_position(
    module: ModuleType, family: str
) -> None:
    walk = REFERENCE[family]
    for words in word_lists():
        table: list[bool] = module._one_liner_table(words, module._STEPS[family])
        assert table[: len(words) + 1] == [walk(words[at:]) for at in range(len(words) + 1)], words


# ---------------------------------------------------------------- the work, counted


class Work:
    """Counts the words the steps look at, and the tables made with the words each covers."""

    def __init__(self, module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        self.steps: int = 0
        self.tables: list[int] = []
        table: Callable[[Sequence[str], Callable[[str], int]], list[bool]] = module._one_liner_table

        def counted_table(args: Sequence[str], step: Callable[[str], int]) -> list[bool]:
            self.tables.append(len(args))

            def counted_step(arg: str) -> int:
                self.steps += 1
                return step(arg)

            return table(args, counted_step)

        monkeypatch.setattr(module, "_one_liner_table", counted_table)


def recorder_inline(command: str) -> bool:
    return normalize.has_inline_code(command.split())


def guard_inline(command: str) -> bool:
    return guard.offline_answer(command)[1] == "outbound"


WORDS = 20_000
SHAPES = [
    ("node ", "-e 1"),
    ("perl ", "-e 1"),
    ("ruby ", "-e 1"),
    ("python3 ", "-c 1"),
    ("nodejs ", "-e 1"),
    ("perl5.34 ", "-e 1"),
    ("-/ruby ", "ruby -e 1"),  # a word that is an option and an interpreter name at once
    ("-I/perl ", "perl -e 1"),
    ("-/python3 ", "python3 -c 1"),
    ("perl -I ", "perl -e 1"),  # each value is the next interpreter name
    ("ruby -r ", "ruby -e 1"),
    ("node -r ", "node -e 1"),
]


@pytest.mark.parametrize(("unit", "code"), SHAPES, ids=[u.strip() for u, _ in SHAPES])
@pytest.mark.parametrize(
    ("module", "inline"),
    [(normalize, recorder_inline), (guard, guard_inline)],
    ids=["recorder", "guard"],
)
def test_many_interpreter_names_cost_a_fixed_multiple_of_the_words(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    inline: Callable[[str], bool],
    unit: str,
    code: str,
) -> None:
    text: str = unit * (WORDS // len(unit.split()))
    assert len(text.split()) == WORDS  # the old walks looked at about WORDS**2 / 2 words
    for command, expected in ((text, False), (text + code, True)):
        work = Work(module, monkeypatch)
        assert inline(command) is expected
        total: int = len(command.split())
        # one table a family, over the whole command (a copy of the rest per name is caught too)
        assert len(work.tables) <= len(normalize._STEPS) and set(work.tables) <= {total}
        assert work.steps <= len(normalize._STEPS) * total, work.steps
