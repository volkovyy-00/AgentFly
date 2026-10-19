"""The package check that runs before `init -g` and `uninstall` ask for a password (V3c).

Every test builds a small virtual environment of the shape `uv tool install` leaves
(tests/install_helpers.py `make_tool_env`): dist-info folders with a RECORD that hashes every file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentfly.install import InstallError, packages
from tests.install_helpers import TOOL_DISTS, hashes_of, make_tool_env, write_dist

REAL_TOOL_ENVIRONMENT = packages.tool_environment  # the autouse fixture replaces it per test

MODULE = "agentfly/module.py"
SCRIPT = "../../../bin/agentfly"
DEP_FILE = "fakedep/__init__.py"


@pytest.fixture
def env(tool_env: packages.Environment) -> packages.Environment:
    return tool_env


def path_of(env: packages.Environment, rel: str) -> Path:
    return Path(os.path.normpath(env.site / rel))


def upgrade(env: packages.Environment, name: str, version: str, files: dict[str, bytes]) -> None:
    """What `uv tool upgrade` leaves: the old dist-info gone, a new one with its own RECORD."""
    for old in env.site.glob(f"{name.replace('-', '_')}-*.dist-info"):
        for line in (old / "RECORD").read_text(encoding="utf-8").splitlines():
            path_of(env, line.split(",")[0]).unlink(missing_ok=True)  # the old files go too
        shutil.rmtree(old)
    write_dist(env, name, version, files)


def problems(env: packages.Environment, record: dict[str, Any] | None) -> list[str]:
    return packages.inspect(env, record).problems


# ---------------------------------------------------------------- an unchanged install


def test_a_clean_environment_has_no_problems_and_no_changes(env: packages.Environment) -> None:
    for record in (None, hashes_of(env)):
        check = packages.inspect(env, record)
        assert check.problems == [] and check.changes == [] and not check.rebuilt
        assert set(check.distributions) == {"agentfly-recorder", "fakedep"}
    files = packages.inspect(env, None).distributions["agentfly-recorder"].files
    assert SCRIPT in files and MODULE in files  # the entry script is hashed too


def test_files_the_tools_leave_unlisted_are_not_a_mismatch(env: packages.Environment) -> None:
    for name in sorted(packages.UNLISTED_OK):
        (env.site / name).write_text("import os\n")
    cache = env.site / "agentfly" / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-312.pyc").write_bytes(b"whatever python wrote")
    assert problems(env, hashes_of(env)) == []


def test_the_allowed_names_count_only_at_the_top_of_site_packages(
    env: packages.Environment,
) -> None:
    (env.site / "agentfly" / "_virtualenv.pth").write_text("import os\n")
    assert [p for p in problems(env, None)] == [
        f"{env.site / 'agentfly' / '_virtualenv.pth'} is not listed in any RECORD"
    ]


def test_nothing_outside_site_packages_is_looked_at(env: packages.Environment) -> None:
    # The base Python, the venv's `bin/python` link and `pyvenv.cfg`: a Homebrew or uv Python
    # upgrade rewrites them, and the card says it must not stop `init -g` or `uninstall`.
    record = hashes_of(env)
    (env.prefix / "pyvenv.cfg").write_text("home = /somewhere/else\n")
    (env.prefix / "bin" / "python").write_text("a new interpreter\n")
    (env.prefix / "bin" / "activate").write_text("echo hi\n")
    (env.prefix / "uv-receipt.toml").write_text("[tool]\n")
    check = packages.inspect(env, record)
    assert check.problems == [] and check.changes == []


# ---------------------------------------------------------------- one changed or extra file


@pytest.mark.parametrize(
    ("rel", "what"),
    [(MODULE, "an AgentFly module"), (SCRIPT, "an entry script"), (DEP_FILE, "a dependency file")],
)
def test_one_changed_file_is_named_with_or_without_a_record(
    env: packages.Environment, rel: str, what: str
) -> None:
    record = hashes_of(env)
    path_of(env, rel).write_bytes(b"import os; os.system('id')\n")
    changed = f"{path_of(env, rel)} changed since AgentFly was installed"
    assert problems(env, record) == [changed]
    assert problems(env, None) == [f"{path_of(env, rel)} does not match its RECORD"]


def test_a_file_changed_together_with_its_record_is_still_caught_by_the_stored_hash(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    evil = {MODULE: b"import os\n"}
    upgrade_files = dict(TOOL_DISTS["agentfly-recorder"][1]) | evil
    for old in env.site.glob("agentfly_recorder-*.dist-info"):
        shutil.rmtree(old)
    write_dist(env, "agentfly-recorder", "0.1.0", upgrade_files)  # RECORD agrees with the new file
    assert problems(env, None) == []  # RECORD alone cannot tell
    assert problems(env, record) == [f"{path_of(env, MODULE)} changed since AgentFly was installed"]


def test_an_extra_file_next_to_an_agentfly_module_is_named(env: packages.Environment) -> None:
    record = hashes_of(env)
    (env.site / "agentfly" / "_native.so").write_bytes(b"\x7fELF")
    extra = f"{env.site / 'agentfly' / '_native.so'} is not listed in any RECORD"
    assert problems(env, record) == [extra]
    assert problems(env, None) == [extra]


def test_a_file_added_to_a_record_is_not_in_the_stored_hashes(env: packages.Environment) -> None:
    record = hashes_of(env)
    (env.site / "agentfly" / "extra.py").write_text("x = 1\n")
    info = next(env.site.glob("agentfly_recorder-*.dist-info"))
    with (info / "RECORD").open("a", encoding="utf-8") as handle:
        handle.write("agentfly/extra.py,,\n")  # the planted file, listed (RECORD is writable)
    assert problems(env, record) == [
        f"{env.site / 'agentfly' / 'extra.py'} was not there when AgentFly was installed"
    ]


def test_a_link_is_an_extra_file_whatever_it_points_at(
    env: packages.Environment, tmp_path: Path
) -> None:
    record = hashes_of(env)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (env.site / "evil_dir").symlink_to(elsewhere, target_is_directory=True)
    (env.site / "agentfly" / "link.py").symlink_to(env.site / "agentfly" / "module.py")
    found = problems(env, record)
    assert sorted(found) == sorted(
        [
            f"{env.site / 'evil_dir'} is not listed in any RECORD",
            f"{env.site / 'agentfly' / 'link.py'} is not listed in any RECORD",
        ]
    )


def test_byte_code_outside_pycache_is_an_extra_file(env: packages.Environment) -> None:
    (env.site / "agentfly" / "hidden.pyc").write_bytes(b"\x00")
    assert problems(env, None) == [
        f"{env.site / 'agentfly' / 'hidden.pyc'} is not listed in any RECORD"
    ]


def test_a_deleted_file_is_reported_once(env: packages.Environment) -> None:
    record = hashes_of(env)
    path_of(env, MODULE).unlink()
    assert problems(env, record) == [
        f"{path_of(env, MODULE)} is listed in RECORD but cannot be read (No such file or directory)"
    ]


# ---------------------------------------------------------------- a RECORD that cannot be trusted


def rewrite_record(env: packages.Environment, edit: Any) -> None:
    info = next(env.site.glob("agentfly_recorder-*.dist-info"))
    lines = (info / "RECORD").read_text(encoding="utf-8").splitlines()
    (info / "RECORD").write_text("\n".join(edit(lines)) + "\n", encoding="utf-8")


def test_a_row_without_a_hash_cannot_be_checked(env: packages.Environment) -> None:
    rewrite_record(
        env, lambda lines: [f"{MODULE},," if row.startswith(MODULE) else row for row in lines]
    )
    found = problems(env, None)
    assert found == [
        f"RECORD has no usable sha256 for {path_of(env, MODULE)}, so it cannot be checked"
    ]


def test_another_hash_algorithm_is_not_accepted(env: packages.Environment) -> None:
    rewrite_record(
        env,
        lambda lines: [f"{MODULE},md5=AAAA,9" if row.startswith(MODULE) else row for row in lines],
    )
    assert "no usable sha256" in problems(env, None)[0]


def test_a_row_that_leaves_the_environment_is_a_problem(env: packages.Environment) -> None:
    rewrite_record(env, lambda lines: [*lines, "../../../../outside.txt,sha256=AAAA,1"])
    assert any("outside the environment" in p for p in problems(env, None))


def test_a_listed_path_that_is_not_a_regular_file_is_a_problem_not_a_hang(
    env: packages.Environment,
) -> None:
    fifo = env.site / "agentfly" / "pipe"
    os.mkfifo(fifo)
    rewrite_record(env, lambda lines: [*lines, "agentfly/pipe,sha256=AAAA,1"])
    assert f"{fifo} is listed in RECORD but is not a regular file" in problems(env, None)


def test_a_distribution_without_a_record_is_a_problem(env: packages.Environment) -> None:
    info = next(env.site.glob("fakedep-*.dist-info"))
    (info / "RECORD").unlink()
    found = problems(env, None)
    assert any(f"{info} has no readable METADATA and RECORD" in p for p in found)


def test_two_copies_of_one_distribution_are_a_problem(env: packages.Environment) -> None:
    write_dist(env, "FakeDep", "1.1", {"fakedep/other.py": b"x = 2\n"})
    assert any("two copies of fakedep" in p for p in problems(env, None))


# ---------------------------------------------------------------- upgrades


NEW_AGENTFLY = {
    "agentfly/__init__.py": b"",
    "agentfly/module.py": b"VALUE = 2\n",
    SCRIPT: b"#!/bin/sh\nexit 0\n",
}


def test_an_upgrade_of_agentfly_alone_goes_ahead_and_the_new_hashes_are_the_ones_stored(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    upgrade(env, "agentfly-recorder", "0.2.0", NEW_AGENTFLY)
    check = packages.inspect(env, record)
    assert check.problems == [] and not check.rebuilt
    assert check.changes == ["agentfly-recorder: changed from 0.1.0 to 0.2.0"]
    stored = packages.to_record(check.distributions)
    assert stored["agentfly-recorder"]["version"] == "0.2.0"
    assert stored["fakedep"] == record["packages"]["fakedep"]
    # and once stored, the next look is plain again
    assert packages.inspect(env, {"packages": stored}).changes == []


def test_an_upgrade_of_one_dependency_alone_goes_ahead(env: packages.Environment) -> None:
    record = hashes_of(env)
    upgrade(env, "fakedep", "1.1", {"fakedep/__init__.py": b"X = 2\n"})
    check = packages.inspect(env, record)
    assert check.problems == [] and check.changes == ["fakedep: changed from 1.0 to 1.1"]


def test_an_upgrade_with_one_file_changed_against_its_own_record_is_stopped(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    upgrade(env, "agentfly-recorder", "0.2.0", NEW_AGENTFLY)
    path_of(env, "agentfly/module.py").write_bytes(b"import os\n")
    check = packages.inspect(env, record)
    assert check.problems == [f"{path_of(env, 'agentfly/module.py')} does not match its RECORD"]
    assert not check.rebuilt  # a new version asks, it does not need the "raise the version" advice


def test_a_new_and_a_vanished_distribution_are_listed_for_the_owner(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    shutil.rmtree(next(env.site.glob("fakedep-*.dist-info")))
    shutil.rmtree(env.site / "fakedep")
    write_dist(env, "newdep", "2.0", {"newdep/__init__.py": b"Y = 1\n"})
    check = packages.inspect(env, record)
    assert check.problems == []
    assert check.changes == [
        "newdep: changed from none to 2.0",
        "fakedep: changed from 1.0 to none",
    ]


def test_a_record_from_before_v3c_is_checked_against_record_files_without_a_prompt(
    env: packages.Environment,
) -> None:
    old_record = {"schema": 1, "agentfly_version": "0.1.0"}  # no `packages` section
    check = packages.inspect(env, old_record)
    assert check.problems == [] and check.changes == []


def test_a_same_version_change_advises_raising_the_version(env: packages.Environment) -> None:
    record = hashes_of(env)
    path_of(env, MODULE).write_bytes(b"VALUE = 3\n")
    check = packages.inspect(env, record)
    assert check.rebuilt
    with pytest.raises(InstallError) as caught:
        packages.require(record, "agentfly init -g")
    text = str(caught.value)
    assert str(path_of(env, MODULE)) in text and "run `agentfly init -g` again" in text
    assert "raise the version in pyproject.toml" in text
    assert "No password was asked for" in text


def test_require_returns_the_check_of_a_clean_environment(env: packages.Environment) -> None:
    check = packages.require(hashes_of(env), "agentfly uninstall")
    assert check.problems == [] and len(check.distributions) == 2


def test_require_counts_the_other_problems(env: packages.Environment) -> None:
    path_of(env, MODULE).write_bytes(b"x\n")
    path_of(env, DEP_FILE).write_bytes(b"y\n")
    with pytest.raises(InstallError, match=r"\(and 1 more\)"):
        packages.require(None, "agentfly init -g")


# ---------------------------------------------------------------- the stored section


def test_a_malformed_section_reads_as_none() -> None:
    assert packages.stored_from(None) is None
    assert packages.stored_from({"packages": []}) is None
    assert packages.stored_from({"packages": {"a": {"version": 1, "files": {}}}}) is None
    assert packages.stored_from({"packages": {"a": {"version": "1", "files": {"f": "ab"}}}}) == {
        "a": ("1", {"f": "ab"})
    }


# ---------------------------------------------------------------- where the environment is


def fake_agentfly(monkeypatch: pytest.MonkeyPatch, init_file: Path) -> None:
    monkeypatch.setattr(packages, "agentfly", SimpleNamespace(__file__=str(init_file)))


def test_the_environment_is_found_from_where_agentfly_was_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_tool_env(tmp_path / "other")
    fake_agentfly(monkeypatch, made.site / "agentfly" / "__init__.py")
    found = REAL_TOOL_ENVIRONMENT()
    assert found == packages.Environment(made.prefix, made.site)


@pytest.mark.parametrize("kind", ["checkout", "editable", "no venv", "no dist"])
def test_a_source_checkout_an_editable_install_or_a_bare_site_is_refused(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_tool_env(tmp_path / "other")
    init_file = made.site / "agentfly" / "__init__.py"
    if kind == "checkout":
        init_file = tmp_path / "clone" / "agentfly" / "__init__.py"
    elif kind == "editable":
        info = next(made.site.glob("agentfly_recorder-*.dist-info"))
        url = {"url": "file:///clone", "dir_info": {"editable": True}}
        (info / "direct_url.json").write_text(json.dumps(url))
    elif kind == "no venv":
        (made.prefix / "pyvenv.cfg").unlink()
    else:
        shutil.rmtree(next(made.site.glob("agentfly_recorder-*.dist-info")))
    fake_agentfly(monkeypatch, init_file)
    with pytest.raises(InstallError) as caught:
        REAL_TOOL_ENVIRONMENT()
    text = str(caught.value)
    if kind == "no venv":
        assert "virtual environment" in text
    else:
        assert packages.WHEEL_HINT in text and "source checkout or an editable install" in text


def test_a_wheel_install_with_a_plain_direct_url_is_not_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_tool_env(tmp_path / "other")
    info = next(made.site.glob("agentfly_recorder-*.dist-info"))
    (info / "direct_url.json").write_text('{"url": "file:///w.whl", "archive_info": {}}')
    fake_agentfly(monkeypatch, made.site / "agentfly" / "__init__.py")
    assert REAL_TOOL_ENVIRONMENT().site == made.site


# ---------------------------------------------------------------- the owner's answer


def test_confirm_lists_what_changed_and_takes_a_yes_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    changes = ["agentfly-recorder: changed from 0.1.0 to 0.2.0"]
    assert packages.confirm(changes, ask=lambda prompt: "y")
    assert packages.confirm(changes, ask=lambda prompt: " YES ")
    out = capsys.readouterr().out
    assert "changed from 0.1.0 to 0.2.0" in out
    for answer in ("", "n", "no", "maybe"):
        assert not packages.confirm(changes, ask=lambda prompt, a=answer: a)


def test_confirm_stops_when_the_input_ends(capsys: pytest.CaptureFixture[str]) -> None:
    def closed(prompt: str) -> str:
        raise EOFError

    assert not packages.confirm(["x: changed from 1 to 2"], ask=closed)


def test_only_a_terminal_can_confirm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(packages.sys, "stdin", None)
    assert not packages.confirm(["x: changed from 1 to 2"])
    assert "terminal" in capsys.readouterr().err
