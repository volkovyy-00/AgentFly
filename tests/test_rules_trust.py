"""V5b-fix: the recorder only believes an active rules file that its owner alone can write.

The file is /Library/Application Support/AgentFly/rules.toml (D3): root's, so the agent's user
cannot change it. A link, a file that is not root's, a file others can write, a pipe or a folder in
its place is refused like a file with a syntax error: the packaged default runs and `/health`,
`/api/rules`, `doctor`, `agentfly start`, `agentfly status` and `agentfly rules check` say why.

Tests run as an ordinary user, so "root" here is `rulefile.ACTIVE_OWNER_UID`, which the autouse
fixture in `tests/conftest.py` sets to the test's own user id (and its umask to 022).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentfly.recorder.app as app_module
import agentfly.recorder.rules as rules_mod
from agentfly.cli import main
from agentfly.install import service
from agentfly.recorder import rulefile
from tests.helpers import REPO, free_port, start_recorder, stop_recorder, wait_for_health

GOOD = rulefile.default_text()
IN_FORCE = "the packaged default rules are in force"


def plant_link(path: Path) -> None:
    target = path.with_name("elsewhere.toml")
    target.write_text(GOOD, encoding="utf-8")
    path.symlink_to(target)


def plant_dangling_link(path: Path) -> None:
    path.symlink_to(path.with_name("nowhere.toml"))


def plant_group_writable(path: Path) -> None:
    path.write_text(GOOD, encoding="utf-8")
    path.chmod(0o664)


def plant_world_writable(path: Path) -> None:
    path.write_text(GOOD, encoding="utf-8")
    path.chmod(0o666)


def plant_pipe(path: Path) -> None:
    os.mkfifo(path)


def plant_folder(path: Path) -> None:
    path.mkdir()


def plant_another_owner(path: Path) -> None:
    path.write_text(GOOD, encoding="utf-8")
    # The file is this user's; the recorder is told to expect somebody else (root, in production).
    rulefile.ACTIVE_OWNER_UID = os.getuid() + 1


# name -> (how to plant it, a fragment of the reason that must be shown)
REFUSED: dict[str, tuple[Callable[[Path], None], str]] = {
    "a symbolic link": (plant_link, "symbolic link"),
    "a link that points nowhere": (plant_dangling_link, "symbolic link"),
    "a file the group can write": (plant_group_writable, "written by group or others"),
    "a file everybody can write": (plant_world_writable, "written by group or others"),
    "a named pipe": (plant_pipe, "not a regular file"),
    "a folder": (plant_folder, "not a regular file"),
    "a file that is not the owner's": (plant_another_owner, "is owned by"),
}


@pytest.fixture
def untrusted(active_rules: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Plant one kind of refused file at the active path; `ACTIVE_OWNER_UID` is put back after."""
    monkeypatch.setattr(rulefile, "ACTIVE_OWNER_UID", rulefile.ACTIVE_OWNER_UID)

    def plant(name: str) -> Path:
        REFUSED[name][0](active_rules)
        return active_rules

    return plant


def start() -> TestClient:
    return TestClient(app_module.app, base_url="http://127.0.0.1:8787")


# ---------------------------------------------------------------- a file the recorder believes


def test_a_plain_file_that_only_its_owner_can_write_is_the_rules_in_force(
    active_rules: Path,
) -> None:
    active_rules.write_text(GOOD, encoding="utf-8")
    active_rules.chmod(0o644)
    loaded = rules_mod.load_active()
    assert (loaded.source, loaded.problem) == ("active", None)
    assert rulefile.load_active_file(active_rules).errors == ()


def test_a_read_only_file_is_fine_too(active_rules: Path) -> None:
    active_rules.write_text(GOOD, encoding="utf-8")
    active_rules.chmod(0o444)
    assert rules_mod.load_active().source == "active"


# ---------------------------------------------------------------- every refused file


@pytest.mark.parametrize("name", REFUSED)
def test_a_refused_file_is_not_loaded_and_the_default_runs(
    name: str, untrusted: Callable[[str], Path]
) -> None:
    path = untrusted(name)
    loaded = rules_mod.load_active()
    assert loaded.source == "default" and loaded.rules == rules_mod.DEFAULT.rules
    problem = loaded.problem or ""
    assert str(path) in problem and REFUSED[name][1] in problem
    assert problem.endswith(IN_FORCE) and len(problem) <= rulefile.MAX_PROBLEM_CHARS


