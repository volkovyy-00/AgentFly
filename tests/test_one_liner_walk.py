"""R1G (owner 2026-10-23): the one-liner walks cost a fixed multiple of the command's words.

Each interpreter name used to start a walk over a copy of every later word, and node's walk reads
on to the script or `--`, so `node node node ...` took 70-87 s for 20,000 words on main, in the
recorder and in the offline guard alike. Node's answer is now worked out once for the whole
command, from the right (`_node_one_liners`), and the other walks read the words in place. The
work is counted, not timed (tests/README.md): the words each walk looks at.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Iterator, Sequence
from types import ModuleType

import pytest

import agentfly.hook_client as guard
from agentfly.recorder import normalize
from tests.cases import MARKED_ALLOWED, NAMED_OUTBOUND, RECORDER_ONLY


def old_node_one_liner(args: Iterable[str]) -> bool:
    """`normalize._node_one_liner` as at 809eac5, copied word for word (the reference)."""
    for arg in args:
        if arg == "--" or arg.endswith((".js", ".mjs", ".cjs", ".ts")):
            return False
        if arg.startswith(("--eval", "--print")):
            return True
        if arg.startswith("-") and not arg.startswith("--") and arg[1:].isalpha():
            if "e" in arg[1:] or "p" in arg[1:]:
                return True
    return False


NODE_WORDS = [
    "node", "-e", "-p", "-pe", "-r", "--eval", "--eval=x", "--print", "--print=1", "--", "app.js",
    "x.mjs", "x.ts", "x.cjs", "-C", "dev", "--input-type", "module", "-e1", "-", "x", "prod",
    "--eval.js", "--print=x.ts",  # code and a script name at once: the script name wins
]  # fmt: skip


def word_lists() -> list[list[str]]:
    """The shared cases' words, and random runs of node's options and plain words."""
    found: list[list[str]] = [
        list(argv)
        for command in NAMED_OUTBOUND + RECORDER_ONLY + MARKED_ALLOWED
        for argv in normalize.normalize(command).all_commands()
    ]
    rng = random.Random(17)
    found += [[rng.choice(NODE_WORDS) for _ in range(rng.randint(0, 12))] for _ in range(3000)]
    return found


@pytest.mark.parametrize("module", [normalize, guard], ids=["recorder", "guard"])
def test_node_gives_the_old_walks_answer_at_every_position(module: ModuleType) -> None:
    for words in word_lists():
        found: list[bool] = module._node_one_liners(words)
        assert found == [old_node_one_liner(words[at:]) for at in range(len(words) + 1)], words


def recorder_inline(command: str) -> bool:
    return normalize.has_inline_code(command.split())


def guard_inline(command: str) -> bool:
    return guard.offline_answer(command)[1] == "outbound"


class Looks:
    """Counts the words the walks look at: each one node's pass reads, each one `_after` yields."""

    def __init__(self, module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count: int = 0
        stop: Callable[[str], bool] = module._node_stop
        after: Callable[[Sequence[str], int], Iterator[str]] = module._after

        def counted_stop(arg: str) -> bool:
            self.count += 1
            return stop(arg)

        def counted_after(words: Sequence[str], index: int) -> Iterator[str]:
            for word in after(words, index):
                self.count += 1
                yield word

        monkeypatch.setattr(module, "_node_stop", counted_stop)
        monkeypatch.setattr(module, "_after", counted_after)


WORDS = 20_000


@pytest.mark.parametrize("name", ["node", "perl", "ruby", "python3", "nodejs", "perl5.34"])
@pytest.mark.parametrize(
    ("module", "inline"),
    [(normalize, recorder_inline), (guard, guard_inline)],
    ids=["recorder", "guard"],
)
def test_many_interpreter_names_cost_a_fixed_multiple_of_the_words(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    inline: Callable[[str], bool],
    name: str,
) -> None:
    looks = Looks(module, monkeypatch)
    assert inline(f"{name} " * WORDS) is False
    assert looks.count <= 2 * WORDS, looks.count  # the old walks looked at about WORDS**2 / 2
    looks.count = 0
    code: str = "-c 1" if name.startswith("python") else "-e 1"
    assert inline(f"{name} " * WORDS + code) is True  # the last name's code is still found
    assert looks.count <= 2 * WORDS + 4, looks.count
