"""Install and uninstall against a temporary root: the whole flow, the files and the order."""

from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agentfly.install import InstallError, cursor, hooks_file, installer, pythons, records
from agentfly.install.layout import Layout
from agentfly.install.pythons import PythonBuild
from agentfly.recorder import rulefile
from tests.install_helpers import (
    OTHER_TOOL_ENTRY,
    FsOps,
    call_unless_it_hangs,
    fake_python_tar,
    make_layout,
    run_hook_command,
    status_of,
    stop_at,
    write_archive,
)
from tests.test_install_rules import EDITED, SHIPPED, unreadable

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
        "rules.toml",
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
        result = run_hook_command(command, isolated_home, event)
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
    # The backups sit beside hooks.json, not in the folder uninstall removes.
    assert layout.backups.parent == layout.cursor_dir
    assert OTHER_FILE in [path.read_text() for path in layout.backups.iterdir()]


def test_uninstall_removes_a_file_it_created_and_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    outcome = installer.uninstall(layout)
    assert outcome.changed
    assert not layout.hooks_file.exists() and not layout.system_root.exists()


def test_a_failed_deletion_leaves_no_entry_and_no_interpreter_behind(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)
    command = registered_command(layout)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(5, "disk says no", "somewhere")

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", fail)
        with pytest.raises(InstallError, match=r"disk says no.*run `agentfly uninstall` again"):
            installer.uninstall(layout)
    assert hooks_file.our_entries(layout.hooks_file.read_text(), installer.prefix(layout)) == []
    assert not layout.system_root.exists()  # moved aside: the interpreter path is already gone
    assert run_registered(command) == 127  # Cursor lets this through; exit 2 would deny everything
    assert installer.is_installed(layout)  # the moved folder is still ours to clean up
    outcome = installer.uninstall(layout)  # the next run finishes the job
    assert any("leftover" in line for line in outcome.messages)
    assert not installer.is_installed(layout)


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
        assert status_of(layout, build, source)
        outcome = do_install(layout, archive)
        assert outcome.changed
        assert status_of(layout, build, source) == set()
    assert layout.client.read_bytes() == source.read_bytes()


