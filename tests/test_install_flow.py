"""Install and uninstall against a temporary root: the whole flow, the files and the order."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from agentfly.install import InstallError, cursor, hooks_file, installer, pythons, records
from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild
from tests.helpers import client_env
from tests.install_helpers import (
    OTHER_TOOL_ENTRY,
    fake_python_tar,
    make_layout,
    write_archive,
)

OTHER_FILE = (
    '{\n  "version": 1,\n  "hooks": {\n    "stop": [\n      '
    + OTHER_TOOL_ENTRY
    + "\n    ]\n  }\n}\n"
)


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


def snapshot(layout: Layout) -> dict[str, tuple[int, int, int]]:
    """Every file under the system folders: inode, mtime and size."""
    state: dict[str, tuple[int, int, int]] = {}
    for root in (layout.system_root, layout.cursor_dir):
        for path in root.rglob("*"):
            info = path.lstat()
            state[str(path)] = (info.st_ino, info.st_mtime_ns, info.st_size)
    return state


def test_install_writes_the_files_the_record_and_the_hooks(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    outcome = do_install(layout, archive)
    assert outcome.changed
    assert sorted(p.name for p in layout.system_root.iterdir()) == [
        "hashes.json",
        "hook_client.py",
        "python",
    ]
    record = records.read(layout)
    assert record is not None
    assert record["python"]["interpreter_sha256"] == pythons.file_sha256(layout.interpreter)
    assert record["python"]["tree_sha256"] == pythons.tree_digest(layout.python_dir)
    assert record["python"]["archive_sha256"] == archive[1].sha256
    assert record["client"]["sha256"] == pythons.file_sha256(layout.client)
    assert record["client"]["sha256"] == pythons.file_sha256(installer.client_source())
    assert record["hooks_file"]["created"] is True
    assert {e["event"] for e in record["hooks_file"]["entries"]} == set(cursor.EVENTS)


def test_nobody_but_the_owner_can_write_what_was_installed(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    old = os.umask(0o077)  # a strict umask must not make the files unreadable for the user
    try:
        do_install(layout, archive)
    finally:
        os.umask(old)
    for path in [layout.system_root, layout.hooks_file, *layout.system_root.rglob("*")]:
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        assert not mode & 0o022, (path, oct(mode))
        assert mode & 0o004, (path, oct(mode))


def test_every_registered_command_runs_through_sh_and_answers_json(
    layout: Layout, archive: tuple[Path, PythonBuild], isolated_home: Path
) -> None:
    do_install(layout, archive)
    hooks = json.loads(layout.hooks_file.read_text())["hooks"]
    assert set(hooks) == set(cursor.EVENTS)
    for event, group in hooks.items():
        command = group[0]["command"]
        assert command.startswith(f'"{layout.interpreter}" -I -S "{layout.client}" cursor ')
        result = subprocess.run(
            ["/bin/sh", "-c", command],
            input=json.dumps({"hook_event_name": event}),
            capture_output=True,
            text=True,
            env=client_env(isolated_home),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert isinstance(json.loads(result.stdout), dict)


def test_a_second_install_changes_nothing(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)
    before = snapshot(layout)
    again = do_install(layout, archive)
    assert not again.changed
    assert snapshot(layout) == before
    assert len(list(layout.backups.iterdir())) == 1  # one backup, from the first run


def test_another_tools_entries_survive_and_a_backup_is_kept(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)
    assert OTHER_TOOL_ENTRY in layout.hooks_file.read_text()
    (backup,) = layout.backups.iterdir()
    assert backup.read_text() == OTHER_FILE
    installer.uninstall(layout)
    assert layout.hooks_file.read_text() == OTHER_FILE  # byte for byte
    assert not layout.system_root.exists()


def test_uninstall_removes_a_file_it_created_and_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    outcome = installer.uninstall(layout)
    assert outcome.changed
    assert not layout.hooks_file.exists() and not layout.system_root.exists()


def test_uninstall_removes_the_entries_before_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk says no")

    monkeypatch.setattr(shutil, "rmtree", fail)
    with pytest.raises(OSError):
        installer.uninstall(layout)
    assert hooks_file.our_entries(layout.hooks_file.read_text(), installer.prefix(layout)) == []
    assert layout.system_root.exists()  # a failed removal never leaves entries without a client


def test_uninstall_needs_neither_cursor_nor_a_known_version(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    assert not layout.cursor_app.exists()
    installer.uninstall(layout)
    assert not layout.system_root.exists()


def test_uninstall_with_nothing_installed_is_quiet(layout: Layout) -> None:
    assert not installer.is_installed(layout)
    outcome = installer.uninstall(layout)
    assert not outcome.changed and not layout.system_root.exists()


def test_uninstall_refuses_a_broken_file_that_mentions_us(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.hooks_file.write_text(layout.hooks_file.read_text() + " garbage")
    with pytest.raises(InstallError, match="not valid JSON"):
        installer.uninstall(layout)
    assert layout.system_root.exists()


def test_a_bad_checksum_writes_nothing(layout: Layout, tmp_path: Path) -> None:
    path, _ = write_archive(tmp_path / "download", fake_python_tar())
    wrong = PythonBuild("pinned.tar.gz", "", "0" * 64)
    with pytest.raises(InstallError, match=r"checksum mismatch for pinned\.tar\.gz"):
        installer.install(
            layout, wrong, cursor_version="3.24.12", source=installer.client_source(), archive=path
        )
    assert not layout.system_root.exists() and not layout.cursor_dir.exists()


def test_a_failure_after_staging_removes_the_staging_folder(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise InstallError("hook command does not start")

    monkeypatch.setattr(installer, "smoke", broken)
    with pytest.raises(InstallError):
        do_install(layout, archive)
    assert not layout.system_root.exists()


def test_a_tampered_client_or_python_is_repaired(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    path, build = archive
    source = installer.client_source()
    for victim in (layout.client, layout.python_dir / "lib" / "python3.12" / "helper.py"):
        victim.chmod(0o644)
        victim.write_text("tampered\n")
        assert installer.status(layout, build, source)
        outcome = do_install(layout, archive)
        assert outcome.changed
        assert installer.status(layout, build, source) == set()
    assert layout.client.read_bytes() == source.read_bytes()


def test_a_removed_hook_entry_is_put_back(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.hooks_file.write_text(OTHER_FILE)
    assert installer.status(layout, archive[1], installer.client_source()) == {"hooks"}
    do_install(layout, archive)
    assert len(hooks_file.our_entries(layout.hooks_file.read_text(), installer.prefix(layout))) == 8
    assert OTHER_TOOL_ENTRY in layout.hooks_file.read_text()


def test_the_command_path_must_be_quotable(tmp_path: Path) -> None:
    bad = make_layout(tmp_path / 'we"ird')
    with pytest.raises(InstallError, match="cannot be quoted"):
        installer.install(
            bad,
            PythonBuild("x", "", "0" * 64),
            cursor_version="3.24.12",
            source=installer.client_source(),
        )


def test_a_failure_after_the_hooks_are_live_takes_the_entries_out_before_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    real = installer._apply_hooks

    def apply_then_interrupt(*args: object, **kwargs: object) -> bool:
        real(*args, **kwargs)  # type: ignore[arg-type]
        raise KeyboardInterrupt

    monkeypatch.setattr(installer, "_apply_hooks", apply_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        do_install(layout, archive)
    # No entry may outlive the client it runs (S2 F1): theirs stay, ours and the folder are gone.
    assert not layout.system_root.exists()
    assert layout.hooks_file.read_text() == OTHER_FILE


def test_a_failed_repair_puts_the_old_python_and_client_back(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    do_install(layout, archive)
    helper = layout.python_dir / "lib" / "python3.12" / "helper.py"
    helper.chmod(0o644)
    helper.write_text("old tree\n")
    layout.client.chmod(0o644)
    layout.client.write_text("old client\n")

    def fail(*args: object, **kwargs: object) -> None:
        raise InstallError("locked check failed")

    monkeypatch.setattr(installer, "assert_locked", fail)
    with pytest.raises(InstallError, match="locked check failed"):
        do_install(layout, archive)
    assert helper.read_text() == "old tree\n"  # the previous tree, not deleted, not the new one
    assert layout.client.read_text() == "old client\n"
    assert not list(layout.system_root.glob(".old-*")) and not list(
        layout.system_root.glob(".staging-*")
    )


def test_uninstall_keeps_the_folder_while_foreign_entries_still_point_into_it(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    data = json.loads(layout.hooks_file.read_text())
    data["hooks"]["stop"] = [{"command": f'env X=1 "{layout.interpreter}" -I -S', "timeout": 1}]
    layout.hooks_file.write_text(json.dumps(data))
    before = layout.hooks_file.read_text()
    with pytest.raises(InstallError, match="point into .* Nothing was removed"):
        installer.uninstall(layout)
    assert layout.hooks_file.read_text() == before and layout.python_dir.exists()


def test_an_entry_in_a_sibling_folder_with_a_similar_name_is_not_mistaken_for_ours(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    data = json.loads(layout.hooks_file.read_text())
    sibling = f"{layout.system_root}-other/run.sh"
    data["hooks"]["stop"] = [{"command": sibling, "timeout": 1}]
    layout.hooks_file.write_text(json.dumps(data))
    installer.uninstall(layout)
    assert sibling in layout.hooks_file.read_text() and not layout.system_root.exists()
