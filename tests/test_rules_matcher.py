"""V5b-fix2: the path matcher, whose cost does not grow with the depth of the path.

A slash pattern is split at each `**` into blocks of fixed length: a head (anchored patterns), a
tail (patterns that do not end in `**`) and middle blocks (a run with `**` on both sides). Only a
pattern with a middle block is *floating*, and only it may walk the path. The old walk is kept in
`tests/glob_oracle.py`; the first two tests hold the new matcher to it.
"""

from __future__ import annotations

import fnmatch
import os
import random

import pytest

from agentfly.recorder import rulefile
from tests.glob_oracle import old_glob, old_matches

PART_CHOICES = ["**", "*", "?", "a", "b", "a*", "[ab]", "[!a]", "x?"]
SEGMENT_CHOICES = ["a", "b", "ab", "x1", "c"]


def test_the_new_glob_answers_as_the_old_one_on_random_patterns() -> None:
    rng = random.Random(5)
    matched = 0
    for _ in range(20_000):
        pattern = tuple(rng.choice(PART_CHOICES) for _ in range(rng.randint(1, 8)))
        segments = [rng.choice(SEGMENT_CHOICES) for _ in range(rng.randint(0, 12))]
        for form in (pattern, ("**", *pattern)):  # anchored, and unanchored (an implicit `**`)
            expected = old_glob(form, segments)
            assert rulefile._glob(form, segments) == expected, (form, segments)
            matched += expected
    assert 2_000 < matched < 20_000, "the cases must hold both answers in numbers"


PATTERNS = [
    "~/.aws/config",
    "~/.ssh/",
    "/etc/ssl/private/*",
    "cfg/x.txt",
    "cfg/**/x.txt",
    "**/a/**/b/**/x",
    "/a/b/**/c/d/e/f",
    ".env",
    "*.PEM",
]
PATHS = [
    "~/.aws/config",
    "$HOME/.ssh/id",
    "/etc/ssl/private/k",
    "a/../cfg/x.txt",
    "//cfg//x.txt",
    "/Users/X/CFG/x.TXT",
    "/a/b/q/c/d/e/f",
    "x.pem",
]


@pytest.mark.parametrize("raw", PATTERNS)
def test_pattern_matches_answers_as_before_on_real_paths(raw: str) -> None:
    pattern = rulefile.compile_pattern(raw)
    home = os.path.expanduser("~")
    paths = [*PATHS, f"{home}/.aws/config", f"{home}/.ssh/k/l", f"{home}/x/cfg/k/x.txt"]
    for path in paths:
        assert pattern.matches(path) == old_matches(pattern, path), (raw, path)
        assert pattern.matches(path, None, home) == old_matches(pattern, path), (raw, path)


def test_the_home_folder_is_taken_from_the_caller_when_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pattern = rulefile.compile_pattern("~/.aws/config")

    def refuse(path: str) -> str:
        raise AssertionError("the home folder was looked up")

    monkeypatch.setattr(os.path, "expanduser", refuse)
    assert pattern.matches("/h/me/.aws/config", None, "/h/me")
    assert not pattern.matches("/h/other/.aws/config", None, "/h/me")


def test_a_clause_looks_up_the_home_folder_once_however_many_patterns_it_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clause = rulefile.Clause(
        ("shell",), tuple(rulefile.compile_pattern(f"/opt/p{i}/**/x.txt") for i in range(40))
    )
    real = os.path.expanduser
    lookups = 0

    def counting(path: str) -> str:
        nonlocal lookups
        lookups += 1
        return real(path)

    monkeypatch.setattr(os.path, "expanduser", counting)
    action = {"hook_event_name": "beforeShellExecution", "command": "cat /a/b /c/d ~/e"}
    assert not clause.matches(action, {})
    assert lookups == 1


@pytest.mark.parametrize("raw", [".ssh/**", "a/**/b", "**/x/**", "cfg/**/x.txt", "src/**/gen.py"])
def test_floating_is_true_for_a_run_between_two_stars(raw: str) -> None:
    assert rulefile.floating(rulefile.compile_pattern(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "~/.aws/config",
        "~/.aws/**",
        "~/.ssh/**",
        "/etc/ssl/private/*",
        "a/b",
        "**/secret.txt",
        "/a/**/b",
        ".env",
        "*/*/*/*/*/*/*/k0.pem",
        "*/*/secret0/*.json",
    ],
)
def test_floating_is_false_without_a_run_between_two_stars(raw: str) -> None:
    assert not rulefile.floating(rulefile.compile_pattern(raw))