def test_a_removed_hook_entry_is_put_back(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    layout.hooks_file.write_text(OTHER_FILE)
    assert status_of(layout, archive[1]) == {"hooks"}
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
    armed = False
    mark = installer.prefix(layout)
    touched: list[tuple[str, tuple[object, ...], bool]] = []  # call, args, ours still live

    def watch(count: int, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        if not armed:
            return
        inside = "dir_fd" in kwargs or any(str(a).startswith(str(layout.system_root)) for a in args)
        if inside:  # `rmtree` works by name relative to an open folder, hence `dir_fd`
            text = layout.hooks_file.read_text()
            touched.append((name, args, bool(hooks_file.our_entries(text, mark))))

    def apply_then_interrupt(*args: Any, **kwargs: Any) -> bool:
        nonlocal armed
        real(*args, **kwargs)
        armed = True
        raise KeyboardInterrupt

    monkeypatch.setattr(installer, "_apply_hooks", apply_then_interrupt)
    with FsOps(watch), pytest.raises(KeyboardInterrupt):
        do_install(layout, archive)
    # No entry may outlive the client it runs (S2 F1): theirs stay, ours and the folder are gone.
    assert not layout.system_root.exists()
    assert layout.hooks_file.read_text() == OTHER_FILE
    # And in that order: nothing in our folder changes while one of our entries is still live.
    assert touched and not [call for call in touched if call[2]], touched
    assert touched[0][0] == "rename" and Path(str(touched[0][1][0])) == layout.system_root


# ---------------------------------------------------------------- interruption at every step


def registered_command(layout: Layout) -> str:
    """The first command in hooks.json: what Cursor has cached and keeps running until restart."""
    hooks = json.loads(layout.hooks_file.read_text())["hooks"]
    return next(
        group[0]["command"] for group in hooks.values() if "AgentFly" in group[0]["command"]
    )


def run_registered(command: str) -> int:
    return run_hook_command(command, Path(os.environ["HOME"])).returncode


def sweep(
    layout: Layout,
    tmp_path: Path,
    action: Callable[[], object],
    error: type[BaseException],
) -> int:
    """Run `action` once per file-system call, stopping at that call, and check what is left.

    After each stop the cached command must exit 0 or 127 (never 2, which makes Cursor deny
    everything), and a plain second run must finish the job. Returns how many calls there are.
    """
    library = tmp_path / "Library"
    template = tmp_path / "template"
    shutil.copytree(library, template, symlinks=True)
    command = registered_command(layout)
    with FsOps() as dry:
        action()
    total = len(dry.calls)
    assert total > 5, total
    for number in range(1, total + 1):
        shutil.rmtree(library)
        shutil.copytree(template, library, symlinks=True)
        with FsOps(stop_at(number, error("stopped"))) as ops:
            with pytest.raises((error, InstallError)):
                action()
        assert len(ops.calls) >= number, f"call {number} never happened"  # cleanup may add more
        code = run_registered(command)
        stopped = ops.calls[number - 1][0]
        assert code in (0, 127), f"stopped at call {number} ({stopped}): exit {code}"
        action()
        assert not layout.system_root.exists() and not installer._leftovers(layout)
    return total


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_uninstall_stopped_at_any_step_leaves_the_command_exiting_0_or_127(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path, error: type[BaseException]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)
    sweep(layout, tmp_path, lambda: installer.uninstall(layout), error)


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_the_cleanup_of_a_failed_first_install_stopped_at_any_step_is_safe_too(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path, error: type[BaseException]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)
    record = records.read(layout)
    assert record is not None
    info = record["hooks_file"]

    def cleanup() -> None:
        installer._undo_first_install(layout, created_hooks=False, hooks_info=info)

    sweep(layout, tmp_path, cleanup, error)


# ---------------------------------------------------------------- foreign entries, refusals


def write_hooks(layout: Layout, text: str, *, escaped: bool) -> None:
    """Write `text`, with every slash JSON-escaped (`\\/`) when asked: valid, but not greppable."""
    layout.hooks_file.write_text(text.replace("/", "\\/") if escaped else text)


def install_with_foreign_entry(
    layout: Layout, archive: tuple[Path, PythonBuild], *, escaped: bool
) -> None:
    do_install(layout, archive)
    data = json.loads(layout.hooks_file.read_text())
    # Not the exact quoted interpreter, so it is not ours; it still runs our client.
    data["hooks"]["stop"] = [{"command": f'env X=1 "{layout.client}"', "timeout": 1}]
    write_hooks(layout, json.dumps(data), escaped=escaped)


@pytest.mark.parametrize("escaped", [False, True])
def test_a_foreign_entry_that_runs_our_client_makes_uninstall_refuse_and_change_nothing(
    layout: Layout, archive: tuple[Path, PythonBuild], escaped: bool
) -> None:
    install_with_foreign_entry(layout, archive, escaped=escaped)
    before = snapshot(layout)
    with pytest.raises(InstallError, match="point into .* Nothing was removed"):
        installer.uninstall(layout)
    assert snapshot(layout) == before  # no write, no backup, folder intact


@pytest.mark.parametrize("escaped", [False, True])
def test_an_unparseable_file_naming_our_folder_makes_uninstall_refuse_and_change_nothing(
    layout: Layout, archive: tuple[Path, PythonBuild], escaped: bool
) -> None:
    do_install(layout, archive)
    write_hooks(layout, layout.hooks_file.read_text() + " garbage", escaped=escaped)
    before = snapshot(layout)
    assert installer.is_installed(layout)
    with pytest.raises(InstallError, match="not valid JSON"):
        installer.uninstall(layout)
    assert snapshot(layout) == before


def test_an_unparseable_file_that_is_not_ours_is_left_alone(layout: Layout) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text("{ not json, and about /opt/other")
    outcome = installer.uninstall(layout)
    assert not outcome.changed and not installer.is_installed(layout)


# ---------------------------------------------------------------- backups and exact give-back

ORIGINALS = {
    "no hooks key": '{"version": 1}\n',
    "empty hooks": '{"version":1,"hooks":{}}',
    "empty array of another event": '{"hooks": {"stop": []}}',
    "empty array of our event": '{"hooks": {"preToolUse": []}}',
    "empty object over two lines": '{\n  "version": 1,\n  "hooks": {\n  }\n}\n',
    "tabs": '{\n\t"version": 1,\n\t"hooks": {\n\t}\n}\n',
    "other tool's entries": OTHER_FILE,
    "with a BOM": "\ufeff" + OTHER_FILE,
    "with CRLF": OTHER_FILE.replace("\n", "\r\n"),
}


@pytest.mark.parametrize("original", ORIGINALS.values(), ids=ORIGINALS.keys())
def test_install_then_uninstall_gives_another_tools_file_back_byte_for_byte(
    layout: Layout, archive: tuple[Path, PythonBuild], original: str
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_bytes(original.encode("utf-8"))
    do_install(layout, archive)
    assert hooks_file.our_entries(layout.hooks_file.read_text(), installer.prefix(layout))
    installer.uninstall(layout)
    assert layout.hooks_file.read_bytes() == original.encode("utf-8")
    assert not layout.system_root.exists()
    assert original in [p.read_bytes().decode() for p in layout.backups.iterdir()]


def test_a_file_edited_after_install_is_spliced_not_overwritten_with_the_original(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text('{"version": 1}\n')
    do_install(layout, archive)
    data = json.loads(layout.hooks_file.read_text())
    data["hooks"]["afterFileEdit"] = [json.loads(OTHER_TOOL_ENTRY)]  # another tool, later
    layout.hooks_file.write_text(json.dumps(data))
    installer.uninstall(layout)
    left = json.loads(layout.hooks_file.read_text())
    assert left["hooks"] == {"afterFileEdit": [json.loads(OTHER_TOOL_ENTRY)]}


def test_a_record_that_names_some_other_file_is_not_trusted_for_the_give_back(
    layout: Layout, archive: tuple[Path, PythonBuild], tmp_path: Path
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text('{"version": 1}\n')
    do_install(layout, archive)
    (tmp_path / "planted").write_text('{"version": 1, "planted": true}\n')
    for name in ("../../../../planted", "planted", "missing"):
        record = json.loads(layout.record.read_text())
        record["hooks_file"]["original_backup"] = name
        layout.record.write_text(json.dumps(record))
        assert (
            installer._exact_original(layout, record["hooks_file"], layout.hooks_file.read_text())
            is None
        )
    installer.uninstall(layout)
    assert "planted" not in layout.hooks_file.read_text()


def test_every_rewrite_of_the_hooks_file_is_preceded_by_a_backup_of_what_it_replaces(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    seen: list[str] = []

    def check(count: int, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        if name == "replace" and Path(str(args[1])) == layout.hooks_file:
            current = layout.hooks_file.read_text()
            backups = (
                [p.read_text() for p in layout.backups.iterdir()] if layout.backups.is_dir() else []
            )
            assert current in backups, "rewrote hooks.json without a backup of it"
            seen.append(current)

    with FsOps(check):
        do_install(layout, archive)  # first install
        layout.hooks_file.write_text(OTHER_FILE.replace("5", "6"))  # an entry went missing: repair
        do_install(layout, archive)
        installer.uninstall(layout)
    assert len(seen) == 3


def test_a_file_we_created_is_removed_without_a_backup(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    do_install(layout, archive)
    installer.uninstall(layout)
    assert not layout.hooks_file.exists() and not layout.backups.exists()


# ---------------------------------------------------------------- a failed restore


def break_the_new_install(layout: Layout, archive: tuple[Path, PythonBuild]) -> Path:
    """An installed copy whose Python and client differ, so the next run is a repair."""
    do_install(layout, archive)
    helper = layout.python_dir / "lib" / "python3.12" / "helper.py"
    helper.chmod(0o644)
    helper.write_text("old tree\n")
    layout.client.chmod(0o644)
    layout.client.write_text("old client\n")
    return helper


def fail_rename(match: Callable[[Path, Path], bool]) -> Callable[..., None]:
    def before(count: int, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        if name == "rename" and match(Path(str(args[0])), Path(str(args[1]))):
            raise OSError(5, "rename refused", str(args[0]))

    return before


def new_tree_steps_aside(src: Path, dst: Path) -> bool:
    return dst.name == "failed-python"


def old_tree_comes_back(src: Path, dst: Path) -> bool:
    return src.name == "python" and src.parent.name.startswith(".old-")


def second_rename_of_the_swap(src: Path, dst: Path) -> bool:
    return src.name == "python" and src.parent.name.startswith(".staging-")


@pytest.mark.parametrize("match", [new_tree_steps_aside, old_tree_comes_back])
def test_a_restore_that_fails_keeps_the_old_python(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    match: Callable[[Path, Path], bool],
) -> None:
    helper = break_the_new_install(layout, archive)
    command = registered_command(layout)

    def fail(*args: object, **kwargs: object) -> None:
        raise InstallError("locked check failed")

    monkeypatch.setattr(installer, "assert_locked", fail)
    with FsOps(fail_rename(match)):
        with pytest.raises(InstallError, match="locked check failed") as caught:
            do_install(layout, archive)
    (kept,) = layout.system_root.glob(".old-*")
    assert (kept / "python" / "lib" / "python3.12" / helper.name).read_text() == "old tree\n"
    assert str(kept) in capsys.readouterr().err
    assert any(str(kept) in note for note in caught.value.__notes__)
    assert layout.interpreter.is_file() and run_registered(command) == 0  # a Python is in place


def test_a_repair_that_stops_halfway_through_the_swap_gets_the_old_python_back(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    helper = break_the_new_install(layout, archive)

    with FsOps(fail_rename(second_rename_of_the_swap)):
        with pytest.raises(OSError, match="rename refused"):
            do_install(layout, archive)
    # The live Python was already moved to the graveyard when the swap stopped.
    assert helper.read_text() == "old tree\n" and layout.interpreter.is_file()
    assert not list(layout.system_root.glob(".old-*")) and not list(
        layout.system_root.glob(".staging-*")
    )


def test_leftovers_of_an_interrupted_uninstall_are_reported_and_removed(layout: Layout) -> None:
    stray = layout.system_root.parent / f".{layout.system_root.name}-removing-1"
    (stray / "python").mkdir(parents=True)
    (stray / "hook_client.py").write_text("x")
    assert installer.is_installed(layout)
    outcome = installer.uninstall(layout)
    assert outcome.changed and any("leftover" in line for line in outcome.messages)
    assert not stray.exists() and not installer.is_installed(layout)


# ---------------------------------------------------------------- found by the final audit


@pytest.mark.parametrize("blank", ["", "  \n"])
def test_an_empty_hooks_file_installs_and_comes_back_as_it_was(
    layout: Layout, archive: tuple[Path, PythonBuild], blank: str
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(blank)
    do_install(layout, archive)
    assert hooks_file.our_entries(layout.hooks_file.read_text(), installer.prefix(layout))
    installer.uninstall(layout)
    assert layout.hooks_file.read_text() == blank and not layout.system_root.exists()


def damage_one_of_our_entries(layout: Layout) -> None:
    """Change one registered timeout in place, so the next run is a repair and the layout stays."""
    text = layout.hooks_file.read_text()
    assert '"timeout": 2' in text
    layout.hooks_file.write_text(text.replace('"timeout": 2', '"timeout": 3', 1))


def test_a_repair_keeps_the_byte_for_byte_give_back_when_only_our_entries_changed(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    original = '{"version": 1}\n'
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(original)
    do_install(layout, archive)
    damage_one_of_our_entries(layout)
    assert do_install(layout, archive).changed  # the repair
    installer.uninstall(layout)
    assert layout.hooks_file.read_text() == original


def test_a_repair_does_not_bring_back_the_original_over_another_tools_later_edit(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text('{"version": 1}\n')
    do_install(layout, archive)
    data = json.loads(layout.hooks_file.read_text())
    data["hooks"]["afterFileEdit"] = [json.loads(OTHER_TOOL_ENTRY)]
    data["hooks"][cursor.EVENTS[0]][0]["timeout"] = (
        3  # one of ours differs, so the next run repairs
    )
    layout.hooks_file.write_text(json.dumps(data, indent=2))
    do_install(layout, archive)
    installer.uninstall(layout)
    left = json.loads(layout.hooks_file.read_text())
    assert left["hooks"] == {"afterFileEdit": [json.loads(OTHER_TOOL_ENTRY)]}


def test_a_cleanup_that_cannot_finish_says_what_is_left(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise InstallError("hook command does not start")

    def cannot_clean(*args: object, **kwargs: object) -> None:
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(installer, "smoke", broken)
    monkeypatch.setattr(installer, "_undo_first_install", cannot_clean)
    with pytest.raises(InstallError, match="does not start") as caught:
        do_install(layout, archive)
    assert "agentfly uninstall" in capsys.readouterr().err
    assert any("did not finish" in note for note in caught.value.__notes__)
    assert layout.system_root.exists()  # the safe side: nothing half-removed


def test_uninstall_keeps_backups_an_earlier_version_left_inside_the_folder(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    layout.cursor_dir.mkdir(parents=True)
    layout.hooks_file.write_text(OTHER_FILE)
    do_install(layout, archive)
    old = layout.system_root / "backups"
    old.mkdir()
    (old / "hooks.json.20260101-000000").write_text('{"older": true}\n')
    outcome = installer.uninstall(layout)
    assert any("earlier backup" in line for line in outcome.messages)
    assert not layout.system_root.exists()
    assert '{"older": true}\n' in [p.read_text() for p in layout.backups.iterdir()]


def test_a_leftover_that_will_not_delete_does_not_stop_the_folder_from_moving_aside(
    layout: Layout, archive: tuple[Path, PythonBuild], monkeypatch: pytest.MonkeyPatch
) -> None:
    do_install(layout, archive)
    command = registered_command(layout)
    stray = layout.system_root.parent / f".{layout.system_root.name}-removing-1"
    stray.mkdir()
    (stray / "stuck").write_text("x")
    real = shutil.rmtree

    def refuse_the_stray(path: object, *args: object, **kwargs: object) -> None:
        if Path(str(path)) == stray:
            raise OSError(1, "Operation not permitted", str(path))
        real(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(shutil, "rmtree", refuse_the_stray)
    with pytest.raises(InstallError, match="Operation not permitted"):
        installer.uninstall(layout)
    assert not layout.system_root.exists() and run_registered(command) == 127


def test_an_install_sweeps_what_an_interrupted_uninstall_moved_aside(
    layout: Layout, archive: tuple[Path, PythonBuild]
) -> None:
    stray = layout.system_root.parent / f".{layout.system_root.name}-removing-1"
    (stray / "python").mkdir(parents=True)
    do_install(layout, archive)
    assert not stray.exists()


# ---------------------------------------------------------------- an edited rules file (D30, V5e)


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    # The smoke runs and the byte-compile are the tests above; these look only at the rules file.
    monkeypatch.setattr(installer, "smoke", lambda *args, **kwargs: None)
    monkeypatch.setattr(pythons, "compile_stdlib", lambda *args, **kwargs: None)


def copies(layout: Layout) -> list[Path]:
    return sorted(layout.backups.glob("rules.toml.*"))


def edit(layout: Layout, mode: int = 0o644, data: bytes = EDITED.encode()) -> None:
    layout.rules.write_bytes(data)
    layout.rules.chmod(mode)


@pytest.mark.parametrize("who", ["root's 0644", "root's 0600", "another user's"])
def test_uninstall_keeps_a_copy_of_an_edited_rules_file_and_says_where(
    who: str,
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    quick: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    do_install(layout, archive)
    edit(layout, 0o600 if who == "root's 0600" else 0o644)
    if who == "another user's":  # uninstall never asks who owns it; this only shows that
        monkeypatch.setattr(installer, "rules_owner_uid", lambda lay: os.getuid() + 1)
    written: list[tuple[Path, Layout, int]] = []
    real = installer._write_atomic

    def spy(path: Path, data: bytes, lay: Layout, mode: int = 0o644) -> None:
        written.append((path, lay, mode))
        real(path, data, lay, mode)

    monkeypatch.setattr(installer, "_write_atomic", spy)
    outcome = installer.uninstall(layout)
    (copy,) = copies(layout)
    assert copy.read_bytes() == EDITED.encode()
    assert copy.parent == layout.backups and copy.name.startswith("rules.toml.")
    assert outcome.messages[0] == f"kept a copy of your edited rules file in {copy}"
    assert not layout.system_root.exists()
    assert (copy, layout, stat.S_IMODE(copy.stat().st_mode)) in written  # the system user's
    if who == "root's 0600":
        assert stat.S_IMODE(copy.stat().st_mode) & 0o077 == 0
    else:
        assert stat.S_IMODE(copy.stat().st_mode) == 0o644


@pytest.mark.parametrize("mode", [0o640, 0o604], ids=["0640", "0604"])
def test_a_copy_is_readable_by_others_only_if_the_original_was_by_group_and_others(
    mode: int, layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    do_install(layout, archive)
    edit(layout, mode)
    installer.uninstall(layout)
    (copy,) = copies(layout)
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600


def test_two_rounds_leave_two_copies(
    layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    for round_ in ("first", "second"):
        do_install(layout, archive)
        edit(layout, data=f"# {round_}\n{rulefile.default_text()}".encode())
        installer.uninstall(layout)
    first, second = copies(layout)
    assert {first.read_text()[:8], second.read_text()[:8]} == {"# first\n", "# second"}


NOT_EDITED = ["this version's default", "this version's default at 0600", "no file"] + [
    f"older default {f.stem}" for f in SHIPPED
]


@pytest.mark.parametrize("what", NOT_EDITED)
def test_an_unedited_default_or_no_file_is_not_copied(
    what: str, layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    do_install(layout, archive)
    if what == "this version's default at 0600":
        layout.rules.chmod(0o600)
    elif what == "no file":
        layout.rules.unlink()
    elif what.startswith("older default"):
        (fixture,) = [f for f in SHIPPED if what.endswith(f.stem)]
        layout.rules.write_bytes(fixture.read_bytes())
    outcome = installer.uninstall(layout)
    assert copies(layout) == [] and not any("rules" in line for line in outcome.messages)
    assert not layout.system_root.exists()


def spoil_backups(
    how: str, layout: Layout, elsewhere: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if how == "a link":
        elsewhere.mkdir()
        layout.backups.symlink_to(elsewhere)
    elif how == "a file":
        layout.backups.write_text("not a folder\n")
    else:
        real = installer._write_atomic

        def failing(path: Path, data: bytes, lay: Layout, mode: int = 0o644) -> None:
            if path.name.startswith("rules.toml."):
                raise OSError(28, "No space left on device", str(path))
            real(path, data, lay, mode)

        monkeypatch.setattr(installer, "_write_atomic", failing)


def outside_backups(layout: Layout) -> dict[str, tuple[int, int, int]]:
    """`snapshot` without the backups folder (a failed write may leave it, empty, behind)."""
    return {k: v for k, v in snapshot(layout).items() if not k.startswith(str(layout.backups))}


@pytest.mark.parametrize("how", ["a link", "a file", "a failed write"])
def test_a_copy_that_cannot_be_written_stops_uninstall_before_anything_is_removed(
    how: str,
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    quick: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    do_install(layout, archive)
    edit(layout)
    elsewhere = tmp_path / "elsewhere"
    with monkeypatch.context() as patch:
        spoil_backups(how, layout, elsewhere, patch)
        hooks, rules = layout.hooks_file.read_bytes(), layout.rules.read_bytes()
        before = outside_backups(layout)
        with pytest.raises(InstallError) as caught:
            installer.uninstall(layout)
    message = str(caught.value)
    assert message.startswith(f"cannot keep a copy of the edited rules file {layout.rules} in ")
    assert message.endswith("; nothing was removed") and "\n" not in message
    assert layout.hooks_file.read_bytes() == hooks and layout.rules.read_bytes() == rules
    assert layout.system_root.is_dir() and outside_backups(layout) == before
    if how == "a link":
        assert list(elsewhere.iterdir()) == []  # nothing followed the link
    # the cause fixed, the next run finishes and leaves one copy
    if layout.backups.is_symlink() or layout.backups.is_file():
        layout.backups.unlink()
    installer.uninstall(layout)
    assert not layout.system_root.exists() and len(copies(layout)) == 1


SKIPPED = {
    "a link": "a symbolic link",
    "a link to a 0600 file": "a symbolic link",
    "a folder": "not a regular file",
    "a named pipe": "not a regular file",
    "a file over the limit": f"over {rulefile.MAX_FILE_BYTES} bytes",
}


@pytest.mark.parametrize("kind", SKIPPED)
def test_what_the_recorder_could_never_load_is_named_and_not_copied(
    kind: str, layout: Layout, archive: tuple[Path, PythonBuild], quick: None, tmp_path: Path
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    target, fifo = tmp_path / "target.toml", None
    if kind.startswith("a link"):
        target.write_text(EDITED, encoding="utf-8")
        target.chmod(0o600 if kind.endswith("0600 file") else 0o644)
        layout.rules.symlink_to(target)
    elif kind == "a folder":
        layout.rules.mkdir()
        (layout.rules / "inside.toml").write_text(EDITED, encoding="utf-8")
    elif kind == "a named pipe":
        os.mkfifo(layout.rules)
        fifo = layout.rules
    else:
        layout.rules.write_bytes(b"#" * (rulefile.MAX_FILE_BYTES + 1))
    outcome = call_unless_it_hangs(lambda: installer.uninstall(layout), fifo)
    said = [line for line in outcome.messages if str(layout.rules) in line]
    assert said == [
        f"{layout.rules} is {SKIPPED[kind]}, which the recorder never loads; no copy was kept"
    ]
    assert copies(layout) == [] and not layout.system_root.exists()
    if kind.startswith("a link"):
        assert target.read_text(encoding="utf-8") == EDITED


def test_a_file_of_exactly_the_limit_is_copied(
    layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    do_install(layout, archive)
    edit(layout, data=b"#" * rulefile.MAX_FILE_BYTES)
    installer.uninstall(layout)
    (copy,) = copies(layout)
    assert copy.stat().st_size == rulefile.MAX_FILE_BYTES


def test_a_file_in_place_of_the_system_folder_is_left_to_the_folder_removal(
    layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    do_install(layout, archive)
    shutil.rmtree(layout.system_root)
    layout.system_root.write_text("not a folder\n")
    with pytest.raises(InstallError, match="cannot finish removing AgentFly"):  # as before V5e
        installer.uninstall(layout)
    assert copies(layout) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_a_rules_file_that_cannot_be_read_stops_uninstall_with_the_way_out(
    layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    do_install(layout, archive)
    edit(layout)
    with unreadable(layout.rules):
        with pytest.raises(InstallError, match="nothing was removed. Move it away by hand"):
            installer.uninstall(layout)
        assert layout.system_root.is_dir() and copies(layout) == []


def test_a_stale_temp_file_or_a_link_in_its_place_gets_none_of_the_bytes(
    layout: Layout, tmp_path: Path
) -> None:
    # A run killed between the chmod and the rename leaves its temp; a fresh one is made, at 0600,
    # so neither that file's mode nor a hard link planted at its name sees what is written.
    target = tmp_path / "copy"
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    other = tmp_path / "other"
    other.write_text("someone else's\n")
    other.chmod(0o644)
    os.link(other, temp)
    installer._write_atomic(target, b"secret\n", layout, 0o600)
    assert other.read_text() == "someone else's\n" and not temp.exists()
    assert target.read_bytes() == b"secret\n" and stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_folder_swapped_in_after_the_first_look_is_named_and_skipped_too(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    quick: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    do_install(layout, archive)
    layout.rules.unlink()
    layout.rules.mkdir()
    plain = tmp_path / "plain"
    plain.write_text(EDITED, encoding="utf-8")
    real = Path.lstat

    def first_look(self: Path) -> os.stat_result:  # the `lstat` saw a plain file
        return real(plain) if self == layout.rules else real(self)

    monkeypatch.setattr(Path, "lstat", first_look)
    assert installer._keep_rules_copy(layout) == [
        f"{layout.rules} is not a regular file, which the recorder never loads; no copy was kept"
    ]


def test_a_later_refusal_still_says_where_the_copy_went(
    layout: Layout, archive: tuple[Path, PythonBuild], quick: None
) -> None:
    do_install(layout, archive)
    edit(layout)
    layout.hooks_file.write_text(layout.hooks_file.read_text() + " garbage")
    with pytest.raises(InstallError) as caught:
        installer.uninstall(layout)
    (copy,) = copies(layout)
    assert "not valid JSON" in str(caught.value)
    assert str(caught.value).endswith(f"(kept a copy of your edited rules file in {copy})")
    assert layout.system_root.is_dir() and "\n" not in str(caught.value)
