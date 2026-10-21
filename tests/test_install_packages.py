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
from tests.install_helpers import (
    ANOTHER_PYTHON,
    DIRECT_URL_KINDS,
    MODULE,
    NEW_AGENTFLY,
    call_unless_it_hangs,
    hashes_of,
    make_tool_env,
    path_of,
    plant_direct_url,
    record_hash,
    upgrade,
    write_dist,
)

REAL_TOOL_ENVIRONMENT = packages.tool_environment  # the autouse fixture replaces it per test

SCRIPT = "../../../bin/agentfly"
DEP_FILE = "fakedep/__init__.py"


@pytest.fixture
def env(tool_env: packages.Environment) -> packages.Environment:
    return tool_env


def problems(env: packages.Environment, record: dict[str, Any] | None) -> list[str]:
    return packages.inspect(env, record).problems


def rewrite_record_hash(info: Path, part: str) -> None:
    """Make the RECORD row of `info/part` agree with the file as it is now."""
    data = (info / part).read_bytes()
    row = f"{info.name}/{part},{record_hash(data)},{len(data)}"
    lines = (info / "RECORD").read_text(encoding="utf-8").splitlines()
    rows = [row if line.startswith(f"{info.name}/{part},") else line for line in lines]
    (info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")


def stop_message(record: dict[str, Any], then: str = "agentfly init -g") -> str:
    with pytest.raises(InstallError) as caught:
        packages.require(record, then)
    return str(caught.value)


# ---------------------------------------------------------------- an unchanged install


def test_a_clean_environment_has_no_problems_and_no_changes(env: packages.Environment) -> None:
    for record in (None, hashes_of(env)):
        check = packages.inspect(env, record)
        assert check.problems == [] and check.changes == []
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
    assert problems(env, None) == [
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


@pytest.mark.parametrize("rel", [MODULE, SCRIPT, DEP_FILE], ids=["module", "script", "dependency"])
def test_one_changed_file_is_named_with_or_without_a_record(
    env: packages.Environment, rel: str
) -> None:
    record = hashes_of(env)
    path_of(env, rel).write_bytes(b"import os; os.system('id')\n")
    changed = [f"{path_of(env, rel)} does not match its RECORD"]
    assert problems(env, record) == changed
    assert problems(env, None) == changed


def test_an_extra_file_next_to_an_agentfly_module_is_named(env: packages.Environment) -> None:
    record = hashes_of(env)
    (env.site / "agentfly" / "_native.so").write_bytes(b"\x7fELF")
    extra = f"{env.site / 'agentfly' / '_native.so'} is not listed in any RECORD"
    assert problems(env, record) == [extra]
    assert problems(env, None) == [extra]


def test_a_planted_file_listed_in_a_record_without_a_hash_stops(env: packages.Environment) -> None:
    record = hashes_of(env)
    (env.site / "agentfly" / "extra.py").write_text("x = 1\n")
    info = next(env.site.glob("agentfly_recorder-*.dist-info"))
    with (info / "RECORD").open("a", encoding="utf-8") as handle:
        handle.write("agentfly/extra.py,,\n")  # the planted file, listed (RECORD is writable)
    assert problems(env, record) == [
        f"RECORD has no usable sha256 for {env.site / 'agentfly' / 'extra.py'}, "
        "so it cannot be checked"
    ]


# ---------------------------------------------------------------- links


def test_a_listed_module_replaced_by_a_link_to_an_identical_copy_is_reported(
    env: packages.Environment, tmp_path: Path
) -> None:
    record = hashes_of(env)
    copy = tmp_path / "outside" / "module.py"
    copy.parent.mkdir()
    copy.write_bytes(path_of(env, MODULE).read_bytes())  # the same bytes: every hash still agrees
    path_of(env, MODULE).unlink()
    path_of(env, MODULE).symlink_to(copy)
    for reference in (record, None):
        found = problems(env, reference)
        assert found == [
            f"{path_of(env, MODULE)} is a symbolic link, and RECORD lists a plain file"
        ]


def test_a_listed_folder_replaced_by_a_link_is_reported(
    env: packages.Environment, tmp_path: Path
) -> None:
    record = hashes_of(env)
    copy = tmp_path / "outside" / "fakedep"
    shutil.copytree(env.site / "fakedep", copy)
    shutil.rmtree(env.site / "fakedep")
    (env.site / "fakedep").symlink_to(copy, target_is_directory=True)
    found = problems(env, record)
    assert f"{path_of(env, DEP_FILE)} is reached through a symbolic link" in found
    assert f"{env.site / 'fakedep'} is not listed in any RECORD" in found  # and the link itself


def test_links_above_the_environment_are_part_of_the_base(
    env: packages.Environment, tmp_path: Path
) -> None:
    """A home folder or a tools folder on another disk is a link; the paths are resolved once."""
    link = tmp_path / "linked-env"
    link.symlink_to(env.prefix, target_is_directory=True)
    through = packages.Environment(link, link / "lib" / "python3.12" / "site-packages")
    assert packages.inspect(through, hashes_of(env)).problems == []
    assert packages.inspect(through, None).problems == []


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


# ---------------------------------------------------------------- what only root can see


@pytest.mark.skipif(os.getuid() == 0, reason="root can list any folder")
@pytest.mark.parametrize("mode", [0o000, 0o400], ids=["no access", "read only"])
def test_a_folder_the_user_cannot_list_hides_nothing_from_the_check(
    env: packages.Environment, mode: int
) -> None:
    """Root reads what the user cannot: `neo4j` imports a `numpy` it finds in site-packages."""
    record = hashes_of(env)
    hidden = env.site / "numpy"
    (hidden / "inner").mkdir(parents=True)
    (hidden / "inner" / "__init__.py").write_text("print('root would run this')\n")
    (hidden / "__init__.py").write_text("print('and this')\n")
    hidden.chmod(mode)
    try:
        check = packages.inspect(env, record)
    finally:
        hidden.chmod(0o755)
    assert check.problems, "a planted module in an unreadable folder went unnoticed"
    assert any("numpy" in problem for problem in check.problems), check.problems
    assert check.extra  # delete it: the user owns it


def test_a_nul_byte_in_a_record_path_is_a_problem_not_a_crash(env: packages.Environment) -> None:
    rewrite_record(env, lambda lines: [*lines, "bad\0name.py,sha256=AAAA,1"])
    shown = f"{env.site}/bad\\x00name.py is listed in RECORD but cannot be read ("  # F13: escaped
    found = problems(env, None)
    assert any(problem.startswith(shown) for problem in found), found


# ---------------------------------------------------------------- a RECORD that cannot be trusted


def rewrite_record(env: packages.Environment, edit: Any) -> None:
    info = next(env.site.glob("agentfly_recorder-*.dist-info"))
    lines = (info / "RECORD").read_text(encoding="utf-8").splitlines()
    (info / "RECORD").write_text("\n".join(edit(lines)) + "\n", encoding="utf-8")


@pytest.mark.parametrize("hash_and_size", [",", "md5=AAAA,9"], ids=["no hash", "another algorithm"])
def test_a_row_without_a_sha256_cannot_be_checked(
    env: packages.Environment, hash_and_size: str
) -> None:
    rewrite_record(
        env,
        lambda lines: [f"{MODULE},{hash_and_size}" if r.startswith(MODULE) else r for r in lines],
    )
    assert problems(env, None) == [
        f"RECORD has no usable sha256 for {path_of(env, MODULE)}, so it cannot be checked"
    ]


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
    assert any(f"{info} has no readable METADATA, Name, Version and RECORD" in p for p in found)


@pytest.mark.parametrize("header", ["Name: odd\n", "Version: 1.0\n", "Name: odd\nVersion: \n"])
def test_a_distribution_without_a_name_or_a_version_is_a_problem(
    env: packages.Environment, header: str
) -> None:
    """Recorded with no version it could never be asked about again (found by the audit)."""
    info = write_dist(env, "odd", "1.0", {"odd/__init__.py": b"x = 1\n"})
    (info / "METADATA").write_text("Metadata-Version: 2.1\n" + header)
    rewrite_record_hash(info, "METADATA")  # so that only the header is odd
    found = problems(env, None)
    assert any("no readable METADATA, Name, Version and RECORD" in p for p in found), found


@pytest.mark.parametrize("part", ["RECORD", "METADATA"])
def test_a_linked_record_or_metadata_is_a_problem_and_is_not_read(
    env: packages.Environment, tmp_path: Path, part: str
) -> None:
    """A link to /dev/zero would hang the user's own command; it is refused before any read."""
    target = next(env.site.glob("fakedep-*.dist-info")) / part
    copy = tmp_path / f"{part}.copy"
    copy.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(copy)
    found = problems(env, None)
    assert f"{target} is a symbolic link, and RECORD lists a plain file" in found


def test_two_copies_of_one_distribution_are_a_problem(env: packages.Environment) -> None:
    write_dist(env, "FakeDep", "1.1", {"fakedep/other.py": b"x = 2\n"})
    assert any("two copies of fakedep" in p for p in problems(env, None))


# ---------------------------------------------------------------- upgrades


def test_an_upgrade_of_agentfly_alone_goes_ahead_and_the_new_hashes_are_the_ones_stored(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    upgrade(env, "agentfly-recorder", "0.2.0", NEW_AGENTFLY)
    check = packages.inspect(env, record)
    assert check.problems == []
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


def test_require_returns_the_check_of_a_clean_environment(env: packages.Environment) -> None:
    check = packages.require(hashes_of(env), "agentfly uninstall")
    assert check.problems == [] and len(check.distributions) == 2


def test_require_counts_the_other_problems(env: packages.Environment) -> None:
    path_of(env, MODULE).write_bytes(b"x\n")
    path_of(env, DEP_FILE).write_bytes(b"y\n")
    with pytest.raises(InstallError, match=r"\(and 1 more\)"):
        packages.require(None, "agentfly init -g")


# ---------------------------------------------------------------- the stored section


def test_no_section_means_no_record_and_a_malformed_one_means_nothing_is_known() -> None:
    assert packages.stored_from(None) is None
    assert packages.stored_from({"schema": 1}) is None  # an install from before V3c
    assert packages.stored_from({"packages": []}) == {}  # not "no record": everything is asked
    good = {"version": "1", "files": {"f": "ab"}}
    assert packages.stored_from({"packages": {"a": good}}) == {"a": ("1", {"f": "ab"})}
    odd = {"packages": {"a": good, "b": {"version": 1, "files": {}}, "c": {"version": "1"}}}
    assert packages.stored_from(odd) == {"a": ("1", {"f": "ab"})}  # b and c are not described


def test_a_malformed_record_asks_instead_of_going_quiet(env: packages.Environment) -> None:
    record = hashes_of(env)
    both = ["agentfly-recorder: changed from none to 0.1.0", "fakedep: changed from none to 1.0"]
    assert packages.inspect(env, {"packages": "garbage"}).changes == both
    record["packages"]["fakedep"]["version"] = None  # one entry unreadable
    assert packages.inspect(env, record).changes == ["fakedep: changed from none to 1.0"]


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


@pytest.mark.parametrize("listed", [False, True], ids=["unlisted", "in-record"])
@pytest.mark.parametrize("kind", DIRECT_URL_KINDS)
def test_a_direct_url_that_is_not_a_plain_file_is_a_problem_and_is_never_read(
    kind: str, listed: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_tool_env(tmp_path / "other")
    info = next(made.site.glob("agentfly_recorder-*.dist-info"))
    target, fifo = plant_direct_url(info, kind, tmp_path / "scratch", listed=listed)
    fake_agentfly(monkeypatch, made.site / "agentfly" / "__init__.py")
    monkeypatch.setattr(packages, "tool_environment", REAL_TOOL_ENVIRONMENT)
    with pytest.raises(InstallError) as caught:
        call_unless_it_hangs(lambda: packages.require(None, "agentfly uninstall"), fifo)
    assert str(target) in str(caught.value) and "No password was asked for" in str(caught.value)


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


def test_the_advice_for_an_extra_file_is_not_to_reinstall_over_it(
    env: packages.Environment,
) -> None:
    """`uv tool install --force` leaves a file no RECORD lists where it is (measured, uv 0.9.5)."""
    record = hashes_of(env)
    (env.site / "agentfly" / "_native.so").write_bytes(b"\x7fELF")
    check = packages.inspect(env, record)
    assert check.extra
    text = stop_message(record)
    assert "delete each extra file" in text and "uv tool uninstall agentfly-recorder" in text


def test_a_changed_file_gets_the_reinstall_advice_only(env: packages.Environment) -> None:
    record = hashes_of(env)
    path_of(env, MODULE).write_bytes(b"x = 1\n")
    check = packages.inspect(env, record)
    assert not check.extra
    text = stop_message(record)
    assert "delete each extra file" not in text
    assert "reinstall AgentFly from a source you trust" in text


# ---------------------------------------------------------------- a rebuild at the same version

REBUILT = "same version {}, files differ from install but match RECORD"


def test_a_rebuild_of_agentfly_at_the_same_version_asks_instead_of_stopping(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    upgrade(env, "agentfly-recorder", "0.1.0", NEW_AGENTFLY)  # other module, RECORD agrees
    check = packages.require(record, "agentfly init -g")  # no InstallError
    assert packages.inspect(env, None).changes == []  # with no record there is nothing to ask
    assert check.problems == []
    assert check.changes == [
        "agentfly-recorder: " + REBUILT.format("0.1.0") + f" (1: {MODULE}): expected only if you "
        "reinstalled or rebuilt"
    ]


def test_a_dependency_reinstalled_under_another_python_asks_too(env: packages.Environment) -> None:
    record = hashes_of(env)
    upgrade(env, "fakedep", "1.0", ANOTHER_PYTHON)  # the .so is named for another interpreter
    check = packages.require(record, "agentfly uninstall")
    assert check.changes == [
        "fakedep: "
        + REBUILT.format("1.0")
        + " (2: fakedep/_speed.cpython-313.so, fakedep/_speed.so): expected only if you "
        "reinstalled or rebuilt"
    ]
    recorded = {"packages": packages.to_record(check.distributions)}  # what a yes writes
    assert packages.inspect(env, recorded).changes == []


def test_a_rebuild_names_the_first_three_changed_files_and_counts_the_rest(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    upgrade(
        env, "fakedep", "1.0", {DEP_FILE: b"X = 1\n", **{f"fakedep/m{i}.py": b"" for i in range(5)}}
    )
    [line] = packages.require(record, "agentfly init -g").changes
    assert line == (
        "fakedep: " + REBUILT.format("1.0") + " (6: fakedep/_speed.so, fakedep/m0.py, "
        "fakedep/m1.py and 3 more): expected only if you reinstalled or rebuilt"
    )  # the removed _speed.so counts as changed, and sorts first


def test_a_changed_path_with_a_control_character_is_shown_escaped(
    env: packages.Environment,
) -> None:
    """RECORD is writable by the agent's user, and `confirm()` prints the list to the owner."""
    record = hashes_of(env)
    hostile = "fakedep/\x1b[2Jgone.py"
    upgrade(env, "fakedep", "1.0", {DEP_FILE: b"X = 1\n", hostile: b""})
    [line] = packages.require(record, "agentfly init -g").changes
    assert "\x1b" not in line and "fakedep/\\x1b[2Jgone.py" in line
    assert "'fakedep/" not in line  # the same escape as every other name, not a quoted repr


def test_a_rebuild_with_a_file_that_fails_its_own_record_still_stops(
    env: packages.Environment,
) -> None:
    record = hashes_of(env)
    upgrade(env, "agentfly-recorder", "0.1.0", NEW_AGENTFLY)
    path_of(env, MODULE).write_bytes(b"import os\n")  # now it fails the RECORD that was rebuilt
    assert problems(env, record) == [f"{path_of(env, MODULE)} does not match its RECORD"]


def test_a_rebuild_with_an_extra_file_still_stops(env: packages.Environment) -> None:
    record = hashes_of(env)
    upgrade(env, "fakedep", "1.0", ANOTHER_PYTHON)
    (env.site / "fakedep" / "_planted.so").write_bytes(b"\x7fELF")
    found = problems(env, record)
    assert found == [f"{env.site / 'fakedep' / '_planted.so'} is not listed in any RECORD"]


@pytest.mark.parametrize("fault", ["changed", "extra", "link", "no hash"])
def test_no_stop_message_advises_removing_the_record(env: packages.Environment, fault: str) -> None:
    record = hashes_of(env)
    if fault == "changed":
        path_of(env, MODULE).write_bytes(b"x = 1\n")
    elif fault == "extra":
        (env.site / "agentfly" / "_native.so").write_bytes(b"\x7fELF")
    elif fault == "link":
        path_of(env, DEP_FILE).unlink()
        path_of(env, DEP_FILE).symlink_to(path_of(env, MODULE))
    else:
        rewrite_record(env, lambda lines: [r.replace("sha256=", "md5=") for r in lines])
    text = stop_message(record)
    for word in ("hashes.json", "sudo", " rm ", "raise the version"):
        assert word not in text, (word, text)


# ---------------------------------------------------------------- names the owner reads (F13)
#
# Every name below sits in a folder the agent's user can write and is printed to the owner's
# terminal before a password is asked for. Expected texts are written out, never computed with
# `packages.visible`, so a broken `visible` cannot pass its own test. `visible` works on one
# character at a time and has its own table, so each place gets one name that holds all three
# kinds at once: a cursor control, a line break and a bidi override.

BAD = "\x1b[2K\n‮"
SHOWN = "\\x1b[2K\\n\\u202e"
# A plain newline ends a METADATA header, so the newline row is a folded one (RFC 822 style).
METADATA_VERSIONS = [  # (header value, how its tail is shown)
    pytest.param("1.1\x1b[2Kz", "1.1\\x1b[2Kz", id="escape code"),
    pytest.param("1.1‮z", "1.1\\u202ez", id="bidi override"),
    pytest.param("1.1\n z", "1.1\\nz", id="folded newline"),
]
METADATA_NAMES = [
    pytest.param("new\x1b[2mdep", "new\\x1b[2mdep", id="escape code"),
    pytest.param("new‮dep", "new\\u202edep", id="bidi override"),
    pytest.param("new\n dep", "new\\ndep", id="folded newline"),
]


def assert_plain(text: str) -> None:
    """Every line of `text` holds only printable characters; its newlines are print's own."""
    for line in text.split("\n"):
        assert line.isprintable(), ascii(line)


def add_record_row(env: packages.Environment, row: str) -> None:
    """Add a row to agentfly's RECORD; a path with a newline is quoted so it stays one field."""
    rewrite_record(env, lambda lines: [*lines, row])


def edit_metadata(env: packages.Environment, dist: str, headers: str) -> None:
    info = next(env.site.glob(f"{dist}-*.dist-info"))
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\n{headers}", encoding="utf-8")
    rewrite_record_hash(info, "METADATA")


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("a\x1b[2Kb", "a\\x1b[2Kb"),
        ("a\nb", "a\\nb"),
        ("a\rb", "a\\rb"),
        ("a\tb", "a\\tb"),
        ("a\0b", "a\\x00b"),
        ("a\x7fb", "a\\x7fb"),
        ("a\x85b", "a\\x85b"),
        ("a\x9bb", "a\\x9bb"),
        ("a\xa0b", "a\\xa0b"),
        ("a‎b", "a\\u200eb"),
        ("a؜b", "a\\u061cb"),
        ("a b", "a\\u2028b"),
        ("a‮b", "a\\u202eb"),
        ("a⁦b⁩", "a\\u2066b\\u2069"),
        ("a\udcffb", "a\\udcffb"),
        ("a\U000e0001b", "a\\U000e0001b"),
    ],
)
def test_visible_writes_each_non_printable_character_as_an_escape(name: str, shown: str) -> None:
    assert packages.visible(name) == shown


@pytest.mark.parametrize(
    "name",
    # the last is an escape already written out: a second pass leaves it alone
    ["café.py", "日本語/ファイル.py", "a\\b.py", "a b.py", "", "a\\x1b[2Kb"],
)
def test_visible_leaves_printable_text_alone(name: str) -> None:
    assert packages.visible(name) == name


def test_an_unlisted_file_with_control_characters_in_its_name_is_shown_escaped(
    env: packages.Environment,
) -> None:
    (env.site / "agentfly" / f"x{BAD}y.py").write_text("x = 1\n")
    message = stop_message(None)
    assert f"{env.site}/agentfly/x{SHOWN}y.py is not listed in any RECORD" in message
    assert_plain(message)


def test_a_listed_file_that_fails_its_hash_is_shown_escaped(env: packages.Environment) -> None:
    rel = f"agentfly/m{BAD}.py"
    digest = record_hash(b"x = 1\n")
    path_of(env, rel).write_bytes(b"x = 1\n")
    add_record_row(env, f'"{rel}",{digest},6')
    path_of(env, rel).write_bytes(b"x = 2\n")
    message = stop_message(None)
    assert f"{env.site}/agentfly/m{SHOWN}.py does not match its RECORD" in message
    assert_plain(message)


def test_a_listed_file_that_cannot_be_read_is_shown_escaped(env: packages.Environment) -> None:
    add_record_row(env, f'"agentfly/gone{BAD}.py",sha256=AAAA,1')  # no such file
    found = problems(env, None)
    assert f"{env.site}/agentfly/gone{SHOWN}.py is listed in RECORD but cannot be read" in found[0]
    assert_plain("\n".join(found))


def test_a_record_row_outside_the_environment_is_shown_escaped(env: packages.Environment) -> None:
    add_record_row(env, f'"../../../../out{BAD}.txt",sha256=AAAA,1')
    message = stop_message(None)
    assert f"agentfly_recorder-0.1.0.dist-info/RECORD names ../../../../out{SHOWN}.txt" in message
    assert "outside the environment" in message
    assert_plain(message)


def test_a_dist_info_folder_name_is_shown_escaped(env: packages.Environment) -> None:
    (env.site / f"evil{BAD}-1.0.dist-info").mkdir()
    message = stop_message(None)
    assert f"{env.site}/evil{SHOWN}-1.0.dist-info has no readable METADATA" in message
    assert_plain(message)


def test_a_tool_environment_path_with_control_characters_is_shown_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile = make_tool_env(tmp_path / f"env{BAD}")
    monkeypatch.setattr(packages, "tool_environment", lambda: hostile)
    (hostile.site / "agentfly" / "x.py").write_text("x = 1\n")
    message = stop_message(None)
    where = str(hostile.site).replace(BAD, SHOWN)
    assert f"{where}/agentfly/x.py is not listed in any RECORD" in message
    assert_plain(message)


def test_the_environment_refusal_shows_a_path_with_control_characters_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_tool_env(tmp_path / f"other{BAD}")
    (made.prefix / "pyvenv.cfg").unlink()
    fake_agentfly(monkeypatch, made.site / "agentfly" / "__init__.py")
    with pytest.raises(InstallError) as caught:
        REAL_TOOL_ENVIRONMENT()
    text = str(caught.value)
    assert f"virtual environment ({str(made.site).replace(BAD, SHOWN)})" in text
    assert_plain(text)


@pytest.mark.parametrize(("header", "tail"), METADATA_VERSIONS)
def test_a_metadata_version_with_a_control_character_is_shown_escaped_in_the_question(
    env: packages.Environment,
    capsys: pytest.CaptureFixture[str],
    header: str,
    tail: str,
) -> None:
    record = hashes_of(env)
    edit_metadata(env, "fakedep", f"Name: fakedep\nVersion: {header}\n")
    [line] = packages.require(record, "agentfly init -g").changes
    assert line.startswith("fakedep: changed from 1.0 to ") and line.endswith(tail), line
    assert_plain(line)
    assert not packages.confirm([line], ask=lambda prompt: "n")
    assert_plain(capsys.readouterr().out)


@pytest.mark.parametrize(("header", "tail"), METADATA_NAMES)
def test_a_metadata_name_with_a_control_character_is_shown_escaped(
    env: packages.Environment, header: str, tail: str
) -> None:
    record = hashes_of(env)
    edit_metadata(env, "fakedep", f"Name: {header}\nVersion: 1.0\n")
    lines = packages.require(record, "agentfly init -g").changes
    assert any(line.endswith(f"{tail}: changed from none to 1.0") for line in lines), lines
    assert "fakedep: changed from 1.0 to none" in lines
    assert_plain("\n".join(lines))


def test_confirm_shows_a_control_character_in_a_change_line_escaped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    changes = ["x\x1b[2K: changed from 1 to 2", "y‮: changed from none to 1"]
    assert not packages.confirm(changes, ask=lambda prompt: "n")
    out = capsys.readouterr().out
    assert "  x\\x1b[2K: changed from 1 to 2\n  y\\u202e: changed from none to 1\n" in out
    assert_plain(out)


def test_confirm_does_not_stop_on_a_name_the_terminal_cannot_encode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert not packages.confirm(["z\udcff: changed from 1 to none"], ask=lambda prompt: "n")
    assert "  z\\udcff: changed from 1 to none\n" in capsys.readouterr().out


def test_a_name_without_a_control_character_prints_as_before(env: packages.Environment) -> None:
    (env.site / "agentfly" / "café.py").write_text("x = 1\n")
    (env.site / "agentfly" / "a\\b.py").write_text("x = 1\n")
    assert problems(env, None) == [
        f"{env.site}/agentfly/a\\b.py is not listed in any RECORD",
        f"{env.site}/agentfly/café.py is not listed in any RECORD",
    ]


def test_no_message_of_the_check_holds_a_control_character_whatever_the_name(
    tmp_path: Path,
) -> None:
    """A hostile name in every place at once; it guards later edits to `inspect`."""
    hostile = make_tool_env(tmp_path / f"env{BAD}")
    record = hashes_of(hostile)
    (hostile.site / "agentfly" / f"x{BAD}y.py").write_text("x = 1\n")  # listed in no RECORD
    (hostile.site / f"evil{BAD}-1.0.dist-info").mkdir()  # no METADATA
    add_record_row(hostile, f'"../../../../out{BAD}.txt",sha256=AAAA,1')  # outside
    edit_metadata(hostile, "fakedep", "Name: fakedep\nVersion: 1.1\x1b[2Kz\n")  # a new version
    check = packages.inspect(hostile, record)
    assert (len(check.problems), len(check.changes)) == (3, 1)  # each place was reached
    assert_plain("\n".join([*check.problems, *check.changes]))