class Compares:
    """Counts the `fnmatch` compares a block of code makes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        self.real = fnmatch.fnmatchcase
        monkeypatch.setattr(fnmatch, "fnmatchcase", self)

    def __call__(self, name: str, part: str) -> bool:
        self.count += 1
        return self.real(name, part)


def deep(depth: int, *, first: tuple[str, ...] = (), last: tuple[str, ...] = ()) -> list[str]:
    """A path `depth` segments deep: `first`, filler folders, `last`."""
    return [*first, *("d",) * (depth - len(first) - len(last)), *last]


@pytest.mark.parametrize("depth", [4, 20, 60])
@pytest.mark.parametrize(
    "raw, first, last",
    [
        ("/etc/ssl/private/k*", ("etc", "ssl", "private"), ("k9",)),
        ("/etc/ssl/private/k*", ("etc", "ssl", "private"), ("z",)),
        ("x/y.txt", (), ("x", "y.txt")),
        ("x/y.txt", (), ("q", "y.txt")),
        ("*/*/secret0/*.json", (), ("secret0", "k.json")),
        ("*/*/secret0/*.json", (), ("other", "k.json")),
    ],
)
def test_a_pattern_that_is_not_floating_compares_each_part_once_whatever_the_depth(
    monkeypatch: pytest.MonkeyPatch,
    depth: int,
    raw: str,
    first: tuple[str, ...],
    last: tuple[str, ...],
) -> None:
    pattern = rulefile.compile_pattern(raw)
    assert not rulefile.floating(pattern)
    segments = deep(depth, first=first, last=last)
    compares = Compares(monkeypatch)
    home = "/h/me"
    resolved_path = "/" + "/".join(segments)
    pattern.matches(resolved_path, None, home)
    assert compares.count <= len(pattern.parts), (raw, depth, compares.count)


def test_a_bare_star_part_calls_fnmatch_never(monkeypatch: pytest.MonkeyPatch) -> None:
    compares = Compares(monkeypatch)
    assert rulefile._glob(("*", "*", "*"), ["a", "b", "c"])
    assert rulefile._glob(("**", "*", "**", "*"), ["a", "b", "c"])
    assert not rulefile._glob(("*", "*"), ["a", "b", "c"])
    assert compares.count == 0


def test_the_tail_is_checked_before_a_middle_block(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = rulefile.compile_pattern("p0/**/x0.txt")
    assert rulefile.floating(pattern)
    path = "/" + "/".join([*("p0",) * 59, "f.py"])
    compares = Compares(monkeypatch)
    assert not pattern.matches(path, None, "/h/me")
    assert compares.count <= 2


def test_the_head_is_checked_before_the_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = rulefile.compile_pattern("/a/**/p0/**/x0.txt")
    path = "/" + "/".join(["z", *("p0",) * 58, "x0.txt"])
    compares = Compares(monkeypatch)
    assert not pattern.matches(path, None, "/h/me")
    assert compares.count == 1


def test_middle_blocks_are_placed_in_order_and_do_not_overlap() -> None:
    pattern = rulefile.compile_pattern("**/a/b/**/a/b/**/c")
    assert pattern.matches("/a/b/a/b/c", None, "/h")
    assert pattern.matches("/q/a/b/q/a/b/q/c", None, "/h")
    assert not pattern.matches("/a/b/c", None, "/h")  # one `a/b` cannot serve both blocks
    assert not pattern.matches("/a/b/a/c", None, "/h")
    assert not pattern.matches("/a/b/a/b/c/d", None, "/h")  # the tail is the file name `c`


def test_compiled_patterns_answer_as_the_old_ones_on_random_slash_patterns() -> None:
    rng = random.Random(11)
    home = os.path.expanduser("~")
    for _ in range(5_000):
        raw = "/".join(rng.choice(PART_CHOICES) for _ in range(rng.randint(1, 6)))
        raw = rng.choice(["", "/", "~/"]) + raw + rng.choice(["", "", "/"])
        pattern = rulefile.compile_pattern(raw)
        base = rng.choice(["", home])
        path = base + "/" + "/".join(rng.choice(SEGMENT_CHOICES) for _ in range(rng.randint(0, 10)))
        assert pattern.matches(path, None, home) == old_matches(pattern, path), (raw, path)
