"""V5b: `init -g` puts the rules file in place once, and nothing it does later touches an edit.

Against a temporary root, like test_install_flow.py: the file is written only when missing, as the
system user's, readable by everybody and writable by nobody else; a repair, a second `init -g` and
an upgrade leave an edited copy alone; `uninstall` takes it away with the folder.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agentfly.install import InstallError, installer, records
from agentfly.install.layout import SYSTEM, Layout
from agentfly.install.pythons import PythonBuild
from agentfly.recorder import rulefile
from tests.install_helpers import fake_python_tar, make_layout, status_of, write_archive
from tests.rules_helpers import BROKEN_TOML

EDITED = "# edited by the owner\n" + rulefile.default_text()


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
    assert record is not None and "rules" not in json.dumps(record)


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
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    def gone() -> str:
        raise OSError("no such file")

    monkeypatch.setattr(rulefile, "default_text", gone)
    with pytest.raises(InstallError, match="default rules"):
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
