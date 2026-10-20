"""V5b, V5b-fix (D28): `init -g` puts the rules file in place, and never touches an edit.

Against a temporary root, like test_install_flow.py: the file is written when missing, as the
system user's, readable by everybody and writable by nobody else; a file that is byte for byte a
default the package once carried (the owner never edited it) is replaced by this version's; a
repair, a second `init -g` and an upgrade leave an edited copy alone; `uninstall` takes it away with
the folder. What is written is the packaged default as read once, checked against the wheel's
RECORD hash and parsed cleanly.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agentfly.install import InstallError, installer, packages, pythons, records
from agentfly.install.layout import SYSTEM, Layout
from agentfly.install.pythons import PythonBuild
from agentfly.recorder import rulefile
from tests.install_helpers import (
    TOOL_DISTS,
    fake_python_tar,
    make_layout,
    make_tool_env,
    status_of,
    write_archive,
)
from tests.rules_helpers import BROKEN_TOML, default_as

EDITED = "# edited by the owner\n" + rulefile.default_text()
SHIPPED = sorted((Path(__file__).parent / "fixtures" / "shipped_defaults").glob("*.toml"))
RECORD_PATH = installer.DEFAULT_RECORD_PATH


@pytest.fixture(autouse=True)
def quick_install(monkeypatch: pytest.MonkeyPatch) -> None:
    # The install's own checks (a smoke run of every hook command, byte-compiling the Python) are
    # tests/test_install_flow.py's business; none of these tests looks at them (~1.5 s each).
    monkeypatch.setattr(installer, "smoke", lambda *args, **kwargs: None)
    monkeypatch.setattr(pythons, "compile_stdlib", lambda *args, **kwargs: None)


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return make_layout(tmp_path)


@pytest.fixture
def archive(tmp_path: Path) -> tuple[Path, PythonBuild]:
    return write_archive(tmp_path / "download", fake_python_tar())


def do_install(layout: Layout, archive: tuple[Path, PythonBuild]) -> installer.Outcome:
    path, build = archive
    return installer.install(
        layout, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )


def fingerprint(path: Path) -> tuple[int, int, int]:
    info = path.lstat()
    return info.st_ino, info.st_mtime_ns, info.st_size


# ---------------------------------------------------------------- a first install


def test_the_rules_file_is_where_the_spec_says(layout: Layout) -> None:
    assert layout.rules == layout.system_root / "rules.toml"
    assert SYSTEM.rules == Path("/Library/Application Support/AgentFly/rules.toml")
    assert rulefile.ACTIVE_RULES != SYSTEM.rules, "the conftest keeps tests off the real file"


def test_install_writes_the_packaged_default_as_a_readable_unwritable_file(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    old = os.umask(0o077)  # a strict umask must not make the file unreadable for the user
    try:
        outcome = do_install(layout, archive)
    finally:
        os.umask(old)
    assert layout.rules.read_text(encoding="utf-8") == rulefile.default_text()
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o644
    assert any("rules" in message for message in outcome.messages)
    assert rulefile.load_file(layout.rules).errors == ()


def test_the_file_is_written_with_the_layouts_owner_in_one_atomic_step(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, int]] = []
    real = installer._write_atomic

    def spy(path: Path, data: bytes, lay: Layout, mode: int = 0o644) -> None:
        calls.append((path, mode))
        real(path, data, lay, mode)

    monkeypatch.setattr(installer, "_write_atomic", spy)
    do_install(layout, archive)
    assert (layout.rules, 0o644) in calls, "the same helper that chowns and renames every file"


def test_the_folder_listing_has_the_rules_file_and_no_leftovers(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    assert sorted(p.name for p in layout.system_root.iterdir()) == [
        "hashes.json",
        "hook_client.py",
        "python",
        "rules.toml",
    ]
    assert installer.lock_problems(layout, check_owner=False) == []


def test_the_record_does_not_hash_the_rules_file(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    record = records.read(layout)
    # The packaged default is a file of the package, so its hash is among the package's; the
    # active file is the owner's and is neither named nor hashed on its own.
    assert record is not None and "rules.toml" not in json.dumps(record)


# ---------------------------------------------------------------- an edit is the owner's


def test_a_second_init_leaves_an_edited_copy_alone(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    before = fingerprint(layout.rules)
    assert status_of(layout, archive[1]) == set(), "an edit is not drift"
    outcome = do_install(layout, archive)
    assert not outcome.changed
    assert fingerprint(layout.rules) == before and layout.rules.read_text() == EDITED


def test_a_repair_of_something_else_never_overwrites_the_edit(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    layout.client.chmod(0o644)
    layout.client.write_text("tampered\n")
    assert status_of(layout, archive[1]) == {"client"}
    assert do_install(layout, archive).changed
    assert layout.client.read_bytes() == installer.client_source().read_bytes()
    assert layout.rules.read_text() == EDITED


def test_an_edit_that_is_not_valid_is_still_left_alone(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(BROKEN_TOML, encoding="utf-8")
    do_install(layout, archive)
    assert layout.rules.read_text() == BROKEN_TOML, "doctor reports it; init does not"


# ---------------------------------------------------------------- an install from before this card


def test_an_install_from_before_the_card_gets_the_file_on_its_next_init(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    assert status_of(layout, archive[1]) == {"rules"}
    client, interpreter = fingerprint(layout.client), fingerprint(layout.interpreter)
    outcome = do_install(layout, archive)
    assert outcome.changed and any("rules" in message for message in outcome.messages)
    assert layout.rules.read_text() == rulefile.default_text()
    assert status_of(layout, archive[1]) == set()
    assert (fingerprint(layout.client), fingerprint(layout.interpreter)) == (client, interpreter)


def test_a_missing_record_counts_the_rules_file_as_missing_too(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    assert "rules" in status_of(layout, archive[1])


# ---------------------------------------------------------------- what stands in the way


def test_a_symbolic_link_in_its_place_is_refused_and_its_target_is_not_written(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path
) -> None:
    do_install(layout, archive)
    target = tmp_path / "elsewhere.toml"
    target.write_text("mine\n")
    layout.rules.unlink()
    layout.rules.symlink_to(target)
    assert "rules" in status_of(layout, archive[1])
    with pytest.raises(InstallError, match="symbolic link"):
        do_install(layout, archive)
    assert target.read_text() == "mine\n" and layout.rules.is_symlink()


def test_a_folder_in_its_place_is_refused(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    layout.rules.mkdir()
    with pytest.raises(InstallError, match="not a regular file"):
        do_install(layout, archive)


def test_a_packaged_default_that_cannot_be_read_stops_the_install_with_a_message(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(rulefile, "default_path", lambda: tmp_path / "gone.toml")
    with pytest.raises(InstallError, match="cannot read the packaged default rules"):
        do_install(layout, archive)
    assert not layout.system_root.exists(), "a failed first install leaves nothing behind"


# ---------------------------------------------------------------- uninstall


def test_uninstall_takes_the_rules_file_away_with_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    installer.uninstall(layout)
    assert not layout.system_root.exists()
    assert not layout.rules.exists()


def test_the_status_lists_only_the_known_parts(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    layout.client.write_text("tampered\n")
    found: Any = status_of(layout, archive[1])
    assert found == {"rules", "client"}


# ---------------------------------------------------------------- an unedited older default (D28)


def tamper_with_the_client(layout: Layout) -> None:
    """Something else to repair, so that `init -g` has work to do besides the rules."""
    layout.client.chmod(0o644)
    layout.client.write_text("tampered\n")


@pytest.mark.parametrize("old", SHIPPED, ids=[f.stem for f in SHIPPED])
def test_an_unedited_older_default_is_replaced_and_the_restart_is_asked_for(
    old: Path, layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_bytes(old.read_bytes())
    assert status_of(layout, archive[1]) == {"rules"}, "an older default is drift"
    client, interpreter = fingerprint(layout.client), fingerprint(layout.interpreter)
    outcome = do_install(layout, archive)
    assert outcome.changed
    (said,) = [m for m in outcome.messages if "replaced" in m]
    assert "unedited default rules" in said and "restart the recorder" in said
    assert layout.rules.read_bytes() == rulefile.default_path().read_bytes()
    assert stat.S_IMODE(layout.rules.stat().st_mode) == 0o644
    assert status_of(layout, archive[1]) == set()
    assert (fingerprint(layout.client), fingerprint(layout.interpreter)) == (client, interpreter)


def test_the_current_default_is_left_alone(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    before = fingerprint(layout.rules)
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    assert fingerprint(layout.rules) == before
    assert not any("rules" in message for message in outcome.messages)


def test_an_edit_is_kept_with_one_notice_line_when_init_has_other_work(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    notices = [m for m in outcome.messages if "kept your edited rules file" in m]
    assert len(notices) == 1 and str(layout.rules) in notices[0]
    assert layout.rules.read_text() == EDITED


def test_an_edit_that_is_not_valid_is_kept_too(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(BROKEN_TOML, encoding="utf-8")
    tamper_with_the_client(layout)
    outcome = do_install(layout, archive)
    assert any("kept your edited rules file" in m for m in outcome.messages)
    assert layout.rules.read_text() == BROKEN_TOML


def test_an_intact_install_with_an_edit_says_only_that_nothing_changed(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_text(EDITED, encoding="utf-8")
    outcome = do_install(layout, archive)
    assert (outcome.changed, outcome.messages) == (
        False,
        ["already installed and intact; nothing changed"],
    )


def test_an_oversized_file_in_its_place_counts_as_an_edit(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.rules.write_bytes(b"#" * (rulefile.MAX_FILE_BYTES + 10))
    assert status_of(layout, archive[1]) == set()


def test_the_states_of_the_rules_file(layout: Layout, archive: tuple[Path, PythonBuild]) -> None:
    wanted = rulefile.sha256_of(rulefile.default_path().read_bytes())
    state = installer.rules_state
    assert state(layout, wanted) == "missing"
    do_install(layout, archive)
    assert state(layout, wanted) == "current"
    layout.rules.write_bytes(SHIPPED[0].read_bytes())
    assert state(layout, wanted) == "older"
    layout.rules.write_text(EDITED, encoding="utf-8")
    assert state(layout, wanted) == "edited"
    layout.rules.unlink()
    layout.rules.mkdir()
    assert state(layout, wanted) == "blocked"


# ------------------------------------------------------- what is written is what was checked


def test_a_default_changed_after_the_package_was_hashed_is_refused_and_nothing_is_written(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    swapped = tmp_path / "swapped.toml"
    swapped.write_text(default_as("warn"), encoding="utf-8")  # a valid file, but not the hashed one
    monkeypatch.setattr(rulefile, "default_path", lambda: swapped)
    with pytest.raises(InstallError, match="not the file that was checked"):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def hashed_package_holding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data: bytes | None
) -> Path:
    """A tool environment whose RECORD lists `data` as the default (none: lists no default)."""
    version, files = TOOL_DISTS["agentfly-recorder"]
    files = {k: v for k, v in files.items() if k != RECORD_PATH}
    path = tmp_path / "default.toml"
    if data is not None:
        files[RECORD_PATH] = data
        path.write_bytes(data)
    env = make_tool_env(tmp_path / "env2", {**TOOL_DISTS, "agentfly-recorder": (version, files)})
    monkeypatch.setattr(packages, "tool_environment", lambda: env)
    monkeypatch.setattr(rulefile, "default_path", lambda: path)
    return path


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        (BROKEN_TOML, "cannot be used"),
        (default_as("warn"), "rule R1"),  # a default that D27 would refuse is not installed
        ("schema = 1\n", "rule R1: missing"),
    ],
    ids=["not toml", "weak R1", "no R1"],
)
def test_a_packaged_default_that_does_not_parse_cleanly_is_never_written(
    text: str,
    complaint: str,
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hashed_package_holding(monkeypatch, tmp_path, text.encode())
    with pytest.raises(InstallError, match=complaint):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def test_a_default_that_the_record_does_not_list_is_refused(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hashed_package_holding(monkeypatch, tmp_path, None)
    with pytest.raises(InstallError, match="not listed in AgentFly's RECORD"):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def test_a_link_in_its_place_is_refused_before_anything_else_is_repaired(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path
) -> None:
    do_install(layout, archive)
    target = tmp_path / "elsewhere.toml"
    target.write_text("mine\n")
    layout.rules.unlink()
    layout.rules.symlink_to(target)
    tamper_with_the_client(layout)
    with pytest.raises(InstallError, match="symbolic link"):
        do_install(layout, archive)
    assert layout.client.read_text() == "tampered\n", "refused before the repair started"
    assert target.read_text() == "mine\n"


def test_recorded_hash_is_the_hash_the_check_made() -> None:
    check = packages.inspect(packages.tool_environment(), None)
    digest = packages.recorded_hash(check, RECORD_PATH)
    assert digest == rulefile.sha256_of(rulefile.default_path().read_bytes())
    assert packages.recorded_hash(check, "agentfly/nothing.toml") is None
    assert packages.recorded_hash(check, RECORD_PATH, "no-such-package") is None
