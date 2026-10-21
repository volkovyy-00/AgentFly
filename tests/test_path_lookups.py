"""V5d: the file-system look-ups of a command's words.

A word is judged as text first (joined to the root, `.` and `..` folded, `~` not expanded, against
the root as sent and as resolved) and only a word inside is walked on disk, one `lstat` a part, a
missing part ends the walk, links must not lead out. All the words of one hook share a budget
(`clean.Lookups`). The walk is checked against `os.path.realpath(strict=True)`; the speed of the
whole hook on 300 words of 1,022 characters is checked through the real `apply_rules`.
"""

from __future__ import annotations

import os
import posixpath
import random
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import agentfly.recorder.app as app_module
import agentfly.recorder.store as store_module
from agentfly.recorder import clean
from agentfly.recorder.clean import Lookups, clean_command, cleaned_words
from agentfly.recorder.names import words
from agentfly.recorder.rules import Session
from agentfly.recorder.store import build_step_record
from tests.helpers import wallclock
from tests.recorder_harness import Recorder

CLIENT_WAIT = 0.5  # agentfly/hook_client.py `_BUDGET_S`: the recorder gets this long


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """`ws` (the project) and `outside` (beside it), with files, folders and links of every kind."""
    base = tmp_path.resolve()
    ws, outside = base / "ws", base / "outside"
    for folder in (ws / "sub", ws / "a" / "b" / "c", outside):
        folder.mkdir(parents=True)
    for file in (ws / "f.py", ws / "sub" / "a.py", ws / "a" / "b" / "c" / "d.py", outside / "g.py"):
        file.write_text("x\n")
    (ws / "sub" / ".env").write_text("K=v\n")
    (outside / ".env").write_text("K=v\n")
    links = {
        ws / "l1": "a",  # inside, to a folder
        ws / "l2": "a/b",
        ws / "rel": "../ws/a",  # leaves the root and comes back
        ws / "abs": str(ws / "a"),
        ws / "out": "../outside",  # leads out
        ws / "absout": str(outside),
        ws / "a" / "up": "..",
        ws / "dang": "nowhere",
        ws / "loop1": "loop2",
        ws / "loop2": "loop1",
        base / "wsalias": str(ws),  # the root as sent
        base / "into": str(ws),  # a link from outside into the project
    }
    for link, target in links.items():
        link.symlink_to(target)
    return ws