@pytest.mark.parametrize("name", REFUSED)
def test_trust_problem_says_what_the_recorder_says(
    name: str, untrusted: Callable[[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = untrusted(name)
    monkeypatch.setattr(os, "read", lambda *a: pytest.fail("trust_problem read the file"))
    problem = rulefile.trust_problem(path, rulefile.ACTIVE_OWNER_UID)
    assert problem is not None and REFUSED[name][1] in problem
    assert rulefile.load_active_file(path).errors == (problem,), "one test, one wording"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o600, 0o444])
def test_trust_problem_is_none_for_a_file_the_recorder_believes_whatever_it_says(
    mode: int, active_rules: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active_rules.write_text("this is not a rules file\n", encoding="utf-8")
    active_rules.chmod(mode)  # the recorder's rule is "no one else can write", not "0644" (D3)
    monkeypatch.setattr(os, "read", lambda *a: pytest.fail("trust_problem read the file"))
    assert rulefile.trust_problem(active_rules, rulefile.ACTIVE_OWNER_UID) is None


def test_trust_problem_leaves_no_descriptor_open(
    active_rules: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: set[int] = set()
    real_open, real_close = os.open, os.close

    def spy_open(*args: Any, **kwargs: Any) -> int:
        fd = real_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def spy_close(fd: int) -> None:
        opened.discard(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "close", spy_close)
    active_rules.write_text(GOOD, encoding="utf-8")
    assert rulefile.trust_problem(active_rules, rulefile.ACTIVE_OWNER_UID) is None
    active_rules.chmod(0o666)  # refused by the check after the open
    assert rulefile.trust_problem(active_rules, rulefile.ACTIVE_OWNER_UID) is not None
    assert rulefile.trust_problem(active_rules.with_name("nowhere"), 0) is not None
    assert opened == set()


@pytest.mark.parametrize("name", REFUSED)
def test_the_page_and_health_say_why(name: str, untrusted: Callable[[str], Path]) -> None:
    untrusted(name)
    with start() as client:
        health = client.get("/health").json()
        listing = client.get("/api/rules").json()
    assert REFUSED[name][1] in health["rules_problem"]
    assert health["rules_problem"].endswith(IN_FORCE)
    assert listing["source"] == "default" and listing["problem"] == health["rules_problem"]


def test_a_refused_file_is_logged_once_with_what_runs_instead(
    untrusted: Callable[[str], Path], caplog: pytest.LogCaptureFixture
) -> None:
    untrusted("a file everybody can write")
    with caplog.at_level("WARNING", logger="agentfly"), start():
        pass
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("rules:")]
    assert len(lines) == 1 and lines[0].count(IN_FORCE) == 1


def test_the_reason_is_never_cut_off_by_a_long_path_or_a_long_problem() -> None:
    long_path = "/" + "d" * 600 + "/rules.toml"
    line = rulefile.refusal(long_path, tuple(f"rule R{n}: {'x' * 400}" for n in range(30)))
    assert len(line) <= rulefile.MAX_PROBLEM_CHARS and line.endswith(IN_FORCE)
    assert "(and 29 more)" in line or "..." in line


# ---------------------------------------------------------------- the commands


@pytest.mark.parametrize("name", REFUSED)
def test_rules_check_with_no_file_refuses_what_the_recorder_refuses(
    name: str, untrusted: Callable[[str], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    untrusted(name)
    assert main(["rules", "check"]) == 1
    assert REFUSED[name][1] in capsys.readouterr().err
    assert main(["rules", "test"]) == 1


def test_a_draft_is_not_trust_checked_but_the_active_path_given_as_a_file_is(
    active_rules: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = tmp_path / "draft.toml"
    draft.write_text(GOOD, encoding="utf-8")
    draft.chmod(0o666)  # a draft is the user's own file: anybody may write it
    assert main(["rules", "check", str(draft)]) == 0
    active_rules.write_text(GOOD, encoding="utf-8")
    active_rules.chmod(0o666)
    assert main(["rules", "check", str(active_rules)]) == 1
    assert "written by group or others" in capsys.readouterr().err
    alias = tmp_path / "alias.toml"
    alias.symlink_to(active_rules)  # the same file under another name is the same file
    assert rulefile.is_active_path(alias) and rulefile.is_active_path(active_rules)
    assert not rulefile.is_active_path(draft)


def test_rules_check_through_a_link_to_the_active_file_judges_the_active_file(
    active_rules: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    active_rules.write_text(GOOD, encoding="utf-8")
    active_rules.chmod(0o644)
    link = tmp_path / "link.toml"
    link.symlink_to(active_rules)
    assert main(["rules", "check", str(link)]) == 0
    captured = capsys.readouterr()
    assert str(active_rules) in captured.out and str(link) not in captured.out
    assert main(["rules", "test", str(link)]) == 0  # `rules test` goes through the same door
    captured = capsys.readouterr()
    assert str(active_rules) in captured.out and str(link) not in captured.out
    active_rules.chmod(0o664)
    for command in ("check", "test"):
        assert main(["rules", command, str(link)]) == 1
        err = capsys.readouterr().err
        assert str(active_rules) in err and "written by group or others" in err
        assert "symbolic link" not in err and str(link) not in err


def test_rules_check_calls_the_active_file_so_however_it_is_given(
    active_rules: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CR5: the active path itself once said "(file given)", a link to it "(the active file)"."""
    active_rules.write_text(GOOD, encoding="utf-8")
    active_rules.chmod(0o644)
    link = tmp_path / "link.toml"
    link.symlink_to(active_rules)
    draft = tmp_path / "draft.toml"
    draft.write_text(GOOD, encoding="utf-8")
    for given, what in ((active_rules, "the active file"), (link, "the active file")):
        assert main(["rules", "check", str(given)]) == 0
        assert f"in {active_rules} ({what})" in capsys.readouterr().out
    assert main(["rules", "check", str(draft)]) == 0
    assert f"in {draft} (file given)" in capsys.readouterr().out


def test_a_missing_file_given_as_the_active_path_is_not_a_crash(
    active_rules: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rules", "check", str(active_rules)]) == 1
    assert "cannot be read" in capsys.readouterr().err


def answer_with(monkeypatch: pytest.MonkeyPatch, **extra: Any) -> None:
    body = {"ok": True, "offline_guard_count": 0, "last_hook_at": None, **extra}
    monkeypatch.setattr(service, "wait_for_health", lambda timeout=None: body)
    monkeypatch.setattr(service, "health", lambda timeout=2.0: body)


def test_start_and_status_print_the_rules_problem_the_recorder_reports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = f"/Library/x/rules.toml: is owned by user id 501, not root; {IN_FORCE}"
    answer_with(monkeypatch, rules_problem=problem)
    assert main(["start"]) == 0  # it runs, on the default: that is not a failure to start
    out = capsys.readouterr()
    assert "recorder answers on" in out.out and f"rules: {problem}" in out.err
    assert main(["status"]) == 0
    assert f"rules:    {problem}" in capsys.readouterr().out


def test_start_and_status_say_nothing_about_rules_when_there_is_no_problem(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_with(monkeypatch)
    assert main(["start"]) == 0 and main(["status"]) == 0
    out = capsys.readouterr()
    assert "rules" not in out.out.replace("recorder", "") + out.err


@pytest.mark.slow
def test_the_problem_is_one_line_even_if_it_holds_line_breaks(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_with(monkeypatch, rules_problem="a\nb\n\tc")
    main(["status"])
    assert "rules:    a b c\n" in capsys.readouterr().out


# ---------------------------------------------------------------- a real recorder process


def run_child(home: Path, plant: Callable[[Path], None]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A child recorder whose rules file is `<home>/test-rules.toml` (see `RECORDER_CODE`)."""
    plant(home / "test-rules.toml")
    port = free_port()
    process = start_recorder(home, port)
    try:
        health = wait_for_health(port, process)
        url = f"http://127.0.0.1:{port}/api/rules"
        with urllib.request.urlopen(url, timeout=5) as response:
            return health, json.loads(response.read())
    finally:
        stop_recorder(process)


@pytest.mark.slow
def test_a_child_recorder_reads_a_file_its_owner_alone_can_write(isolated_home: Path) -> None:
    health, listing = run_child(isolated_home, lambda p: p.write_text(GOOD, encoding="utf-8"))
    assert "rules_problem" not in health and listing["source"] == "active"


@pytest.mark.slow
def test_a_child_recorder_refuses_a_file_everybody_can_write_and_says_so_over_http(
    isolated_home: Path,
) -> None:
    health, listing = run_child(isolated_home, plant_world_writable)
    assert "written by group or others" in health["rules_problem"]
    assert health["rules_problem"].endswith(IN_FORCE)
    assert listing["source"] == "default" and listing["problem"] == health["rules_problem"]


@pytest.mark.slow
def test_a_child_recorder_refuses_a_link(isolated_home: Path) -> None:
    health, listing = run_child(isolated_home, plant_link)
    assert "symbolic link" in health["rules_problem"] and listing["source"] == "default"


def test_the_production_owner_of_the_active_file_is_root() -> None:
    """The fixture swaps in the test's own user; a fresh process shows what a recorder expects."""
    shown = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import agentfly.recorder.rulefile as r; print(r.ACTIVE_OWNER_UID)",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert shown.stdout.strip() == "0"
