"""`agentfly init -g` and `agentfly uninstall` as commands: arguments, sudo, fixed paths."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import IO

import pytest

from agentfly.cli import build_parser, init, main, uninstall
from agentfly.install import elevate, installer, pythons
from agentfly.install.layout import SYSTEM, Layout
from tests.helpers import REPO
from tests.install_helpers import fake_python_tar, make_cursor_app, make_layout, write_archive


def test_the_system_paths_are_the_ones_in_the_spec() -> None:
    assert str(SYSTEM.system_root) == "/Library/Application Support/AgentFly"
    assert str(SYSTEM.hooks_file) == "/Library/Application Support/Cursor/hooks.json"
    assert str(SYSTEM.cursor_app) == "/Applications/Cursor.app"


def test_no_flag_or_variable_can_move_the_system_paths() -> None:
    parser = build_parser()
    commands = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    for name in ("init", "uninstall"):
        options = {s for a in commands.choices[name]._actions for s in a.option_strings}
        assert options <= {"-h", "--help", "-g", "--global"}, options
    for source in (REPO / "agentfly" / "install").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"\benviron\b|getenv", text), source.name
    init_text = (REPO / "agentfly/cli/init.py").read_text(encoding="utf-8")
    assert init_text.count("os.environ") == 2  # SUDO_UID and SUDO_GID, to try the hook as the user
    assert not re.search(
        r"\benviron\b|getenv", (REPO / "agentfly/cli/uninstall.py").read_text(encoding="utf-8")
    )


def test_init_without_g_says_so_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init"]) == 2
    assert "init -g" in capsys.readouterr().err


def test_the_sudo_command_runs_the_package_as_a_module() -> None:
    command = elevate.sudo_command(["init", "-g"])
    assert command == [
        "/usr/bin/sudo",
        sys.executable,
        "-I",
        "-B",
        "-m",
        "agentfly.cli",
        "init",
        "-g",
    ]


def test_the_module_entry_point_works_the_way_sudo_will_run_it() -> None:
    # `-m agentfly.cli` needs a __main__; without it Python says "cannot be directly executed".
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-m", "agentfly.cli", "init", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--global" in result.stdout


@pytest.fixture
def system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    """The CLI modules pointed at a temporary root (a test patch; the CLI has no flag)."""
    layout = make_layout(tmp_path)
    make_cursor_app(layout)
    monkeypatch.setattr(init, "SYSTEM", layout)
    monkeypatch.setattr(uninstall, "SYSTEM", layout)
    return layout


def test_init_as_a_user_downloads_then_pipes_the_archive_to_sudo(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = fake_python_tar()
    _, build = write_archive(tmp_path / "unused", data)
    seen: dict[str, object] = {}

    def fake_download(wanted: pythons.PythonBuild, target: Path) -> None:
        target.write_bytes(data)

    def fake_sudo(tail: list[str], stdin: IO[bytes] | None = None) -> int:
        assert stdin is not None
        seen.update(tail=tail, body=stdin.read())
        return 0

    monkeypatch.setattr(pythons, "download", fake_download)
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(elevate, "run_elevated", fake_sudo)
    assert main(["init", "-g"]) == 0
    assert seen == {"tail": ["init", "-g"], "body": data}


def test_init_as_a_user_on_an_intact_install_asks_for_no_password(
    system: Layout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["init", "-g"]) == 0
    assert "already installed" in capsys.readouterr().out


def test_init_refuses_an_unknown_cursor_before_asking_for_a_password(
    system: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(system.cursor_app)
    make_cursor_app(system, "1.0.0")
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["init", "-g"]) == 1
    err = capsys.readouterr().err
    assert "Cursor 1.0.0" in err and "nothing was written" in err
    assert not system.system_root.exists()


def test_init_as_root_installs_from_the_piped_archive(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    monkeypatch.setattr(init, "_stdin_archive", lambda: path)
    assert init._as_root("3.24.12", build) == 0
    assert system.interpreter.is_file() and system.hooks_file.is_file()


def test_uninstall_with_nothing_installed_asks_for_no_password(
    system: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(elevate, "run_elevated", lambda *a, **k: pytest.fail("asked for sudo"))
    assert main(["uninstall"]) == 0
    assert "nothing of AgentFly's is installed" in capsys.readouterr().out


def test_uninstall_as_a_user_runs_itself_under_sudo(
    system: Layout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(elevate, "run_elevated", lambda tail, stdin=None: calls.append(tail) or 0)
    assert main(["uninstall"]) == 0
    assert calls == [["uninstall"]]
    assert uninstall.RESTART_HINT in capsys.readouterr().out


def test_init_repairing_only_the_client_does_not_download_the_python_again(
    system: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )
    system.client.write_text("tampered\n")
    calls: list[tuple[list[str], object]] = []
    monkeypatch.setattr(pythons, "select_build", lambda *a: build)
    monkeypatch.setattr(pythons, "download", lambda *a: pytest.fail("downloaded the Python"))
    monkeypatch.setattr(
        elevate, "run_elevated", lambda tail, stdin=None: calls.append((tail, stdin)) or 0
    )
    assert main(["init", "-g"]) == 0
    assert calls == [(["init", "-g"], subprocess.DEVNULL)]


def test_a_filesystem_error_during_uninstall_is_one_line_and_a_failure(
    system: Layout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, build = write_archive(tmp_path / "dl", fake_python_tar())
    installer.install(
        system, build, cursor_version="3.24.12", source=installer.client_source(), archive=path
    )

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted", str(system.system_root))

    monkeypatch.setattr(uninstall.os, "geteuid", lambda: 0)  # take the root branch, no sudo
    monkeypatch.setattr(shutil, "rmtree", refuse)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and err.startswith("agentfly uninstall:")
    assert "Operation not permitted" in err and "Traceback" not in err


def test_an_oserror_that_escapes_the_installer_is_still_one_line(
    system: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(layout: Layout) -> bool:
        raise OSError(13, "Permission denied", "/Library/Application Support/AgentFly")

    monkeypatch.setattr(installer, "is_installed", broken)
    assert main(["uninstall"]) == 1
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and "Permission denied" in err and "Traceback" not in err
