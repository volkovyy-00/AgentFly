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
    FsOps,
    fake_python_tar,
    make_layout,
    stop_at,
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
    armed: list[bool] = []
    mark = installer.prefix(layout)
    touched: list[tuple[str, tuple[object, ...], bool]] = []  # call, args, ours still live

    def watch(count: int, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        if not armed:
            return
        inside = "dir_fd" in kwargs or any(str(a).startswith(str(layout.system_root)) for a in args)
        if inside:  # `rmtree` works by name relative to an open folder, hence `dir_fd`
            text = layout.hooks_file.read_text()
            touched.append((name, args, bool(hooks_file.our_entries(text, mark))))

    def apply_then_interrupt(*args: object, **kwargs: object) -> bool:
        real(*args, **kwargs)  # type: ignore[arg-type]
        armed.append(True)
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
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        input=json.dumps({"hook_event_name": "beforeShellExecution", "command": "ls"}),
        capture_output=True,
        text=True,
        env=client_env(Path(os.environ["HOME"])),
        check=False,
    )
    return result.returncode


def sweep(
    layout: Layout,
    tmp_path: Path,
    action: object,
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
        action()  # type: ignore[operator]
    total = len(dry.calls)
    assert total > 5, total
    for number in range(1, total + 1):
        shutil.rmtree(library)
        shutil.copytree(template, library, symlinks=True)
        with FsOps(stop_at(number, error("stopped"))) as ops:
            with pytest.raises((error, InstallError)):
                action()  # type: ignore[operator]
        assert len(ops.calls) >= number, f"call {number} never happened"  # cleanup may add more
        code = run_registered(command)
        stopped = ops.calls[number - 1][0]
        assert code in (0, 127), f"stopped at call {number} ({stopped}): exit {code}"
        action()  # type: ignore[operator]
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
    info = records.read(layout)["hooks_file"]  # type: ignore[index]

    def cleanup() -> None:
        installer._undo_first_install(layout, created_hooks=False, hooks_info=info)

    sweep(layout, tmp_path, cleanup, error)


# ---------------------------------------------------------------- foreign entries, refusals


def install_with_foreign_entry(
    layout: Layout, archive: tuple[Path, PythonBuild], *, escaped: bool
) -> None:
    do_install(layout, archive)
    data = json.loads(layout.hooks_file.read_text())
    # Not the exact quoted interpreter, so it is not ours; it still runs our client.
    data["hooks"]["stop"] = [{"command": f'env X=1 "{layout.client}"', "timeout": 1}]
    text = json.dumps(data)
    layout.hooks_file.write_text(text.replace("/", "\\/") if escaped else text)


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
    text = layout.hooks_file.read_text() + " garbage"
    layout.hooks_file.write_text(text.replace("/", "\\/") if escaped else text)
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


def fail_rename(match: object) -> object:
    def before(count: int, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        if name == "rename" and match(Path(str(args[0])), Path(str(args[1]))):  # type: ignore[operator]
            raise OSError(5, "rename refused", str(args[0]))

    return before


@pytest.mark.parametrize("which", ["new tree steps aside", "old tree comes back"])
def test_a_restore_that_fails_keeps_the_old_python(
    layout: Layout,
    archive: tuple[Path, PythonBuild],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    which: str,
) -> None:
    helper = break_the_new_install(layout, archive)
    command = registered_command(layout)

    def fail(*args: object, **kwargs: object) -> None:
        raise InstallError("locked check failed")

    monkeypatch.setattr(installer, "assert_locked", fail)
    if which == "new tree steps aside":
        match = lambda src, dst: dst.name == "failed-python"  # noqa: E731
    else:
        match = lambda src, dst: src.name == "python" and src.parent.name.startswith(".old-")  # noqa: E731
    with FsOps(fail_rename(match)):  # type: ignore[arg-type]
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

    def second_rename_of_the_swap(src: Path, dst: Path) -> bool:
        return src.name == "python" and src.parent.name.startswith(".staging-")

    with FsOps(fail_rename(second_rename_of_the_swap)):  # type: ignore[arg-type]
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