@pytest.fixture()
def fs_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every path any system call below `pathlib` and `os.path` is asked about."""
    seen: list[str] = []
    for name in ("lstat", "stat", "readlink"):
        real: Callable[..., Any] = getattr(os, name)

        def spy(path: Any, *args: Any, _real: Callable[..., Any] = real, **kwargs: Any) -> Any:
            seen.append(os.fspath(path))
            return _real(path, *args, **kwargs)

        monkeypatch.setattr(os, name, spy)
    return seen


def test_the_budget_is_pinned() -> None:
    assert clean.LOOKUP_STEPS == 4_000
    assert clean.MAX_LINK_HOPS == 32


# ---------------------------------------------------------------- text first


@pytest.mark.parametrize(
    "marker",
    ["/net/x/deep/file", "/etc/hosts", "../beyond/f", "/tmp/not-ours/../x", "/private/net/y"],
)
def test_a_word_outside_as_text_makes_no_file_system_call(
    marker: str, tree: Path, fs_calls: list[str]
) -> None:
    assert clean_command(f"cat {marker}", tree) == "cat <arg>"
    below = [call for call in fs_calls if "net/" in call or "hosts" in call or "beyond" in call]
    assert below == [] and not any(call.endswith("not-ours") for call in fs_calls)


def test_the_root_is_looked_up_once_however_many_words_there_are(
    tree: Path, fs_calls: list[str]
) -> None:
    clean_command("cat /net/x/0", tree)
    one_word = list(fs_calls)
    assert one_word and all(call.startswith(str(tree)[:3]) for call in one_word)
    fs_calls.clear()
    clean_command("cat " + " ".join(f"/net/x/{k}" for k in range(50)), tree)
    assert fs_calls == one_word  # the root's own calls, the same for 50 words


def test_a_link_from_outside_into_the_project_counts_as_outside(tree: Path) -> None:
    via_link = tree.parent / "into" / "sub" / "a.py"
    assert via_link.exists()
    assert clean_command(f"cat {via_link}", tree) == "cat <arg>"
    assert clean_command(f"cat {tree / 'sub' / 'a.py'}", tree) == "cat sub/a.py"
    assert clean_command("cat sub/a.py", tree) == "cat sub/a.py"


def test_the_root_as_sent_counts_when_it_is_a_link(tree: Path) -> None:
    alias = tree.parent / "wsalias"
    assert clean_command(f"cat {alias}/sub/a.py {tree}/sub/a.py", alias) == "cat sub/a.py sub/a.py"
    assert clean_command(f"cat {alias}/../outside/g.py", alias) == "cat <arg>"


def test_a_relative_word_is_joined_to_the_root_and_tilde_is_not_expanded(
    tree: Path, fs_calls: list[str]
) -> None:
    assert clean_command("cat ../outside/g.py", tree) == "cat <arg>"
    assert [call for call in fs_calls if "g.py" in call] == []
    (tree / "~").mkdir()
    (tree / "~" / "k").write_text("")
    assert clean_command("cat ~/k", tree) == "cat ~/k"  # a folder named `~` in the project


def test_a_word_over_1024_characters_is_not_looked_up_even_inside_as_text(
    tree: Path, fs_calls: list[str]
) -> None:
    lookups = Lookups(tree)
    before = len(fs_calls)
    for word in ("a" * 1_025, "a/" * 600, f"{tree}/" + "a/" * 600):
        assert lookups.project_relative(word) is None
    assert len(fs_calls) == before  # not one call: the root was not even asked


# ---------------------------------------------------------------- the walk


def test_a_missing_part_ends_the_look_up_after_one_call(tree: Path, fs_calls: list[str]) -> None:
    assert clean_command("cat nope/a/b/c/d/e/f", tree) == "cat <arg>"
    below = [call for call in fs_calls if call.startswith(str(tree) + "/")]
    assert below == [f"{tree}/nope"]


def test_links_inside_lead_inside_or_out(tree: Path) -> None:
    lookups = Lookups(tree)
    assert lookups.project_relative("l1/b/c/d.py") == "a/b/c/d.py"
    assert lookups.project_relative("rel/b") == "a/b"
    assert lookups.project_relative("abs/b") == "a/b"
    assert lookups.project_relative("a/up/sub/a.py") == "sub/a.py"
    assert lookups.project_relative("out/g.py") is None  # leads out
    assert lookups.project_relative("absout/g.py") is None
    assert lookups.project_relative("dang") is None
    assert lookups.project_relative("loop1") is None
    assert lookups.project_relative("sub") == "sub"
    assert lookups.project_relative(".") == "."
    assert lookups.project_relative("") == "."  # `Path("")` is the root, as before


def test_a_root_that_is_gone_or_a_loop_looks_up_nothing(tmp_path: Path) -> None:
    assert Lookups(tmp_path / "gone").project_relative(".") is None
    assert Lookups(tmp_path / "gone").project_relative("x") is None
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    assert Lookups(loop).project_relative("a") is None


def random_words(rng: random.Random, tree: Path, count: int) -> Iterator[str]:
    pool = [
        "a", "b", "c", "sub", "f.py", "d.py", "a.py", "l1", "l2", "rel", "abs", "out", "absout",
        "up", "dang", "loop1", "loop2", "..", "..", ".", "", "nope", "g.py", "ws", "outside",
    ]  # fmt: skip
    prefixes = [
        "",
        "",
        "",
        f"{tree}/",
        f"{tree.parent}/wsalias/",
        f"{tree.parent}/into/",
        "/",
        "//",
    ]
    for _ in range(count):
        parts = [rng.choice(pool) for _ in range(rng.randrange(1, 7))]
        yield rng.choice(prefixes) + "/".join(parts)


def oracle(word: str, sent: str, root: str) -> str | None:
    """The answer in words: inside the root as text, then `realpath(strict=True)`, then inside."""

    def inside(base: str) -> bool:
        folded = posixpath.normpath(word if word.startswith("/") else f"{base}/{word}")
        folded = folded[1:] if folded.startswith("//") else folded
        return folded == base or folded.startswith(base.rstrip("/") + "/")

    if not (inside(sent) or inside(root)):
        return None
    try:
        real = os.path.realpath(word if word.startswith("/") else f"{root}/{word}", strict=True)
    except (OSError, ValueError):
        return None
    return clean.contained_relative(real, root)


@pytest.mark.parametrize("alias", [False, True], ids=["root as is", "root as a link"])
@pytest.mark.parametrize("shared", [False, True], ids=["a Lookups a word", "one Lookups"])
def test_the_walk_answers_as_realpath_strict_does(tree: Path, alias: bool, shared: bool) -> None:
    sent = tree.parent / "wsalias" if alias else tree
    one = Lookups(sent, steps=10**9)
    rng = random.Random(21)
    for word in random_words(rng, tree, 1_500):
        lookups = one if shared else Lookups(sent, steps=10**9)
        assert lookups.project_relative(word) == oracle(word, str(sent), str(tree)), word


# ---------------------------------------------------------------- the budget


def test_a_word_past_the_budget_is_not_a_file_and_the_walk_is_kept(tree: Path) -> None:
    lookups = Lookups(tree, steps=2)
    assert lookups.project_relative("a/b/c/d.py") is None  # four calls
    assert lookups.left == 0
    assert lookups.project_relative("a/b") == "a/b"  # a and b were seen: no call, no step
    assert lookups.project_relative("sub") is None  # one call it cannot pay
    assert lookups.left == 0


def test_a_folder_seen_once_is_not_looked_up_again(tree: Path, fs_calls: list[str]) -> None:
    for name in range(40):
        (tree / "a" / "b" / "c" / f"w{name}.py").write_text("")
    lookups = Lookups(tree)
    for name in range(40):
        assert lookups.project_relative(f"{tree}/a/b/c/w{name}.py") == f"a/b/c/w{name}.py"
    below = [call for call in fs_calls if call.startswith(f"{tree}/")]
    assert len(below) == 3 + 40  # a, a/b, a/b/c, then one call a file
    assert lookups.left == clean.LOOKUP_STEPS - 43


def test_a_word_asked_twice_and_a_result_are_not_looked_up_again(
    tree: Path, fs_calls: list[str]
) -> None:
    lookups = Lookups(tree)
    assert lookups.project_relative(f"{tree}/sub/a.py") == "sub/a.py"
    calls = len(fs_calls)
    assert lookups.project_relative(f"{tree}/sub/a.py") == "sub/a.py"
    assert lookups.project_relative("sub/a.py") == "sub/a.py"  # what the cleaner saved
    assert len(fs_calls) == calls


def test_the_cleaner_and_the_step_record_share_one_budget(tree: Path, fs_calls: list[str]) -> None:
    lookups = Lookups(tree)
    assert clean_command("cat sub/a.py sub/a.py", tree, lookups) == "cat sub/a.py sub/a.py"
    assert lookups.left == clean.LOOKUP_STEPS - 2  # `sub` and `a.py`, once (the program is no path)
    calls = len(fs_calls)
    assert lookups.names_file("sub/a.py")
    assert len(fs_calls) == calls


def payload(tree: Path, command: str) -> dict[str, Any]:
    return {
        "hook_event_name": "beforeShellExecution",
        "command": command,
        "workspace_roots": [str(tree)],
    }


def record(tree: Path, command: str) -> Any:
    session = Session(id="s", marked=False, start_time="", next_step=1)
    return build_step_record(payload(tree, command), session, "allow", None, order=1)


def test_past_the_budget_the_words_are_saved_as_arg_and_are_not_the_file(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = record(tree, "cat sub/a.py")
    assert (kept.command, kept.file_path) == ("cat sub/a.py", "a.py")
    monkeypatch.setattr(clean, "LOOKUP_STEPS", 0)
    spent = record(tree, "cat sub/a.py")
    assert (spent.command, spent.file_path) == ("cat <arg>", None)


def test_the_cleaned_command_is_split_once(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    splits: list[str] = []
    real = store_module.cleaned_words

    def spy(command: str) -> list[str]:
        splits.append(command)
        return real(command)

    monkeypatch.setattr(store_module, "cleaned_words", spy)
    monkeypatch.setattr(store_module, "words", lambda text: pytest.fail("a second split"))
    record(tree, "cat sub/a.py https://x.com/y")
    assert splits == ["cat sub/a.py x.com"]


def test_an_absolute_program_inside_is_saved_relative_and_one_through_a_link_out_by_name(
    tree: Path,
) -> None:
    assert record(tree, f"{tree}/sub/.env --version").file_path == "sub/.env"
    assert record(tree, f"{tree}/out/.env --version").file_path == ".env"  # leads out
    assert record(tree, f"{tree}/nope/.env --version").file_path == ".env"  # not there
    assert record(tree, f"{tree.parent}/outside/.env --version").file_path == ".env"


def test_an_outside_program_is_not_the_step_file(tree: Path, fs_calls: list[str]) -> None:
    assert record(tree, "/bin/ls -l").file_path is None
    assert not any(call.startswith("/bin") for call in fs_calls)


def test_the_cleaned_words_are_the_words_of_names_words() -> None:
    rng = random.Random(5)
    alphabet = ["a", "b", "x.py", "<arg>", " ", " ", "\t", "'", '"', "\\", ";", "-l", "é", "\n"]
    for _ in range(5_000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 14)))
        assert cleaned_words(text) == words(text), repr(text)


# ---------------------------------------------------------------- speed


@pytest.fixture()
def rec(tmp_path: Path) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data")
    app_module._store = previous


def long_words(folder: Path, name_length: int, count: int, *, create: bool) -> list[str]:
    """`count` distinct words of exactly 1,022 characters: `folder`, folders of `name_length`
    characters (the last one shorter), and a file `fNNN.py`."""
    leaf = len("/f000.py")
    room = 1_022 - len(str(folder)) - 1 - leaf
    unit = "d" * (name_length - 1) + "x/"
    chain = (unit * (room // len(unit) + 1))[:room].rstrip("/")
    chain += "x" * (room - len(chain))
    deep = f"{folder}/{chain}"
    if create:
        os.makedirs(deep)
    found = [f"{deep}/f{k:03d}.py" for k in range(count)]
    for word in found:
        assert len(word) == 1_022
        if create:
            Path(word).write_text("")
    return found


SHAPES = ["outside", "inside, missing", "inside, existing"]


@wallclock
@pytest.mark.parametrize("name_length", [2, 60])
@pytest.mark.parametrize("shape", SHAPES)
def test_300_words_of_1022_characters_are_answered_within_the_clients_wait(
    shape: str, name_length: int, tree: Path, rec: Recorder
) -> None:
    """The real hook (`apply_rules`), default rules, best of three. Measured on the author's Mac
    (one core, load 30, so a quiet machine does better): CPU 57-123 ms; before V5d 190-1,650 ms."""
    folder = {"outside": tree.parent / "outside", "inside, missing": tree / "none"}.get(
        shape, tree / "there"
    )
    words_ = long_words(folder, name_length, 300, create=shape == "inside, existing")
    command = "cat " + " ".join(words_)
    rec.run("warm", command, workspace_roots=[str(tree)])
    best = float("inf")
    for n in range(3):
        started = time.perf_counter()
        rec.run(f"c{n}", command, workspace_roots=[str(tree)])
        best = min(best, time.perf_counter() - started)
    assert best < CLIENT_WAIT, f"{shape}, {name_length}: {best:.3f} s of {CLIENT_WAIT} s"
    if shape == "inside, existing":  # the folders seen once are kept: no word becomes `<arg>`
        cleaned = clean_command(command, tree)
        assert cleaned.count(".py") == 300 and "<arg>" not in cleaned
